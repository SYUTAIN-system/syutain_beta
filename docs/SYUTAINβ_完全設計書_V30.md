# SYUTAINβ 完全設計書 V30

> **「コードを一行も書けない人間が、AIエージェントと共に自律型事業OSを構築し、その全過程を公開するドキュメンタリー」**

**最終更新**: 2026-04-04
**V30テーマ**: Build in Public + GitHub公開 + 6層品質防御 + 27Bモデル統合 + intel活用パイプライン

---

## システム統計（2026年4月4日、本番DB直接取得）

| 項目 | 値 |
|------|-----|
| Python | 52,325行 / 132ファイル |
| TypeScript/TSX | 57,681行（Next.js Web UI） |
| PostgreSQL | 45テーブル / 32,066イベント |
| ゴール処理 | 97件（完了52 / キャンセル35 / エスカレーション8） |
| タスク実行 | 1,068件 |
| 承認処理 | 364件（自動188 / 手動169 / 却下7） |
| エピソード記憶 | 137件 / 自動抽出スキル20件 |
| ペルソナ記憶 | 541件（11カテゴリ） |
| 情報収集 | 1,358件 |
| SNS自動投稿 | 621件（Bluesky 298+, Threads 160+, X 112+） |
| 提案生成 | 70件 |
| LLM呼び出し | 10,390回（ローカル74.0%） |
| 累計LLMコスト | ¥968.86 |
| LoopGuard発動 | 54回 |
| エージェント | 20体 |
| ツール | 67モジュール |
| スケジューラジョブ | 70件 |
| APIエンドポイント | 64本 |
| GitHub | https://github.com/SYUTAIN-system/syutain_beta（Public） |

---

## 第1章: プロジェクト概要

### 1.1 SYUTAINβとは

4台のPC（Mac mini M4 Pro、RTX 5070マシン、RTX 3080マシン、GTX 980Tiマシン）をTailscale VPNで接続し、NATSメッセージングで通信する自律型AI事業OS。

6体のAI「役員」（CORTEX/FANG/NERVE/FORGE/MEDULLA/SCOUT）が24時間稼働し、情報収集→分析→コンテンツ生成→品質検証→公開→学習のループを自律実行する。

全コードはAI（Claude Code）が生成。設計と判断は島原大知（非エンジニア）が担当。

### 1.2 V30の位置づけ

V29からの主要変更:
1. **Build in Public方針の全階層反映** — note記事テーマを「SYUTAINβで何が起きたか」に統一
2. **GitHub公開** — 全コードをPublicリポジトリとして公開、セキュリティ対応完了
3. **6層品質防御** — note記事の品質ゲートを大幅強化
4. **27Bモデル統合** — BRAVO上でqwen3.5:27bを高品質ローカル推論に使用
5. **KV Cache Q8全ノード有効化** — VRAM効率改善
6. **intel活用パイプライン** — 英語記事取り込み、SNS/記事の両方に情報注入
7. **SNS拡散力最大化** — Blueskyリンクカード、ハッシュタグ、noteリンク自動付与

---

## 第2章: 設計原則

### 2.1 5つの設計原則

1. **モデル独立** — 特定のLLMに依存しない。モデルは手段
2. **安全側倒し** — ガードが壊れたらESCALATE、CONTINUE不可
3. **段階的実装** — 各Stepを完了してから次へ
4. **資産化** — 全中間成果物をDBに保存。途中停止しても資産
5. **Build in Public** — 失敗も成功も全て公開。ドキュメンタリーとして記録

### 2.2 CLAUDE.md 26条ルール（V29準拠、V30継続）

1. 設計書の設計を最優先
2. V25は原典、過去設計を消さない
3. 段階的実装
4. 同じ処理3回→停止してエスカレーション
5. LLM呼び出しは必ずchoose_best_model_v6()経由
6. 2段階精錬（ローカル→API）
7. 全ツール呼び出しはtry-except+log_usage()
8. .envの内容をログに出力しない。APIキーをハードコードしない
9. 設定値はDBまたは.envから読み込む
10. 戦略ファイル参照してからコンテンツ生成
11. SNS/商品/価格/暗号通貨はApprovalManager経由
12. 重要な判断はDiscord+Web UIで通知
13. ローカルLLM配置: ALPHA=Qwen3.5-9B(MLX,オンデマンド), BRAVO=Qwen3.5-9B+27B, CHARLIE=Qwen3.5-9B, DELTA=Qwen3.5-4B
14. macOSでdeclare -Aを使わない
15. タスクをPostgreSQLに記録してLoopGuard 9層で監視
16. Emergency Kill条件厳守
17. ノード不可時はフォールバック実装
18. 全中間成果物をDBに保存
19. NATSでノード間通信、HTTPはフォールバック
20. MCP接続は動的確認、不可時は代替手段
21. 4台全てPhase 1から稼働
22. 突然変異エンジンは完全隔離
23. Brain-αはpersona_memory参照してから判断
24. 新判断基準はdaichi_dialogue_logに記録
25. セッション終了時にmemory_manager.save_session_memory()
26. tabooカテゴリは絶対に違反しない

---

## 第3章: インフラストラクチャ

### 3.1 4ノード構成

#### ALPHA（Mac mini M4 Pro 16GB RAM）— 司令塔

| 項目 | 内容 |
|------|------|
| IP | Tailscale VPN / ローカル |
| OS | macOS / launchd |
| GPU | Apple M4 Pro（統合メモリ） |
| ローカルLLM | Qwen3.5-9B（MLX、オンデマンド起動） |
| 常駐エージェント | OS_Kernel, ApprovalManager, ProposalEngine, WebUIServer, ChatAgent |
| サービス | PostgreSQL, NATS Server(JetStream), FastAPI(:8000), Next.js(:3000), Caddy(:8443) |
| 特記 | 司令塔業務最優先。推論はBRAVO/CHARLIEに委譲 |

#### BRAVO（Ryzen + RTX 5070 12GB）— 実行者 + 高品質推論

| 項目 | 内容 |
|------|------|
| IP | Tailscale VPN / ssh $REMOTE_SSH_USER@$BRAVO_IP |
| OS | Ubuntu 24.04 / systemd |
| GPU | RTX 5070 12GB VRAM |
| RAM | 31GB |
| ローカルLLM | **qwen3.5:9b**（通常推論）+ **qwen3.5:27b**（高品質、5 tok/s、GPU+CPUオフロード）+ nemotron-jp + nemotron-mini |
| Ollama設定 | OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0 |
| 常駐エージェント | ComputerUseAgent, ContentWorker, BrowserAgent |
| ブラウザ | 4層構成: LightPanda(:9222)→Stagehand→Chromium(:9223)→ComputerUse(gpt-5.4) |
| 特記 | 推論優先ノード。27Bモデルはhighest_localティア用 |

#### CHARLIE（Ryzen 9 + RTX 3080 10GB）— 推論エンジン

| 項目 | 内容 |
|------|------|
| IP | Tailscale VPN / ssh $REMOTE_SSH_USER@$CHARLIE_IP |
| OS | Ubuntu 24.04（Win11デュアルブート） / systemd |
| GPU | RTX 3080 10GB VRAM |
| ローカルLLM | Qwen3.5-9B(Ollama常駐) + nemotron-jp |
| Ollama設定 | OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0 |
| 特記 | Win11ブート時はオフライン。BRAVO+DELTAでフォールバック |

#### DELTA（Xeon E5 + GTX 980Ti 6GB + 48GB RAM）— 監視・補助

| 項目 | 内容 |
|------|------|
| IP | Tailscale VPN / ssh $REMOTE_SSH_USER@$DELTA_IP |
| OS | Ubuntu 24.04 / systemd |
| GPU | GTX 980Ti 6GB VRAM |
| RAM | 48GB（CPU推論のバッファ用途あり） |
| ローカルLLM | Qwen3.5-4B(Ollama、GPU-first) |
| Ollama設定 | OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0 |
| 特記 | 突然変異エンジン専用（SQLCipher暗号化DB） |

### 3.2 ネットワーク

- Tailscale VPN（WireGuardベース、100.x.x.x CGNAT範囲）
- NATS JetStream 4ノードRAFTクラスタ
- 6ストリーム: TASKS, AGENTS, PROPOSALS, MONITOR, BROWSER, INTEL

### 3.3 KV Cache量子化（V30新規）

全ノードで有効化済み:
```
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
```
- KV cacheのVRAM使用量50%削減（実測）
- 品質劣化: perplexity +0.004（実測、誤差範囲内）
- Qwenモデルで安定動作確認済み
- **Gemmaモデルでは使用禁止**（5倍速度低下バグ、Ollama Issue #11949）

---

## 第4章: LLMモデル選択（V30拡張）

### 4.1 ティア構成

| ティア | モデル | ノード | 実測速度 | 用途 |
|--------|-------|-------|---------|------|
| **L** | qwen3.5:4b | DELTA | 31.7 tok/s | 分類・タグ付け・軽量タスク |
| **L** | qwen3.5:9b | BRAVO/CHARLIE | 89 tok/s | 通常の生成・分析 |
| **L** | nemotron-jp | BRAVO/CHARLIE | ~35 tok/s | 日本語特化タスク |
| **L+** | **qwen3.5:27b** | **BRAVO固定** | **5.0 tok/s** | **批評・検証・高品質判断（V30新規）** |
| **A** | gemini-2.5-flash | API | — | API優先タスク |
| **A** | deepseek-v3.2 | API | — | 最終品質 |
| **A** | claude-haiku-4-5 | API | — | 高推論力タスク |
| **A** | gemini-2.5-pro | API | — | 最終公開品質 |
| **S** | gpt-5.4 | API | — | Computer Use / Tool Search |

### 4.2 choose_best_model_v6() ルーティング

```python
quality="low"           → DELTA 4B or BRAVO/CHARLIE 9B
quality="medium"        → ローカル9B or Gemini Flash
quality="high"          → API (Gemini Flash / Claude Haiku / DeepSeek)
quality="highest_local" → BRAVO 27B（V30新規、高品質ローカル推論）
final_publish=True      → API (Gemini Pro / Claude Sonnet)
```

### 4.3 モデル別実績（本番DB、10,390回）

| モデル | 呼び出し数 | コスト(円) | 比率 |
|--------|-----------|-----------|------|
| qwen3.5-9b | 3,873 | ¥0 | 37.3% |
| nemotron-jp | 2,627 | ¥0 | 25.3% |
| qwen3.5-4b | 1,161 | ¥0 | 11.2% |
| jina-embeddings-v3 | 1,193 | ¥11.93 | 11.5% |
| gemini-2.5-flash | 550 | ¥126.91 | 5.3% |
| deepseek-v3.2 | 315 | ¥26.09 | 3.0% |
| jina-reader | 261 | ¥130.50 | 2.5% |
| claude-haiku-4-5 | 226 | ¥232.76 | 2.2% |
| tavily-search | 140 | ¥280.00 | 1.3% |
| gpt-5.4 | 20 | ¥73.42 | 0.2% |
| 他 | 24 | ¥87.25 | 0.2% |
| **合計** | **10,390** | **¥968.86** | **ローカル74.0%** |

---

## 第5章: 5段階自律ループ

```
PERCEIVE → PLAN → EXECUTE → VERIFY → DECIDE
                                       │
                             COMPLETE / CONTINUE / ESCALATE / STOP
                                       │ if CONTINUE
                             back to PERCEIVE
```

### 5.1 Perceiver（14項目チェックリスト）
`agents/perceiver.py`（410行）— ノード可用性、残予算、ペルソナ記憶、戦略ファイル、MCP接続、ブラウザ能力、過去試行履歴、競合ゴール等を並列走査

### 5.2 Planner
`agents/planner.py` — DAG生成、ノード割当、依存ツリー構築

### 5.3 Executor
`agents/executor.py` — NATS経由でタスクディスパッチ、2段階精錬（ローカル→API）

### 5.4 Verifier
`agents/verifier.py` — Sprint Contract（事前合意の成功条件）照合、3値判定（success/partial/failure）

### 5.5 9層LoopGuard

| 層 | 名称 | トリガー条件 | アクション | 本番発動数 |
|----|------|-------------|-----------|-----------|
| 1 | リトライ予算 | 同一タスク2回超 | SWITCH_PLAN | 6 |
| 2 | 同一失敗クラスタ | 同じエラー2回→30分凍結 | SWITCH_PLAN | **27** |
| 3 | プランナーリセット | 3回re-plan超 | ESCALATE | 1 |
| 4 | 価値ガード | 無価値リトライ検出 | SWITCH_PLAN | 0 |
| 5 | 承認デッドロック | 承認ループ検出 | ESCALATE | 0 |
| 6 | コスト・時間ガード | 80%予算/60分/100kトークン | ESCALATE | 3 |
| 7 | Emergency Kill | 50ステップ/90%予算/5同一エラー/120分 | EMERGENCY_STOP | **22** |
| 8 | セマンティックループ | 出力反復パターン検出 | SEMANTIC_STOP | 1 |
| 9 | Cross-Goal干渉 | 複数ゴール間の資源競合 | INTERFERENCE_STOP | 0 |
| | **合計** | | | **54** |

---

## 第6章: Build in Public方針（V30新規）

2026年4月2日決定。全システム階層に反映済み。

### 6.1 方針

- note記事のテーマは「SYUTAINβで実際に何が起きたか」が最優先
- 外部AIニュース解説記事（「GPTの使い方」「Claude活用法」等）は禁止
- SYUTAINβの実運用データ・実失敗・実メトリクスに基づく記事のみ
- 情報収集（intel_items）は記事の「補足素材」として使用。メインテーマにしない
- 6月1日まで全記事無料（リーチ拡大フェーズ）
- SYUTAINβの自動生成記事と島原の手動記事は別ストリーム

### 6.2 反映箇所

| ファイル | 反映内容 |
|---------|---------|
| `agents/proposal_engine.py` | Layer 1プロンプトに方針明記、外部AI記事禁止ルール |
| `brain_alpha/content_pipeline.py` | Stage 1テーマ選定を全面書き換え、実データ注入 |
| `scheduler.py` | note_draft_generationをcontent_pipeline経由に統一 |
| `prompts/strategy_identity.md` | note記事の方針セクション新設 |
| `strategy/CONTENT_STRATEGY.md` | セクション0.1に最重要方針として追加 |
| `strategy/note_genre_templates.py` | タイトル生成にBIP方針+SEOガイダンス |

---

## 第7章: note記事品質パイプライン（V30大幅強化）

### 7.1 コンテンツパイプライン（6段階）

`brain_alpha/content_pipeline.py`

| Stage | 名称 | モデル | 内容 |
|-------|------|-------|------|
| 1 | ネタ選定 | Gemini Flash | 実データ+intel→テーマ自動選定（BIP方針準拠） |
| 1.5 | 3軸タイトル生成 | Gemini Flash | ジャンルKW×切り口×感情トリガー+SEO最適化 |
| 2 | 構成案 | nemotron-jp | 無料パート+有料パートのPhase A-E構成 |
| 3 | 初稿 | Gemini Pro | 実データ注入、10000字以上、ファクト検証内蔵 |
| 4 | リライト | ローカル9B | 島原大知の文体で書き直し |
| 4.5 | セルフ批評 | **27B or API** | 9Bが書いた記事を27Bが批評（交差検証） |

### 7.2 品質チェッカー（4段階）

`brain_alpha/note_quality_checker.py`

| Stage | 名称 | モデル | コスト上限 |
|-------|------|-------|-----------|
| 0 | 機械的品質チェック（15項目） | なし | ¥0 |
| 1.5 | 事実整合性チェック | gpt-4o-mini | ¥1/記事 |
| 1.7 | **外部検索ファクト検証（V30新規）** | Tavily/Jina | ¥2-4/記事 |
| 1 | Haikuチェック | claude-haiku-4-5 | ¥3/記事 |
| 2 | GPT-5.4チェック | gpt-5.4 | ¥5/記事 |

### 7.3 機械的品質チェック15項目（V30: 13→15項目）

| # | チェック内容 | 判定 |
|---|------------|------|
| 1 | 文字数（10000字以上） | スコア |
| 2 | フックワード（冒頭3行） | スコア |
| 3 | 具体的数字（8個以上） | スコア |
| 4 | CTAワード+有料セクション | スコア |
| 5 | 一文長（80字超が10%未満） | スコア |
| 6 | 漢字率（35%以下） | スコア |
| 7 | 有料境界マーカー | スコア |
| 8 | 見出し数（5個以上） | スコア |
| 9 | 番号付きリスト（3項目以上） | スコア |
| 10 | 有料パート実質性（3000字以上） | スコア |
| 11 | 情報密度（固有名詞8/1000字以上） | スコア |
| 12 | メタ指示漏洩 | **即D判定** |
| 13 | 秘密情報検出 | **即D判定** |
| **14** | **タイトル健全性（V30新規）** | **即D判定** |
| **15** | **重複コンテンツ検出（V30新規）** | スコア |

### 7.4 外部検索ファクト検証（V30新規、Stage 1.7）

- 「日本語記事がない/少ない」系の主張を検出
- Tavily APIで実際に日本語記事を検索
- 日本語記事3件以上 → reject（虚偽の主張）
- 日本語記事0件 → pass（主張は正当、エビデンス付き）
- 日本語記事1-2件 → pass（修正推奨）
- 検索結果をintel_itemsに保存（記事生成・システム改善に活用）

### 7.5 公開フロー安全装置（V30新規）

- 公開URL検証: `note.com/{user}/n/{id}`パターン必須
- エディタURLでのSNS告知は構造的に不可能
- Playwright再試行ロジック: 公開ボタン未完了を自動リトライ

### 7.6 コスト上限（V30引き上げ）

| 項目 | V29 | V30 |
|------|-----|-----|
| 記事あたり | ¥6 | **¥15** |
| 日次 | ¥60 | **¥120** |
| 月次 | ¥500 | **¥1,000** |

---

## 第8章: SNSパイプライン（V30強化）

### 8.1 投稿スケジュール（49件/日）

| プラットフォーム | アカウント | 件数/日 | 時間帯 |
|----------------|----------|---------|--------|
| X | @Sima_daichi | 4 | 10:00, 13:00, 17:00, 20:00 |
| X | @syutain_beta | 6 | 11:00, 13:30, 15:00, 17:30, 19:00, 21:00 |
| Bluesky | @syutain.bsky.social | 26 | 10:00-22:30（30分間隔） |
| Threads | @syutain_beta | 13 | 10:30-22:30（1時間間隔） |

### 8.2 V30新機能

- **Bluesky Rich Text Facets**: URL自動検出→クリック可能リンク+OGPリンクカード生成
- **ハッシュタグ自動付与**: テーマ別マッピング（X:2個、Threads:3個）
- **noteリンク自動挿入**: 全投稿の20%に直近のnote記事URL
- **intel情報コンテキスト注入**: 海外トレンド/英語記事要約をプロンプトに注入
- **SEOタイトル最適化**: 40-60字、検索キーワード誘導

### 8.3 品質管理

- プラットフォーム別閾値: X=0.68, Bluesky=0.62, Threads=0.64
- 7軸品質スコアリング
- Best-of-N候補選択（最大3候補）
- テーマ品質フィードバックループ（7日間履歴）
- AI臭い表現検出・却下

---

## 第9章: 情報収集・活用パイプライン（V30拡張）

### 9.1 6ソース情報収集

| ソース | ツール | 頻度 |
|--------|-------|------|
| Tavily検索 | tavily_client.py | 毎時 |
| Jina Reader | jina_client.py | オンデマンド |
| YouTube API | info_pipeline.py | 日次 |
| RSS/Atom | info_pipeline.py | 6時間間隔 |
| 競合分析 | competitive_analyzer.py | 週次 |
| 海外トレンド | overseas_trend_detector.py | 日次 |

### 9.2 英語記事取り込みパイプライン（V30新規）

```
overseas_trend_detector（スケジューラ定期実行）
  → 英語キーワード15個でTavily検索
  → 日本語カバレッジ確認
  → 英語記事URLをDBに保存
      ↓
enrich_overseas_trends（同ジョブ内で連続実行）
  → Jina Readerで英語記事全文取得
  → ローカルLLMで日本語要約+キーポイント抽出+システム改善示唆
  → intel_items に保存（source='english_article', review_flag='actionable'）
      ↓
記事生成・SNS投稿の両方で活用
```

### 9.3 intel活用4施策（V30計画、実装予定）

1. X @syutain_beta「今日のAI速報」定期投稿
2. 週次インテルダイジェスト（Bluesky/note無料公開）
3. システム改善の自動提案（system_insights→提案エンジン）
4. Discord定期報告への「今週の注目トレンド」セクション追加

---

## 第10章: セキュリティ（V30: GitHub公開対応）

### 10.1 GitHub公開セキュリティ

- 全PythonファイルからTailscale IP（13ファイル）を`os.getenv()`に外部化
- SSHユーザー名（7ファイル）を`REMOTE_SSH_USER`環境変数に統一
- `config/node_*.yaml`, `config/nats-server.conf`を.gitignore追加、.exampleファイル作成
- 運用ログ・セッション引き継ぎ・SYSTEM_STATE.mdを.gitignore追加
- 個人心理プロファイル3件をGitHubから除外（ローカルには残存）
- orphanブランチでクリーンな初期コミット（過去履歴のIP完全排除）
- `.env.example`に全環境変数テンプレート

### 10.2 コンテンツ自動除去（content_redactor）

17パターンの正規表現+.env値マッチング:
- APIキー、IPアドレス、メールアドレス、Discord Webhook URL
- DBパスワード、SSH認証情報、Bearerトークン、長hex文字列
- 4チェックポイント: SNS生成後、note Stage 4.5後、Playwright公開前、機械チェック#13

---

## 第11章: パワーモード

### 11.1 夜間モード（V30: 23:00→09:00 JST、10時間）

| 設定 | 夜間 | 日中 |
|------|------|------|
| バッチコンテンツ生成 | 有効 | 無効 |
| 並列推論 | 有効 | 無効 |
| ローカルLLM優先度 | 100 | 80 |
| 最大同時タスク | 6 | 3 |
| GPU温度上限 | 85℃ | 80℃ |

### 11.2 夜間スケジュール

| 時刻(JST) | ジョブ |
|-----------|-------|
| 22:00 | SNSバッチ1（X島原4+X SYUTAIN6） |
| 22:30 | SNSバッチ2（Bluesky前半13） |
| 23:00 | SNSバッチ3（Bluesky後半13）+ 夜間モード切替 |
| 23:30 | SNSバッチ4（Threads13）+ 夜間バッチコンテンツ生成 |
| 23:45 | **noteドラフト生成（content_pipeline経由、V30修正）** |
| 03:45 | メモリ統合 |
| 05:00 | 承認キュー清掃 |
| 09:00 | 日中モード切替 |

---

## 第12章: ハーネスエンジニアリング

### 方法論

```
エラー発生
  → 即時修正（止血）
  → 根本原因分析（なぜ起きたか）
  → ガードレール構築（そのエラーの種類全体を構造的に不可能にする）
  → CLAUDE.mdルールに追加（AIが再導入するのを防ぐ）
  → エピソード記憶に記録（システムが次回から学習する）
```

### 構成要素

- `tools/failure_memory.py` — 失敗記録+LLM根本原因分析+自動警告
- `tools/harness_linter.py` — taboo強制、ペルソナ整合性、予算事前チェック、コンテンツ安全ゲート
- `tools/harness_health.py` — ハーネスヘルススコア（信頼性の定量化）
- `tools/skill_manager.py` — 高パフォーマンスエピソードを再利用可能スキルに変換
- `tools/doc_gardener.py` — 週次ドキュメント-コード矛盾自動検出
- `AGENTS.md` — エージェント能力マップ（perceiverが自動参照）

---

## 第13章: AI役員（Discord Bot）

| Bot | 役割 | マシン | LLM | 主要機能 |
|-----|------|--------|-----|---------|
| CORTEX | CEO | ALPHA | qwen3.5:4b | ハートビート(10分)、パイプライン管理 |
| FANG | CSO | BRAVO | qwen3.5:9b | KPIレポート(21:00)、戦略提案 |
| NERVE | COO | BRAVO | qwen3.5:9b | ミーティング、オペレーション |
| FORGE | CTO | CHARLIE | qwen3.5:9b | コードレビュー、技術判断 |
| MEDULLA | 副CEO | DELTA | qwen3.5:4b | 巡回(30分)、CEO代行 |
| SCOUT | 情報収集 | DELTA | qwen3.5:4b | マルチソースリサーチ |

---

## 第14章: 変更履歴

### V25（2026-03-15）— 原典
- 4ノード構成、5段階自律ループ、9層LoopGuard、45テーブルDB

### V26-V28（2026-03-20〜04-01）
- Brain-α融合、SNSパイプライン、note自動公開、ハーネスエンジニアリング

### V29（2026-04-01）
- 並列Claude Code + Codex自律デバッグ、Harness Engineering形式化

### V30（2026-04-04）
- **Build in Public方針の全階層反映**
- **GitHub公開**（セキュリティ対応、orphanコミット）
- **6層品質防御**（機械チェック#14,#15、外部検索検証、公開URL検証、Playwright再試行）
- **27Bモデル統合**（BRAVO、highest_localティア、Stage 4.5交差検証）
- **KV Cache Q8全ノード有効化**（VRAM効率50%改善）
- **英語記事取り込みパイプライン**（Jina全文取得→ローカルLLM要約→DB保存）
- **SNS拡散力最大化**（Blueskyリンクカード、ハッシュタグ、noteリンク、SEOタイトル）
- **情報活用パイプライン**（intel→SNS/記事の両方に注入）
- **夜間モード延長**（07:00→09:00、10時間稼働）
- **noteドラフト生成をcontent_pipeline統一**（重複コードパス排除）
- **コスト上限引き上げ**（記事¥15、日次¥120、月次¥1,000）

---

**Links:**
- GitHub: https://github.com/SYUTAIN-system/syutain_beta
- Bluesky: https://bsky.app/profile/syutain.bsky.social
- X: https://x.com/syutain_beta / https://x.com/Sima_daichi
- Threads: https://www.threads.net/@syutain_beta
- note: https://note.com/5070
