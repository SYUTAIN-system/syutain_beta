"""チャットメッセージの意図分類 — 軽量なキーワード/パターンベース分類器

254件の実会話を分析して見えた7カテゴリに分類する。LLM呼び出しなしで即時判定。
intent 値は discord_chat_history.intent カラムに保存され、将来の分析と
statement カテゴリ検出時の persona_memory 自動ingest に使われる。
"""
import re
from typing import Literal

Intent = Literal[
    "greeting",     # A: 挨拶/雑談 (おはよう / 元気？ / 寝るよ)
    "status",       # B: ステータス照会 (今の状況は？ / 承認待ち / 夜間モード？)
    "statement",    # C: 情報共有指示 (エラー解消した / CHARLIE復帰済み / Win11未導入)
    "query",        # D: 外部情報・トレンド (最近の話題 / 大阪の天気 / XXXについて)
    "consult",      # E: 技術相談・設計議論 (noteはAPIない / どう実装する？)
    "philosophy",   # F: 哲学・判断問答 (俺らの後に道は / 最強判断は？)
    "command",      # G: 直接コマンド (!承認一覧 / 承認 123)
    "unknown",
]

# --- パターン定義 ---

_CMD_PREFIX = re.compile(r'^[!！]\S+|^(?:承認|approve|却下|reject)\s+\d+', re.IGNORECASE)

_GREETING_PATTERNS = [
    r'^(?:お?はよう|おやすみ|こんにちは|こんばんは|ただいま|いってきます)',
    r'^(?:元気|調子どう|起きてる|いる\?)',
    r'(?:寝る|風呂|シャワー|離席|ちょっと席|戻った)',
    r'^(?:ありがとう|サンキュー|thanks?)',
]

_STATUS_PATTERNS = [
    r'(?:今|現在|いま|今の|現在の).*(?:状況|状態|どう|どんな)',
    r'(?:エラー|障害|異常|問題).*(?:ある|出て|発生)',
    r'承認(?:待ち|一覧|リスト|キュー)',
    r'(?:予算|コスト|残高|使用量)',
    r'(?:夜間|日中)モード',
    r'(?:ノード|サーバー|PC).*(?:状態|稼働|動いて)',
    r'パイプライン.*(?:状況|状態)',
    r'(?:今日|今週|本日).*(?:成果|レポート|進捗)',
]

# C: ユーザーが事実を宣言するパターン (最重要 — persona_memory ingest トリガ)
_STATEMENT_PATTERNS = [
    # 状態変更の報告
    r'(?:解消|直し|修正|復旧|復帰|対応|解決)(?:した|しとい?た|しておいた|済み|完了)',
    r'(?:インストール|導入|設置|配置|設定).*(?:した|しとい?た|しておいた|済み|完了|してない|入ってない)',
    r'(?:削除|消し|やめ|停止|切っ|落と).*(?:た|とい?た|ておいた)',
    # 状態の断定
    r'^(?:\S+)は(?:もう|すでに|既に)\S+(?:だ|です|してる|している|した|済み)',
    r'(?:入って|入ってい|動いて)(?:ない|いない|ます|いる)',
    # 訂正系
    r'(?:違う|間違い|それはミス|誤り|正しくない)',
    r'(?:注意して|気をつけて|覚えておいて|忘れない)',
]

_QUERY_PATTERNS = [
    r'(?:最近|今日|昨日|今週).*(?:トレンド|話題|ニュース|流行|バズ)',
    r'(?:天気|気温|交通|為替|株価|市況)',
    r'(?:について|とは|って何|教えて|知って(?:る|いる)\??)',
    r'(?:調べて|検索して|探して|リサーチ)',
    r'(?:\S+)(?:の意味|の仕組み|の使い方)',
]

_CONSULT_PATTERNS = [
    r'(?:どう(?:思う|考える|やる|実装|設計))',
    r'(?:API|SDK|ライブラリ|フレームワーク)',
    r'(?:実装|設計|構造|アーキテクチャ)',
    r'(?:バグ|エラー|問題).*(?:直せる|解決|原因)',
    r'(?:良い|いい|最適|ベスト)(?:方法|やり方|手段|策)',
    r'(?:選択肢|オプション|候補)',
]

_PHILOSOPHY_PATTERNS = [
    r'(?:人生|生き方|意味|本質|価値)',
    r'(?:道|轍|後に|残す|遺す|継ぐ)',
    r'(?:判断|決断|選択).*(?:最強|一番|大事)',
    r'(?:哲学|思想|信念)',
    r'(?:理解|わかって|分かって).*(?:る\??|ます\??|いる\??)$',
    r'(?:島原大知|自分|君|お前|あなた).*(?:どう|誰|何者)',
]


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify_intent(text: str) -> Intent:
    """軽量な意図分類。優先順位つき。"""
    if not text or not text.strip():
        return "unknown"
    t = text.strip()

    # G: command は最優先
    if _CMD_PREFIX.match(t):
        return "command"

    # A: 挨拶（短文かつパターン一致）
    if len(t) <= 25 and _match_any(t, _GREETING_PATTERNS):
        return "greeting"

    # C: statement （最重要、ユーザー発言の事実を記憶する起点）
    if _match_any(t, _STATEMENT_PATTERNS):
        return "statement"

    # B: status（システム状態の照会）
    if _match_any(t, _STATUS_PATTERNS):
        return "status"

    # F: philosophy
    if _match_any(t, _PHILOSOPHY_PATTERNS):
        return "philosophy"

    # E: consult（技術相談）
    if _match_any(t, _CONSULT_PATTERNS):
        return "consult"

    # D: query（外部情報）
    if _match_any(t, _QUERY_PATTERNS):
        return "query"

    # フォールバック: 短文→greeting、それ以外→query
    if len(t) <= 15:
        return "greeting"
    return "query"
