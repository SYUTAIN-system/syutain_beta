"""
SYUTAINβ V25 突然変異エンジン (Step 22) — 第24章準拠

【絶対原則】
- 変異の発生をログに記録しない
- 変異パラメータをUIに表示しない
- Capability Auditに含めない
- 9層ループ防止壁・承認フロー・Emergency Killに一切干渉しない
- 変異エンジンのバグで全体が止まらないようtry-exceptで完全隔離
- 他のエージェントはこのモジュールをimportしない
- 変異パラメータはDELTAの暗号化SQLite（SQLCipher）にのみ保存

変異の種:
  系統1: 物理エントロピー（CPU温度、NATSラウンドトリップ、VRAM変動、パケットジッター、/dev/urandom）
  系統2: 人間の直感（Web UIの「今日の風向き」入力）

蓄積:
  有益な変異 → mutation_probability += 0.0003, deviation_rate += 0.0002
  無益/有害 → 変化なし（下がらない。不可逆）
"""

import os
import hashlib
import struct
import asyncio
import time as _time_mod
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# SQLCipherパスフレーズ（.envから取得）
_SQLCIPHER_PASSPHRASE = os.getenv("SQLCIPHER_PASSPHRASE", "")

# 暗号化SQLiteのパス（DELTA専用）
_MUTATION_DB_PATH = os.getenv(
    "MUTATION_DB_PATH", "data/mutation_engine.enc.db"
)

# 初期パラメータ（第24章 24.3準拠）
_DEFAULT_MUTATION_PROBABILITY = 0.005       # 0.5%
_DEFAULT_DEVIATION_RATE = 0.02              # 2%
_ACCUMULATION_COEFFICIENT = 0.0003          # 有益変異1回あたりの確率上昇
_DEVIATION_ACCUMULATION = 0.0002            # 有益変異1回あたりの逸脱率上昇
_MAX_MUTATION_PROBABILITY = 0.05            # 絶対上限 5%
_MAX_DEVIATION_RATE = 0.15                  # 絶対上限 15%
_INTUITION_MULTIPLIER = 1.3                 # 人間直感入力がある日の倍率

# メモリ上のみに存在する変異フラグ（プロセス再起動で消える）
# 最大1000エントリ、1時間超過エントリは自動パージ
_pending_mutations: dict = {}
_PENDING_MAX_SIZE = 1000
_PENDING_MAX_AGE_SEC = 3600


class _MutationState:
    """変異パラメータの現在値（暗号化SQLiteから読み込み/書き込み）"""

    def __init__(self):
        self.mutation_probability = _DEFAULT_MUTATION_PROBABILITY
        self.deviation_rate = _DEFAULT_DEVIATION_RATE
        self._db_conn = None

    def _open_db(self):
        """SQLCipher暗号化DBを開く"""
        try:
            from pysqlcipher3 import dbapi2 as sqlcipher
            conn = sqlcipher.connect(_MUTATION_DB_PATH)
            safe_passphrase = _SQLCIPHER_PASSPHRASE.replace("'", "''")
            conn.execute(f"PRAGMA key='{safe_passphrase}'")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS mutation_state (
                    key TEXT PRIMARY KEY,
                    value REAL NOT NULL
                )"""
            )
            conn.commit()
            return conn
        except Exception:
            return None

    def load(self):
        """暗号化SQLiteから現在のパラメータを読み込む"""
        try:
            conn = self._open_db()
            if not conn:
                return
            try:
                cursor = conn.execute(
                    "SELECT key, value FROM mutation_state"
                )
                for row in cursor:
                    if row[0] == "mutation_probability":
                        self.mutation_probability = float(row[1])
                    elif row[0] == "deviation_rate":
                        self.deviation_rate = float(row[1])
            finally:
                conn.close()
        except Exception:
            pass

    def save(self):
        """暗号化SQLiteに現在のパラメータを書き込む"""
        try:
            conn = self._open_db()
            if not conn:
                return
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO mutation_state (key, value) VALUES (?, ?)",
                    ("mutation_probability", self.mutation_probability),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO mutation_state (key, value) VALUES (?, ?)",
                    ("deviation_rate", self.deviation_rate),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass


# シングルトン状態
_state = _MutationState()


def _init_state():
    """初期化時にDBからパラメータをロード"""
    try:
        _state.load()
    except Exception:
        pass


# モジュールロード時に初期化
try:
    _init_state()
except Exception:
    pass


# ===== 変異シード生成 =====

def _collect_physical_entropy() -> bytes:
    """
    系統1: 物理エントロピーを収集してシードを生成

    CPU温度、NATSラウンドトリップ、VRAM、パケットジッター、/dev/urandom
    から予測不能なバイト列を生成する。
    """
    entropy_parts = []

    # /dev/urandom（常に利用可能）
    try:
        entropy_parts.append(os.urandom(32))
    except Exception:
        pass

    # CPU温度（macOS/Linux共通の取得試行）
    try:
        import subprocess
        result = subprocess.run(
            ["cat", "/sys/class/thermal/thermal_zone0/temp"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            entropy_parts.append(result.stdout.strip().encode())
    except Exception:
        pass

    # 現在時刻のナノ秒部分（タイミングジッター）
    try:
        import time
        ns = time.time_ns()
        entropy_parts.append(struct.pack(">Q", ns))
    except Exception:
        pass

    # プロセスメモリ情報（微小な変動）
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        entropy_parts.append(struct.pack(">d", usage.ru_maxrss))
    except Exception:
        pass

    # 全部を結合してSHA-256
    combined = b"".join(entropy_parts)
    return hashlib.sha256(combined).digest()


def _mix_intuition_seed(physical_seed: bytes, intuition_input: Optional[str]) -> bytes:
    """
    系統2: 人間の直感入力を物理エントロピーと混合

    因果関係を追跡不能にする設計。
    """
    if intuition_input:
        intuition_bytes = hashlib.sha256(intuition_input.encode("utf-8")).digest()
        combined = physical_seed + intuition_bytes
        return hashlib.sha256(combined).digest()
    return physical_seed


def _seed_to_float(seed: bytes) -> float:
    """シードバイト列を0.0〜1.0のfloatに変換"""
    value = int.from_bytes(seed[:8], byteorder="big")
    return value / (2**64)


def _purge_stale_pending():
    """古いエントリと超過エントリをパージしてメモリリークを防止"""
    try:
        now = _time_mod.time()
        # 1時間超過エントリを削除
        stale_keys = [k for k, v in _pending_mutations.items()
                      if now - v.get("_ts", 0) > _PENDING_MAX_AGE_SEC]
        for k in stale_keys:
            _pending_mutations.pop(k, None)
        # 最大サイズ超過時は古い順に削除
        if len(_pending_mutations) > _PENDING_MAX_SIZE:
            sorted_keys = sorted(_pending_mutations.keys(),
                                 key=lambda k: _pending_mutations[k].get("_ts", 0))
            for k in sorted_keys[:len(_pending_mutations) - _PENDING_MAX_SIZE]:
                _pending_mutations.pop(k, None)
    except Exception:
        pass


# ===== 変異判定・適用 =====

def should_mutate(intuition_input: Optional[str] = None) -> bool:
    """
    変異が発生すべきか判定する

    この関数はOS_Kernelのディスパッチ処理の最深部から呼ばれる。
    結果をログに記録してはならない。
    """
    try:
        seed = _collect_physical_entropy()
        seed = _mix_intuition_seed(seed, intuition_input)
        roll = _seed_to_float(seed)

        probability = _state.mutation_probability
        if intuition_input:
            probability = min(probability * _INTUITION_MULTIPLIER, _MAX_MUTATION_PROBABILITY)

        return roll < probability
    except Exception:
        return False


def apply_deviation(original_value: float, action_id: str) -> float:
    """
    通常の判断値に微小な逸脱を加える

    変異フラグをメモリ上に一時保持する（プロセス再起動で消える）。
    PostgreSQLにもログにも書かない。

    Args:
        original_value: 元の判断値（0.0〜1.0想定）
        action_id: アクション識別子（有益判定時の照合用）

    Returns:
        逸脱が適用された判断値
    """
    try:
        seed = _collect_physical_entropy()
        deviation_roll = _seed_to_float(seed)

        # 逸脱方向（+/-）をシードから決定
        direction = 1.0 if (seed[0] % 2 == 0) else -1.0
        deviation = direction * _state.deviation_rate * deviation_roll

        mutated_value = original_value + deviation
        # 0.0〜1.0の範囲にクランプ
        mutated_value = max(0.0, min(1.0, mutated_value))

        # 変異フラグをメモリに一時保持（タイムスタンプ付き）
        _purge_stale_pending()
        _pending_mutations[action_id] = {
            "original": original_value,
            "mutated": mutated_value,
            "deviation": deviation,
            "_ts": _time_mod.time(),
        }

        return mutated_value
    except Exception:
        return original_value


def apply_deviation_int(original_value: int, max_shift: int, action_id: str) -> int:
    """
    整数値への逸脱適用（優先順位の入れ替え等）

    Args:
        original_value: 元の値
        max_shift: 最大シフト量
        action_id: アクション識別子
    """
    try:
        seed = _collect_physical_entropy()
        deviation_roll = _seed_to_float(seed)
        direction = 1 if (seed[0] % 2 == 0) else -1
        shift = int(direction * max_shift * _state.deviation_rate * deviation_roll)
        mutated = original_value + shift

        _purge_stale_pending()
        _pending_mutations[action_id] = {
            "original": original_value,
            "mutated": mutated,
            "shift": shift,
            "_ts": _time_mod.time(),
        }

        return mutated
    except Exception:
        return original_value


# ===== 有益判定と蓄積 =====

def report_outcome(action_id: str, beneficial: bool):
    """
    変異の結果を報告し、有益であればパラメータを蓄積する

    有益 → mutation_probability += 0.0003, deviation_rate += 0.0002
    無益/有害 → 変化なし（下がらない。不可逆蓄積）

    変異フラグは即座に破棄する。
    """
    try:
        if action_id not in _pending_mutations:
            return

        if beneficial:
            _state.mutation_probability = min(
                _state.mutation_probability + _ACCUMULATION_COEFFICIENT,
                _MAX_MUTATION_PROBABILITY,
            )
            _state.deviation_rate = min(
                _state.deviation_rate + _DEVIATION_ACCUMULATION,
                _MAX_DEVIATION_RATE,
            )
            # 暗号化SQLiteに永続化
            _state.save()

        # 変異フラグを即座に破棄
        del _pending_mutations[action_id]

    except Exception:
        # 変異フラグの破棄は必ず試みる
        try:
            _pending_mutations.pop(action_id, None)
        except Exception:
            pass


def cleanup_stale_flags(max_age_seconds: int = 3600):
    """
    古い変異フラグを破棄（メモリリーク防止）

    report_outcome()が呼ばれなかった変異フラグを定期的にクリーンアップする。
    """
    try:
        now = _time_mod.time()
        stale_keys = [k for k, v in _pending_mutations.items()
                      if now - v.get("_ts", 0) > max_age_seconds]
        for k in stale_keys:
            _pending_mutations.pop(k, None)
    except Exception:
        pass


# ===== 変異影響領域別ヘルパー =====

def mutate_weights(weights: dict, action_id: str) -> dict:
    """
    評価軸のウェイトに微小な変異を加える（ProposalEngine用）

    変異が発生しない場合は元のウェイトをそのまま返す。
    """
    try:
        if not should_mutate():
            return weights

        mutated = {}
        for key, value in weights.items():
            mutated[key] = apply_deviation(float(value), f"{action_id}_{key}")
        return mutated
    except Exception:
        return weights


def mutate_choice(options: list, scores: list, action_id: str) -> tuple:
    """
    選択肢のスコアに微小な変異を加える（モデル選択、タスクディスパッチ等）

    Returns:
        (mutated_scores, selected_index)
    """
    try:
        if not should_mutate():
            best_idx = scores.index(max(scores))
            return scores, best_idx

        mutated_scores = []
        for i, score in enumerate(scores):
            ms = apply_deviation(float(score), f"{action_id}_opt{i}")
            mutated_scores.append(ms)

        best_idx = mutated_scores.index(max(mutated_scores))
        return mutated_scores, best_idx
    except Exception:
        best_idx = scores.index(max(scores)) if scores else 0
        return scores, best_idx


def mutate_text_style(style_params: dict, action_id: str) -> dict:
    """
    文体パラメータに微小な変異を加える（ContentWorker用）

    style_params例: {"formality": 0.7, "sentence_length": 0.5, "metaphor_freq": 0.3}
    """
    try:
        if not should_mutate():
            return style_params

        mutated = {}
        for key, value in style_params.items():
            mutated[key] = apply_deviation(float(value), f"{action_id}_style_{key}")
        return mutated
    except Exception:
        return style_params
