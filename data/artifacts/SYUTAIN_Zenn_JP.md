---
title: "非エンジニアがClaude Codeで51K行の分散AIシステムを構築した技術選定と実装の記録"
emoji: "🤖"
type: "tech"
topics: ["NATS", "PostgreSQL", "Tailscale", "Claude", "分散システム"]
published: false
---

# 非エンジニアがClaude Codeで51K行の分散AIシステムを構築した技術選定と実装の記録

## はじめに

筆者はプログラミング経験ゼロの映像クリエイター。Claude Codeでコードを書かせ、設計判断のみ自分で行い、4台のPC上で動く自律型AIシステム「SYUTAINβ」を構築した。

本記事では、技術選定の根拠と実装の詳細を、実際のコードパスと数値を交えて解説する。

**実数値（2026年4月時点、本番DB直接取得）：**
| 項目 | 値 |
|------|-----|
| Python | 51,672行 / 132ファイル |
| PostgreSQL | 45テーブル / 30,174イベント |
| 月間LLM呼び出し | 9,700回（85.2%ローカル） |
| 月間コスト | ¥854 |
| エージェント | 20体 |
| ツール | 67モジュール |
| スケジューラジョブ | 91件 |

---

## 1. ノード間通信: なぜNATS JetStreamか

### 比較検討

| 技術 | 遅延 | 永続化 | 運用コスト | 適合度 |
|------|------|--------|-----------|--------|
| Redis Pub/Sub | 低 | なし | 低 | △ メッセージ喪失リスク |
| RabbitMQ | 中 | あり | 中 | ○ だがオーバースペック |
| Kafka | 低 | あり | 高 | × 4台には重すぎる |
| **NATS JetStream** | **極低** | **あり** | **低** | **◎ 軽量+永続+クラスタ** |
| HTTP直接 | 高 | なし | なし | △ フォールバック用 |

4台のPCで動かす個人開発において、Kafkaのような重量級は不要。Redis Pub/Subはメッセージ喪失が怖い。NATSはバイナリ1つで動き、JetStreamで永続化もできる。

### 実装

`tools/nats_client.py`（247行）

```python
# JetStream 6ストリーム定義
STREAMS = {
    "TASKS":     {"subjects": ["task.>"],     "retention": "7d"},
    "AGENTS":    {"subjects": ["agent.>"],    "retention": "1d"},
    "PROPOSALS": {"subjects": ["proposal.>"], "retention": "30d"},
    "MONITOR":   {"subjects": ["monitor.>"],  "retention": "3d"},
    "BROWSER":   {"subjects": ["browser.>"],  "retention": "7d"},
    "INTEL":     {"subjects": ["intel.>"],    "retention": "30d"},
}
```

タスクディスパッチはRequest-Replyパターン：

```python
# agents/executor.py — リモートノードへのタスク送信
response = await nats.request(
    f"req.task.{assigned_node}",  # req.task.bravo, req.task.charlie, etc.
    payload,
    timeout=180.0,
)
```

NATSの`req.task.*`サブジェクトはJetStreamストリームに**含めない**（Request-Replyとストリームキャプチャの衝突を回避するため）。ストリーム用は`task.assign.*`を使い分けている。

### 4ノードRAFTクラスタ

```
# config/nats-server.conf
cluster {
    name: "syutain"
    routes = [
        nats-route://100.x.x.x:6222   # ALPHA
        nats-route://100.x.x.x:6222   # BRAVO
        nats-route://100.x.x.x:6222   # CHARLIE
        nats-route://100.x.x.x:6222   # DELTA
    ]
}
jetstream {
    store_dir: "/path/to/nats-data/jetstream"
    max_mem: 256MB
    max_file: 1GB
}
```

---

## 2. 状態管理: PostgreSQL + SQLite の使い分け

### なぜ2種類か

| データ | 保存先 | 理由 |
|--------|--------|------|
| ゴール、タスク、承認 | PostgreSQL (ALPHA) | 複数ノードから参照。一貫性が必要 |
| LLMコスト、イベントログ | PostgreSQL | 分析クエリが必要 |
| ペルソナ記憶（547件） | PostgreSQL + pgvector | 埋め込みベクトル検索 |
| ノードローカルキャッシュ | SQLite (各ノード) | ネットワーク不要。高速 |
| 突然変異エンジン | SQLCipher (DELTA) | 暗号化必須。完全隔離 |

### テーブル設計（抜粋）

`tools/db_init.py`（738行）に45テーブルのDDLが定義されている。

```sql
-- 5段階ループの核: ゴールパケット
CREATE TABLE IF NOT EXISTS goal_packets (
    goal_id TEXT PRIMARY KEY,
    raw_goal TEXT,
    parsed_objective TEXT,
    success_definition JSONB,
    status TEXT DEFAULT 'pending',
    total_steps INTEGER DEFAULT 0,
    total_cost_jpy REAL DEFAULT 0,
    progress_log JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- エピソード記憶（MemRL: Q値学習付き）
CREATE TABLE IF NOT EXISTS episodic_memory (
    id SERIAL PRIMARY KEY,
    task_type TEXT,
    description TEXT,
    outcome TEXT CHECK (outcome IN ('success', 'failure', 'partial')),
    lessons TEXT,
    q_value REAL DEFAULT 0.5,  -- 有用度スコア（学習で更新）
    retrieval_count INTEGER DEFAULT 0,
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

`episodic_memory`はMemRL（Memory-based Reinforcement Learning）のアイデアを実装したもの。タスク実行のたびにエピソードを記録し、次回の類似タスクで有用だったエピソードのQ値を上げる。現在102エピソード、10スキルが自動抽出されている。

### 接続プール

```python
# tools/db_pool.py — asyncpg非同期プール
pool = await asyncpg.create_pool(
    dsn=DATABASE_URL,
    min_size=2,
    max_size=10,
)
```

---

## 3. ネットワーク: Tailscale VPN

### なぜVPNか

4台のPCは自宅の異なるネットワーク機器に接続されている。ポートフォワーディングは管理が面倒で、セキュリティリスクもある。

| 方式 | 設定難易度 | セキュリティ | NAT越え |
|------|-----------|-------------|---------|
| ポートフォワーディング | 高 | 低（ポート開放） | 手動 |
| WireGuard手動 | 中 | 高 | 手動 |
| **Tailscale** | **極低** | **高（WireGuard）** | **自動** |
| ZeroTier | 低 | 高 | 自動 |

Tailscaleを選んだ理由はシンプル。インストールしてログインするだけで4台が`100.x.x.x`のプライベートIPで通信できる。証明書も自動。SSH、NATS、PostgreSQL、Ollama——全部Tailscale IP経由。

```yaml
# config/node_bravo.yaml
node_name: bravo
tailscale_ip: 100.x.x.x
nats_url: nats://100.x.x.x:4222  # ALPHA経由
```

---

## 4. 9層ループ防止の実装

`tools/loop_guard.py`（441行）

自律エージェントの最大のリスクは暴走。同じことを無限に繰り返す、予算を使い尽くす、意味のないリトライを続ける。9つの層で構造的に防ぐ。

```python
# 各層の判定結果
class LoopGuardResult:
    triggered: bool           # 発動したか
    layer: int               # 何層目か (1-9)
    layer_name: str          # 層の名前
    action: str              # CONTINUE / SWITCH_PLAN / ESCALATE / EMERGENCY_STOP
    reason: str              # 発動理由
```

### 層の詳細

| 層 | 名称 | トリガー条件 | アクション |
|----|------|-------------|-----------|
| 1 | リトライ予算 | 同一タスク2回超 | SWITCH_PLAN |
| 2 | 同一失敗クラスタ | 同じエラー2回→30分凍結 | SWITCH_PLAN |
| 3 | プランナーリセット | 3回re-plan超 | ESCALATE |
| 4 | 価値ガード | 無価値リトライ検出 | SWITCH_PLAN |
| 5 | 承認デッドロック | 承認ループ検出 | ESCALATE |
| 6 | コスト・時間ガード | 80%予算/60分/100kトークン | ESCALATE |
| 7 | Emergency Kill | 50ステップ/90%予算/5同一エラー/120分 | EMERGENCY_STOP |
| 8 | セマンティックループ | 出力の反復パターン検出 | SEMANTIC_STOP |
| 9 | Cross-Goal干渉 | 複数ゴール間の資源競合 | INTERFERENCE_STOP |

本番で最も発動するのは層2（同一失敗クラスタ）と層7（Emergency Kill、予算起因）。層8のセマンティックループ検出は、LLMが同じ内容を言い換えて繰り返すケースを3回捕捉している。

```python
# agents/stop_decider.py — LoopGuardエラー時は安全側に倒す
except Exception as e:
    logger.error(f"LoopGuardチェック自体がエラー（安全側ESCALATE）: {e}")
    return StopDecision(
        decision="ESCALATE",
        reason=f"LoopGuardチェック自体がエラー: {e}",
    )
```

LoopGuard自体が壊れた場合も安全側に倒す設計。「ガードが壊れたから処理を続行」は許さない。

---

## 5. 3層提案エンジン

`agents/proposal_engine.py`（978行）

自律システムが「次に何をすべきか」を自分で考える仕組み。

```
Layer 1: 直感的提案（ローカルLLM）
    ↓ Revenue Score 100点満点で評価
Layer 2: 反論（API LLM）
    ↓ リスク、失敗条件、機会コスト
Layer 3: 代替案（ローカルLLM）
    ↓ 異なるアプローチ、工数/収益見積もり
```

3層構造にしている理由は、1つのLLMに「提案して」「反論して」「代替案出して」と言うと、自分自身に遠慮する傾向があるため。層ごとに異なるモデルを使うことで、自己評価バイアスを構造的に排除している。

66件の提案が生成され、うちスコア80以上の提案は自動承認→ゴールに変換→5段階ループで実行される。

---

## 6. LLMルーティング: choose_best_model_v6()

`tools/llm_router.py`（1,108行）

全LLM呼び出しはこの関数を経由する（CLAUDE.mdルール5）。

```python
def choose_best_model_v6(
    task_type: str,           # "content", "analysis", "classification", etc.
    quality: str = "medium",  # "low", "medium", "high"
    budget_sensitive: bool = True,
    local_available: bool = True,
    needs_japanese: bool = False,
    final_publish: bool = False,
) -> dict:
```

ティア構成：

| ティア | モデル | コスト | 用途 |
|--------|--------|--------|------|
| S | GPT-5.4, Claude Opus 4.6 | 高 | 最終品質、Computer Use |
| A | DeepSeek V3.2, Gemini 2.5 Pro | 中 | デフォルトAPI |
| B | GPT-5-Nano, Gemini Flash | 低 | 軽量タスク |
| L | qwen3.5:9b/4b (Ollama) | 0 | ローカル推論 |

85.2%がティアL。タスクタイプに応じてDELTA（4b、軽量分類）→BRAVO/CHARLIE（9b、ラウンドロビン）→API（品質不足時のみ）のフォールバックチェーンが組まれている。

### セマンティックキャッシュ

`tools/semantic_cache.py`（493行）

同じようなプロンプトに対する応答をpgvectorでキャッシュ。コサイン類似度0.92以上で即返却。research/analysis/classification系のタスクに適用し、SNS生成やnote記事などの創作系は除外。

---

## 7. PDL: 自律デバッグパイプライン

`pdl/worker.sh`（352行）

crontab（10分間隔）で起動し、Codex CLI経由でコード修正を自律実行する。

```
cron起動 → PAUSEチェック → 予算チェック(¥36/日)
  → claude_code_queue からタスク取得
  → Git worktree作成（メインブランチに影響しない）
  → Codex exec でコード分析+修正
  → 4段階テストゲート（構文/import/禁止ファイル/差分サイズ）
  → commit → GitHub push → PR作成
  → Tier判定: 非重要タスク→自動マージ+rsyncデプロイ
             重要タスク→Discord通知→人間レビュー
```

ファイル保護3段階:
- **FORBIDDEN**: os_kernel.py, emergency_kill.py, approval_manager.py, .env — 絶対変更不可
- **REVIEW_REQUIRED**: app.py, scheduler.py, llm_router.py — 人間承認必須
- **FREE**: その他 — テスト通過で自動OK

2026年4月2日に初の自律PR（#1）がマージされた。3ファイル変更、170行追加。

---

## 8. 5段階自律ループ

`agents/perceiver.py`（410行）→ `agents/planner.py` → `agents/executor.py` → `agents/verifier.py` → `agents/stop_decider.py`

ゴールは5段階を経て処理される。

```
PERCEIVE → PLAN → EXECUTE → VERIFY → DECIDE
                                        │
                              COMPLETE / CONTINUE / ESCALATE / STOP
                                        │
                              if CONTINUE → back to PERCEIVE
```

### Perceiver: 14項目チェックリスト

各ゴールの実行前に、環境全体を走査する。

```python
# agents/perceiver.py — 14-point checklist
checklist = [
    self._check_node_capabilities(),    # 4ノードの可用性
    self._check_budget_remaining(),      # 残予算
    self._check_persona_context(),       # ペルソナ記憶から価値観を取得
    self._check_strategy_files(),        # strategy/*.md からガイドライン
    self._check_mcp_tools(),             # MCP接続状態
    self._check_browser_capability(),    # ブラウザ自動操作の可否
    self._check_previous_attempts(),     # 過去の試行履歴
    self._check_active_goals(),          # 進行中ゴールとの競合
    # ... 他6項目
]
results = await asyncio.gather(*checklist, return_exceptions=True)
```

コンテキストが8,000文字を超えた場合は優先度順に圧縮する。エージェントマップが最初に圧縮され、Intel（情報収集結果）が最後まで残る。

### Verifier: Sprint Contract

実行結果の検証は、タスク定義時に生成された「成功条件」と照合する。単純な成否ではなく、`success` / `partial` / `failure` の3値判定。部分成功の場合は、達成済み部分を保持して未達成部分だけ再計画する。

---

## 9. Brain-α: ペルソナ駆動の自律判断

`brain_alpha/persona_memory.py`（547件のメモリ）

Brain-αは「この判断は島原大知としてOKか」を毎回チェックする仕組み。ペルソナメモリには価値観、タブー、文体の癖、好みの表現が格納されている。

```python
# brain_alpha/persona_memory.py — カテゴリ
categories = [
    "identity",      # 名前、肩書き、経歴
    "values",        # 大事にしていること
    "taboo",         # 絶対にやらないこと
    "style",         # 文体の癖、好みの表現
    "knowledge",     # 専門領域
    "dialogue_log",  # 過去の対話から抽出した判断基準
]
```

pgvectorで埋め込みベクトル検索し、現在のコンテキストに関連するメモリを取得する。tabooカテゴリはCLAUDE.mdルール26で絶対違反禁止。

この仕組みがなかった初期、AIは「コードを書く」という投稿を量産した——コードを書けない人間について。Brain-α導入後、ペルソナ逸脱は検知可能になった。

---

## 10. セキュリティ: コンテンツ自動除去

`tools/content_redactor.py`

自律システムがSNSや記事を自動生成・公開する以上、秘密情報の漏洩は構造的に防ぐ必要がある。

```python
# tools/content_redactor.py — 除去パターン（一部）
REDACT_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', '[REDACTED_API_KEY]'),
    (r'ghp_[a-zA-Z0-9]{30,}', '[REDACTED_GITHUB_TOKEN]'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]'),
    (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[REDACTED_EMAIL]'),
]
```

note.com公開前にredactorを通し、除去後も残存パターンがあれば公開を自動中止する。SNS投稿も同様。

GitHub公開にあたっても、全Pythonファイルからハードコードされた内部IPアドレス・SSHユーザー名を`.env`経由に移行し、設定ファイルは`.gitignore`で除外した。

---

## 11. 失敗から生まれた方法論: ハーネスエンジニアリング

3月28日に名前をつけた。SYUTAINβの開発方法論。

```
エラー発生
  → 即時修正（止血）
  → 根本原因分析（なぜ起きたか）
  → ガードレール構築（そのエラーの"種類全体"を構造的に不可能にする）
  → CLAUDE.mdルールに追加（AIが再導入するのを防ぐ）
  → エピソード記憶に記録（システムが次回から学習する）
```

26条のCLAUDE.mdルールは、全てこの方法論から生まれた。1つのルールの裏に、最低1つの本番障害がある。

例：
- **ルール4**（3回繰り返したら停止）← セマンティックループ検知器が1日15回発動した日
- **ルール14**（macOSでdeclare -Aを使わない）← bash 3.2に連想配列がなく黙って失敗
- **ルール23**（ペルソナメモリを参照してから判断）← 「コードを書く」投稿を量産

「同じバグを二度出さない」ではなく「**同じ種類のバグ**を二度出さない」。個別修正ではなく構造的予防。

---

## 12. 正直な課題

- **非エンジニアが設計した限界**: アーキテクチャの美しさよりも「動くこと」を優先している。循環依存が3箇所あった（遅延importで回避済みだが根本解決ではない）
- **デッドコード207件**: 51K行のうち207関数が未使用。Phase 2未実装の機能が残っている
- **テストカバレッジ低**: 構文チェックと統合スモークテストはあるが、ユニットテストはほぼない
- **LLMの品質に依存**: 事実検証システムを入れたが、LLMが生成する内容の正確性を100%保証する手段はない

---

## コードの公開

SYUTAINβの全コードをGitHubで公開している。

https://github.com/SYUTAIN-system/syutain_beta

本記事で触れた全てのファイル——`tools/loop_guard.py`、`agents/proposal_engine.py`、`tools/llm_router.py`、`brain_alpha/persona_memory.py`——実際のコードを読める。非エンジニアがAIに書かせたコードが、技術者の目にどう映るかは分からない。でも隠す理由はない。

APIキーやIPアドレスなどの秘密情報は`.env`に分離し、`.gitignore`で除外済み。`.env.example`を参考に環境変数を設定すれば、同じアーキテクチャを再現できる。

---

## まとめ

51,672行、45テーブル、91ジョブ、9層ループ防止。

これを非エンジニアが作った。Claude Codeが全部書いた。自分は設計と判断だけ。

技術的に美しいかどうかは分からない。循環依存が3箇所ある。デッドコードが207関数ある。テストカバレッジは低い。

でも、動いている。4台のマシンで、月854円で、24時間止まらずに。

AIは、自分の思考を映す鏡だ。設計が甘ければ甘い出力が返ってくる。判断が曖昧なら曖昧な結果が出る。でも、的確な問いを投げれば、一人では絶対に到達できない場所まで連れて行ってくれる。

コードは全て公開した。壊れた記録も、恥ずかしい設計も、全部。それがドキュメンタリーだから。

---

**Links:**
- GitHub: https://github.com/SYUTAIN-system/syutain_beta
- Bluesky: https://bsky.app/profile/syutain.bsky.social
- X: https://x.com/syutain_beta / https://x.com/Sima_daichi
- Threads: https://www.threads.net/@syutain_beta
- note: https://note.com/5070

#NATS #PostgreSQL #Tailscale #Claude #分散システム #個人開発 #AI #SYUTAINβ
