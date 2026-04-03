"""
SYUTAINβ V25 セマンティックループ検知（Semantic Loop Detection）
設計書 第8章 Layer 8準拠

直近3アクションの目的・手法・結果が意味的に類似していないかを検知する。
外部Embedding APIは使わず、テキスト類似度で判定（コスト¥0）。
"""

import re
import logging
from typing import Optional
from collections import Counter
from difflib import SequenceMatcher

logger = logging.getLogger("syutain.semantic_loop_detector")

# 類似度閾値（設計書: 0.85以上で発動）
SIMILARITY_THRESHOLD = 0.85
# 比較対象アクション数（設計書: 直近3アクション）
WINDOW_SIZE = 3
# 状態ハッシュ重複閾値（設計書: 3回で発動）
STATE_HASH_DUPLICATE_THRESHOLD = 3


class SemanticLoopDetector:
    """セマンティックループ検知エンジン"""

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD, window_size: int = WINDOW_SIZE):
        self._threshold = threshold
        self._window_size = window_size
        # アクション履歴: [{purpose, method, result, summary}, ...]
        self._action_history: list[dict] = []
        # 状態ハッシュ履歴
        self._state_hashes: list[str] = []

    def record_action(self, purpose: str, method: str, result: str, summary: str = ""):
        """アクションを記録"""
        action = {
            "purpose": purpose,
            "method": method,
            "result": result,
            "summary": summary or f"{purpose} -> {method} -> {result}",
        }
        self._action_history.append(action)
        # 状態ハッシュ生成（正規化テキストのハッシュ）
        normalized = self._normalize(action["summary"])
        self._state_hashes.append(normalized)

    def check_semantic_loop(self) -> dict:
        """
        セマンティックループを検知する。

        Returns:
            {
                "detected": bool,
                "type": "semantic" | "state_hash" | None,
                "similarity_score": float,
                "details": str,
            }
        """
        try:
            # 状態ハッシュ重複チェック（Layer 7の一部でもある）
            hash_result = self._check_state_hash_duplicates()
            if hash_result["detected"]:
                return hash_result

            # セマンティック類似度チェック（直近N件）
            semantic_result = self._check_semantic_similarity()
            if semantic_result["detected"]:
                return semantic_result

            return {
                "detected": False,
                "type": None,
                "similarity_score": semantic_result.get("similarity_score", 0.0),
                "details": "ループ未検知",
            }
        except Exception as e:
            logger.error(f"セマンティックループ検知エラー: {e}")
            # エラー時は安全側（非検知）で処理
            return {
                "detected": False,
                "type": None,
                "similarity_score": 0.0,
                "details": f"検知エラー: {e}",
            }

    def _check_state_hash_duplicates(self) -> dict:
        """状態ハッシュの重複を検知（infinite_loop_score >= 3で発動）"""
        if len(self._state_hashes) < STATE_HASH_DUPLICATE_THRESHOLD:
            return {"detected": False, "type": None, "similarity_score": 0.0, "details": ""}

        counter = Counter(self._state_hashes)
        for text, count in counter.most_common(1):
            if count >= STATE_HASH_DUPLICATE_THRESHOLD:
                logger.warning(f"状態ハッシュ重複検知: 同一状態が{count}回出現")
                return {
                    "detected": True,
                    "type": "state_hash",
                    "similarity_score": 1.0,
                    "details": f"同一状態が{count}回出現（閾値: {STATE_HASH_DUPLICATE_THRESHOLD}回）",
                }
        return {"detected": False, "type": None, "similarity_score": 0.0, "details": ""}

    def _check_semantic_similarity(self) -> dict:
        """直近のアクション間のセマンティック類似度チェック"""
        if len(self._action_history) < self._window_size:
            return {"detected": False, "similarity_score": 0.0, "details": "履歴不足"}

        recent = self._action_history[-self._window_size:]

        # 全ペアの類似度を計算
        summaries = [a["summary"] for a in recent]
        pair_scores = []
        for i in range(len(summaries)):
            for j in range(i + 1, len(summaries)):
                score = self._text_similarity(summaries[i], summaries[j])
                pair_scores.append(score)

        if not pair_scores:
            return {"detected": False, "similarity_score": 0.0, "details": ""}

        avg_score = sum(pair_scores) / len(pair_scores)
        min_score = min(pair_scores)

        # 全ペアの最低類似度が閾値以上 = 全アクションが類似
        if min_score >= self._threshold:
            logger.warning(
                f"セマンティックループ検知: 直近{self._window_size}アクションの類似度 "
                f"avg={avg_score:.3f}, min={min_score:.3f} (閾値: {self._threshold})"
            )
            return {
                "detected": True,
                "type": "semantic",
                "similarity_score": avg_score,
                "details": (
                    f"直近{self._window_size}アクションが意味的に類似 "
                    f"(avg={avg_score:.3f}, min={min_score:.3f}, 閾値={self._threshold})"
                ),
            }

        return {"detected": False, "similarity_score": avg_score, "details": ""}

    def _text_similarity(self, text_a: str, text_b: str) -> float:
        """
        2つのテキスト間の類似度を計算（0.0〜1.0）。
        外部APIを使わず、複数の手法を組み合わせる。
        """
        if not text_a or not text_b:
            return 0.0

        norm_a = self._normalize(text_a)
        norm_b = self._normalize(text_b)

        # 完全一致
        if norm_a == norm_b:
            return 1.0

        # 1. SequenceMatcher（編集距離ベース）
        seq_score = SequenceMatcher(None, norm_a, norm_b).ratio()

        # 2. トークンベース Jaccard係数
        tokens_a = set(norm_a.split())
        tokens_b = set(norm_b.split())
        if tokens_a or tokens_b:
            jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        else:
            jaccard = 0.0

        # 3. N-gram類似度（bigram）
        bigrams_a = set(self._ngrams(norm_a, 2))
        bigrams_b = set(self._ngrams(norm_b, 2))
        if bigrams_a or bigrams_b:
            ngram_score = len(bigrams_a & bigrams_b) / len(bigrams_a | bigrams_b)
        else:
            ngram_score = 0.0

        # 重み付き平均
        combined = seq_score * 0.4 + jaccard * 0.3 + ngram_score * 0.3
        return combined

    @staticmethod
    def _normalize(text: str) -> str:
        """テキストを正規化"""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _ngrams(text: str, n: int) -> list[str]:
        """N-gramを生成"""
        return [text[i:i + n] for i in range(max(0, len(text) - n + 1))]

    def reset(self):
        """履歴をリセット"""
        self._action_history.clear()
        self._state_hashes.clear()

    def get_history_size(self) -> int:
        """記録済みアクション数を返す"""
        return len(self._action_history)


# シングルトン
_instance: Optional[SemanticLoopDetector] = None


def get_semantic_loop_detector() -> SemanticLoopDetector:
    """SemanticLoopDetectorのシングルトンを取得"""
    global _instance
    if _instance is None:
        _instance = SemanticLoopDetector()
    return _instance
