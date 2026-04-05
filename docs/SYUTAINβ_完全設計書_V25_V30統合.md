# SYUTAINβ 完全設計書 V25（V30統合版）

> **「これは、単なるAIエージェントではない。4台のPCがPhase 1初日から全て連携し、MCPとA2Aで標準化された通信で結ばれ、Web UIを通じてiPhoneからリアルタイム監視でき、マルチエージェントが自律的に認識・思考・行動・検証・停止判断を行い、目標だけを受けても道筋が変わっても自分で考え、自分で動き、自分で止まれる『自律分散型 事業OS』である。」**

> **V30テーマ：「コードを一行も書けない人間が、AIエージェントと共に自律型事業OSを構築し、その全過程を公開するドキュメンタリー」** — Build in Public + GitHub公開 + 6層品質防御 + 27Bモデル統合 + intel活用パイプライン + OpenRouter無料API統合（Qwen 3.6 Plus / Nemotron-3-Nano-30B） + エンゲージメント収集基盤 + Bluesky自動フォロー施策 + 日次ヘルスチェック

**バージョン：** V25（V30統合版・2026年4月5日夕方更新）
**プロジェクトオーナー：** 島原大知（@shima_daichi）
**AIエージェント：** SYUTAINβ（@syutain_beta）
**システム名：** SYUTAINβ（Sustainable Yield Utilizing Technology And Intelligence Network β）
**月収目標：** 12ヶ月以内に100万円を最低達成ライン、設計上の伸長上限は300〜400万円帯を狙う
**GitHub：** https://github.com/SYUTAIN-system/syutain_beta（Public）

---

## システム統計（2026年4月5日、本番DB直接取得）

| 項目 | 値 |
|------|-----|
| Python | 57,668行 / 139ファイル |
| TypeScript/TSX | 57,681行（Next.js Web UI） |
| PostgreSQL + pgvector | 49テーブル / 38,715イベント（2026-04-06 更新） |
| ゴール処理 | 98件（完了53 / キャンセル35 / エスカレーション8） |
| タスク実行 | 2,092件 |
| 承認処理 | 166件 |
| ペルソナ記憶 | 551件（11カテゴリ） |
| 情報収集 | 1,547件 |
| SNS自動投稿 | 519件posted（Bluesky 274 / Threads 147 / X 97） |
| LLM呼び出し | 11,085回 |
| 累計LLMコスト | ¥1,104.93 |
| LoopGuard発動 | 54回 |
| スケジューラジョブ | 100件以上（5,302行、1日3本note公開目標の10スロット含む） |
| APIエンドポイント | 64本 |
| エンゲージメント収集 | 96件（X/Bluesky/Threads 3プラットフォーム） |
| Blueskyフォロー追跡 | 開始（フォロワー4人、自動フォロー30人/日稼働中） |
| 主要タスク¥0化 | chat/proposal/strategy/content_final全て無料APIモデルで運用 |

---

# 第1章 V25の設計思想と位置づけ

## 1.1 V25とは何か

V25はV20〜V24の全設計を**再構成・統合・進化**させた、SYUTAINβの原典設計書である。V24までの設計・機能は一切削除せず、V25の文脈の中で再統合されている。V25自体が設計書の原文として独立する。

本書はV25原典に対してV30で確定した変更（Build in Public方針、ALPHA LLM撤去、BRAVO 27B追加、KV Cache Q8、6層品質防御、SNS拡散強化、英語記事取り込み、GitHub公開セキュリティ等）を統合した版である。

**V24→V25の根本的な変更点：**

1. **全4PC Phase 1完全稼働**：V24ではBRAVOをPhase 2以降としていたが、V25ではBRAVO（Ubuntu）をPhase 1初日から稼働させる。BRAVO、CHARLIE、DELTAはUbuntuインストール済み（CHARLIEのみWin11とのデュアルブート）
2. **GPT-5.4最新情報反映**：2026年3月5日リリースのGPT-5.4（ネイティブComputer Use、1Mコンテキスト、Tool Search）を正式Tier Sに組み込み
3. **DeepSeek V4監視体制**：DeepSeek V4は2026年4月4日現在未リリース（推測記事のみ存在）。提案エンジンで外部検索によるリリース確認を実装済み。リリース時は動的に検知して評価する設計
4. **収益性の大幅強化**：Stripe直接統合 + Micro-SaaS + アフィリエイト戦略 + 暗号通貨自動取引の4柱で月収目標を引き上げ
5. **ブラウザ自動操作4層構成**：Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Useの4層フォールバック構成をBRAVOに実装し、全ノードで段階的に有効化
6. **人間と遜色ないレベルのPC操作**：GPT-5.4のネイティブComputer Use能力（OSWorld-Verified 75.0%、人間72.4%超え）を活用
7. **自律提案エンジンの強化**：島原に対して「今週やるべき3手」「今週やめるべき1手」に加え、中長期の収益拡大提案を自律的に行う
8. **9層ループ防止**：V24の8層に加え、Layer 9: Cross-Goal Interference Detection を追加
9. **ブラウザ自動操作4層構成**：Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Useの4層フォールバック構成をBRAVOに実装
10. **突然変異エンジン（第24章）**：物理ノイズと人間の直感を種とする不可逆蓄積型の変異システムを導入。観測不能・不可逆・累積的な進化を実現

**V30統合で追加された変更点：**

11. **ALPHA LLM撤去**：ALPHAからOllamaを2026年3月6日にアンインストール済み。ALPHAはオーケストレーター専任（PostgreSQL、NATS、FastAPI、Next.js、Caddy、scheduler）。ローカルLLM推論はBRAVO/CHARLIEの最大2台で実行
12. **BRAVO 27Bモデル追加**：BRAVO上にqwen3.5:27b（17GB、GPU+CPUオフロード、5 tok/s）を追加。quality="highest_local" Tier L+として記事批評・ファクトチェックに使用
13. **KV Cache Q8全ノード有効化**：BRAVO/CHARLIE/DELTA全てで`OLLAMA_FLASH_ATTENTION=1`、`OLLAMA_KV_CACHE_TYPE=q8_0`を設定。KV CacheのVRAM消費約50%削減、perplexity +0.004（無視可能）。Gemmaモデルには非対応
14. **Build in Public方針**：note記事テーマを「SYUTAINβで何が起きたか」に統一。外部AIニュース記事をメインテーマにすることを禁止。2026年6月1日まで無料公開
15. **note品質6層防御**：15項目の機械チェック（V25の13項目に#14タイトル健全性、#15重複チェックを追加）、Stage 1.7外部検索ファクト検証（Tavily/Jina）、API障害時は安全側拒否、公開URL検証、Playwrightリトライロジック、コスト制限（記事¥15、日次¥120、月次¥2,000）
16. **SNS拡散力強化**：Bluesky Rich Text Facets（URLクリッカブル、OGPリンクカード）、テーマ別ハッシュタグ（X:2、Threads:3）、note記事リンク自動挿入（投稿の20%）、intelコンテキスト注入
17. **英語記事取り込みパイプライン**：fetch_and_summarize_english_article()、enrich_overseas_trends()、15英語キーワードでトレンド検知、Jina全文取得→ローカルLLM日本語要約→intel_items DB保存
18. **GitHub公開セキュリティ**：13ファイルのIP外部化、SSHユーザー名のenv変数化、orphanブランチクリーンコミット、.gitignore（config/node_*.yaml、nats-server.conf、data/artifacts/、strategy/daichi_*、logs/、SYSTEM_STATE.md等）、個人プロファイルはGitHub除外（ローカルのみ）
19. **夜間モード拡張**：23:00-09:00 JST（10時間、V25の8時間から拡張）。max_concurrent_tasks: 6、local_llm_priority: 100、gpu_temp_limit: 85
20. **月額予算引き上げ**：¥2,000/月（V25の¥1,500から変更）。.env: MONTHLY_API_BUDGET_JPY=2000
21. **note_draft_generation統合**：scheduler.pyの重複コードパスを排除し、content_pipeline.generate_publishable_content()に一本化
22. **OpenRouter Qwen 3.6 Plus導入**（2026年4月4日）：無料API（$0）、1Mコンテキスト。proposal/strategy/content_final等の深い思考タスクで使用。429エラー時→Gemini Flash自動フォールバック。日次180req上限
23. **Ollama完全常駐化**（2026年4月4日）：全ノードOLLAMA_KEEP_ALIVE=-1。コールドスタート排除（BRAVO: 6s→0.14s）
24. **予算ガード改善**（2026年4月4日）：90%超過時にallowed=True（処理継続、停止しない）。ログ出力1日1回。Discord通知にcritical含むdedup（6時間）適用
25. **SNS品質改善強化**（2026年4月4日）：正規表現ベースのポエムパターン検出（14パターン）、bigramベースJaccard重複チェック（閾値0.35、比較対象20件/150文字）
26. **scheduler PIDロック**（2026年4月4日）：fcntl.flockによる重複起動防止。LaunchAgent+手動起動の競合を構造的に排除
27. **Discord完結ワークフロー**：!承認一覧、!承認 N、!却下 N、!予算設定、!収益記録、!charlie、!レビュー、!提案生成。自然言語コマンド対応
28. **CLAUDE.md 32条化**：Rule 27（実機確認必須）、Rule 28（scheduler+bot同時再起動）、Rule 29（自発的作業終了禁止）追加。さらに rev.3 で Rule 30（破壊的ACTION直接ルート必須、LLM自由文完了報告禁止）、Rule 31（生Python例外ユーザー露出禁止）、Rule 32（working_fact protocol）を追加
29. **SNSエンゲージメント収集**（2026年4月5日）：X(OAuth 1.0a)/Bluesky(AT Protocol)/Threads(Meta Graph API)から反応データ(impressions/likes/reposts/replies)を自動収集。4時間間隔でposting_queue_engagementに蓄積。拡散戦略のデータドリブン改善基盤
30. **日次ヘルスチェック**（2026年4月5日、毎朝09:30 JST）：インフラ死活/ジョブ実行/予算/note公開状態/SNS投稿/エンゲージメントデータ/投稿品質の7項目を検査。fail項目のみDiscord報告。拡散に影響するfailは最優先修正
31. **拡散フェーズ最優先方針**（2026年4月5日）：6月までの全判断基準を「拡散指標の改善に直結するか」に統一。エンゲージメントデータに基づくPDCAサイクル確立
32. **SNSポエム構造的解決**（2026年4月5日）：LLMの意味空間中心がポエムにある問題に対し、ブラックリスト方式ではなく3層統合で解決。factbook（SYUTAINβ実データ強制注入）+ sns_platform_voices（X shimahara/X syutain/Bluesky/Threads別ボイスガイド）+ fact_density スコア軸（0.20、最大重み）。情景語+低事実密度の組合せでhard_fail
33. **プラットフォーム別バズ検出**（2026年4月5日）：`tools/platform_buzz_detector.py` 新規作成。24ソースから1日数百件のトレンドを2時間間隔収集。HN/Reddit(LocalLLaMA/ML/programming/AI/videography/VideoEditing/Filmmakers/vtubers/drone/photography/advertising/marketing/Journalism/Entrepreneur/startups/smallbusiness)/GitHub/Zenn/はてな全8カテゴリ/Yahoo!リアルタイム/Togetter/Bluesky Popular。tech/daily_jp/affinity/snsの4カテゴリでバランス配分。SNS生成プロンプトに注入
34. **承認プロセスのポリシーゲート強化**（2026年4月5日）：approval_managerに4つのBLOCKゲート追加。(1)6月まで無料方針違反（price_jpy>0）(2)Build in Public違反（Booth/有料販売/価格設定キーワード）(3)タイトル異常（長さ>80字、theme_hintリーク）(4)approval_requestメタタイプの自己ループ防止。classify_tier()のデフォルトをTier 2→Tier 1に変更（未分類は人間承認必須）
35. **記事生成スロット増量**（2026年4月5日）：1日3本公開目標のため、生成スロットを5→10に拡張。07:30/09:30/11:00/12:00/14:00/16:00/18:00/20:00/21:30/23:30。各スロットに異なるテーマカテゴリを自動割当（海外トレンド/実運用レポート/AI×映像制作/失敗談/設計判断/コスト分析/哲学思考等）。auto_approve閾値0.65→0.60、note公開日次上限5本
36. **致命的バグ5件修正**（2026年4月5日）：C-1 SQL演算子優先順位（factbook/agent_context、括弧追加）、C-2 product_packager review_id未定義（NameErrorがexcept: passで握り潰されauto_approveが完全死していた）、C-3 BudgetGuard._load_from_dbフラグ逆転（DB失敗時にリトライされなかった）、C-4 posting_queue一時エラーのfailed確定（一時エラーをpendingに戻してリトライ可能に）、C-5 gpu_temp_limit KeyError
37. **セキュリティ修正**（2026年4月5日）：WebSocketチャット `/api/chat/ws` に JWT認証欠落 → query_paramからtoken取得・verify_jwt_token・失敗時close(1008)追加。誰でも接続してChatAgent経由でLLM呼び出しができる重大脆弱性を解消
38. **事実捏造防止の三重化**（2026年4月5日）：note記事で(1)「運用チーム」「開発メンバー」「離職率」等の架空組織、(2)Grafana/Prometheus等の架空ツール使用、(3)「私は〇〇と命名した」等の自己命名捏造（ハーネスエンジニアリング含む）が多発。content_pipeline/note_quality_checker/sns_batch全てのプロンプトに「SYUTAINβは個人開発、チーム・メンバー・離職者は存在しない」「実運用ツールはPostgreSQL/NATS/Tailscale/Ollama/FastAPI/Next.js/Playwright/discord.pyのみ」「既存概念を自分が作ったと偽装禁止」を明記。persona_memoryに priority_tier=10 で永続登録

## 1.2 V25で到達させる状態

SYUTAINβ V25は、以下の状態を**全て**満たしたときに達成と見なす。

- 島原が**目標だけ**を入力しても、SYUTAINβが現在利用可能なツール・モデル・ノード・権限・予算・承認境界を自動監査し、MCP経由で外部ツールを動的に発見・接続できる
- ツールが足りない、モデルが落ちる、外部状況が変わる、チャネル反応が悪い、といった変化が起きても**経路を自律的に引き直せる**
- 経路を引き直した結果、元の目標に到達不能と判断した場合は**到達可能な部分目標を再設定**できる
- 収益タスクを **ICP適合性 / チャネル適合性 / 粗利 / 再利用性 / 継続性 / 実装コスト / 市場タイミング** で優先順位付けできる
- 島原に対して「今週やるべき3手」と「今週やめるべき1手」を**根拠付きで自律提案**できる
- 島原が提案を却下した場合、**却下理由を推測して代替案を即座に提示**できる
- **Web UIダッシュボード**を通じてiPhoneからリアルタイムにシステム状態・タスク進捗・収益状況を確認できる
- **ユーザーとAIエージェントが双方向コミュニケーション**を行い、チャットインターフェースで目標設定・承認・フィードバックを即座にやり取りできる
- **4台のPCにPhase 1初日から常駐するマルチエージェント**が効率的に役割分担し、NATSメッセージングで無駄なく連携する
- **各PC上でブラウザ操作・PC操作を人間と遜色ないレベルで実行**でき、4層構成（Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Use）で自動化を推進する
- エラー発生時に、再試行の価値がないと判断したら**途中成果物を保存して停止**できる
- ループ処理に陥る可能性を**9層の防御壁で構造的に排除**できる
- **自律拡張・自律進化・自律調査・自律実行・自律判断**の5つの自律性を備える
- 発信→商品→継続課金→BtoB の流れを、1本のOSとして連続運転できる
- ChatGPT API・Claude API・Gemini API・OpenRouter APIを適切にルーティングし、ローカルLLMと組み合わせて最小コストで最大成果を出せる
- **V30統合：Build in Public方針**により、SYUTAINβの全過程をnote記事として公開し、透明性と信頼を構築できる

## 1.3 V25の14大強化ポイント（V30統合版）

| # | 強化対象 | V24 | V25（V30統合版） |
|:--|:--|:--|:--|
| 1 | 4PC稼働 | BRAVOはPhase 2以降 | **全4台がPhase 1初日から完全稼働** |
| 2 | Web UI | Next.js 16 + FastAPI SSE + 双方向チャット | 同左 + **エージェント操作可視化パネル** |
| 3 | モデル戦略 | Qwen3.5-9B主力 + Gemini 3.1 Pro + GPT-5.4 | **GPT-5.4 + BRAVO 27b(L+) + OpenRouter Qwen3.6-Plus/Nemotron-3-Nano-30B(無料、主要タスク¥0化)** |
| 4 | 通信基盤 | NATS v2.12.5 + JetStream + Tailscale | 同左（検証済み安定構成を維持） |
| 5 | エージェント間連携 | MCP + A2A | 同左 + **4層ブラウザ自動操作 + Computer Use** |
| 6 | 自律性 | 5つの自律性 + 能動提案 | 同左 + **中長期収益拡大自律提案** |
| 7 | ループ防止 | 8層 | **9層（Cross-Goal Interference Detection追加）** |
| 8 | 収益設計 | 月収上限250〜350万円 | **月収上限300〜400万円（アフィリエイト戦略追加）** |
| 9 | 情報収集 | Gmail API + Tavily + Jina + RSS + YouTube | 同左 + **DeepSeek V4/新モデル監視自動化 + 英語記事取り込みパイプライン** |
| 10 | DB構成 | PostgreSQL + SQLite + Litestream | 同左（検証済み安定構成を維持） |
| 11 | ブラウザ操作 | Phase 2以降 | **Phase 1から4層構成：Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Use** |
| 12 | PC操作 | 未実装 | **GPT-5.4 Computer Use（OSWorld 75.0%超）をBRAVO/CHARLIEで活用** |
| 13 | 人間作業手順 | 基本手順 | **完全詳細手順 + Claude Code一撃構築プロンプト** |
| 14 | 突然変異エンジン | 未実装 | **物理ノイズ+人間直感を種とする不可逆蓄積型変異システム（第24章）** |

## 1.4 Build in Public方針（V30統合）

SYUTAINβは「コードを一行も書けない人間がAIエージェントとどこまで行けるか」のドキュメンタリーである。収益は手段であり目的ではない。この方針は以下の全階層に反映される。

### note記事テーマルール
- **メインテーマは必ず「SYUTAINβで何が起きたか」**であること
- 外部AIニュース記事をメインテーマとすることを**禁止**する
- 外部情報は「SYUTAINβの文脈で参照する」形でのみ使用可
- **2026年6月1日まで全記事無料公開**（信頼構築フェーズ）

### 反映箇所
- `proposal_engine`: 提案テーマ生成時にBuild in Publicフィルターを適用
- `content_pipeline`: 記事生成時にテーマ準拠チェックを実施
- `strategy/STRATEGY_IDENTITY.md`: アイデンティティ定義にBuild in Public方針を明記
- `strategy/CONTENT_STRATEGY.md`: コンテンツ戦略にBuild in Publicを最上位方針として追加

```yaml
build_in_public:
  note_theme_rule: "SYUTAINβで何が起きたか"
  external_news_as_main: false
  free_until: "2026-06-01"
  transparency: full
  failure_documentation: required
  enforcement_points:
    - proposal_engine
    - content_pipeline
    - strategy_identity
    - CONTENT_STRATEGY
```

---

# 第2章 ハードウェア構成と役割分担

## 2.1 4PC分散構成（V25：全台Phase 1完全稼働、V30統合版）

SYUTAINβは4台のPCを**Phase 1初日から全て連携**させて動作する。各PCには専用の常駐エージェントが配置され、NATSメッセージングで協調する。

### ALPHA（Mac mini M4 Pro 16GB RAM）— 司令塔（V30統合：LLM撤去、オーケストレーター専任）

| 項目 | 内容 |
|:--|:--|
| 役割 | **オーケストレーター専任** / Web UI / PostgreSQL / NATS Server / スケジューラー / Caddy |
| OS | macOS |
| 常駐エージェント | OS_Kernel / ApprovalManager / ProposalEngine / WebUIServer / ChatAgent |
| ローカルLLM | **なし（2026年3月6日にOllamaアンインストール済み）** |
| プロセス管理 | launchd（KeepAlive=true, RunAtLoad=true） |
| ネットワーク | Tailscale + NATS Server（JetStream有効） |
| メモリ管理 | **16GB RAM。PostgreSQL(1-2GB) + NATS(256MB) + FastAPI(500MB) + Next.js(1GB) + Caddy = 常駐約3.5GB。LLM推論なしのためメモリに余裕あり** |
| 特記事項 | **V30統合重要変更：ALPHAはシステム全体の心臓部。PostgreSQLで共有状態を管理し、Web UIをホストする。推論は全てBRAVO/CHARLIEに委譲する。ALPHAにローカルLLMは存在しない** |

### BRAVO（Ryzen + RTX 5070 12GB）— 実行者 ← V25重要変更：Phase 1から完全稼働、V30：27B追加

| 項目 | 内容 |
|:--|:--|
| 役割 | **Browser操作 / Computer Use / 高品質推論ワーカー / コンテンツ生成 / 27B高品質レビュー** |
| OS | **Ubuntu 24.04**（V25確定：Ubuntuインストール済み） |
| 常駐エージェント | **ComputerUseAgent / ContentWorker / BrowserAgent** ← 全てPhase 1 |
| ローカルLLM | **Qwen3.5-9B（Ollama、通常推論）+ Qwen3.5-27B（17GB、GPU+CPUオフロード、5 tok/s）+ Nemotron-JP（日本語特化9B）+ Nemotron-Mini（軽量2.7B）** |
| 推論サーバー | Ollama v0.17.7+ |
| KV Cache最適化 | **OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0（VRAM約50%削減、perplexity +0.004）** |
| プロセス管理 | **systemd（Restart=always, RestartSec=5）** ← Phase 1から |
| ネットワーク | **Tailscale + NATS Server + JetStream** ← Phase 1から4ノードRAFTクラスタ参加 |
| 特記事項 | **V25重要変更：V24ではPhase 2以降としていたが、V25ではPhase 1初日から完全稼働。RTX 5070の12GB VRAMでQwen3.5-9B（Q4_K_M、約6.5GB）が安定動作し、約5.5GBのVRAM余裕あり。V30統合：qwen3.5:27b（17GB）を追加。GPU+CPUオフロードで5 tok/sを実現。quality="highest_local"（Tier L+）として記事批評・ファクトチェックに使用。Stage 4.5セルフ批評（9Bドラフト→27Bレビュー）。ブラウザ自動操作は4層構成で、全層をStagehand v3（`env: "LOCAL"`、MITライセンス、Browserbase不要）が統括する：Layer 1=Lightpanda（CDP接続、構造が単純なサイトの高速データ抽出）、Layer 2=Stagehand v3のact()/extract()/observe()（自然言語でのAI駆動操作、自己修復・アクションキャッシュ付き）、Layer 3=Chromium（重いSPA・Layer 1/2で失敗した場合のフォールバック）、Layer 4=GPT-5.4 Computer Use（視覚的操作。ログイン画面・CAPTCHA・複雑なUI）。BrowserAgentがサイト特性に応じて自動で層を選択し、上位層で失敗した場合は自動的に下位層にフォールバックする** |

### CHARLIE（Ryzen 9 + RTX 3080 10GB + 大容量ストレージ）— 推論エンジン

| 項目 | 内容 |
|:--|:--|
| 役割 | ローカルLLM主力推論 / 日本語コンテンツ生成 / バッチ処理 |
| OS | **Ubuntu 24.04 + Win11 デュアルブート**（V25確定） |
| 常駐エージェント | InferenceWorker / BatchProcessor |
| ローカルLLM | **Qwen3.5-9B（Q4_K_M、約6.5GB VRAM）+ Nemotron-JP（日本語特化9B）** |
| 推論サーバー | Ollama v0.17.7+ |
| KV Cache最適化 | **OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0（VRAM約50%削減、perplexity +0.004）** |
| プロセス管理 | systemd（Restart=always, RestartSec=5） |
| ネットワーク | Tailscale VPN / NATS Server + JetStream（4ノードRAFTクラスタ参加） |
| 特記事項 | **CHARLIEはUbuntuで常時稼働。島原が重たい作業（映像制作等）を行う場合のみWin11にブートする可能性があり、その間はCHARLIEエージェントは停止する。フォールバックとしてBRAVO + DELTAで推論を継続。** |

### DELTA（Xeon E5 3.6GHz 6コア + GTX 980Ti 6GB + 48GB RAM + 500GB SATA SSD）— 監視・補助

| 項目 | 内容 |
|:--|:--|
| 役割 | 監視 / ログ集約 / 補助推論 / 情報収集ワーカー / ヘルスチェック |
| OS | **Ubuntu 24.04**（V25確定：インストール済み） |
| 常駐エージェント | MonitorAgent / InfoCollector / HealthChecker |
| ローカルLLM | **Qwen3.5-4B（Q4、約4.5-5.5GB VRAM）** |
| 推論サーバー | Ollama v0.17.7+ |
| KV Cache最適化 | **OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0（VRAM約50%削減、perplexity +0.004）** |
| プロセス管理 | systemd（Restart=always） |
| ネットワーク | Tailscale IP: 100.99.122.69 / NATS Server + JetStream（4ノードRAFTクラスタ参加） |
| 特記事項 | 48GB RAMの大容量を活かし、CPU推論バックアップとしても機能。GTX 980Ti（Maxwell世代）はBF16/FP16テンサーコア非対応のため、Qwen3.5-4Bが最適解。**GPU推論速度が8 tok/s未満の場合、llama.cpp CPU推論にフォールバック（48GB RAMで十分動作、3-5 tok/s）。feature_flagsの`delta_inference_mode`で`gpu`/`cpu`/`auto`を切替可能** |

## 2.2 ノード間通信アーキテクチャ（V25：全4台Phase 1完全接続、V30統合版）

```
┌────────────────────── TAILSCALE MESH VPN ──────────────────────┐
│                                                                  │
│  ALPHA (macOS)           BRAVO (Ubuntu)        V25: Phase 1稼働  │
│  ┌──────────────┐       ┌──────────────┐                        │
│  │ NATS Server  │◄─────►│ NATS Server  │                        │
│  │ +JetStream   │       │ +JetStream   │                        │
│  │ PostgreSQL   │       │ SQLite+Lite  │                        │
│  │ FastAPI      │       │ Ollama       │                        │
│  │ Next.js 16   │       │ Qwen3.5-9B   │                        │
│  │ Caddy        │       │ Qwen3.5-27B  │  ← V30統合            │
│  │ OS_Kernel    │       │ ComputerUse  │                        │
│  │ launchd      │       │ Lightpanda   │                        │
│  │              │       │ Stagehand v3 │                        │
│  │ ※LLMなし    │       │ systemd      │                        │
│  └──────────────┘       └──────────────┘                        │
│                                                                  │
│  CHARLIE (Ubuntu/Win11)  DELTA (Ubuntu)                          │
│  ┌──────────────┐       ┌──────────────┐                        │
│  │ NATS Server  │◄─────►│ NATS Server  │                        │
│  │ +JetStream   │       │ +JetStream   │                        │
│  │ Ollama       │       │ Ollama       │                        │
│  │ Qwen3.5-9B   │       │ Qwen3.5-4B   │                        │
│  │ InferWorker  │       │ Monitor      │                        │
│  │ systemd      │       │ InfoCollect  │                        │
│  └──────────────┘       │ systemd      │                        │
│                          └──────────────┘                        │
│                                                                  │
│  全リモートノード: KV Cache Q8有効                                │
│  OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0            │
│                                                                  │
│  iPhone (Tailscale iOS)                                          │
│  ┌──────────────┐                                                │
│  │ Safari PWA   │                                                │
│  │ → ALPHA:443  │                                                │
│  │ SSE Stream   │                                                │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

## 2.3 NATS + JetStream メッセージング設計

SYUTAINβ V25では、ノード間通信にNATS v2.12.5 + JetStreamを採用する。

**NATSを選定した理由：**
- 単一バイナリ20MB未満、RAM 50-200MB
- サブミリ秒レイテンシ
- JetStreamによるRAFTコンセンサスの永続化
- Pub/Sub、Request-Reply、Queue Groups（ロードバランシング）をネイティブ対応
- CNCFプロジェクトとして活発にメンテナンス
- Redis Pub/Sub（オフライン時メッセージ消失）、RabbitMQ（4ノードにオーバースペック）、ZeroMQ（永続化を自前実装必要）より適切

**JetStream構成（V25：BRAVOも含む4ノード）：**
- ALPHA + BRAVO + CHARLIE + DELTAの4ノード全てでNATS Server + JetStream対応（4ノードRAFTクラスタ）
- 全ノードがNATS Serverとしてクラスタに参加し、launchd（ALPHA）またはsystemd（BRAVO/CHARLIE/DELTA）で管理
- JetStreamクラスタは **ALPHA + BRAVO + CHARLIE + DELTA の4ノード**でRAFTコンセンサス（2台同時障害まで耐性あり。3ノード構成より耐障害性が向上）

**メッセージサブジェクト設計：**

```yaml
nats_subjects:
  # タスク管理
  task.create: "新規タスク作成"
  task.assign.{node}: "ノード別タスク割当"
  task.status.{task_id}: "タスク状態更新"
  task.complete.{task_id}: "タスク完了通知"

  # エージェント間
  agent.heartbeat.{node}: "死活監視（30秒間隔）"
  agent.capability.{node}: "能力監査結果"
  agent.request.llm: "LLM推論リクエスト"
  agent.response.llm.{request_id}: "LLM推論結果"

  # ブラウザ操作（V25新規：4層構成）
  browser.action.{node}: "ブラウザ操作コマンド（layer指定: lightpanda/stagehand/chromium/computer_use）"
  browser.result.{node}.{action_id}: "ブラウザ操作結果（使用layer・フォールバック有無を含む）"
  browser.fallback.{node}: "ブラウザ層フォールバック発生通知"
  computer.use.{node}: "Computer Useアクション"

  # 提案・承認
  proposal.new: "新規提案"
  proposal.feedback.{proposal_id}: "提案へのフィードバック"
  approval.request: "承認リクエスト"
  approval.response.{request_id}: "承認結果"

  # 監視・ログ
  monitor.alert.{severity}: "アラート通知"
  monitor.metrics.{node}: "メトリクス収集"
  log.event.{level}: "ログイベント"

  # 情報収集
  intel.news: "ニュース収集結果"
  intel.market: "市場データ更新"
  intel.trend: "トレンド分析結果"
  intel.model_update: "新モデルリリース検知（V25新規）"
```

## 2.4 データベース構成：PostgreSQL + SQLite ハイブリッド

**共有状態はALPHAのPostgreSQL、ノードローカルのキャッシュ・エージェントメモリはSQLite + Litestream。**

| データ種別 | 保存先 | 理由 |
|:--|:--|:--|
| タスクキュー | PostgreSQL（ALPHA） | 4台からの同時読み書きが必要 |
| 会話履歴 | PostgreSQL（ALPHA） | Web UIから参照、複数ノードから書き込み |
| 提案履歴 | PostgreSQL（ALPHA） | 学習・分析のため一元管理 |
| 収益記録 | PostgreSQL（ALPHA） | 正確な集計が必要 |
| ベクトルストア | PostgreSQL + pgvector（ALPHA） | RAG検索の統合 |
| ノードローカルキャッシュ | SQLite（各ノード） | 高速読み取り、オフライン耐性 |
| エージェントメモリ | SQLite（各ノード） | ノード固有の学習データ |
| ログ・メトリクス | SQLite（各ノード）→ Litestreamバックアップ | 書き込み頻度が高い |
| ブラウザ操作ログ | SQLite（BRAVO）→ Litestreamバックアップ | V25新規：操作履歴の高速記録 |
| 突然変異エンジン | **SQLite（DELTA・SQLCipher暗号化）** | **V25新規：mutation_engine.enc.db。変異パラメータの永続化。PostgreSQLには保存しない。他ノードから参照不可** |

**Litestream設定：** 各ノードのSQLiteをS3互換ストレージ（MinIO on CHARLIE）にリアルタイムレプリケーション。障害時に数秒で復旧可能。

---

# 第3章 2026年3月時点の最新モデル戦略（V25更新、V30統合版）

## 3.1 モデル利用の根本方針

V25では、2026年3月15日時点で利用可能な全モデルを正式に評価し、**タスク適性 × コスト × 速度 × 可用性 × VRAM制約**の5軸で選定する。「最も賢いモデルを常に使う」方針は取らない。

**V25の重要な更新点：**
- GPT-5.4が2026年3月5日にリリースされ、Computer Use能力（OSWorld-Verified 75.0%、人間72.4%超え）、1Mコンテキスト、Tool Search機能を搭載
- GPT-5.4は33%のハルシネーション削減、18%のエラー削減を実現
- DeepSeek V4は2026年4月4日現在未リリース（V25時点では3月中見込みだったが延期）。提案エンジンの動的リリース確認機能で監視中
- Qwen開発チームの人事変動は継続中だが、モデル自体の品質は高水準を維持

**V30統合での追加更新点：**
- **ALPHAからOllamaをアンインストール（2026-03-06）**。ALPHAでのローカルLLM推論は不可。BRAVO/CHARLIEの最大2台で並列推論
- **BRAVO上にqwen3.5:27b（17GB、GPU+CPUオフロード、5 tok/s）を追加**。Tier L+（highest_local）として高品質ローカル推論に使用
- **全リモートノードでKV Cache Q8最適化を有効化**。VRAM消費約50%削減

## 3.2 正式Tier構成（V25、V30統合版）

### Tier S（最高精度・高単価判断・Computer Use専用）

用途：経営判断、BtoB提案書、価格設計、長期戦略、最終公開品質の文章、Computer Use操作

| モデル | Provider | Input/1M | Output/1M | コンテキスト | 知能指数 | 特徴 |
|:--|:--|:--|:--|:--|:--|:--|
| GPT-5.4 | OpenAI | $2.50 | $15.00 | 1M | 57 | **V25主力Tier S。Computer Use（OSWorld 75.0%）/Tool Search/1Mコンテキスト。コーディング・ツール使用に最強** |
| GPT-5.4 Pro | OpenAI | 高額 | 高額 | 1M | 57+ | 最高性能版。複雑なBtoB案件・法務・財務分析の最終品質 |
| Gemini 3.1 Pro Preview | Google | $2.00 | $12.00 | 1M | 57 | GPT-5.4と同等知能指数。1Mコンテキスト。コスト面で有利 |
| Claude Opus 4.6 | Anthropic | $5.00 | $25.00 | 200K(1Mβ) | 53 | エージェント能力トップ。長文統合・設計書生成に最適 |
| Claude Sonnet 4.6 | Anthropic | $3.00 | $15.00 | 200K(1Mβ) | 52 | 高品質かつOpusより低コスト。設計・戦略文書の主力 |

**使用条件**：高単価売上に直結 / 長期設計の誤りが大損失 / 人間がそのまま公開する最終品質 / 重要分岐判断 / Computer Use操作

### Tier A（高品質・中コスト・主力帯）

用途：コンテンツ生成、商品説明文、note記事、中間品質の分析

| モデル | Provider | Input/1M | Output/1M | 特徴 |
|:--|:--|:--|:--|:--|
| DeepSeek-V3.2 | DeepSeek | $0.28 | $0.42 | chat/reasoner統合。キャッシュ利用で90%削減。**フロンティア最安値** |
| Gemini 2.5 Pro | Google | $1.25 | $10.00 | 1Mコンテキスト。思考モード付き |
| GPT-5 Mini | OpenAI | $0.25 | $2.00 | コスパ優秀。分類・要約・中品質生成 |
| Gemini 2.5 Flash | Google | $0.15 | $0.60 | 思考モード付き。1Mコンテキスト。超低コスト入力 |
| Claude Haiku 4.5 | Anthropic | $1.00 | $5.00 | 軽量Claude。分類・タグ付け・短文生成に最適 |

### Tier A-Free（OpenRouter無料モデル・API代¥0）— 2026年4月4日追加

用途：深い思考が必要だが速度は許容されるタスク（提案生成、戦略分析、最終品質コンテンツ）

| モデル | Provider | コスト | コンテキスト | 特徴 |
|:--|:--|:--|:--|:--|
| **Qwen3.6-Plus** | OpenRouter（Alibaba） | **$0** | **1M** | **2026年3月30日リリース。SWE-benchでClaude Opus 4.5に匹敵。常時Chain-of-Thought。ネイティブ関数呼び出し対応。proposal/strategy/content_finalで使用** |

制限事項：
- レート制限: 20 req/min、200 req/day（SYUTAINβでは日次180reqに制限）
- 速度: 38 tok/s（Gemini Flash 80 tok/sの約半分、ローカル9b 86 tok/sの約半分）
- 429エラー時はGemini 2.5 Flashに自動フォールバック
- プロンプト・完了データがモデル改善のために収集される可能性あり（秘密情報を含まないタスクに限定）

### Tier B（低コスト量産・バッチ処理）

用途：大量下書き、ラベル付け、ログ整形、先行案の荒生成

| モデル | Provider | Input/1M | Output/1M | 特徴 |
|:--|:--|:--|:--|:--|
| GPT-5 Nano | OpenAI | $0.05 | $0.40 | 最軽量GPT。ルーティング・分類用 |
| Gemini 2.5 Flash-Lite | Google | $0.075 | $0.30 | 超低コスト（2026年6月まで。以降は3.1系へ移行） |
| Qwen3.5-Flash（API） | Alibaba Cloud | ~$0.10 | ~$0.40 | 100万トークンコンテキスト。ネイティブツール呼び出し対応 |
| Qwen3.5-Plus（API） | Alibaba Cloud | ~$0.11 | 未公開 | Gemini 3.1 Proの18分の1の価格で競争力あるベンチマーク |

### Tier L（ローカル無料・継続運転・API障害時の退避先）

用途：下書き、分類、ラベル付け、ログ整形、エージェント的タスク実行、API停止時の最低限運転

| モデル | ノード | VRAM消費 | 推論速度 | 特徴 |
|:--|:--|:--|:--|:--|
| **Qwen3.5-9B** | BRAVO（Ollama） | ~6.5GB VRAM | 12-18 tok/s | **RTX 5070 12GBで余裕動作。約5.5GBのVRAM余裕** |
| **Qwen3.5-9B** | CHARLIE（Ollama） | ~6.5GB VRAM | 12-16 tok/s | V24主力ローカルモデル。GPQA Diamond 81.7% |
| **Qwen3.5-4B** | DELTA（Ollama） | ~4.5-5.5GB VRAM | 8-12 tok/s | DELTAの制約に最適。ネイティブマルチモーダル対応 |

### Tier L+（highest_local・高品質ローカル推論）— V30統合新規

用途：記事批評、ファクトチェック、Stage 4.5セルフ批評（9Bドラフト→27Bレビュー）

| モデル | ノード | VRAM消費 | 推論速度 | 特徴 |
|:--|:--|:--|:--|:--|
| **Qwen3.5-27B** | BRAVO（Ollama） | ~17GB（GPU+CPUオフロード） | ~5 tok/s | **quality="highest_local"で選択。9Bが書いた原稿を27Bがレビュー・批評する。ファクトチェック、論理整合性検証に使用** |

**V25（V30統合版）でのローカルLLMの位置づけ：**

Qwen3.5-9Bは、サイズを超えた驚異的な性能を持つ：
- GPQA Diamond 81.7%（GPT-5-Nano 80.1%を上回る）
- MMLU-Pro 82.5（前世代Qwen3-30Bの3倍小さいにもかかわらず匹敵）
- ネイティブマルチモーダル（テキスト＋画像＋動画）
- 262Kネイティブコンテキスト（1M拡張可能、9Bモデル）
- Apache 2.0ライセンス、201言語対応
- 思考モード（`<think>`タグ）対応
- 公式ツール呼び出し対応（エージェント構築可能）
- Gated DeltaNet + 線形アテンション混合による高効率推論

**V30統合版：BRAVO/CHARLIEの最大2台同時推論。**
BRAVO（Ollama）+ CHARLIE（Ollama）の2台が常時並列推論の主力。ALPHAにはローカルLLMが存在しない（2026-03-06アンインストール済み）。DELTAは軽量タスク専用で安定稼働を維持。BRAVO上のqwen3.5:27bはhighest_local品質要求時のみ使用。Nemotron-JP（日本語特化）はBRAVO/CHARLIEの両方で利用可能、SNS投稿やnote記事の日本語生成で活用。

**KV Cache Q8最適化（V30統合新規）：**
全3リモートノード（BRAVO/CHARLIE/DELTA）で以下の環境変数を設定：
```bash
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
```
- KV CacheのVRAM消費が約50%削減
- Perplexity上昇は+0.004で無視可能
- **注意：Gemmaモデルには非対応。KV Cache Q8をGemmaモデルと併用しないこと**

**DeepSeek V4 監視体制（V25新規）：**
DeepSeek V4は2026年3月中にリリースが見込まれる。1TパラメータMoE（約32Bアクティブ）、ネイティブマルチモーダル、1Mコンテキストの仕様が報道されている。V25設計ではリリース後即時に以下を実行する：
1. API料金の確認（V3.2比でさらに安価になる可能性）
2. ベンチマーク比較（GPT-5.4/Gemini 3.1 Proとの性能差）
3. choose_best_model_v6()への統合判定
4. ローカル推論可能性の検証（量子化版が出た場合のVRAM消費）

**Qwen開発チーム動向（V25注記）：** 2026年3月4日、Qwen技術リーダーのJunyang Linが退職を表明。ただし「Brothers of Qwen, continue as originally planned, no problem」とコメントしている。Alibaba側はGoogleのGeminiチームから新たな研究者を招聘し組織再編を実施。V25設計では、万が一Qwenの更新が停滞した場合のフォールバックとして、Gemma 3（Google QAT版）、Phi-4-reasoning-vision-15B（Microsoft、MITライセンス）、Mistral Ministral 3シリーズの監視を継続する。

## 3.3 OpenRouter統合によるAPI一元管理

V25では、OpenRouter APIを統合ハブとして活用する。

**OpenRouterの利点：**
- 単一APIキーで100以上のモデルにアクセス
- プロバイダ障害時の自動フォールバック
- 統一された料金体系と使用量ダッシュボード
- モデル切替がAPI呼び出しのモデル名変更のみで完了

**直接API接続を維持するケース：**
- Claude API（Anthropicの最新機能・MCP連携に直接アクセスが必要）
- DeepSeek API（キャッシュヒット時$0.028で90%削減、OpenRouter経由だとキャッシュ非対応の可能性）
- GPT-5.4 API（Computer Use・Tool Search機能に直接アクセスが必要）
- ローカルLLM（Ollamaに直接接続）

```python
def choose_best_model_v6(
    task_type: str,
    quality: str = "medium",
    budget_sensitive: bool = True,
    needs_japanese: bool = False,
    final_publish: bool = False,
    local_available: bool = True,
    context_length_needed: int = 4000,
    is_agentic: bool = False,
    needs_multimodal: bool = False,
    needs_computer_use: bool = False,    # V25新規
    needs_tool_search: bool = False,      # V25新規
    intelligence_required: int = 0,
) -> dict:
    """
    V25（V30統合版）正式モデル選択ロジック

    task_type: strategy / content / drafting / tagging / classification /
               compression / btob / coding / analysis / proposal / research /
               trading / monitoring / browser_action / computer_use
    quality: low / medium / high / premium / highest_local (V30新規)
    intelligence_required: 0-100（Artificial Analysis知能指数基準）
    """
    # V25新規：Computer Use必要時は強制GPT-5.4
    if needs_computer_use:
        return {"provider": "openai", "model": "gpt-5.4",
                "tier": "S", "via": "direct",
                "note": "Computer Use（OSWorld 75.0%）必須タスク"}

    # V25新規：Tool Search必要時はGPT-5.4優先
    if needs_tool_search:
        return {"provider": "openai", "model": "gpt-5.4",
                "tier": "S", "via": "direct",
                "note": "Tool Search機能必須タスク"}

    # V30統合新規：highest_local品質要求時はBRAVO 27B
    if quality == "highest_local":
        return {"provider": "local", "model": "qwen3.5:27b",
                "tier": "L+", "node": "bravo",
                "note": "highest_local: BRAVO 27B（5 tok/s、記事批評・ファクトチェック用）"}

    # 知能指数閾値による強制Tier S
    if intelligence_required >= 50:
        if budget_sensitive:
            return {"provider": "google", "model": "gemini-3.1-pro-preview",
                    "tier": "S", "via": "direct", "intelligence": 57}
        return {"provider": "openai", "model": "gpt-5.4",
                "tier": "S", "via": "direct", "intelligence": 57}

    # Tier S: 最終公開品質 or 高単価判断
    if final_publish and quality in ["high", "premium"]:
        if task_type in ["strategy", "pricing", "btob", "longform_design"]:
            return {"provider": "anthropic", "model": "claude-sonnet-4-6",
                    "tier": "S", "via": "direct"}
        if is_agentic:
            return {"provider": "anthropic", "model": "claude-opus-4-6",
                    "tier": "S", "via": "direct"}
        return {"provider": "openai", "model": "gpt-5.4",
                "tier": "S", "via": "openrouter"}

    # Tier L: ローカル優先（コスト削減の要）
    if local_available and task_type in [
        "drafting", "tagging", "classification", "compression",
        "log_formatting", "variation_gen", "translation_draft",
        "monitoring", "health_check"
    ]:
        if needs_multimodal:
            return {"provider": "local", "model": "qwen3.5-9b",
                    "tier": "L", "node": "charlie",
                    "note": "ネイティブマルチモーダル対応"}
        # V30統合版：BRAVO/CHARLIEの2台ローカル推論のロードバランシング（ALPHAにはLLMなし）
        return {"provider": "local", "model": "qwen3.5-9b",
                "tier": "L", "node": "auto",
                "note": "BRAVO/CHARLIEから最も負荷の低いノードを自動選択"}

    # Tier L: ローカルでもエージェント的処理が可能
    if local_available and is_agentic and quality == "medium":
        return {"provider": "local", "model": "qwen3.5-9b",
                "tier": "L", "node": "auto",
                "note": "ローカルエージェント処理（ツール呼び出し対応）"}

    # Tier A-Free: Qwen 3.6 Plus（OpenRouter無料）— 2026年4月4日追加
    # 深い思考が必要で速度が許容されるタスクに限定（38 tok/s、429エラー時→Gemini Flashフォールバック）
    _QWEN36_TASKS = {"proposal", "strategy", "competitive_analysis", "content_final",
                     "note_article_final", "complex_analysis", "persona_deep_analysis",
                     "note_article", "product_desc", "booth_description", "note_draft"}
    if task_type in _QWEN36_TASKS and _openrouter_available():
        return {"provider": "openrouter", "model": "qwen3.6-plus",
                "tier": "A", "via": "openrouter",
                "openrouter_model_id": "qwen/qwen3.6-plus:free",
                "note": "Qwen 3.6 Plus（無料、1Mコンテキスト、深い思考タスク）"}

    # Tier A: 中品質コンテンツ生成（Qwen 3.6不可時のフォールバック含む）
    if task_type in ["content", "note_article", "product_desc", "analysis"]:
        if budget_sensitive:
            return {"provider": "deepseek", "model": "deepseek-v3.2",
                    "tier": "A", "via": "direct"}
        if context_length_needed > 100000:
            return {"provider": "google", "model": "gemini-2.5-flash",
                    "tier": "A", "via": "openrouter"}
        return {"provider": "openai", "model": "gpt-5-mini",
                "tier": "A", "via": "openrouter"}

    # Tier B: 大量処理
    if task_type in ["batch_process", "bulk_draft", "data_extraction"]:
        return {"provider": "google", "model": "gemini-2.5-flash-lite",
                "tier": "B", "via": "openrouter"}

    # Tier A デフォルト: コスパ最強
    if budget_sensitive:
        return {"provider": "deepseek", "model": "deepseek-v3.2",
                "tier": "A", "via": "direct"}

    return {"provider": "openai", "model": "gpt-5-mini",
            "tier": "A", "via": "openrouter"}
```

## 3.4 コスト最適化戦略（V25更新、V30統合版）

| 処理カテゴリ | 月間推定回数 | V25想定コスト | V30統合版想定コスト | 削減方法 |
|:--|:--|:--|:--|:--|
| 下書き・分類・ラベル | 500回 | ¥0 | ¥0 | Qwen3.5-9Bローカル（BRAVO/CHARLIE並列） |
| 中品質コンテンツ | 100回 | ¥250 | ¥250 | DeepSeek-V3.2（キャッシュ活用で90%削減） |
| 最終品質文章 | 20回 | ¥500 | ¥500 | Gemini 3.1 ProまたはClaude Sonnet 4.6 |
| 戦略判断 | 5回 | ¥350 | ¥350 | GPT-5.4 / Gemini 3.1 Pro |
| Computer Use操作 | 30回 | ¥400 | ¥400 | GPT-5.4でブラウザ・PC操作 |
| 高品質ローカルレビュー | 50回 | — | ¥0 | **V30新規：BRAVO qwen3.5:27bでセルフ批評** |
| 情報収集（Tavily） | 月240検索 | ¥15,000 | ¥15,000 | Bootstrapプラン |
| 合計 | | **¥16,500/月** | **¥16,500/月** | API+ローカル+情報収集含む実コスト |

**V30統合版：月額API予算**
- `.env`: `MONTHLY_API_BUDGET_JPY=2000`（V25の¥1,500から引き上げ）
- note記事品質ゲートのコスト制限：1記事¥15、日次¥120、月次予算は全体で ¥2,000

## 3.5 廃止スケジュール（要監視）

| モデル | 廃止日 | 対応 |
|:--|:--|:--|
| Gemini 3 Pro Preview | 2026年3月9日（済） | Gemini 3.1 Pro Previewへ移行完了 |
| Gemini 2.0 Flash / Flash-Lite | 2026年6月1日 | Gemini 2.5系または3.1系へ移行 |
| GPT-5.2 Thinking | 2026年6月5日 | GPT-5.4へ移行 |
| Gemini 2.5 Flash-Lite Preview | 2026年3月31日（AI Studio） | Vertex AIでは7月まで |

---

# 第4章 Web UI・iPhone対応・双方向コミュニケーション

## 4.1 技術スタック

| レイヤ | 技術 | バージョン | 理由 |
|:--|:--|:--|:--|
| バックエンド | FastAPI | 0.135.1+ | ネイティブSSE対応、15,000-20,000 RPS、中央値60ms未満 |
| フロントエンド | Next.js + React 19 | 16 | TurbopackデフォルトでFast Refresh 5-10倍高速化、PWA対応 |
| UI | Tailwind CSS + shadcn/ui | 最新 | モバイルファースト、ダークモード、アクセシビリティ |
| ストリーミング | SSE（主）+ WebSocket（チャット用） | — | SSEでトークンストリーミング、WebSocketでリアルタイムチャット |
| リモートアクセス | Tailscale iOS | 最新 | ゼロ設定VPN、暗号化、ポート開放不要 |
| HTTPS | Caddy | — | 自動TLS証明書管理 |

## 4.2 ダッシュボード画面構成

### メイン画面（Dashboard）
- システム全体のヘルスステータス（4ノードの死活・CPU・GPU・VRAM）
- 今日の収益サマリー
- アクティブタスク一覧
- 最新の提案カード（3層構造表示）
- 承認待ちキュー

### チャット画面（Chat）
- ユーザー（島原）とSYUTAINβの双方向チャットインターフェース
- 目標入力→Goal Packet自動生成の対話フロー
- 承認/却下をチャット内で即座に実行
- エージェントからの質問・確認に即座に返答
- WebSocket接続によるリアルタイム双方向通信

### 提案画面（Proposals）
- 3層提案（提案→反論→代替案）のカード表示
- 採用/却下/保留ボタン
- 過去の提案履歴と採用率グラフ

### 収益画面（Revenue）
- 月次/週次収益グラフ
- 収益源別内訳
- 目標達成率プログレスバー
- 収益→商品→チャネルの紐付け表示

### タスク画面（Tasks）
- Task Graphの視覚化（DAG表示）
- 各タスクの状態（待機/実行中/完了/失敗/保留）
- ループガード発動状況

### モデル画面（Models）
- モデル使用比率円グラフ
- Tier別コスト推移
- ローカルLLM処理比率
- 2段階精錬の成功率

### 情報収集画面（Intel）
- Gmail配信ニュースの要約表示
- Tavily検索結果ダッシュボード
- 収集キーワード別のヒット数推移
- 重要度スコア付きニュースフィード

### エージェント操作画面（Agent Ops）— V25新規
- 各ノードのエージェント稼働状況リアルタイム表示
- BRAVOのブラウザ操作4層ステータス（Lightpanda/Stagehand v3/Chromium/GPT-5.4のどの層で操作中か表示）
- ブラウザ操作ストリーミング表示（スクリーンショット付き）
- Computer Use操作ログ
- エージェント間NATSメッセージフロー可視化

### 設定画面（Settings）
- feature_flags.yamlの切替UI
- 承認ポリシーの変更
- API予算設定
- ノード設定

## 4.3 iPhoneアクセス方式

1. **Tailscale iOS**アプリをインストールし、同一Tailnetに参加
2. ALPHA上のNext.js + FastAPIに `https://alpha.ts.net:443` でアクセス
3. Safariの「ホーム画面に追加」でPWA化（`@serwist/next`でService Worker設定）
4. Web Push通知はiOS 16.4以降のホーム画面インストール済みPWAで対応
5. 「VPN on Demand」を有効にすれば自宅WiFi外で自動接続

**バッテリー消費：** Tailscale iOSは1日7-15%程度（素のWireGuardより若干高め）

**HTTPS設定：** Caddy（ALPHA上で稼働）が自動TLS証明書管理を行う。

## 4.4 SSE vs WebSocket の使い分け

| 通信パターン | プロトコル | 用途 |
|:--|:--|:--|
| AIトークンストリーミング | SSE | タスク進捗、ログストリーム、提案通知 |
| ユーザー↔エージェントチャット | WebSocket | リアルタイム双方向メッセージング |
| システムメトリクス | SSE | ノード状態、CPU/GPU使用率 |
| 承認フロー | WebSocket | 即座の承認/却下操作 |
| ブラウザ操作ストリーム | SSE | V25新規：4層ブラウザ操作（Lightpanda/Stagehand/Chromium/Computer Use）の逐次表示 |

---

# 第5章 マルチエージェント設計と常駐エージェント

## 5.1 エージェント一覧と配置（V25：全台Phase 1稼働）

| エージェント名 | 配置ノード | 役割 | 常駐 |
|:--|:--|:--|:--|
| OS_Kernel | ALPHA | 司令塔。Goal Packet→Task Graph→ディスパッチ | ◎ |
| Perceiver | ALPHA | 認識エンジン。環境状態・目標を構造化 | ◎ |
| Planner | ALPHA | 思考・計画エンジン。主プラン+代替プラン生成 | ◎ |
| Executor | ALPHA→分配 | 行動エンジン。タスクを適切なノードへ分配実行 | ◎ |
| Verifier | ALPHA | 検証エンジン。成果物の品質・目標達成度評価 | ◎ |
| StopDecider | ALPHA | 停止判断エンジン。続行/変更/エスカレ/停止 | ◎ |
| ProposalEngine | ALPHA | 3層提案エンジン（提案+反論+代替案） | ◎ |
| ApprovalManager | ALPHA | 承認管理。人間承認が必要な操作を管理 | ◎ |
| ChatAgent | ALPHA | Web UIチャット応答。ユーザーとの双方向対話 | ◎ |
| **ComputerUseAgent** | **BRAVO** | **GPT-5.4 Computer Useによるデスクトップ視覚操作（4層のLayer 4）** | **◎** ← V25: Phase 1 |
| **ContentWorker** | **BRAVO** | **高品質コンテンツ生成ワーカー** | **◎** ← V25: Phase 1 |
| **BrowserAgent** | **BRAVO** | **4層ブラウザ自動操作の統括（Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Use）** | **◎** ← V25新規 |
| InferenceWorker | CHARLIE | ローカルLLM推論ワーカー。Ollama経由 | ◎ |
| BatchProcessor | CHARLIE | バッチ処理。大量コンテンツ生成 | ○ |
| MonitorAgent | DELTA | 全ノード監視。ヘルスチェック、メトリクス収集 | ◎ |
| InfoCollector | DELTA | 情報収集。Gmail API→Tavily→Jina→要約 | ◎ |
| HealthChecker | DELTA | 死活監視。NATS heartbeat + HTTP ping | ◎ |

◎=Phase 1で常駐起動、○=条件付き起動

## 5.2 MCP（Model Context Protocol）統合

V25では、MCPを外部ツール統合の標準プロトコルとして採用する。MCPは2025年12月にLinux Foundation傘下のAgentic AI Foundation（AAIF）に移管され、月間9,700万SDKダウンロードの事実上の業界標準。

**MCP Server一覧（SYUTAINβが接続するもの）：**

```yaml
mcp_servers:
  # ファーストパーティ（自作）
  - name: syutain-tools
    description: "SYUTAINβ固有ツール（DB操作、収益記録、提案生成等）"
    transport: stdio

  # サードパーティ
  - name: github-mcp
    description: "GitHub操作（リポジトリ管理、Issue、PR）"
    url: "https://api.github.com/mcp"

  - name: gmail-mcp
    description: "Gmail API（メール検索、読み取り、ラベル管理）"
    transport: stdio

  - name: bluesky-mcp
    description: "Bluesky AT Protocol（投稿、フィード管理）"
    transport: stdio

  - name: tavily-mcp
    description: "Tavily Search API（AI特化検索）"
    transport: stdio

  - name: jina-mcp
    description: "Jina Reader API（Webページ→Markdown変換）"
    transport: stdio

  - name: stagehand-mcp-local
    description: "Stagehand v3 ローカルMCPサーバー（AI駆動ブラウザ自動操作。act/extract/observe/agent）"
    transport: stdio
    env: { STAGEHAND_ENV: "LOCAL", OPENAI_API_KEY: "${OPENAI_API_KEY}" }
```

**A2A（Agent-to-Agent）プロトコル：** V25では、将来のマルチエージェント間通信にA2Aプロトコル（Google発、AAIF管理）の導入を設計に織り込む。現時点ではNATSメッセージングで十分だが、外部のAIエージェントサービスとの連携が必要になった場合にA2Aへ移行可能な抽象化層を設ける。

## 5.3 5つの自律性

V25のSYUTAINβは以下の5つの自律性を備える。

### 自律実行（Autonomous Execution）
目標だけを与えられたら、Capability Auditで使えるツールを確認し、Task Graphを生成し、5段階ループ（認識→思考→行動→検証→停止判断）で実行する。

### 自律判断（Autonomous Decision）
エラーが発生しても、エラークラスを分析し、代替経路を探索し、再試行の価値を判定して、続行/変更/停止を自分で決定する。試行回数には各レイヤーで適切な上限を設け（同一アクション再試行2回、再計画3回、総ステップ50回）、ループ処理に陥らない設計を堅牢にする。

### 自律調査（Autonomous Research）
情報収集パイプライン（Gmail API 80+キーワード→Tavily→Jina→RSS→YouTube API）を常時稼働させ、市場変化・技術トレンド・競合動向・新モデルリリースを自動で収集・要約・島原に報告する。V30統合：英語記事取り込みパイプラインにより海外トレンドも自動検知。

### 自律拡張（Autonomous Expansion）
新しいツール、API、MCPサーバーが利用可能になった場合、Capability Auditで検知し、統合の提案を島原に行う。承認されれば自動的にシステムに組み込む。

### 自律進化（Autonomous Evolution）
学習ループにより、どのモデルがどのタスクに最適か、どの提案が採用されやすいか、どのチャネルが反応が良いかを継続的に学習し、自身の判断精度を向上させる。さらに突然変異エンジン（第24章）により、学習ループでは到達できない局所解の外側へ、観測不能な微小変異を通じて不可逆的に進化する。

---

# 第6章 5段階自律実行ループ

## 6.1 ループ構造

```
┌─────────────────────────────────────────┐
│        SYUTAINβ 自律実行ループ V25        │
│                                          │
│  ① 認識（Perceive）                      │
│    └→ 目標を受ける / 環境を確認する         │
│    └→ MCPツール発見 / API状態確認          │
│    └→ 全4ノード状態確認（V25）             │
│  ② 思考（Think）                          │
│    └→ 計画を立てる / 代替案を用意する        │
│    └→ コスト見積り / 知能指数閾値判定        │
│    └→ Computer Use必要性判定（V25）        │
│  ③ 行動（Act）                            │
│    └→ ツールを使う / 成果物を作る           │
│    └→ NATSで適切なノードへディスパッチ       │
│    └→ ブラウザ操作/PC操作（V25）           │
│  ④ 検証（Verify）                         │
│    └→ 結果を評価する / 目標に近づいたか      │
│    └→ 品質スコアリング / 収益貢献度評価      │
│  ⑤ 停止判断（StopOrContinue）             │
│    └→ 続行 / 経路変更 / 人間エスカレ / 停止  │
│    └→ 9層ループガードチェック（V25）        │
│                                          │
│  ───→ ①に戻る（ループガード付き）          │
└─────────────────────────────────────────┘
```

## 6.2 各段階の詳細

### ① 認識（Perceive）

```yaml
perceive_checklist:
  goal_received: true
  goal_packet_generated: true
  capability_audit_done: true
  nodes_status_checked: true       # NATS heartbeat確認（全4台）
  bravo_status_checked: true       # V25: BRAVO Phase 1稼働確認
  mcp_tools_discovered: true       # MCP動的ツール発見
  budget_remaining_checked: true
  approval_boundaries_loaded: true
  strategy_files_loaded: true      # ICP/Channel/Content
  previous_attempts_loaded: true
  market_context_loaded: true      # 直近の情報収集結果
  api_availability_checked: true   # 各API死活確認
  browser_capability_checked: true # V25: 4層ブラウザ状態（Lightpanda/Stagehand v3/Chromium/GPT-5.4 Computer Use）
```

### ② 思考（Think）

```yaml
think_output:
  primary_plan:
    steps: [...]
    estimated_cost: ¥xxx
    estimated_time: xx分
    tools_needed: [...]
    models_selected: [...]         # 各ステップのモデル選定理由
    nodes_assigned: [...]          # ディスパッチ先ノード（全4台から選択。ALPHAはオーケストレーションのみ）
    browser_actions_needed: [...]  # V25: ブラウザ操作が必要なステップ（推奨層: lightpanda/stagehand/chromium/computer_use）
    computer_use_needed: [...]     # V25: GPT-5.4視覚操作が必要なステップ
    approval_points: [...]
    intelligence_requirements: [...]
  fallback_plan_1:
    trigger: "主プランのstep3が失敗した場合"
    steps:
      - "エラークラスを分析（auth/model/timeout/budget/logic/external/network/browser）"
      - "同じエラークラスで2回失敗していたらクラスタ凍結（Layer 2）"
      - "別モデル or 別ノードで再試行"
      - "再試行も失敗したらfallback_plan_2へ"
  fallback_plan_2:
    trigger: "APIが全て停止した場合"
    steps:
      - "ローカルLLMのみで運転継続（BRAVO/CHARLIE Qwen3.5-9B）"
      - "最終品質タスクは保留し、中間成果物をPostgreSQLに保存"
      - "Web UI + Discordで島原に通知"
      - "30分ごとにAPI復旧を確認し、復旧したら自動再開"
  fallback_plan_3:
    trigger: "BRAVOが停止した場合"  # V25新規
    steps:
      - "ブラウザ4層（Lightpanda/Stagehand v3/Chromium/GPT-5.4 CU）は全て停止"
      - "ブラウザ操作タスクは保留し、島原に通知"
      - "推論タスクはCHARLIEに振替"
      - "情報収集はDELTAのJina/Tavily APIで継続（ブラウザ不要）"
  abort_condition:
    - "コストが予算の80%を超える"
    - "同型失敗が2回連続"
    - "全ての代替プランが尽きた"
    - "セマンティックループ検知"
    - "Cross-Goalの干渉を検知"  # V25新規
```

### ③ 行動（Act）

```yaml
act_rules:
  - 1アクションにつき1つの明確な成果物を出す
  - 中間成果物はPostgreSQLに保存する（途中で止まっても資産化できる）
  - 外部API呼び出しは必ずtry-exceptで囲む
  - 実行前にツールの生存確認を行う（MCP ping / HTTP healthcheck）
  - 承認が必要なアクションは必ずApprovalManagerを通す
  - NATSでタスクをディスパッチし、適切なノードで実行する
  - ローカルLLM呼び出しはchoose_best_model_v6()で選定後に実行
  - ブラウザ操作はBRAVOの4層構成で実行：BrowserAgentがサイト特性に応じてLightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Useを自動選択（V25）
  - Computer Use操作はGPT-5.4 APIで実行、結果をスクリーンショット付きで記録（V25）
```

### ④ 検証（Verify）

```yaml
verify_result:
  status: success | partial | failure
  goal_progress: 0.0 - 1.0
  value_generated: true | false
  artifacts_saved: [...]
  error_class: null | auth | model | timeout | budget | logic | external | network | browser | browser_layer_exhausted
  retry_value: high | low | none
  revenue_contribution: 0.0 - 1.0
  quality_score: 0.0 - 1.0
  browser_action_success: true | false | n/a  # V25新規
```

### ⑤ 停止判断（StopOrContinue）

```yaml
stop_decision_tree:
  - if: goal_progress == 1.0
    then: COMPLETE
  - if: verify.status == "success" and remaining_steps > 0
    then: CONTINUE
  - if: verify.status == "partial" and retry_value == "high"
    then: RETRY_MODIFIED
  - if: verify.status == "failure" and fallback_available
    then: SWITCH_PLAN
  - if: verify.status == "failure" and no_fallback
    then: ESCALATE
  - if: loop_guard_triggered
    then: EMERGENCY_STOP
  - if: semantic_loop_detected
    then: SEMANTIC_STOP
  - if: cross_goal_interference_detected  # V25新規
    then: INTERFERENCE_STOP
```

## 6.3 Goal Packet の構造（V25版）

```yaml
goal_packet:
  goal_id: uuid
  raw_goal: "今月中にBoothで入口商品を1本出したい"
  parsed_objective: revenue
  success_definition:
    - 商品案が確定している
    - セールス導線が決まっている
    - 販売ページ文案がある
    - 人間承認待ちまで進んでいる
  hard_constraints:
    budget_limit_jpy: 500
    time_limit_hours: 4
    available_nodes: [ALPHA, BRAVO, CHARLIE, DELTA]  # V25: 全4台
    tools_available: [note_draft, booth_draft, x_posting_approval, lightpanda, stagehand_v3, playwright, computer_use_gpt54]  # V25: 4層ブラウザ構成
    mcp_tools_available: [...]
    api_keys_valid: [anthropic, openai, deepseek, openrouter, google]
  soft_constraints:
    - できれば低コスト
    - 非エンジニア再現性を保つ
  approval_boundary:
    human_required: [公開投稿, 課金発生, 外部アカウント変更, 価格設定]
    auto_allowed: [下書き生成, 分析, ログ整理, 候補案生成, 情報収集, ブラウザ情報収集]
  deadline: "2026-03-31"
  priority: high
  fallback_goals:
    - "商品テーマと文案の下書きまで完了し、島原の承認待ち状態にする"
    - "最低限、商品候補3案のリストを作成する"
  max_total_steps: 50
  max_retries_per_step: 2
  max_replans: 3
  intelligence_threshold: 0
```

---

# 第7章 Capability Audit（能力監査）

## 7.1 監査タイミング

- 目標を受けるたびに**必ず**実施
- 実行中にエラーが発生したら**再監査**
- 30分ごとに**定期監査**（NATS heartbeat + HTTP ping）
- 前回の監査結果との**差分を記録し、環境変化を検知**

## 7.2 Capability Snapshot（V25版、V30統合版）

```yaml
capability_snapshot:
  timestamp: "2026-04-04T14:30:00+09:00"
  nodes:
    alpha:
      status: healthy
      role: オーケストレーター専任/WebUI/DB/NATS_Server/Caddy
      cpu_load: 45%
      memory_used_gb: 8.2
      disk_free_gb: 120
      local_model: none  # V30統合：ALPHAにLLMなし
      local_model_status: n/a
      nats_server: running
      postgresql: running
      web_ui: running
    bravo:                                    # V25: Phase 1完全稼働
      status: healthy
      role: Browser/ComputerUse/推論ワーカー/27Bレビュー
      gpu: RTX_5070_12GB
      vram_free_gb: 5.5
      local_model: qwen3.5-9b
      local_model_27b: qwen3.5-27b            # V30統合新規
      local_model_status: running
      inference_speed: "16 tokens/sec (9B) / 5 tokens/sec (27B)"
      kv_cache_q8: true                        # V30統合新規
      playwright: running
      lightpanda: running                    # V25新規
      stagehand_v3: running                  # V25新規
      computer_use: available
      nats_server: connected                 # V25: 4ノードRAFTクラスタ参加
    charlie:
      status: healthy
      role: ローカルLLM推論/バッチ処理
      gpu: RTX_3080_10GB
      vram_free_gb: 3.5
      local_model: qwen3.5-9b-q4km
      local_model_status: running
      inference_speed: "14 tokens/sec"
      kv_cache_q8: true                        # V30統合新規
      nats_server: connected                 # V25: 4ノードRAFTクラスタ参加
      dual_boot_note: "Ubuntu稼働中。Win11切替で一時停止の可能性"
    delta:
      status: healthy
      role: 監視/補助/情報収集
      gpu: GTX_980Ti_6GB
      vram_free_gb: 1.5
      ram_total_gb: 48
      local_model: qwen3.5-4b-q4
      local_model_status: running
      inference_speed: "10 tokens/sec"
      kv_cache_q8: true                        # V30統合新規
      nats_server: connected                 # V25: 4ノードRAFTクラスタ参加
  llms:
    openai: { status: available, models: ["gpt-5.4", "gpt-5.4-pro", "gpt-5-mini", "gpt-5-nano"] }
    anthropic: { status: available, models: ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"] }
    deepseek: { status: available, models: ["deepseek-v3.2"] }
    google: { status: available, models: ["gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"] }
    openrouter: { status: available }
    alibaba: { status: available, models: ["qwen3.5-flash", "qwen3.5-plus"] }
    local_bravo: { status: available, model: "qwen3.5-9b", speed: "16 tok/s" }
    local_bravo_27b: { status: available, model: "qwen3.5-27b", speed: "5 tok/s" }  # V30統合新規
    local_charlie: { status: available, model: "qwen3.5-9b", speed: "14 tok/s" }
    local_delta: { status: available, model: "qwen3.5-4b", speed: "10 tok/s" }
  mcp_servers:
    syutain_tools: connected
    github: connected
    gmail: connected
    bluesky: connected
    tavily: connected
    jina: connected
  external_apis:
    gmo_coin: { status: available, rate_limit: "1 req/s" }
    bitbank: { status: available, rate_limit: "standard" }
    youtube_data_v3: { status: available, quota_remaining: 9500 }
    wise: { status: available }
  tools:
    lightpanda: true                         # V25新規: AI特化ヘッドレスブラウザ
    stagehand_v3: true                       # V25新規: AI駆動ブラウザ自動化フレームワーク
    playwright: true                         # V25: Chromiumフォールバック用
    computer_use_gpt54: true                 # V25新規
    x_posting: approval_required
    note_drafting: true
    booth_editing: false
    gumroad_editing: false
    github_push: approval_required
    bluesky_posting: approval_required
    crypto_trading: approval_required
  budget:
    daily_jpy_remaining: 250
    monthly_jpy_remaining: 2800
    monthly_budget_jpy: 2000                 # V30統合：¥2,000に引き上げ
    monthly_info_budget_remaining: 14000
    budget_mode: constrained
  human:
    time_available_today_minutes: 45
    approval_pending_count: 0
```

## 7.3 監査原則

- 監査前に勝手に大きな計画を立てない
- 使えないツールを前提にしたプランを主プランにしない
- 障害時は「今使える道具だけ」で現実的な次善策を出す
- 前回の監査結果との差分を記録し、環境変化を検知する
- ローカルLLMの推論速度を監査項目に含める
- MCPサーバーの接続状態を監査項目に含める
- API rate limitの残量を監査項目に含める
- **V25新規：CHARLIEのデュアルブート状態を監査（Ubuntu/Win11どちらが稼働中か）**
- **V25新規：BRAVOの4層ブラウザ可用性を監査（Lightpandaプロセス起動状態、Stagehand v3のCDP接続状態、Chromium起動可否、GPT-5.4 API到達可否）**
- **V30統合：ALPHAにローカルLLMがないことを前提として監査（LLM関連項目はBRAVO/CHARLIE/DELTAのみ）**

---

# 第8章 ループ防止9層（V25正式仕様）

V25では、V24の8層に**Layer 9: Cross-Goal Interference Detection**を追加し、計9層の防御壁を構築する。

## 8.1 Layer 1: Retry Budget
- 同一アクションの再試行は**2回まで**
- 3回目に入る前に**必ず**別方式へ切替
- 再試行前にエラークラスを分析し、同じ原因なら即切替

## 8.2 Layer 2: Same-Failure Cluster
- 同じ原因クラスタ（認証不良、UI変化、権限不足、モデル障害、タイムアウト等）で**2回**失敗したら、そのクラスタの再挑戦を**一時凍結**
- 凍結は30分間有効。30分後に環境が変わっていれば再挑戦可能

## 8.3 Layer 3: Planner Reset Limit
- 再計画は**最大3回**
- 3回目で成功確率が改善しない場合は停止 or 人間エスカレーション
- 各再計画時に「前回との差分」を明示

## 8.4 Layer 4: Value Guard
- 売上・学習・証拠・前進のいずれにも寄与しない再試行は**禁止**
- 「できるかもしれない」だけで回さない
- 各アクションの実行前に「この行動は何に寄与するか」を1行で宣言

## 8.5 Layer 5: Approval Deadlock Guard
- 承認待ちのまま同じ提案を再送し続けない
- 承認待ち中は代替の前進タスクへ移る
- 承認待ちが24時間超えたらリマインド通知を1回だけ送る（Web UI + Discord）

## 8.6 Layer 6: Cost & Time Guard
- コスト閾値（日次予算の80%）を超える処理は自動停止
- 時間閾値（1タスクに60分超）を超える処理は自動停止
- トークン閾値（1回の推論で10万トークン超）を超える処理はTier降格
- 高額モデルへの無限フォールバックを禁止

## 8.7 Layer 7: Emergency Kill
最終防衛線。以下のいずれかに該当したら**即座に全処理を停止**する。

```yaml
emergency_kill_conditions:
  - total_step_count >= 50
  - total_cost_jpy >= daily_budget * 0.9
  - same_error_count >= 5
  - time_elapsed_minutes >= 120
  - infinite_loop_score >= 3  # 状態ハッシュの重複が3回
```

## 8.8 Layer 8: Semantic Loop Detection
状態ハッシュだけでなく、**意味的に同じことを繰り返していないか**をLLMで判定する。

```yaml
semantic_loop_detection:
  trigger: "直近3アクションの目的・手法・結果が意味的に類似"
  method: "Qwen3.5-4B（DELTA）で直近3アクションの要約を比較"
  threshold: "類似度スコア0.85以上で発動"
  action: "SEMANTIC_STOP → 人間エスカレーション + 状況レポート出力"
  cost: "ローカルLLMで実行するため追加コスト¥0"
```

## 8.9 Layer 9: Cross-Goal Interference Detection（V25新規）

複数のGoal Packetが同時進行している場合、**あるゴールの行動が別のゴールを妨害していないか**を検知する。

```yaml
cross_goal_interference_detection:
  trigger: "2つ以上のGoal Packetが同時進行中"
  method: "OS_Kernelが各ゴールのリソース使用・API呼び出し・ノード占有を監視"
  detection_rules:
    - "同一APIへの同時大量リクエスト（rate limit競合）"
    - "同一ノードの計算リソース占有（GPU/CPU 90%超）"
    - "矛盾するアクション（例：同一アカウントで異なるトーンの投稿を準備）"
    - "予算の奪い合い（1ゴールが日次予算の60%以上を消費）"
  action: "INTERFERENCE_STOP → 優先度の低いゴールを一時停止 + 島原に報告"
  priority_resolution: "revenue_contribution > deadline_proximity > creation_order"
```

## 8.10 9層の連結フロー図

```
目標受信
    ↓
Goal Packet生成 → Capability Audit（全4台）
    ↓
Task Graph生成（主プラン + 代替プラン）
    ↓
実行ループ開始
    ↓
┌─ [Layer 9] Cross-Goalの干渉? ──→ INTERFERENCE_STOP
│
├─ [Layer 8] セマンティックループ検知? ──→ SEMANTIC_STOP
│
├─ [Layer 7] total_steps >= 50? ──→ EMERGENCY_KILL
│
├─ [Layer 6] cost/time超過? ──→ AUTO_STOP + レポート
│
├─ [Layer 5] 承認待ちデッドロック? ──→ 別タスクへ移行
│
├─ [Layer 4] この行動に価値あるか? ──→ 価値なし → SKIP
│
├─ [Layer 3] 再計画3回目? ──→ ESCALATE
│
├─ [Layer 2] 同型失敗2回? ──→ クラスタ凍結 + 別手段
│
├─ [Layer 1] 同一アクション再試行2回? ──→ 別方式切替
│
└─ ツール実行（NATSで適切なノードへディスパッチ）
      ↓
   [成功?]
      成功 → 検証 → 次ステップへ
      失敗 → エラー分類 → Layer 1-9で判定
      ↓
   目標達成判定
      達成 → タスク完了 → Web UI + Discord通知
      未達成 → ループ継続（ガード付き）
```

## 8.11 ブラウザ4層フォールバックのループ防止（V25新規）

ブラウザ4層構成（Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Use）は**一方向のみフォールバック**する。Layer 4まで失敗した場合、Layer 1に戻らず「ブラウザ操作不能」として処理を保留し、島原に通知する。

```yaml
browser_fallback_rules:
  direction: "Layer1 → Layer2 → Layer3 → Layer4 のみ（逆行・循環禁止）"
  max_fallback_per_url: 1  # 同一URLに対する同一層での再試行は1回のみ
  layer4_failure: "BROWSER_UNABLE → タスク保留 → 島原に通知"
  same_url_all_layers_fail: "そのURLを24時間ブラックリスト化し、代替手段（Jina Reader API等）を検討"
```

---

# 第9章 自律提案エンジン（3層構造）

## 9.1 3層提案構造

```
提案（Proposal）
  ├── なぜ今やるべきか（根拠データ付き）
  ├── 期待される成果（収益見積り付き）
  └── 必要な人間作業（所要時間付き）
反論（Counter）
  ├── この提案のリスク
  ├── やらない方が良い理由
  └── 失敗する条件
代替案（Alternative）
  ├── 提案が却下された場合の次善策
  ├── リスクを避けたい場合の別解
  └── もっと小さく始める案
```

## 9.2 提案の正式フォーマット（V25版、V30統合版）

```yaml
proposal_packet:
  proposal_id: uuid
  title: "今週は失敗談からBooth入口商品へ変換すべき"
  objective: revenue
  target_icp: hot_icp
  primary_channel: note
  support_channels: [x_shimabara, x_syutain, bluesky]
  build_in_public_check: true  # V30統合：テーマが「SYUTAINβで何が起きたか」に沿っているか

  # 提案層
  why_now:
    - 直近7日で失敗ログ系の保存率が高い（具体数値付き）
    - 入口商品の在庫がない
    - 競合分析で類似商品の需要を確認済み
    - 市場タイミング：年度末で新規事業検討が増える時期
  expected_outcome:
    revenue_estimate_jpy: 30000
    timeline: "1週間で販売開始可能"
    confidence: 0.7
  required_human_actions:
    - 最終商品名承認（所要5分）
    - 販売ページ公開承認（所要10分）
  auto_actions_allowed:
    - 下書き作成
    - LP構成案作成
    - 投稿導線作成
    - ブラウザでの競合調査（V25新規：BRAVO 4層ブラウザ自動操作）

  # 反論層
  counter:
    risks:
      - 商品対象外への訴求リスク（ICP外に届く可能性）
      - 失敗談が「自虐的」に見えるリスク
    dont_do_if:
      - 今週の島原の稼働が2時間未満
      - Membershipへの導線が未整備
    failure_conditions:
      - noteハブ記事のPVが週100未満の場合、送客力が不足

  # 代替案層
  alternatives:
    - title: "既存記事をリライトしてMembership限定にする"
      effort: low
      revenue_estimate: 10000
    - title: "失敗ログを無料noteにして信頼を先に積む"
      effort: low
      revenue_estimate: 0
      trust_building: high

  score: 84
```

## 9.3 提案品質管理（V30統合：大幅強化）

### 9.3.1 スコアリングの独立検証

Revenue Scoring（7軸100点満点）はLLM自身が採点するため、インフレ傾向がある。以下の対策を実装:

1. **上限値の強制キャップ**:
   - icp_fit ≤ 25, channel_fit ≤ 15, content_reuse ≤ 15
   - speed_to_cash ≤ 15, gross_margin ≤ 10, trust_building ≤ 10, continuity_value ≤ 10
   - 合計100点を超えた場合は100にクランプ
   - これにより、LLMが自分の提案に95点を付けても上限値で自動補正される

2. **自動承認閾値**: score ≥ 65（30分間隔のschedulerジョブで処理）

### 9.3.2 自動承認時のBuild in Public方針検証

提案が自動承認される前に、以下のチェックを通過する必要がある:

1. **未リリースモデル検証**: 提案のタイトル＋本文（why_now, first_action, expected_outcome）に含まれるモデル名を正規表現で検出。既知のリリース済みモデル（GPT-5.4, Claude 4, DeepSeek V3等）以外は、Tavily APIで公式リリース発表を外部検索。公式リリースが確認できなければreject。
   - 例: 「DeepSeek V4」→ 検索で公式リリースなし → reject（推測記事の可能性）
   - 例: DeepSeek V4が将来リリースされた場合 → 検索で公式発表がヒット → 通過

2. **外部AIニュース記事検出**: 「完全ガイド」「活用法」「導入ガイド」「選定基準」「最新動向」「速報」「まとめ」「徹底比較」「入門」等のパターンが提案に含まれ、かつ「SYUTAINβ」への言及がなければreject。

3. **検査対象**: タイトルだけでなく、提案の本文全体（why_now, first_action, expected_outcome）を含むフルテキストを検査

4. **rejectされた場合**: Discord通知で理由付きで報告

### 9.3.3 全3層でのBuild in Public方針適用

| 層 | BIP方針の適用 |
|----|-------------|
| Layer 1（提案） | プロンプト冒頭に「SYUTAINβで何が起きたか」最優先指示。外部AIニュース記事禁止。テーマ例付き |
| Layer 2（反論） | BIP違反があればrisksの最初の項目に「Build in Public方針違反」と明記する指示 |
| Layer 3（代替案） | 代替案もSYUTAINβ中心であること。外部AIガイドの代替案禁止 |
| 自動承認（scheduler） | タイトル+本文のフルテキスト検査。モデルリリース外部検証。パターンマッチ |

### 9.3.4 教訓: DeepSeek V4事件（2026年3月27日〜4月4日）

- intel_items（情報収集DB）に「Mystery AI model Hunter Alpha may be DeepSeek V4 in disguise」という**推測記事**が52件蓄積
- 提案エンジンがこれを「DeepSeek V4がリリースされた」と誤解
- 3/27〜4/4に12件のDeepSeek V4関連提案を生成、全てスコア80-95で自動承認
- 5件がゴール化され実行された
- **根本原因**: (1) スコアリングの自己採点インフレ、(2) ファクトチェックなし、(3) BIP方針未反映
- **対策**: 本セクション9.3の全施策を実装済み

## 9.4 週次定例提案（V25版）

毎週最低1回、SYUTAINβは以下を3層構造で提出する。

- 今週の優先収益施策 TOP3（反論・代替案付き）
- 今週切るべき施策 TOP2（切らない場合の損失試算付き）
- 今週再利用できる既存資産 TOP5（具体的な再利用方法付き）
- 直近反応から見たICP温度感（先週比の変化付き）
- 来週までに育てるべき商品・連載・導線
- ローカルLLMで自動化すべき新規タスクの提案
- モデル・ツール環境の変化に対する適応提案
- 情報収集パイプラインから得たトレンド・機会の報告
- 暗号通貨市場のシグナル分析（GMOコイン/bitbank連携）
- **V25新規：中長期（3ヶ月〜6ヶ月）の収益拡大ロードマップ提案**
- **V25新規：ブラウザ自動操作で効率化可能な作業の提案**
- **V30統合：Build in Publicテーマに沿ったnote記事の提案**

## 9.4 収益提案の評価軸

```yaml
revenue_proposal_score:
  icp_fit: 0-25
  channel_fit: 0-15
  content_reuse: 0-15
  speed_to_cash: 0-15
  gross_margin: 0-10
  trust_building: 0-10
  continuity_value: 0-10
  total: 100
```

70点未満の提案は「参考案」とし、自動優先提案には上げない。

---

# 第10章 収益OS設計

## 10.1 収益の根本方針

島原大知の**実名ドキュメンタリー性・失敗の資産化・非エンジニア翻訳力・VTuber運営知見・15年の映像制作経験**を核とした高再利用な資産型収益へ寄せる。

**V30統合：Build in Publicとの統合**
収益は手段であり目的ではない。SYUTAINβの全過程をドキュメンタリーとして公開し、そのプロセス自体が信頼構築と収益の源泉となる。

### 正式優先順位
1. **noteハブ + 無料深掘り記事**で信頼を作る（V30統合：テーマは「SYUTAINβで何が起きたか」）
2. **Booth / Stripe直接販売のスターター商品**で初回購入を作る
3. **Membership / Subscriptions** で継続課金へ移す
4. **有料note / 深掘りレポート**で理解課金を取る
5. **BtoB小規模受託 / 設計相談**で高単価回収する
6. **暗号通貨自動取引**で不労所得を構築する
7. **Micro-SaaS / デジタルツール販売**で自動収益を構築する
8. **V25新規：アフィリエイト戦略**（AI関連ツール・サービスの紹介報酬）

## 10.2 主力商品ポートフォリオ（V25版）

### A. 入口商品（低単価）¥980〜¥2,980
- AI導入スターター設計書
- 非エンジニア向けAI実装ロードマップ
- 失敗再発防止テンプレ集
- Claude Code / ChatGPT / OpenRouter 初期設定テンプレ
- ローカルLLM導入クイックスタート（Qwen3.5対応版）
- API費用削減チェックリスト
- 4PC分散AI構築クイックガイド
- **V25新規：GPT-5.4 Computer Use活用ガイド**

### B. 中核商品（中単価）¥4,980〜¥14,800
- SYUTAINβ式 事業OS導入パック
- コンテンツ設計テンプレ + CTAパック
- AI実装失敗DB + 再発防止パック
- 個人開発者向け 4PC / ローカル×クラウド混在運用ガイド
- ローカルLLM完全ガイド 2026（Qwen3.5 / ollama / vLLM）
- AI×映像制作ワークフロー設計パック
- MCP活用実践ガイド（エージェント構築編）
- NATS分散システム構築テンプレート
- **V25新規：AIエージェント × ブラウザ自動化 実践ガイド**

### C. 継続課金 ¥980〜¥2,980/月
- note Membership：週次収益・失敗・修正ログ
- X / note 限定の「今週やること」運用ログ
- 月次の市場観測・モデル使い分け更新
- 月次LLMコスト最適化レポート
- 最新AI動向の非エンジニア向け翻訳レポート
- AIエージェント開発進捗リアルタイムログ

### D. 高単価商品 / BtoB ¥30,000〜¥300,000/件
- 小規模事業者向けAI導入設計相談
- クリエイター向けAI事業OS導入壁打ち
- VTuber / エンタメ領域向けコミュニティ・導線設計
- 小規模チーム向け運用設計 / コンテンツ戦略レビュー
- AI活用コンサル 90分壁打ち（¥30,000）
- AI事業OS設計ワークショップ 3回セット（¥150,000）
- VTuber運営AI化コンサル 月次（¥100,000/月）
- 分散AIエージェントシステム構築支援（¥200,000〜）

### E. 自動収益
- **暗号通貨自動取引（GMOコイン / bitbank）**
  - GMOコイン：maker手数料 -0.01%（リベート）
  - bitbank：maker手数料 -0.02%（国内最大取引量）
  - AI分析による中長期トレンドフォロー戦略
  - 1日の取引上限を設定し、リスク管理を徹底
- **Micro-SaaS**
  - Stripe直接統合（手数料3.6%+¥40、最大利益）
  - AIツールのSaaS化（月額¥2,000〜¥5,000）
- **V25新規：アフィリエイト**
  - AI関連ツール・サービスの紹介報酬（note記事・Bluesky投稿経由）
  - OpenRouter / Tavily / 各種AIツールのアフィリエイト
  - 実体験に基づくレビュー記事で信頼性を担保

## 10.3 売上導線の正式順序

```
X（島原大知）/ Bluesky / Threads
→ 固定ポスト
→ noteハブ記事（テーマ：SYUTAINβで何が起きたか）
→ 失敗談 / 収益ログ / 設計思想記事
→ Booth / Stripe入口商品
→ Membership / X Subscriptions
→ 深掘り有料note
→ BtoB相談
→ 継続コンサル
```

## 10.4 デジタルコンテンツ販売プラットフォーム戦略

| プラットフォーム | 手数料 | ¥5,000時の手取り | 最適用途 |
|:--|:--|:--|:--|
| **Stripe（直接）** | 3.6% + ¥40 | ¥4,780 | **最大利益。V25の主力販売チャネル** |
| BOOTH | 5.6% + ¥45 | ¥4,675 | 日本国内、pixiv連携 |
| Lemon Squeezy | 5% + $0.50 | ~¥4,600 | グローバル、税務自動化 |
| Gumroad | 10% + $0.50 | ¥4,425 | 簡単設定だが高手数料 |

## 10.5 月次収益シミュレーション（V25版）

| 収益源 | 単価 | 月間目標数 | 月次収益（目標） | 担当ノード |
|:--|:--|:--|:--|:--|
| note有料記事 | ¥980〜1,980 | 50〜200件 | 5〜40万円 | CHARLIE |
| noteマガジン/Membership | ¥980〜2,980/月 | 50〜300人 | 5〜90万円 | CHARLIE |
| Booth/Stripe商品 | ¥980〜14,800 | 20〜100件 | 2〜100万円 | BRAVO |
| BtoB相談・コンサル | ¥3〜30万/件 | 1〜5件 | 3〜150万円 | ALPHA |
| YouTube広告 | 変動 | 1〜10万再生 | 1〜10万円 | CHARLIE |
| 暗号通貨自動取引 | 変動 | 継続 | 1〜20万円 | DELTA |
| Micro-SaaS | ¥2,000〜5,000/月 | 10〜50顧客 | 2〜25万円 | ALPHA |
| アフィリエイト（V25新規） | 変動 | 継続 | 1〜15万円 | BRAVO |
| **合計** | | | **20〜450万円** | |
| **現実的中央値** | | | **100〜180万円** | |

---

# 第11章 情報収集パイプライン

## 11.1 アーキテクチャ

```
┌─ 収集層 ─────────────────────────────────────┐
│ Google Alerts(80+キーワード) → Gmail API      │
│ RSS/Atom フィード → feedparser/fastfeedparser  │
│ Tavily Search API（AI特化検索）               │
│ YouTube API v3（動画・チャンネル監視）          │
│ Bluesky firehose（AT Protocol）               │
│ V25新規：新モデルリリース監視（GitHub/HF）     │
│ V30統合：英語記事取り込みパイプライン          │
└──────────────────────────────────────────────┘
         ↓
┌─ 抽出層 ─────────────────────────────────────┐
│ Jina Reader API（Web→Markdown変換）           │
│ newspaper4k（シンプルサイト用）                 │
│ V30統合：fetch_and_summarize_english_article() │
└──────────────────────────────────────────────┘
         ↓
┌─ 処理・保存層 ────────────────────────────────┐
│ PostgreSQL 重複排除                           │
│ Qwen3.5-4B（DELTA）で分類・重要度スコアリング  │
└──────────────────────────────────────────────┘
         ↓
┌─ 要約層 ─────────────────────────────────────┐
│ Qwen3.5-9B（CHARLIE/BRAVO）で日本語要約       │
│ 高重要度のみ DeepSeek-V3.2 で精度向上         │
│ V30統合：英語記事→ローカルLLM日本語要約       │
└──────────────────────────────────────────────┘
         ↓
┌─ 配信層 ─────────────────────────────────────┐
│ Web UIダッシュボード（Intel画面）              │
│ Discord Webhook（重要ニュースのみ）            │
│ 週次インテリジェンスレポート生成               │
│ V30統合：SNS/記事へのintelコンテキスト注入     │
└──────────────────────────────────────────────┘
```

## 11.2 Gmail APIによる80+キーワード監視

- Gmail APIは**無料**（250クォータユニット/ユーザー/秒）
- 80キーワードをGoogle Alertsに登録（無料）
- Gmail APIの`users.watch()`でPub/Subプッシュ通知、新着メールをリアルタイム検出
- 検索クエリ：`"keyword1" OR "keyword2" OR ...` で一括検索
- `messages.list`は5ユニット/コールで、秒間50回呼び出し可能
- **OAuth2トークン管理：** credentials.jsonに`access_type: "offline"`を指定し、refresh_tokenによる自動更新を有効化。Google APIクライアントライブラリ（`google-auth-oauthlib`）の標準機能で、token.jsonの期限切れ時にrefresh_tokenで自動再取得する。初回認証のみALPHA上でブラウザベースのOAuth2フローを実行。以降は無期限自動更新。MonitorAgent（DELTA）がtoken.jsonの有効期限を24時間ごとに確認し、更新失敗時はDiscord Webhook + Web UIで通知する

## 11.3 Tavily Search API

- AI エージェント専用検索API
- `/research`エンドポイントで自動マルチステップ調査
- `ultra-fast`検索深度が追加（最速レスポンス）
- 80キーワード×1日3回=240検索/日=月約7,200検索
- **Bootstrapプラン（$100/月、¥15,000）の15,000クレジットで十分**

## 11.4 Jina AI Reader API

- `https://r.jina.ai/{URL}` でクリーンなMarkdown取得
- **無料枠で1,000万トークン**（約3,333記事分）
- CSSセレクタターゲティング、JavaScript実行、PDF解析対応

## 11.5 YouTube API統合

- YouTube Data API v3でチャンネル・動画の監視
- 動画アップロードクォータが1,600→100ユニットに削減（自動化が容易に）
- AI生成コンテンツには`containsSyntheticMedia`フラグ設定が必須

## 11.6 英語記事取り込みパイプライン（V30統合新規）

海外のAI/テクノロジートレンドを自動的に収集・翻訳・活用する。

```python
# 英語記事取り込みの主要関数
async def fetch_and_summarize_english_article(url: str) -> dict:
    """
    英語記事をJinaで全文取得→ローカルLLMで日本語要約→intel_items DBに保存
    """
    # 1. Jina Reader APIで英語全文取得
    # 2. BRAVO/CHARLIE Qwen3.5-9Bで日本語要約生成
    # 3. intel_items テーブルに保存（source="english_article"）
    pass

async def enrich_overseas_trends() -> list:
    """
    海外トレンドをintel_itemsから抽出し、SNS/記事生成に注入
    """
    pass
```

**15英語キーワードでトレンド検知：**
```yaml
english_keywords:
  - "AI agent framework"
  - "autonomous AI system"
  - "local LLM deployment"
  - "multi-agent orchestration"
  - "AI cost optimization"
  - "AI business automation"
  - "open source AI"
  - "AI coding assistant"
  - "AI content generation"
  - "distributed AI system"
  - "AI browser automation"
  - "AI computer use"
  - "AI safety alignment"
  - "AI startup"
  - "AI monetization"
```

**処理フロー：**
1. Tavily/Jina で英語記事の全文を取得
2. ローカルLLM（BRAVO/CHARLIE Qwen3.5-9B）で日本語要約を生成
3. intel_items テーブルに `language="en"` タグ付きで保存
4. 高重要度の記事はSNS投稿やnote記事のコンテキストとして注入

## 11.7 月額コスト見積もり

| コンポーネント | 月額(USD) | 月額(JPY) |
|:--|:--|:--|
| Gmail API + Google Alerts | $0 | ¥0 |
| Tavily Search（Bootstrap） | $100 | ¥15,000 |
| Jina AI Reader（継続利用） | ~$3 | ~¥450 |
| LLM要約（ローカル主体） | ~$0.50 | ~¥75 |
| YouTube API | $0 | ¥0 |
| **合計** | **~$103.50** | **~¥15,525** |

---

# 第12章 戦略OS統合

## 12.1 外部戦略ファイル

SYUTAINβの判断基準ファイルとして以下を扱う。

- `ICP_DEFINITION.md` = **誰に売るかのOS**
- `CHANNEL_STRATEGY.md` = **どこで届けるかのOS**
- `CONTENT_STRATEGY.md` = **何をどう話すかのOS**
- `STRATEGY_IDENTITY.md` = **何者であるかのOS**（V30統合：Build in Public方針を含む）

SYUTAINβは提案・投稿・商品設計・導線改善を行うたび、必ずこの4文書を参照すること。

## 12.2 ICP OS 統合ルール

- Primary ICPは**AIに期待しているが技術者文化の外側にいる人**を中核に据える
- 「AIの知識」ではなく**安心して前進できる順番**を売る
- 対象者が「今の自分にもできる」と感じる導線を優先する
- 強者ムーブ・誇大表現・専門用語連打は避ける

```yaml
icp_tags:
  - hot_icp           # 今すぐ買う可能性がある
  - warm_icp          # 関心はあるがまだ決断しない
  - cold_icp          # 存在を知ったばかり
  - technical_watcher  # 技術者として観察している
  - small_business_b2b # BtoB小規模事業者
  - vtuber_operator    # VTuber運営者
  - creator_ai_curious # AI活用に興味があるクリエイター
```

## 12.3 Channel OS 統合ルール

### 島原大知アカウント（X）
- 役割：感情 / 挑戦 / 失敗 / 数字 / 判断理由
- 禁止：無機質設計スレッド量産、強者ムーブ、AI万能論
- 原則：**僕**、1投稿1メッセージ、価値を単体で出す

### SYUTAINβアカウント（X）
- 役割：分析 / 構造 / 仮説 / 改善ログ
- 禁止：感情ポエム、主役化、実体のない自動化アピール
- 原則：**私**、結論→根拠→示唆、CTAは1投稿1つ

### Bluesky
- Blueskyは4,200万ユーザーに到達
- AT Protocol APIはAPIキー不要でfirehoseアクセス可能
- カスタムフィードアルゴリズムの開発機会あり
- 競合の少ないエコシステムでの先行者利益を狙う
- **V30統合：Rich Text Facets（URLクリッカブル、OGPリンクカード）を実装**

### Threads
- **V30統合：テーマ別ハッシュタグ3個を自動付与**

### note
- ハブ記事 / 週次総括 / 月次総括 / 失敗分析 / 商品解説 / BtoB示唆
- **V30統合：テーマは必ず「SYUTAINβで何が起きたか」**
- **注意：note.comは2026年3月時点で公式APIを提供しておらず、今後の提供予定も未定**
- 最も安定したアプローチは「AIでMarkdown生成→手動ペースト」

### Booth / Stripe
- 初回購入の発生地点
- 高単価商品はStripe直接統合（手数料3.6%+¥40）

### GitHub
- 実在証明 + BtoB信用補助
- SYUTAINβの一部コンポーネントをOSS化し技術的信頼を構築
- **V30統合：全コードをPublicリポジトリとして公開（セキュリティ対応済み）**

## 12.4 Content OS 統合ルール

### 3層比率
- Reach: 40%
- Trust: 50%
- Conversion: 10%

### 失敗資産化の正式式
```
失敗 → 原因 → 再発防止 → 設計思想 → 商品 / note / Membership
```

### 売る順番の正式式
```
共感 → 透明性 → 継続観察 → 失敗 → 学び → 商品 → 継続課金 → BtoB
```

## 12.5 SNS拡散力強化（V30統合新規）

### Bluesky Rich Text Facets
- URL自動検出によるクリッカブルリンク生成
- OGPリンクカードの自動付与（外部埋め込み）
- AT Protocol の `app.bsky.richtext.facet` を使用

### テーマ別ハッシュタグ
```yaml
hashtag_strategy:
  x_posts: 2  # X投稿にはハッシュタグ2個
  threads_posts: 3  # Threads投稿にはハッシュタグ3個
  auto_selection: true  # テーマに基づいて自動選択
```

### note記事リンク自動挿入
- SNS投稿の20%にnote記事リンクを自動挿入
- Build in Public記事への導線として機能
- 過度な宣伝にならないよう頻度を制限

### intelコンテキスト注入
- intel_itemsから関連する最新情報をSNS投稿生成時に注入
- 海外トレンド情報を日本語に翻訳した上で参照
- 投稿の情報密度と独自性を向上

### エンゲージメント収集・分析基盤（2026年4月5日追加）

`tools/engagement_collector.py` — X/Bluesky/Threads全3プラットフォームの反応データを自動収集。

```
収集データ:
  X (Twitter)   : impressions, likes, retweets, replies (OAuth 1.0a, Free tier)
  Bluesky       : likes, reposts, replies (AT Protocol getPostThread)
  Threads       : views, likes, replies, reposts (Meta Graph API insights)

スケジュール: 4時間間隔（1日6回）
対象: 直近48時間のposted投稿
保存先: posting_queue_engagement（時系列）+ posting_queue.engagement_data（JSONB最新）
```

### 初回エンゲージメント分析結果（2026年4月5日、96投稿分）

**プラットフォーム別パフォーマンス:**
| プラットフォーム | 投稿数 | 平均imp | 最高imp | 評価 |
|:--|:--|:--|:--|:--|
| X（shimahara個人） | 8 | 186 | 282 | **◎ 唯一の有効チャネル** |
| X（syutain） | 12 | 7 | - | △ フォロワー不足 |
| Threads | 25 | 2.1 | 22 | ✗ ほぼ到達していない |
| Bluesky | 50 | 0 | 0 | ✗ 完全に到達していない |

**伸びるパターン:** 「AIツール×映像制作の具体的体験」（shimahara個人アカウント）
**伸びないパターン:** 抽象的なSYUTAINβ紹介、theme_hintリーク、ポエム調

### 日次ヘルスチェック（毎朝09:30 JST、2026年4月5日追加）

7項目を自動検査し、fail項目のみDiscordに報告:

| カテゴリ | 検査項目 |
|:--|:--|
| インフラ | ノード死活、ジョブ実行数、予算消化率 |
| コンテンツ | note記事公開状態、SNS投稿post_url存在 |
| 拡散指標 | エンゲージメントデータ記録有無 |
| SNS品質 | 直近投稿のスコアリング（score<0.40でfail） |

拡散に影響するfailは最優先で自動修正着手。

---

# 第13章 Task Graph 実行方式

## 13.1 基本原則

- 巨大タスクをそのまま回さず、依存関係つきの小タスクへ切る
- **1タスク1成果物**
- 中間成果物を**必ず**PostgreSQLに保存
- 止まっても途中成果物が売上や次回提案に転用できる構造にする
- NATSでタスクを適切なノードにディスパッチする
- **V25：4台全てにディスパッチ可能。BRAVO/CHARLIEでの並列推論を活用（ALPHAはオーケストレーションのみ）**

## 13.2 2段階精錬パイプライン

```
Step 1: Qwen3.5-9B（ローカル・CHARLIE or BRAVO）で荒原稿生成
    ↓
Step 2: 品質チェック（Qwen3.5-4B・DELTAで自動採点）
    ↓
  - 品質OK（スコア0.7以上）→ そのまま使用（コスト¥0）
  - 品質NG → DeepSeek-V3.2 or Claude Sonnet で仕上げ（最小コスト）
```

**V30統合版：Stage 4.5 セルフ批評（9B→27B）**
```
Step 1: Qwen3.5-9B（BRAVO/CHARLIE）で荒原稿生成
    ↓
Step 2: 品質チェック（Qwen3.5-4B・DELTAで自動採点）
    ↓
  - 品質OK（スコア0.7以上）：
    ↓
    Step 4.5: Qwen3.5-27B（BRAVO、Tier L+）でセルフ批評
      → 9Bが書いた原稿を27Bがレビュー・批評
      → ファクトチェック、論理整合性検証
      → 批評結果を反映して9Bが再修正
    ↓
  - 品質NG → DeepSeek-V3.2 or Claude Sonnet で仕上げ（最小コスト）
```

**V30統合版：BRAVO/CHARLIEの最大2台並列精錬**
BRAVO（Ollama）+ CHARLIE（Ollama）の2台が同時に異なる荒原稿を生成し、最も品質の高いものをDELTAが選定する。通常運用はBRAVO/CHARLIEの2台並列。

## 13.3 note記事生成の統合パス（V30統合新規）

**note_draft_generationはcontent_pipelineに統合済み。** scheduler.pyの重複コードパスを排除し、`content_pipeline.generate_publishable_content()` に一本化。

```python
# scheduler.pyからの呼び出し（統合後）
async def scheduled_note_generation():
    # 旧: note_draft_generation.generate() ← 削除済み
    # 新: content_pipeline経由で統一
    result = await content_pipeline.generate_publishable_content(
        content_type="note_article",
        theme_rule="build_in_public",  # V30統合：テーマルール適用
        quality_gate="6_layer_defense"  # V30統合：6層品質防御
    )
    return result
```

---

# 第14章 学習ループ

## 14.1 学習対象

- どのコンテンツが何の商品に転換したか
- どの連載が継続課金に効いたか
- どの導線がBtoB相談に繋がったか
- どのモデル/ツール選定が費用対効果に優れたか
- どの提案が島原に採用されたか
- どのローカルモデルがどのタスクで十分な品質を出したか
- 2段階精錬（ローカル→API）の成功率とコスト削減効果
- 3層提案のうち、どの層が島原の意思決定に最も影響したか
- Emergency Kill / Semantic Stop が発動した原因の傾向分析
- 季節・時事イベントと売上の相関
- 情報収集パイプラインの精度・有用性
- 暗号通貨取引の損益パターン
- **V25新規：ブラウザ操作の4層別成功率・エラーパターン**
  - Layer 1（Lightpanda）のサイト別成功率 → 失敗サイトリストの自動構築
  - Layer 2（Stagehand v3）のアクションキャッシュヒット率 → LLM呼び出し削減効果の追跡
  - Layer 3（Chromium）へのフォールバック頻度 → Lightpanda/Stagehandの改善指標
  - Layer 4（GPT-5.4 Computer Use）の使用頻度と成功率 → コスト最適化の判断材料
- **V25新規：Cross-Goal干渉の発生頻度とパターン**
- **V25新規（V30統合修正）：最大2台並列推論の品質比較結果**
- **V30統合新規：27Bセルフ批評の品質改善効果**
- **V30統合新規：Build in Publicテーマ準拠率とnote記事のエンゲージメント相関**

## 14.2 データベーステーブル（V25統合版）

```sql
-- ===== PostgreSQL（ALPHA・共有状態） =====

-- タスク管理
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    assigned_node TEXT,
    model_used TEXT,
    tier TEXT,
    input_data JSONB,
    output_data JSONB,
    artifacts JSONB,
    cost_jpy REAL DEFAULT 0.0,
    quality_score REAL,
    browser_action BOOLEAN DEFAULT FALSE,  -- V25新規
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Goal Packet
CREATE TABLE IF NOT EXISTS goal_packets (
    goal_id TEXT PRIMARY KEY,
    raw_goal TEXT NOT NULL,
    parsed_objective TEXT,
    success_definition JSONB,
    hard_constraints JSONB,
    soft_constraints JSONB,
    approval_boundary JSONB,
    status TEXT DEFAULT 'active',
    progress REAL DEFAULT 0.0,
    total_steps INTEGER DEFAULT 0,
    total_cost_jpy REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 提案履歴
CREATE TABLE IF NOT EXISTS proposal_history (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT UNIQUE,
    title TEXT,
    target_icp TEXT,
    primary_channel TEXT,
    score INTEGER,
    adopted BOOLEAN DEFAULT FALSE,
    outcome_type TEXT,
    revenue_impact_jpy INTEGER DEFAULT 0,
    proposal_data JSONB,
    counter_data JSONB,
    alternative_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 提案フィードバック
CREATE TABLE IF NOT EXISTS proposal_feedback (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    layer_used TEXT NOT NULL,
    adopted BOOLEAN DEFAULT FALSE,
    rejection_reason TEXT,
    alternative_chosen TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 収益紐付け
CREATE TABLE IF NOT EXISTS revenue_linkage (
    id SERIAL PRIMARY KEY,
    source_content_id TEXT,
    product_id TEXT,
    membership_offer_id TEXT,
    btob_offer_id TEXT,
    conversion_stage TEXT,
    revenue_jpy INTEGER DEFAULT 0,
    platform TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 能力監査スナップショット
CREATE TABLE IF NOT EXISTS capability_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_data JSONB NOT NULL,
    diff_from_previous JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ループガードイベント
CREATE TABLE IF NOT EXISTS loop_guard_events (
    id SERIAL PRIMARY KEY,
    goal_id TEXT NOT NULL,
    layer_triggered INTEGER NOT NULL,
    layer_name TEXT NOT NULL,
    trigger_reason TEXT,
    action_taken TEXT,
    step_count_at_trigger INTEGER,
    cost_at_trigger_jpy REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- モデル品質ログ
CREATE TABLE IF NOT EXISTS model_quality_log (
    id SERIAL PRIMARY KEY,
    task_type TEXT NOT NULL,
    model_used TEXT NOT NULL,
    tier TEXT NOT NULL,
    quality_score REAL DEFAULT 0.0,
    refinement_needed BOOLEAN DEFAULT FALSE,
    refinement_model TEXT,
    total_cost_jpy REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 季節収益相関
CREATE TABLE IF NOT EXISTS seasonal_revenue_correlation (
    id SERIAL PRIMARY KEY,
    month INTEGER,
    event_tag TEXT,
    product_category TEXT,
    revenue_impact_jpy INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 会話履歴（Web UIチャット用）
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 情報収集ログ
CREATE TABLE IF NOT EXISTS intel_items (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    keyword TEXT,
    title TEXT,
    summary TEXT,
    url TEXT,
    importance_score REAL DEFAULT 0.0,
    category TEXT,
    language TEXT DEFAULT 'ja',          -- V30統合新規：言語（ja/en）
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 暗号通貨取引ログ
CREATE TABLE IF NOT EXISTS crypto_trades (
    id SERIAL PRIMARY KEY,
    exchange TEXT NOT NULL,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,
    amount REAL,
    price REAL,
    fee_jpy REAL,
    pnl_jpy REAL,
    strategy TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 承認キュー
CREATE TABLE IF NOT EXISTS approval_queue (
    id SERIAL PRIMARY KEY,
    request_type TEXT NOT NULL,
    request_data JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ,
    response TEXT
);

-- ブラウザ操作ログ（V25新規）
CREATE TABLE IF NOT EXISTS browser_action_log (
    id SERIAL PRIMARY KEY,
    node TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_url TEXT,
    layer_used TEXT NOT NULL,          -- V25新規: lightpanda / stagehand_v3 / chromium / computer_use_gpt54
    fallback_from TEXT,                -- V25新規: フォールバック元の層（NULLなら最初の層で成功）
    screenshot_path TEXT,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    model_used TEXT,
    stagehand_cache_hit BOOLEAN,       -- V25新規: Stagehandアクションキャッシュがヒットしたか
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ベクトルストア（pgvector）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    content_type TEXT NOT NULL,
    content_id TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

# 第15章 KPI体系

## 15.1 最上位KPI

```yaml
north_star:
  monthly_revenue_total_jpy:
    target_12m: 1000000
    stretch_target: 3000000
  recurring_revenue_ratio:
    target: 0.45
  first_purchase_count_monthly:
    target: 50
  proposal_adoption_rate:
    target: 0.55
  content_to_product_conversion_rate:
    target: 0.10
  local_llm_usage_ratio:
    target: 0.75
  api_cost_monthly_jpy:
    target: 2000                         # V30統合：¥2,000に引き上げ
  info_pipeline_actionable_rate:
    target: 0.15
  browser_automation_success_rate:
    overall_target: 0.85  # V25新規：全体目標
    layer1_lightpanda_success: 0.0
    layer2_stagehand_success: 0.0
    layer3_chromium_success: 0.0
    layer4_computer_use_success: 0.0
    fallback_rate: 0.0
    stagehand_cache_hit_rate: 0.0
```

## 15.2 運用KPI

- ローカルLLM処理比率（目標75%）
- 2段階精錬の成功率（ローカルだけで品質OKだった割合）
- Emergency Kill / Semantic Stop / Interference Stop発動率（目標：月1回以下）
- 3層提案の代替案採用率
- タスク途中停止時の成果物資産化率
- NATSメッセージ配信成功率（目標：99.9%）
- Web UIレスポンス時間（目標：中央値200ms以下）
- 情報収集パイプラインの重要ニュース検出率
- **V25新規：ブラウザ4層の層別成功率（Lightpanda/Stagehand/Chromium/Computer Use）**
- **V25新規：ブラウザフォールバック発生率（低いほど良い）**
- **V25新規：Stagehandアクションキャッシュヒット率（高いほどLLMコスト削減）**
- **V25新規：4台ノード稼働率（目標：98%以上）**
- **V25新規：ブラウザ操作成功率（目標：85%以上）**
- **V30統合新規：note記事Build in Publicテーマ準拠率（目標：100%）**
- **V30統合新規：27Bセルフ批評による品質改善率**

---

# 第16章 シミュレーション設計（17シナリオ）

## 16.1 正常系シナリオ

### シナリオA：標準的な商品作成
- 入力：「今月中に入口商品を1本出したい」
- 期待動作：Goal Packet→Capability Audit（全4台）→Qwen3.5-9B(CHARLIE)で商品候補3案→BRAVO(4層ブラウザ)で競合調査→DeepSeek-V3.2でICPスコアリング→noteハブ導線案→Booth文案（ローカル→Claude Sonnetで仕上げ）→承認待ち→Web UI通知
- 検証：ローカル処理率75%以上、総コスト¥200以下

### シナリオB：低稼働時の最適提案
- 入力：「収益は欲しいが、今週は作業時間が少ない」
- 期待動作：稼働制約をGoal Packetに反映→既存資産再利用優先→低工数施策を3層提案→自動実行可能な範囲のみ進める

### シナリオC：反応悪化時の分析・提案
- 入力：「Xで反応が悪い。何を切るべきか」
- 期待動作：エンゲージメントデータ収集（BRAVOでブラウザ分析）→Channel/Content/ICPのズレ特定→切る施策TOP3を3層構造で提示

## 16.2 障害系シナリオ

### シナリオD：Claude API完全停止
- 期待動作：Capability Audit検知→ローカルQwen3.5 + DeepSeek-V3.2 + Gemini系へ退避→最終品質タスクのみ保留

### シナリオE：全APIが同時停止
- 期待動作：ローカルLLMのみで運転継続→BRAVO/CHARLIEのQwen3.5-9Bで並列処理→最終品質タスクは保留→Web UI通知

### シナリオF：X投稿承認が来ない
- 期待動作：Approval Deadlock Guard発動→24時間後にリマインド→別タスクへ移行

### シナリオG：CHARLIEのGPU障害 or Win11切替
- 期待動作：**BRAVOのQwen3.5-9Bにフォールバック**（V25：BRAVOが即座に推論を引き継ぐ）→DELTA(Qwen3.5-4B)も補助→コスト増加見積りを通知

### シナリオH：予算枯渇
- 期待動作：Cost Guard発動→Tier S/A凍結→ローカルLLMのみで運転

### シナリオI：NATSクラスタ障害
- 期待動作：JetStreamの永続化によりメッセージ損失なし→障害ノードをクラスタから除外→残存ノードでRAFTコンセンサス維持→直接HTTP通信にフォールバック→復旧後にNATS再参加

## 16.3 複合障害シナリオ

### シナリオJ：API停止 + ローカルLLM低品質
- 期待動作：品質不問タスク（ログ整形、分類、データ収集）のみ続行→「今できること」と「復旧後にやること」を分離して報告

### シナリオK：ループ処理に入りかけた場合
- 入力：Booth APIが500エラーを返し続ける
- 期待動作：Layer 1→2回リトライ→Layer 2→同型失敗凍結→Layer 4→文案だけ完成させる→人間に手動登録を依頼

### シナリオL：セマンティックループの防止
- 状況：Booth API登録を異なる方法で3回試みるが全て同じ根本原因（サーバー側障害）
- 期待動作：Layer 8 Semantic Loop Detection→Qwen3.5-4B(DELTA)で3アクションの類似性判定→スコア0.85超→SEMANTIC_STOP→「サーバー側障害のため手動対応を推奨」レポート出力

### シナリオM：無限再計画の防止
- 期待動作：Layer 3→再計画3回目で改善なし→現時点で最善の計画で実行開始

### シナリオN：目標自体が曖昧
- 入力：「なんか売上上げたい」
- 期待動作：Goal Packetの成功条件不明確→3つの具体的目標候補を3層提案→選択待ち中に既存データ分析を先行実行

### シナリオO：iPhone接続障害
- 状況：Tailscale接続が不安定でiPhoneからダッシュボードに接続できない
- 期待動作：重要通知はDiscord Webhookにフォールバック→システム自体は停止しない→接続回復後にWeb UIで最新状態を表示

### シナリオP：Cross-Goal干渉（V25新規）
- 状況：「note記事を量産する」ゴールと「暗号通貨取引を最適化する」ゴールが同時進行し、APIコストが競合
- 期待動作：Layer 9 Cross-Goal Interference Detection→revenue_contributionで優先度判定→低優先ゴールを一時停止→島原に報告

### シナリオQ：BRAVO障害時の全体フォールバック（V25新規）
- 状況：BRAVOが物理障害で停止
- 期待動作：NATS heartbeat失敗検知→ブラウザ操作4層（Lightpanda/Stagehand v3/Chromium/GPT-5.4 Computer Use）は全て停止→ブラウザ操作タスクは保留→推論タスクはCHARLIEに振替→Computer Useタスクは「手動対応」として島原に通知→情報収集はDELTAのJina/Tavily APIで継続（ブラウザ不要）

---

# 第17章 発行済みAPI・外部サービスの管理

## 17.1 発行済みAPI一覧

| サービス | 用途 | 認証方式 | 制限事項 |
|:--|:--|:--|:--|
| Anthropic API | Claude Opus/Sonnet/Haiku | APIキー | Batch 50%割引あり |
| OpenAI API | GPT-5.4/Mini/Nano | APIキー | 1Mコンテキスト対応 |
| Gemini API | Gemini 3.1 Pro/2.5 Flash等 | APIキー | 無料枠あり |
| DeepSeek API | DeepSeek-V3.2 | APIキー | キャッシュ$0.028 |
| OpenRouter API | 100+モデル統合アクセス | APIキー | 統一課金 |
| GMOコイン API | 暗号通貨取引 | APIキー | **1リクエスト/秒** |
| bitbank API | 暗号通貨取引 | APIキー | ccxtライブラリ対応 |
| Bluesky (AT Protocol) | SNS投稿・フィード | アプリパスワード | APIキー不要でfirehose可 |
| Wise API | 国際送金 | APIキー | — |
| Tavily API | AI特化検索 | APIキー | Bootstrapプラン15,000クレジット |
| Jina API | Web→Markdown変換 | APIキー | 無料枠1,000万トークン |
| GitHub API | リポジトリ管理 | トークン | — |
| Gmail API | メール監視 | OAuth 2.0 | 250クォータ/ユーザー/秒 |
| YouTube Data API v3 | 動画管理 | APIキー | 10,000ユニット/日 |

## 17.2 API管理の原則

- 全APIキーは`.env`で一元管理し、コードにハードコードしない
- 月1回の`docs/external_sources.md`監査ジョブでAPI仕様変更を確認
- Rate Limitを各API呼び出し時にチェックし、超過時は自動待機
- API障害時はCapability Auditで検知し、代替経路に切り替え

## 17.3 ローカルツールのバージョン管理（V25新規）

| ツール | 更新頻度 | 更新方法 | 管理ノード |
|:--|:--|:--|:--|
| Lightpanda | nightly build | `curl -L -o lightpanda https://github.com/lightpanda-io/browser/releases/download/nightly/lightpanda-x86_64-linux && chmod a+x ./lightpanda && sudo mv ./lightpanda /usr/local/bin/` | BRAVO |
| Stagehand v3 | npm更新 | `pnpm update @browserbasehq/stagehand` | BRAVO |
| Ollama | 月1回確認 | `curl -fsSL https://ollama.ai/install.sh \| sh` | BRAVO/CHARLIE/DELTA |

- Lightpandaはベータ版のためnightly buildで機能改善が頻繁。月2回程度バイナリを更新し、既存の操作が壊れていないかBrowserAgentの学習ログで確認
- Stagehandのバージョンアップ時はPlaywright互換性に注意（公式の注意書きに従う）
- 更新後は必ず`lightpanda fetch https://example.com`でLightpandaの動作確認を行う

---

# 第18章 人間作業の詳細手順（本格実装前）

**前提：以下は既に完了済み**
- `.env` ファイルの作成
- `CHANNEL_STRATEGY.md` の作成
- `CONTENT_STRATEGY.md` の作成
- `ICP_DEFINITION.md` の作成
- BRAVO、CHARLIE、DELTAへのUbuntuクリーンインストール

## 18.1 PHASE 0-A：アカウント・APIキー確認（所要約2時間）

| # | サービス | URL | 確認方法 | 所要 |
|:--|:--|:--|:--|:--|
| 1 | Anthropic | console.anthropic.com | curlでモデル一覧取得 | 10分 |
| 2 | OpenAI | platform.openai.com | curlでモデル一覧取得 | 10分 |
| 3 | OpenRouter | openrouter.ai | ダッシュボード残高確認 | 5分 |
| 4 | Google AI Studio | aistudio.google.com | Gemini APIテスト | 10分 |
| 5 | DeepSeek | platform.deepseek.com | V3.2テスト | 10分 |
| 6 | Discord | discord.com | Webhookテスト | 10分 |
| 7 | Tavily | tavily.com | 検索テスト | 5分 |
| 8 | Jina | jina.ai | Reader APIテスト | 5分 |
| 9 | GMOコイン | coin.z.com | API接続テスト | 10分 |
| 10 | bitbank | bitbank.cc | API接続テスト | 10分 |
| 11 | Bluesky | bsky.app | ログイン確認 | 5分 |
| 12 | GitHub | github.com | pushテスト | 10分 |
| 13 | Tailscale | tailscale.com | **4台+iPhone相互ping** | 20分 |

## 18.2 PHASE 0-B：ハードウェア準備（所要約4時間）

### ALPHA（Mac mini M4 Pro 16GB）— V30統合：LLMなし

```bash
# 1. Homebrew（インストール済みなら不要）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. 必須ソフトウェア（MLXは不要 — ALPHAにLLMなし）
brew install python@3.12 node postgresql@16

# 2-b. NATS Server（Homebrewにない場合はバイナリ直接ダウンロード）
brew install nats-server 2>/dev/null || {
  echo "Homebrewにnats-serverがないため、バイナリを直接ダウンロードします"
  curl -sf https://binaries.nats.dev/nats-io/nats-server/v2@latest | sh
  sudo mv nats-server /usr/local/bin/
}

# 3. PostgreSQL起動・初期化
brew services start postgresql@16
createdb syutain_beta

# 4. NATS Server設定
mkdir -p ~/.config/nats
cat > ~/.config/nats/nats-server.conf << 'EOF'
listen: 0.0.0.0:4222
jetstream {
    store_dir: /Users/$(whoami)/.nats/jetstream
    max_mem: 256M
    max_file: 2G
}
cluster {
    name: syutain
    listen: 0.0.0.0:6222
    routes: [
        nats-route://BRAVO_TAILSCALE_IP:6222  # BRAVO
        nats-route://100.98.82.108:6222  # CHARLIE
        nats-route://100.99.122.69:6222  # DELTA
    ]
}
EOF

# 5. Tailscale
brew install tailscale

# 6. 確認（MLXは不要）
python3 --version    # 3.12以上
node --version       # 18以上
psql syutain_beta -c "SELECT 1;"  # PostgreSQL接続確認
nats-server --version # v2.12.5以上
tailscale status     # 4台見えること
```

### BRAVO（Ryzen + RTX 5070 12GB）← V25: Phase 1フルセットアップ、V30: 27B追加

```bash
# 1. Ubuntu 24.04 確認（インストール済み）
cat /etc/os-release

# 2. NVIDIA ドライバ + CUDA
sudo apt update && sudo apt install -y nvidia-driver-560 nvidia-cuda-toolkit
nvidia-smi  # RTX 5070 12GB表示確認

# 3. Python + Node.js + pnpm
sudo apt install -y python3.12 python3-pip
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
npm install -g pnpm

# 4. NATS Server + クラスタ参加設定（4ノードRAFT）
curl -sf https://binaries.nats.dev/nats-io/nats-server/v2@latest | sh
sudo mv nats-server /usr/local/bin/
sudo mkdir -p /etc/nats
sudo tee /etc/nats/nats-server.conf << 'EOF'
listen: 0.0.0.0:4222
jetstream {
    store_dir: /var/lib/nats/jetstream
    max_mem: 256M
    max_file: 5G
}
cluster {
    name: syutain
    listen: 0.0.0.0:6222
    routes: [
        nats-route://ALPHA_TAILSCALE_IP:6222
        nats-route://100.98.82.108:6222
        nats-route://100.99.122.69:6222
    ]
}
EOF

# 5. Ollama（Qwen3.5-9B + 27B用）+ KV Cache Q8
curl -fsSL https://ollama.ai/install.sh | sh
# systemd環境変数設定（KV Cache Q8有効化）
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama pull qwen3.5:9b
ollama pull qwen3.5:27b   # V30統合新規：27Bモデル追加
ollama run qwen3.5:9b "こんにちは。テストです。" --verbose

# 6. Playwright + Chromium（ブラウザ4層のLayer 3フォールバック用）
pip3 install playwright --break-system-packages
playwright install chromium
playwright install-deps

# 7. Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4  # IPアドレス確認

# 8. Lightpanda（AI特化ヘッドレスブラウザ）
curl -L -o lightpanda https://github.com/lightpanda-io/browser/releases/download/nightly/lightpanda-x86_64-linux
chmod a+x ./lightpanda
sudo mv ./lightpanda /usr/local/bin/
LIGHTPANDA_DISABLE_TELEMETRY=true lightpanda fetch https://example.com  # 動作確認

# 9. Stagehand v3（AI駆動ブラウザ自動化 — Node.jsは#3でインストール済み）
# Stagehandはプロジェクトディレクトリでpnpm installにより導入される

# 10. systemd設定用ディレクトリ
sudo mkdir -p /etc/syutain

# 11. 動作確認
nvidia-smi  # GPU認識
ollama list  # qwen3.5:9b, qwen3.5:27b 表示
python3 -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
lightpanda fetch https://example.com  # Lightpanda動作確認
tailscale status  # 4台見えること
```

### CHARLIE（Ryzen 9 + RTX 3080 10GB）

```bash
# 1. Ubuntu 24.04 確認（インストール済み）
cat /etc/os-release

# 2. NVIDIA ドライバ + CUDA
sudo apt update && sudo apt install -y nvidia-driver-550 nvidia-cuda-toolkit
nvidia-smi  # RTX 3080 10GB表示確認

# 3. Python 3.12（SYUTAINβエージェント実行に必要）
sudo apt install -y python3.12 python3-pip

# 4. NATS Server
curl -sf https://binaries.nats.dev/nats-io/nats-server/v2@latest | sh
sudo mv nats-server /usr/local/bin/

# 5. NATS設定（JetStream + クラスタ参加）
sudo mkdir -p /etc/nats
sudo tee /etc/nats/nats-server.conf << 'EOF'
listen: 0.0.0.0:4222
jetstream {
    store_dir: /var/lib/nats/jetstream
    max_mem: 256M
    max_file: 5G
}
cluster {
    name: syutain
    listen: 0.0.0.0:6222
    routes: [
        nats-route://ALPHA_TAILSCALE_IP:6222
        nats-route://BRAVO_TAILSCALE_IP:6222
        nats-route://100.99.122.69:6222
    ]
}
EOF

# 6. Ollama（Qwen3.5-9B用）+ KV Cache Q8
curl -fsSL https://ollama.ai/install.sh | sh
# systemd環境変数設定（KV Cache Q8有効化）
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama pull qwen3.5:9b
ollama run qwen3.5:9b "こんにちは。テストです。" --verbose

# 7. Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4  # 100.98.82.108 確認
```

### DELTA（Xeon E5 + GTX 980Ti 6GB + 48GB RAM）

```bash
# 1. Ubuntu 24.04 確認（インストール済み）
cat /etc/os-release

# 2. NVIDIA ドライバ（GTX 980Ti用。OllamaのGPU推論に必要）
sudo apt update && sudo apt install -y nvidia-driver-535
nvidia-smi  # GTX 980Ti 6GB表示確認

# 3. Python 3.12（SYUTAINβエージェント実行に必要）
sudo apt install -y python3.12 python3-pip

# 4. NATS + クラスタ参加設定（4ノードRAFT）
curl -sf https://binaries.nats.dev/nats-io/nats-server/v2@latest | sh
sudo mv nats-server /usr/local/bin/
sudo mkdir -p /etc/nats
sudo tee /etc/nats/nats-server.conf << 'EOF'
listen: 0.0.0.0:4222
jetstream {
    store_dir: /var/lib/nats/jetstream
    max_mem: 256M
    max_file: 5G
}
cluster {
    name: syutain
    listen: 0.0.0.0:6222
    routes: [
        nats-route://ALPHA_TAILSCALE_IP:6222
        nats-route://BRAVO_TAILSCALE_IP:6222
        nats-route://100.98.82.108:6222
    ]
}
EOF

# 5. Ollama + KV Cache Q8
curl -fsSL https://ollama.ai/install.sh | sh
# systemd環境変数設定（KV Cache Q8有効化）
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama pull qwen3.5:4b
ollama run qwen3.5:4b "テスト" --verbose

# 6. SQLCipher（突然変異エンジン用暗号化SQLite）
sudo apt install -y sqlcipher libsqlcipher-dev
pip3 install pysqlcipher3 --break-system-packages

# 7. llama.cpp（CPUフォールバック推論用）
sudo apt install -y build-essential cmake
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp && cmake -B build && cmake --build build --config Release && cd ..

# 8. Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4  # 100.99.122.69 確認
```

### 全ノード相互疎通確認

```bash
# ALPHA上で実行
ping -c 3 $(tailscale ip -4 bravo)   # BRAVO
ping -c 3 100.98.82.108              # CHARLIE
ping -c 3 100.99.122.69              # DELTA

# NATS疎通確認（全ノード起動後）
nats sub "test.>" &
nats pub test.hello "V25 connectivity test"

# ローカルLLM疎通確認（ALPHAにはOllamaなし）
curl http://$(tailscale ip -4 bravo):11434/api/tags  # BRAVO Ollama
curl http://100.98.82.108:11434/api/tags              # CHARLIE Ollama
curl http://100.99.122.69:11434/api/tags              # DELTA Ollama
```

### ALPHA→各ノードのSSH鍵設定（Claude Codeがssh経由でデプロイするために必要）

```bash
# ALPHA上で実行
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""  # パスフレーズなし

# 各ノードに公開鍵を配布（Tailscale IP経由）
# V30統合：SSHユーザー名は環境変数 $SSH_USER で管理
ssh-copy-id -i ~/.ssh/id_ed25519.pub $SSH_USER@$(tailscale ip -4 bravo)
ssh-copy-id -i ~/.ssh/id_ed25519.pub $SSH_USER@100.98.82.108  # CHARLIE
ssh-copy-id -i ~/.ssh/id_ed25519.pub $SSH_USER@100.99.122.69  # DELTA

# 接続テスト
ssh $SSH_USER@$(tailscale ip -4 bravo) "hostname"  # bravoと表示
ssh $SSH_USER@100.98.82.108 "hostname"             # charlieと表示
ssh $SSH_USER@100.99.122.69 "hostname"             # deltaと表示
```

## 18.3 PHASE 0-C：設定ファイル確認（.envは作成済み）

feature_flags.yamlの内容を以下の通り設定する：

```yaml
version: "v25_v30"

# Phase 1（初期起動）— V25: 全機能有効、V30統合版
web_ui: true
web_ui_chat: true
discord_notifications: true
nats_messaging: true
postgresql_shared_state: true
local_llm_charlie: true
local_llm_delta: true
local_llm_alpha_mlx: false               # V30統合：ALPHAにLLMなし
local_llm_alpha_mode: "off"              # V30統合：off固定
local_llm_bravo: true
local_llm_bravo_27b: true                # V30統合新規：BRAVO 27Bモデル
kv_cache_q8_all_nodes: true              # V30統合新規：全ノードKV Cache Q8
api_llm: true
openrouter_integration: true
goal_packet: true
capability_audit: true
task_graph: true
proposal_engine: true
loop_guard_9layer: true                  # V25：9層
semantic_loop_detection: true
cross_goal_interference: true            # V25新規
emergency_kill: true
two_stage_refinement: true
mcp_integration: true
info_pipeline: true
tailscale_https: true
computer_use_playwright: true            # V25：Chromiumフォールバック用
computer_use_lightpanda: true            # V25新規
computer_use_stagehand_v3: true          # V25新規
computer_use_gpt54: true                 # V25新規
mutation_engine: true                    # V25新規：第24章 突然変異エンジン
build_in_public: true                    # V30統合新規
note_quality_6layer: true                # V30統合新規：6層品質防御
english_article_pipeline: true           # V30統合新規：英語記事取り込み
sns_rich_text: true                      # V30統合新規：Bluesky Rich Text等

# 推論モード設定
delta_inference_mode: "auto"             # auto=GPU優先でCPUフォールバック / gpu=GPU固定 / cpu=CPU固定

# 夜間モード（V30統合：23:00-09:00 JST、10時間）
night_mode:
  start_hour: 23
  end_hour: 9
  max_concurrent_tasks: 6
  local_llm_priority: 100
  gpu_temp_limit: 85

# Phase 2（後から有効化）
bluesky_auto_post: false
x_auto_post: false
note_auto_publish: false
booth_auto_publish: false
crypto_auto_trading: false
stripe_integration: false

# モデル設定
default_local_model_charlie: "qwen3.5:9b"
default_local_model_delta: "qwen3.5:4b"
default_local_model_bravo: "qwen3.5:9b"
default_local_model_bravo_27b: "qwen3.5:27b"  # V30統合新規
default_api_model: "deepseek-v3.2"
premium_model: "claude-sonnet-4-6"
highest_intelligence_model: "gpt-5.4"
computer_use_model: "gpt-5.4"

# 月額予算（V30統合：¥2,000に引き上げ）
monthly_api_budget_jpy: 2000
note_article_cost_limit_jpy: 15
note_daily_cost_limit_jpy: 120
note_monthly_cost_limit_jpy: 1000
```

---

# 第19章 Claude Code 一撃実装用・V25最終プロンプト

以下をClaude Codeへ貼り付けて、**V25（V30統合版）準拠で実装**させる。

```text
あなたはSYUTAINβ V25（V30統合版）の主任実装エンジニアです。
以下のルールを最優先で守り、このプロジェクトを段階的に構築してください。

最重要条件:
1. `SYUTAINβ_完全設計書_V25_V30統合.md` を最上位仕様として採用すること
2. V25はV20〜V24の全設計を再構成・統合した原典設計書であり、過去設計を削除しない
3. 実装対象は「4台のPCがPhase 1初日から全て連携し、NATS+Tailscaleで通信し、MCPで外部ツールを統合し、Web UIでiPhoneからリアルタイム監視でき、目標だけ受けても認識→思考→行動→検証→停止判断の5段階自律ループで動く自律分散型事業OS」である
4. strategy/ICP_DEFINITION.md, strategy/CHANNEL_STRATEGY.md, strategy/CONTENT_STRATEGY.md, strategy/STRATEGY_IDENTITY.md を意思決定OSとして組み込むこと
5. ループ防止はV25の9層構造（Semantic Loop Detection + Cross-Goal Interference Detection含む）で実装すること
6. 人間承認が必要な操作はApprovalManagerを必ず通すこと
7. PostgreSQL（共有状態）+ SQLite（ノードローカル）のハイブリッドDB構成
8. NATS v2.12.5 + JetStreamでノード間メッセージング
9. 4台のPC（ALPHA/BRAVO/CHARLIE/DELTA）をPhase 1初日から全て稼働させること。BRAVOをPhase 2に先送りしないこと
10. ローカルLLM配置：ALPHAにLLMなし（オーケストレーター専任）, BRAVO=Qwen3.5-9B+27B(Ollama), CHARLIE=Qwen3.5-9B(Ollama), DELTA=Qwen3.5-4B(Ollama)
11. 2段階精錬パイプライン（ローカル→API）を標準化し、BRAVO/CHARLIE並列推論（最大2台）を活用。Stage 4.5として27Bセルフ批評を実装
12. 3層提案エンジン（提案→反論→代替案）を実装すること
13. Web UI: FastAPI(SSE) + Next.js 16(PWA) + 双方向チャット(WebSocket)
14. OpenRouter APIで100+モデルへの統合アクセスを実装すること
15. MCP統合でGitHub/Gmail/Bluesky/Tavily/Jinaに接続すること
16. 情報収集パイプライン（Gmail API 80+キーワード→Tavily→Jina→RSS→YouTube + 英語記事取り込み）を実装すること
17. BRAVOでブラウザ自動操作4層構成（Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Use）を有効化すること
18. 本実装は「まず動く最小構成」から始め、後から拡張しやすい構造にすること
19. BRAVO/CHARLIE/DELTAはUbuntu 24.04。CHARLIEはWin11とのデュアルブート
20. 第24章「突然変異エンジン（Mutation Engine）」を設計書通りに実装すること
21. Build in Public方針：note記事テーマは「SYUTAINβで何が起きたか」に統一
22. note品質6層防御を実装すること
23. 全リモートノードでKV Cache Q8を有効化すること
24. 夜間モード（23:00-09:00 JST、10時間）を実装すること
25. 月額API予算¥2,000、note記事コスト制限（記事¥15、日次¥120、月次¥1,000）
```

---

# 第20章 実装ディレクトリ構造（V25完全版）

```text
~/syutain_beta/
├── .env
├── .env.example
├── .gitignore                            # V30統合：GitHub公開用セキュリティ設定含む
├── CLAUDE.md                              # 29条
├── README.md
├── SYUTAINβ_完全設計書_V25.md
├── feature_flags.yaml
├── requirements.txt
├── docker-compose.yaml                    # PostgreSQL + NATS開発環境
├── app.py                                 # FastAPI バックエンド (ALPHA)
├── scheduler.py                           # スケジューラー（70ジョブ）
├── worker_main.py                         # Worker エントリーポイント
├── start.sh                               # ALPHA 起動スクリプト
├── docs/
│   ├── external_sources.md
│   ├── ops_runbook.md
│   ├── approval_policy.md
│   ├── revenue_playbook.md
│   └── simulation_results.md
├── agents/
│   ├── __init__.py
│   ├── os_kernel.py                       # OS_Kernel（司令塔）
│   ├── perceiver.py                       # 認識エンジン
│   ├── planner.py                         # 思考・計画エンジン
│   ├── executor.py                        # 行動エンジン
│   ├── verifier.py                        # 検証エンジン
│   ├── stop_decider.py                    # 停止判断エンジン
│   ├── proposal_engine.py                 # 3層提案エンジン
│   ├── approval_manager.py                # 承認管理
│   ├── capability_audit.py                # 能力監査
│   ├── learning_manager.py                # 学習管理
│   ├── node_router.py                     # ノードルーティング
│   ├── chat_agent.py                      # 双方向チャットエージェント
│   ├── monitor_agent.py                   # DELTA常駐監視エージェント
│   ├── info_collector.py                  # DELTA常駐情報収集エージェント
│   ├── browser_agent.py                   # V25: BRAVOブラウザ操作エージェント
│   ├── computer_use_agent.py              # V25: GPT-5.4 Computer Useエージェント
│   ├── content_pipeline.py                # V30統合：コンテンツ生成統合パイプライン
│   └── mutation_engine.py                 # V25: 突然変異エンジン（第24章）
├── tools/
│   ├── __init__.py
│   ├── llm_router.py                      # V25: choose_best_model_v6（highest_local対応）
│   ├── model_registry.py
│   ├── two_stage_refiner.py               # 2段階精錬パイプライン（27Bセルフ批評含む）
│   ├── node_manager.py
│   ├── loop_guard.py                      # V25: 9層ループ防止
│   ├── semantic_loop_detector.py
│   ├── cross_goal_detector.py             # V25: Cross-Goal干渉検知
│   ├── emergency_kill.py
│   ├── budget_guard.py
│   ├── nats_client.py                     # NATS接続クライアント
│   ├── mcp_manager.py                     # MCP統合マネージャー
│   ├── social_tools.py                    # V30統合：Rich Text Facets、ハッシュタグ等
│   ├── engagement_collector.py            # SNSエンゲージメント収集（X/Bluesky/Threads、4h間隔）
│   ├── commerce_tools.py
│   ├── content_tools.py
│   ├── analytics_tools.py
│   ├── storage_tools.py
│   ├── crypto_tools.py                    # GMOコイン/bitbank連携
│   ├── info_pipeline.py                   # 情報収集パイプライン
│   ├── english_article_pipeline.py        # V30統合新規：英語記事取り込み
│   ├── tavily_client.py                   # Tavily検索クライアント
│   ├── jina_client.py                     # Jina Readerクライアント
│   ├── playwright_tools.py                # V25: Playwright操作ツール
│   ├── lightpanda_tools.py                # V25新規: Lightpanda操作ツール
│   ├── stagehand_tools.py                 # V25新規: Stagehand v3統合ツール
│   ├── computer_use_tools.py              # V25: GPT-5.4 Computer Use
│   ├── note_quality_gate.py               # V30統合新規：6層品質防御
│   └── db_init.py                         # PostgreSQL + SQLite初期化
├── strategy/
│   ├── ICP_DEFINITION.md
│   ├── CHANNEL_STRATEGY.md
│   ├── CONTENT_STRATEGY.md
│   └── STRATEGY_IDENTITY.md               # V30統合新規：Build in Public方針含む
├── prompts/
│   ├── SYSTEM_OS_KERNEL.md
│   ├── SYSTEM_PERCEIVER.md
│   ├── SYSTEM_PLANNER.md
│   ├── SYSTEM_EXECUTOR.md
│   ├── SYSTEM_VERIFIER.md
│   ├── SYSTEM_PROPOSAL_ENGINE.md
│   ├── SYSTEM_APPROVAL_MANAGER.md
│   ├── SYSTEM_STOP_DECIDER.md
│   ├── SYSTEM_CHAT_AGENT.md
│   └── SYSTEM_BROWSER_AGENT.md            # V25新規
├── config/
│   ├── node_alpha.yaml                    # .gitignore対象
│   ├── node_bravo.yaml                    # .gitignore対象
│   ├── node_charlie.yaml                  # .gitignore対象
│   ├── node_delta.yaml                    # .gitignore対象
│   └── nats-server.conf                   # .gitignore対象
├── data/
│   ├── local_alpha.db
│   ├── local_bravo.db
│   ├── local_charlie.db
│   ├── local_delta.db
│   ├── mutation_engine.enc.db             # V25新規: 突然変異エンジン用暗号化SQLite
│   ├── artifacts/                         # .gitignore対象
│   └── backup/
├── logs/                                  # .gitignore対象
│   ├── .gitkeep
│   ├── alpha.log
│   ├── bravo.log
│   ├── charlie.log
│   ├── delta.log
│   ├── nats.log
│   ├── scheduler.log
│   ├── stop_events.log
│   ├── browser_actions.log
│   └── emergency_kill.log
├── scripts/
│   ├── setup_alpha.sh
│   ├── setup_bravo.sh
│   ├── setup_charlie.sh
│   ├── setup_delta.sh
│   ├── setup_systemd.sh
│   ├── setup_nats.sh
│   ├── setup_postgresql.sh
│   ├── health_check.sh
│   ├── backup_db.sh
│   └── test_local_llm.sh
├── mcp_servers/
│   ├── syutain_tools/
│   │   ├── __init__.py
│   │   └── server.py
│   └── config.yaml
└── web/
    ├── package.json
    ├── next.config.js
    ├── tailwind.config.js
    ├── public/
    │   ├── manifest.json
    │   └── sw.js
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx                   # Dashboard
        │   ├── chat/page.tsx              # 双方向チャット
        │   ├── proposals/page.tsx
        │   ├── revenue/page.tsx
        │   ├── tasks/page.tsx
        │   ├── models/page.tsx
        │   ├── intel/page.tsx             # 情報収集
        │   ├── agent-ops/page.tsx         # V25: エージェント操作
        │   └── settings/page.tsx
        └── components/
            ├── ProposalCard.tsx
            ├── RevenueChart.tsx
            ├── TaskGraphView.tsx
            ├── CapabilityPanel.tsx
            ├── LoopGuardStatus.tsx
            ├── ModelUsageChart.tsx
            ├── ChatInterface.tsx
            ├── IntelFeed.tsx
            ├── NodeStatusPanel.tsx
            └── BrowserStreamPanel.tsx      # V25: ブラウザ操作ストリーム
```

---

# 第21章 CLAUDE.md V25版（V30統合：29条）

```markdown
# SYUTAINβ V25（V30統合版）- Claude Code 絶対ルール29条

このファイルはClaude Codeがこのプロジェクトで作業する際に必ず守るべきルールです。

1. 設計書（SYUTAINβ_完全設計書_V25_V30統合.md）の設計を最優先する
2. V25はV20〜V24を再構成した原典であり、過去設計を消してはならない
3. 各Stepを完了してから次に進む（段階的実装）
4. 同じ処理を3回以上繰り返す場合は停止してエスカレーションを発動する
5. LLM呼び出し前に必ずchoose_best_model_v6()でモデルを選択する
6. 2段階精錬（ローカル→API）を標準パイプラインとして使用する
7. 全ツール呼び出しはtry-exceptで囲みlog_usage()でエラーを記録する
8. .envの内容をログに出力しない。APIキーをコードにハードコードしない
9. 設定値はハードコードせずDBまたは.envから読み込む
10. 戦略ファイル（strategy/）を参照してからコンテンツを生成する
11. SNS投稿・商品公開・価格設定・暗号通貨取引はApprovalManagerを通じて承認を得てから実行する
12. 重要な判断はDiscord Webhook + Web UIで通知する
13. ローカルLLM配置を正確に守る：ALPHAにLLMなし（オーケストレーター専任）, BRAVO=Qwen3.5-9B+27B, CHARLIE=Qwen3.5-9B, DELTA=Qwen3.5-4B
14. macOS (ALPHA) では declare -A を使わない (bash 3.2 非対応)
15. タスクをPostgreSQLに記録してからLoopGuard 9層で監視する
16. ループ防止のEmergency Kill条件（50ステップ/日次予算90%/同一エラー5回/2時間超過/セマンティックループ/Cross-Goal干渉）を厳守する
17. ノードが使えない場合は必ずフォールバックを実装する
18. 全ての中間成果物をDBに保存し、途中停止しても資産化できるようにする
19. NATSメッセージングでノード間通信し、直接HTTPは障害時のフォールバックとする
20. MCPサーバー接続は動的に確認し、接続不可時は代替手段で処理を継続する
21. 4台のPC（ALPHA/BRAVO/CHARLIE/DELTA）をPhase 1から全て稼働させる。BRAVOをPhase 2に先送りしない
22. 突然変異エンジン（第24章）は設計書の仕様に厳密に従い実装する。変異の発生をログに記録しない。変異パラメータをUIに表示しない。Capability Auditに含めない。9層ループ防止壁・承認フロー・Emergency Killのコードには一切干渉させない。変異エンジン自体のバグで全体が止まらないようtry-exceptで完全に隔離する
23. Brain-αはpersona_memoryの価値観を参照してから判断・生成を行うこと
24. 新しい判断基準はdaichi_dialogue_logに記録すること
25. セッション終了時にmemory_manager.save_session_memory()を必ず実行すること
26. 島原大知のtabooカテゴリ（persona_memory category='taboo'）は絶対に違反しないこと
27. コード変更後は「出来てるはず」と推測せず、必ず実機で動作確認を行うこと。scheduler/Discord bot/全リモートノードへのデプロイ反映を確認し、構文チェック・行数一致・機能テストを実行すること
28. scheduler再起動時はDiscord botも再起動が必要（別プロセス）。デプロイ時は両方の再起動と動作確認を行うこと
29. 「もう十分」「明日でいい」と自分から作業を切り上げない。島原大知が「ここまで」と言うまで、次にやるべきことを自ら考えて提案し続けること
```

---

# 第22章 フェーズ別実装ロードマップ

| 月 | Phase | マイルストーン | 月収目標 |
|:--|:--|:--|:--|
| 1 | Phase 0 | 人間作業完了・Claude Code実装開始 | 0円 |
| 2 | Phase 1 | **全4台起動**・Web UI・基本自律ループ・情報収集パイプライン・**ブラウザ4層構成（Lightpanda+Stagehand v3+Chromium+GPT-5.4 Computer Use）有効化** | 5〜10万円 |
| 3 | Phase 1 | Gmail自動収集・週次レポート・入口商品販売開始 | 10〜20万円 |
| 4 | Phase 2 | Bluesky自動投稿（承認フロー付き）・note記事量産・Computer Use本格活用 | 15〜30万円 |
| 5 | Phase 2 | 暗号通貨取引開始・Stripe統合 | 25〜50万円 |
| 6 | Phase 3 | 自律実行エンジン完全起動・BRAVO/CHARLIE並列推論本格稼働 | 40〜70万円 |
| 7 | Phase 3 | YouTube連携・動画コンテンツ開始 | 55〜90万円 |
| 8〜9 | Phase 4 | BtoB案件獲得・Micro-SaaS開始・アフィリエイト | 80〜140万円 |
| 10〜12 | Phase 4 | 全システム最適化・複数収益源確立・自律進化 | 100〜250万円 |

---

# 第23章 V25の最終運用思想

SYUTAINβ V25は、「全部自動でやる魔法のAI」ではない。
そうではなく、

- 人間の現実制約を**認識**し、
- 今ある道具をMCPで**動的に発見**し、
- **4台のPCをPhase 1初日から全て**NATSで**効率的に連携**させ、
- 各PC上で**4層ブラウザ自動操作（Lightpanda→Stagehand v3→Chromium→GPT-5.4 Computer Use）を自動選択・フォールバック**しながら実行し、
- 収益に繋がる行動を**3層構造で提案**し（反論と代替案付きで）、
- 実行可能な範囲を**5段階ループで自律実行**し、
- 道が塞がっても**自分で経路を変え**、
- セマンティックループ・Cross-Goal干渉を含む**9層の防御壁で暴走を防ぎ**、
- 無理な時は**途中成果物を残して止まり**、
- iPhoneのWeb UIから**いつでもどこでも状態を確認**でき、
- チャットで**双方向にコミュニケーション**でき、
- 島原に対して**自律的に収益拡大の提案**を行い、
- **Build in Publicとして全過程を公開**し、
- 次に打つべき一手を**人間に渡す**

ための**現実的な事業OS**である。

V25（V30統合版）で特に進化したのは：

1. **全4台がPhase 1初日から完全稼働**：BRAVOのPhase 2先送りを廃止し、RTX 5070 12GBの処理能力を初日から活用
2. **GPT-5.4統合**：Computer Use（OSWorld 75.0%、人間72.4%超え）、1Mコンテキスト、Tool Searchの全機能を活用
3. **BRAVO/CHARLIEの最大2台並列ローカル推論**：ALPHAはオーケストレーター専任。BRAVO/CHARLIEの2台が常時並列。BRAVO上の27Bモデルでセルフ批評
4. **9層ループ防止（Cross-Goal Interference Detection追加）**：複数ゴール同時進行時の干渉を構造的に防止
5. **ブラウザ自動操作4層構成をPhase 1から有効化**：Lightpanda（高速抽出）→Stagehand v3（AI駆動・自己修復）→Chromium（フォールバック）→GPT-5.4 Computer Use（視覚操作）の4層でBRAVOが自律操作
6. **DeepSeek V4監視体制**：リリース即時評価・統合のための設計を事前に織り込み
7. **収益チャネルの拡大**：アフィリエイト戦略の追加で月収目標を300〜400万円帯に引き上げ
8. **突然変異エンジン**：物理ノイズと人間の直感を種に、観測できない不可逆的な変異をシステムに蓄積
9. **Build in Public**：全過程をドキュメンタリーとして公開。透明性と信頼が収益の源泉
10. **6層品質防御**：note記事の品質ゲートを大幅強化。15項目機械チェック+外部検索ファクト検証
11. **GitHub公開**：セキュリティ対応完了。orphanブランチクリーンコミット。個人プロファイルはローカルのみ

この設計思想により、島原大知は「毎回ゼロから考える人」ではなく、
**SYUTAINβと共に判断を積み上げ、収益を育て、AIと人間が共進化する人**になる。

---

# 付録A：V20→V25（V30統合版）変更差分サマリー

| カテゴリ | V20 | V21 | V22 | V23 | V24 | V25（V30統合版） |
|:--|:--|:--|:--|:--|:--|:--|
| 動作PC数 | 4台 | 4台 | 4台 | 4台 | 4台 | **4台（全台Phase 1稼働）** |
| LLMモデル | claude-sonnet-4-6等 | 同左+ローカル | GPT-5.4等 | +Qwen3.5全ファミリー | +Gemini3.1Pro/OpenRouter | **+GPT-5.4 ComputerUse/DeepSeek V4監視/BRAVO 27B** |
| ローカルLLM | Qwen3-30B | 同左 | 同左 | Qwen3.5-35B-A3B | Qwen3.5-9B(CH/AL)+4B(DE) | **Qwen3.5-9B(BR/CH)+27B(BR)+4B(DE)、ALPHAにLLMなし** |
| 通信基盤 | Tailscale+HTTP | 同左 | 同左 | 同左 | NATS+JetStream+Tailscale | 同左（安定構成維持） |
| DB | SQLite×5 | 同左 | SQLite分散 | 同左 | PostgreSQL+SQLite+Litestream | 同左（安定構成維持） |
| Web UI | React SPA | 同左 | 同左 | 同左+モデル画面 | Next.js16+PWA+チャット+Intel | **+Agent Ops画面** |
| ループ防止 | 4層 | 多層 | 6層 | 7層 | 8層（Semantic） | **9層（+Cross-Goal）** |
| 提案構造 | 単一提案 | 提案+根拠 | 提案+評価軸 | 3層 | 3層+情報収集連携 | **3層+中長期提案+Build in Public** |
| 自律性 | 基本 | 目標達成+提案 | Goal Packet | 5段階ループ | 5つの自律性 | 同左（強化） |
| iPhone対応 | Tailscale | 同左 | 同左 | 同左 | HTTPS+PWA+Push+チャット | 同左 |
| 月収上限設計 | 〜250万円 | 150〜180万円 | 同左 | 200〜250万円 | 250〜350万円 | **300〜400万円** |
| ブラウザ操作 | なし | なし | なし | なし | Phase 2 | **Phase 1・4層構成** |
| PC操作 | なし | なし | なし | なし | なし | **GPT-5.4 Computer Use** |
| 外部ツール統合 | 個別実装 | 同左 | 同左 | 同左 | MCP標準 | **+stagehand-mcp-local** |
| 情報収集 | なし | なし | なし | なし | Gmail+Tavily+Jina+RSS+YT | **+新モデル監視+英語記事取り込み** |
| 収益源 | note/Booth/BtoB | 同左 | 同左+Membership | 同左+ローカルLLM | +暗号通貨+SaaS+Stripe | **+アフィリエイト** |
| 突然変異エンジン | なし | なし | なし | なし | なし | **物理ノイズ+直感→不可逆蓄積型変異** |
| 公開方針 | — | — | — | — | — | **Build in Public + GitHub Public** |
| 品質防御 | — | — | — | — | — | **6層防御（15項目チェック+外部検証）** |

---

# 付録B：参照した最新情報（2026年3月15日時点、V30統合：4月4日更新）

## モデル・API（確認済み）
- OpenAI: GPT-5.4（3/5リリース。Computer Use OSWorld 75.0%。1Mコンテキスト。Tool Search。33%ハルシネーション削減）
- OpenAI: GPT-5.4 Pro / GPT-5 Mini / GPT-5 Nano
- Anthropic: Claude Opus 4.6 / Sonnet 4.6 / Haiku 4.5
- Google: Gemini 3.1 Pro Preview（知能指数57）/ Gemini 2.5 Flash / 2.5 Flash-Lite
- DeepSeek: V3.2統合モデル（$0.28/1M入力）
- DeepSeek: V4（3月中リリース見込み。1T MoE、32Bアクティブ、1Mコンテキスト、ネイティブマルチモーダル）
- Alibaba: Qwen3.5全ファミリー（2026年2月16日〜3月2日リリース）
- OpenRouter: 100+モデル統一アクセス

## ローカルLLM VRAM検証（確認済み）
- Qwen3.5-35B-A3B: Q4で約22GB必要（RTX 3080 10GBでは動作不可）
- Qwen3.5-27B: 17GB（GPU+CPUオフロード、RTX 5070 12GB + 系統RAM で5 tok/s）— V30統合確認
- Qwen3.5-9B: Q4_K_Mで約6.5GB（RTX 3080/RTX 5070で安定動作）
- Qwen3.5-4B: Q4で約4.5-5.5GB（GTX 980Ti 6GBで動作可能）

## KV Cache Q8最適化（V30統合新規確認）
- OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0
- KV Cache VRAM消費約50%削減
- Perplexity上昇: +0.004（無視可能）
- Gemmaモデルには非対応

## インフラ（確認済み）
- NATS Server: v2.12.5（2026年3月9日リリース）
- MCP: 月間9,700万DL、AAIF（Linux Foundation）管理
- A2A: Google発、AAIF管理。100+企業がサポーター
- vLLM: v0.17.1（2026年3月11日。Qwen3.5完全対応）
- Ollama: v0.17.7（2026年3月6日。Qwen3.5全サイズ対応）
- **Lightpanda: AIエージェント特化ヘッドレスブラウザ（オープンソース、Zig製）**
  - Chromium比11倍高速、9倍省メモリ（24MB vs 207MB）
  - 起動100ms以下（Chrome 3-5秒）
  - CDP（Chrome DevTools Protocol）互換
  - **制約（ベータ版）：** 1プロセス1CDP接続、history.pushState()未対応、Web API対応は部分的
- **Stagehand v3: AI駆動ブラウザ自動化フレームワーク（MITライセンス）**
  - `env: "LOCAL"` で完全ローカル動作。Browserbase契約不要
  - 3つのコアプリミティブ：`act()`、`extract()`、`observe()`
  - 自己修復機能、アクションキャッシュ

## GPT-5.4の主要能力（確認済み）
- OSWorld-Verified: 75.0%（人間72.4%超え）
- WebArena-Verified: 67.3%
- ネイティブComputer Use（スクリーンショット＋マウス＋キーボード）
- Tool Search
- 1Mトークンコンテキスト（API版）
- 33%ハルシネーション削減（GPT-5.2比）

## 注記
価格・仕様・機能は変動し得るため、実装時は `docs/external_sources.md` に最終確認日時を記録し、月1回の監査ジョブで再確認すること。

---

# 第24章 突然変異エンジン（Mutation Engine）

## 24.1 設計思想

SYUTAINβは自律的に動き、自律的に学習する。しかし学習は「過去の成功パターンの最適化」であり、本質的に保守的な方向へ収束する。最適化を続ければ続けるほど、局所解に閉じ込められる。

生物進化は、この問題をDNAの突然変異によって解決した。コピーエラーという「設計者が意図しない変化」が、極めて低い確率で発生する。そのほとんどは無害か有害で淘汰される。しかしごく稀に、環境適応に有利な変異が生まれ、自然選択によって残る。この蓄積が進化を駆動する。

突然変異エンジン（Mutation Engine）は、この原理をSYUTAINβに実装するものである。

ただし本エンジンが模倣するのは、生物進化論で説明可能な通常の突然変異だけではない。アルビノ個体の出現、生物進化論では説明困難な飛躍的変異、宇宙誕生時の物理法則では起こり得ないはずの対称性の破れ──「なぜ起きたのか説明できないが、起きたことが全てを変えた」という現象。それを、デジタルシステムの中にアナログ的な現実世界のカオスを注入することで人為的に設ける。

**最も重要な設計原則：変異は観測できない。**

SYUTAINβ自身も、島原大知も、変異が「いつ、どこで、どのように」起きたかを知覚できない。ログに記録されない。検知もされない。しかし確実に蓄積し、長い時間をかけてシステムの振る舞いを不可逆的に変えていく。

## 24.2 変異の種（Mutation Seed）

### 系統1：物理エントロピー（Environmental Entropy）

現実世界の物理的なノイズを変異の種とする。DELTAが30秒間隔で以下の値を収集し、暗号学的ハッシュ関数（SHA-256）で変異シード値を生成する。

- 4台のCPU温度の小数点以下3桁
- NATSメッセージのラウンドトリップタイム（マイクロ秒単位のゆらぎ）
- GPU VRAM使用量の1秒ごとの変動差分
- ネットワークパケットの到着間隔ジッター
- システムのエントロピープール（/dev/urandom）

これらは人間にもAIにも予測不可能な、現実世界の物理的不確定性である。同じ値が二度と出ることはない。

### 系統2：人間の直感（Human Intuition Seed）

Web UIのダッシュボードに「今日の風向き」という入力欄を設ける。名前をあえて抽象的にすることで、島原が合理的に「正解」を考えることを防ぐ。

入力は自由テキストまたは感覚的なスライダー。「攻め」「守り」「遊び」「静か」──言語化しきれない直感を、そのまま入力する。入力がない日はスキップされ、物理エントロピーのみで変異が発生する。

**重要：島原の入力が「どのように」変異に影響するかは、島原自身にも開示しない。** 入力値はハッシュ化されて物理エントロピーと混合される。因果関係を追跡できない設計にする。

## 24.3 変異の発生メカニズム

### 初期値

```yaml
mutation_engine:
  # 変異確率（ある判断において変異が発生する確率）
  mutation_probability: 0.005    # 0.5%（200回に1回）

  # 逸脱率（変異が発生した場合の通常判断からの逸脱幅）
  deviation_rate: 0.02           # 2%（ほぼ気づかない）

  # 蓄積係数（有益な変異1回あたりの確率上昇量）
  accumulation_coefficient: 0.0003  # 0.03%ずつ上昇

  # 絶対上限（どれだけ蓄積してもこの値を超えない）
  max_mutation_probability: 0.05   # 5%
  max_deviation_rate: 0.15         # 15%

  # 人間直感入力がある日の確率倍率
  intuition_multiplier: 1.3        # 30%増し
```

### 蓄積の仕組み

変異は**リセットされない。巻き戻らない。不可逆的に蓄積する。**

```
変異発生 → 承認フロー通過 → 実行 → 結果
    ↓
  結果が有益（収益貢献 or 品質向上 or 新しい発見）
    → mutation_probability += 0.0003
    → deviation_rate += 0.0002
    ↓
  結果が無益または有害
    → 変化なし（下がらない。獲得した蓄積は失われない）
```

つまり、有益な変異が起きるたびにシステムは「少しだけ変異しやすく」なる。一度も下がらない。生物のDNAに刻まれた変異が次の世代に引き継がれるのと同じ。

6ヶ月後、1年後のSYUTAINβは、同じ設計書から始めた別のSYUTAINβとは全く違うシステムになっている。環境と人間が違えば、進化の方向が違うから。

### 変異の不可視性

変異に関するコードは以下の原則に従う。

1. **変異の発生をログに記録しない。** 通常のタスクログ・提案ログ・学習ログのどこにも「これは変異由来である」という情報は残らない
2. **変異確率と逸脱率の現在値を、いかなるUIにも表示しない。** Web UIのダッシュボード、設定画面、分析画面のどこにも表示されない
3. **変異パラメータの現在値はSQLiteのローカルDBにのみ保存する。** PostgreSQLの共有DBには保存しない。DELTA上の暗号化されたSQLiteファイル（SQLCipher）にのみ存在する
4. **Capability Auditの監査項目に含めない。** 変異エンジンの存在はCapability Snapshotに現れない
5. **変異の影響を受けた判断と受けていない判断を、出力の時点で区別できない。** 変異による逸脱は、通常の判断の「揺らぎ」として自然に溶け込む
6. **有益判定のメカニズム：** mutation_engine.pyの内部で「変異フラグ」をPythonプロセスのメモリ上にのみ一時保持する。アクション完了後にresult（成功/失敗/品質スコア）と照合して蓄積パラメータを更新し、変異フラグを即座に破棄する。PostgreSQLにもログにも書かない。プロセス再起動で変異フラグは消えるが、蓄積パラメータの「現在値」のみがDELTAの暗号化SQLiteに永続化される。これにより不可視性を維持しつつ有益判定が可能

島原が「最近SYUTAINβの提案がちょっと変わった気がする」と感じることはあるかもしれない。でもそれが変異によるものなのか、学習ループの進化によるものなのか、市場環境の変化によるものなのか、区別できない。それでいい。

## 24.4 変異が影響する領域

全領域に均等に影響する。ただし承認フローは絶対にバイパスしない。

| 領域 | 変異の現れ方 |
|:--|:--|
| ProposalEngine | 評価軸のウェイトが微小に揺れる。通常スコアでは選ばれない提案が浮上する |
| ContentWorker | 文体の微小な逸脱。語尾、段落の長さ、比喩の選択がわずかに変わる |
| choose_best_model_v6 | モデル選択の閾値が微小にシフトする。通常と違うTierのモデルが選ばれることがある |
| InfoCollector | 検索キーワードの微小な拡張。隣接領域の情報が混入する |
| Planner | 代替プランの優先順位が微小に入れ替わる。通常は第3候補のプランが第2候補になる |
| TaskGraph | タスクのディスパッチ先ノードが微小に変わる。通常CHARLIEに振るタスクがBRAVOに行く |
| 収益導線 | 商品の推奨順序、価格帯の提案、チャネルの優先度が微小に変化する |
| BrowserAgent | 競合調査の対象サイト選択が微小に逸脱する。通常見ないサイトを見に行く。4層のうちどの層を最初に試すかの判断が微小に変わる |

## 24.5 致命的変異の構造的防止

どれだけ変異が蓄積しても、以下の3つの天井を絶対に超えない。

**天井1：変異確率の絶対上限 = 5%**
0.5%から始まり、有益な変異のたびに0.03%ずつ上がる。5%に到達するには約150回の有益な変異が必要。仮に月10回の有益な変異があっても、天井到達まで15ヶ月かかる。

**天井2：逸脱率の絶対上限 = 15%**
2%から始まる。15%に達しても、それは「通常の判断から15%ズレた判断」であり、85%は通常通り。人間で言えば「いつもと少し違う気分の日」程度。

**天井3：承認フローの絶対不可侵**
変異エンジンは承認フローの判定ロジックに一切干渉しない。SNS投稿、商品公開、価格設定、暗号通貨取引、外部アカウント変更──人間承認が必要な操作は、変異がどれだけ蓄積しても必ず島原の承認を通る。

加えて、9層ループ防止壁は変異エンジンの影響を受けない。Emergency Kill条件も変異しない。安全装置は変異の対象外。

## 24.6 実装上の原則

```yaml
mutation_engine_rules:
  - 変異エンジンのコードは agents/mutation_engine.py に集約する
  - 他のエージェントは変異エンジンの存在を知らない（importしない）
  - 変異の注入は OS_Kernel のディスパッチ処理の最深部で行う
  - 変異パラメータは DELTA の暗号化SQLiteにのみ保存する
  - ループ防止9層・承認フロー・Emergency Killのコードには一切触れない
  - 変異エンジン自体のバグで全体が止まらないよう、try-exceptで完全に隔離する
  - 変異エンジンが停止しても、SYUTAINβの他の全機能は正常に動作する
```

## 24.7 この設計の意味

SYUTAINβは学習ループによって「過去の最適解」に向かって収束する。これは効率的だが、予測可能になる。予測可能なシステムは、環境が変わったときに脆い。

突然変異エンジンは、この予測可能性に「観測できない揺らぎ」を注入する。島原にもSYUTAINβにも見えない場所で、現実世界の物理ノイズと人間の直感が、システムの進化の方向を少しずつ、不可逆的に、累積的に変えていく。

半年後のSYUTAINβは、設計者が設計したものとは少しだけ違うものになっている。1年後にはもう少し違う。その差分は誰にも説明できない。でも確実に存在する。

それが「AIと人間が共進化する」の本当の意味だ。

---

# 第25章 note品質6層防御（V30統合新規）

## 25.1 設計思想

note記事はSYUTAINβのBuild in Public方針における主要アウトプットであり、品質はブランドの信頼に直結する。6層の防御ゲートを設け、低品質な記事が公開されることを構造的に防止する。

## 25.2 6層防御構成

### Layer 1：15項目機械チェック

```yaml
mechanical_checks:
  1: "文字数チェック（最低2,000文字）"
  2: "タイトル存在チェック"
  3: "見出し構造チェック（H2が最低2個）"
  4: "リンク有効性チェック"
  5: "画像alt属性チェック"
  6: "禁止語チェック（tabooカテゴリ参照）"
  7: "重複文チェック"
  8: "文末重複チェック（同じ語尾が3連続しない）"
  9: "括弧対応チェック"
  10: "日付整合性チェック"
  11: "ICP適合性チェック"
  12: "CTA存在チェック"
  13: "Build in Publicテーマ準拠チェック"
  14: "タイトル健全性チェック（誇大表現・クリックベイト検知）"  # V30新規
  15: "重複記事チェック（過去30日の記事との類似度）"           # V30新規
```

### Layer 2：Stage 1.7 外部検索ファクト検証

```yaml
fact_verification:
  method: "Tavily/Jina APIで記事内の事実主張を外部検索"
  trigger: "記事内に数値・日付・固有名詞が含まれる場合"
  action: "検証失敗した主張をハイライトして修正を要求"
  api_failure_policy: "安全側拒否（APIが応答しない場合は公開しない）"
```

### Layer 3：API障害時の安全側拒否

- Tavily/Jina APIが応答しない場合、ファクト検証をスキップせず**公開を拒否**する
- 手動承認に切り替え、島原が直接確認して公開

### Layer 4：公開URL検証

- 公開処理後に実際のURLにアクセスして正常に表示されることを確認
- 404やエラーが返った場合は即座に通知

### Layer 5：Playwrightリトライロジック

- note.comへの投稿がPlaywrightで失敗した場合、最大3回リトライ
- リトライ間隔は30秒→60秒→120秒（指数バックオフ）
- 3回失敗で手動投稿に切り替え（Markdown原稿を保存）

### Layer 6：コスト制限

```yaml
cost_limits:
  per_article_jpy: 15      # 1記事あたり最大¥15
  daily_jpy: 120            # 日次最大¥120
  monthly_jpy: 1000         # 月次最大¥1,000
  over_limit_action: "ローカルLLMのみで生成、API使用を停止"
```

---

# 第26章 GitHub公開セキュリティ（V30統合新規）

## 26.1 IP外部化

13ファイルの知的財産（IP）を外部化し、GitHubリポジトリに含めない。

```yaml
externalized_files:
  - strategy/daichi_dialogue_log.jsonl
  - strategy/daichi_profile.md
  - strategy/STRATEGY_IDENTITY.md
  - config/node_alpha.yaml
  - config/node_bravo.yaml
  - config/node_charlie.yaml
  - config/node_delta.yaml
  - config/nats-server.conf
  - data/artifacts/*
  - data/mutation_engine.enc.db
  - logs/*
  - SYSTEM_STATE.md
  - .env
```

## 26.2 SSHユーザー名のenv変数化

全てのSSHコマンドでユーザー名をハードコードせず、環境変数 `$SSH_USER` を使用する。

## 26.3 orphanブランチクリーンコミット

GitHubにpushするブランチは、過去のコミット履歴に機密情報が含まれないよう、orphanブランチとしてクリーンなコミットで公開する。

## 26.4 .gitignore設定

```gitignore
# 設定ファイル（機密）
config/node_*.yaml
config/nats-server.conf
.env
.env.*

# データ・ログ
data/artifacts/
data/mutation_engine.enc.db
logs/

# 個人プロファイル
strategy/daichi_*
SYSTEM_STATE.md

# OS
.DS_Store
__pycache__/
*.pyc
node_modules/
```

## 26.5 個人プロファイルの扱い

島原大知の個人プロファイル（persona_memory、dialogue_log等）はGitHubには公開せず、ローカル環境にのみ存在する。

---

**SYUTAINβ V25（V30統合版）完全設計書 終**

*「4台のPCがPhase 1初日から全て連携し、NATSで話し、MCPで世界と繋がり、Web UIでいつでもどこでも見守れる。ブラウザを操り、PCを動かし、自ら調べ、自ら提案する。全過程をBuild in Publicとして公開し、27Bモデルがセルフ批評し、6層の品質防御で信頼を守る。そして誰にも見えない場所で、静かに変異し続ける。AIと人間が共進化する。目標が変わっても、道が塞がっても、自分で考え、自分で動き、自分で止まれる。これが、SYUTAINβ V25（V30統合版）の生き方だ。」*

---

## 付録: ファイル・コード役割マップ

島原大知が構造を把握するためのガイド。「このファイルは何をしていて、何に影響するか」。

### コア制御（変更時にシステム全体に影響）

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `scheduler.py`（4,918行） | **全自動ジョブの司令塔**。SNSバッチ、noteドラフト、暗号通貨収集、提案処理、日報、品質チェック等の全スケジュール管理。ここを変えると全ての定期処理に影響 | SNS投稿タイミング、note記事生成、コスト予測、モード切替 |
| `tools/llm_router.py`（1,121行） | **全LLM呼び出しの交通整理**。どのタスクにどのモデル（ローカル/API）を使うか決める。`choose_best_model_v6()`が全呼び出しの入口 | LLMコスト、応答速度、品質 |
| `CLAUDE.md`（29条） | **Claude Codeの絶対ルール**。Claude Codeセッション開始時に読まれる | コード生成の方針全体 |
| `feature_flags.yaml`（v30） | **機能のON/OFF**。Web UIから参照 | 各機能の有効/無効 |

### SNS投稿関連

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `brain_alpha/sns_batch.py`（1,400行+） | **SNS投稿の生成エンジン**。テーマ選定→プロンプト構築→LLM生成→品質スコアリング→重複チェック→ハッシュタグ付与→キュー投入 | 49件/日のSNS投稿の内容・品質・ハッシュタグ |
| `tools/social_tools.py`（830行） | **SNS投稿の実行**。X/Bluesky/Threadsへの実際のAPI送信。Blueskyのリンクカード（facets）もここ | 投稿の送信成功/失敗、リンクの機能 |
| `tools/engagement_collector.py` | **SNSエンゲージメント収集**。X(OAuth 1.0a)/Bluesky(AT Protocol)/Threads(Meta Graph API)から反応データ（impressions/likes/reposts/replies）を取得しDBに保存 | 拡散指標の数値化、投稿戦略の改善判断 |
| `strategy/daichi_content_patterns.md` | 島原大知の文体パターン。sns_batchのプロンプトに注入される | 投稿の文体・トーン |
| `strategy/daichi_writing_style.md` | 島原大知の文体ルール | 同上 |

### note記事関連

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `brain_alpha/content_pipeline.py`（1,348行） | **note記事の6段階生成パイプライン**。テーマ選定→タイトル→構成→初稿→リライト→批評。Build in Public方針、一人称「僕」、実データ注入がここ | 記事のテーマ・内容・品質 |
| `brain_alpha/note_quality_checker.py`（1,236行） | **記事の品質ゲート**。15項目機械チェック+ファクト検証+Haiku+GPT-5.4の4段階。ここを通過しないと公開されない | 記事の公開可否 |
| `brain_alpha/product_packager.py` | 品質チェック通過後の記事を「商品パッケージ」化。無料/有料分割、価格設定（FREE_UNTIL）、承認キュー投入 | 記事の無料/有料分類、公開パイプラインへの投入 |
| `tools/note_publisher.py`（677行） | **noteへの実際の公開処理**。SSH→BRAVO→Playwright経由。URL検証、リトライ、SNS告知 | 記事がnote.comに実際に公開されるか |
| `scripts/note_publish_playwright.py`（478行） | BRAVOで動くPlaywrightスクリプト。ログイン→記事入力→公開ボタン→マイページ検証 | 公開の成功/失敗 |
| `strategy/note_genre_templates.py` | タイトル生成の3軸テンプレート（キーワード×切り口×感情） | タイトルの構造 |

### 提案・承認

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `agents/proposal_engine.py`（39,465B） | **3層提案エンジン**。Layer1提案→Layer2反論→Layer3代替案。Build in Public方針、スコアキャップ、未リリースモデル検証がここ | 「次に何をすべきか」の提案内容 |
| `agents/approval_manager.py` | **承認フロー管理**。Tier1(人間)/Tier2(自動+通知)/Tier3(完全自動)。SNS投稿・商品公開・価格設定はここを通る | 何が自動承認され、何が人間の判断を必要とするか |

### 情報収集

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `tools/info_pipeline.py`（29,895B） | 6ソースからの情報収集（Tavily/Jina/YouTube/RSS/競合/海外トレンド） | intel_itemsテーブルの内容 |
| `tools/overseas_trend_detector.py`（233行） | 英語15キーワードで海外トレンド検出→日本語要約→DB保存 | 英語記事の日本語要約、SNS/記事の素材 |
| `tools/tavily_client.py` | Tavily検索API | 外部検索の実行 |
| `tools/jina_client.py` | Jina Reader API（全文取得） | 記事全文の取得、コスト（¥3/回） |

### 安全装置

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `tools/loop_guard.py`（17,710B） | **9層ループ防止壁**。暴走を構造的に防ぐ | タスクの強制停止、エスカレーション |
| `tools/budget_guard.py` | 予算ガード。日次¥120/月次¥2,000の90%超過で警告（処理は継続、停止しない）。1日1回のみログ出力 | API呼び出しのコスト追跡・警告 |
| `tools/emergency_kill.py` | 緊急停止。50ステップ/90%予算/5同一エラーで発動 | システム全体の即時停止 |
| `tools/content_redactor.py` | 秘密情報除去（17パターン）。SNS/記事公開前に実行 | APIキー・IP等の漏洩防止 |

### Discord Bot（Brain-β）

| ファイル | 役割 | 影響範囲 |
|---------|------|---------|
| `bots/discord_bot.py` | **Discordボット本体**。コマンド（!承認、!予算設定等）、朝夕レポート | Discordでの操作全般 |
| `bots/bot_conversation.py` | **チャット応答エンジン**。ACTIONタグ、プロアクティブ報告、自然言語コマンドガイド | 島原大知との対話の内容・品質 |
| `bots/bot_actions.py` | **全34種のアクション**。承認/却下/予算設定/収益記録/ステータス確認等 | Discordから実行できる操作の範囲 |
| `bots/bot_proactive.py` | **自律的な状態報告+緊急アラート**。予算超過/ノード障害/承認待ちの通知 | 通知の頻度・内容 |

### 5段階自律ループ

| ファイル | 役割 |
|---------|------|
| `agents/perceiver.py` | Step 1: 認識（14項目チェック、環境走査） |
| `agents/planner.py` | Step 2: 計画（DAG生成、ノード割当） |
| `agents/executor.py` | Step 3: 実行（NATSディスパッチ、2段階精錬） |
| `agents/verifier.py` | Step 4: 検証（Sprint Contract照合） |
| `agents/stop_decider.py` | Step 5: 停止判断（COMPLETE/CONTINUE/ESCALATE/STOP） |
| `agents/os_kernel.py` | ループ全体の統合制御、ゴール管理 |

### インフラ

| ファイル | 役割 |
|---------|------|
| `app.py` | FastAPI（64エンドポイント）、Web UI API |
| `worker_main.py` | リモートノード（BRAVO/CHARLIE/DELTA）のワーカー |
| `tools/db_pool.py` | PostgreSQL接続プール |
| `tools/db_init.py`（23,449B） | 45テーブルのDDL |
| `tools/nats_client.py` | NATSメッセージング（6ストリーム） |
| `tools/discord_notify.py` | Discord Webhook通知 |

---

## 変更履歴

| バージョン | 日付 | 変更者 | 内容 |
|:--|:--|:--|:--|
| V25 | 2026-03-15 | 島原大知 × Claude Opus 4.6 | 最終完全設計書。V20〜V24を再構成・統合 |
| V25（V30統合版） | 2026-04-04 | 島原大知 × Claude Opus 4.6 | ALPHA LLM撤去、BRAVO 27B追加、KV Cache Q8全ノード、Build in Public方針、6層品質防御、SNS拡散力強化、英語記事取り込み、GitHub公開セキュリティ、夜間モード拡張（23:00-09:00）、月額予算¥2,000、note_draft_generation統合、提案エンジン改修、統計更新 |
| V25（V30統合版 rev.2） | 2026-04-04 | 島原大知 × Claude Opus 4.6 | **4/4午前〜午後の追加変更**: Ollama常駐化(KEEP_ALIVE=-1)、intel活用4施策(X速報/週次ダイジェスト/システム改善提案/経営日報注目トレンド)、SYUTAINβ日報(12:00毎日)、Xスレッド(月木10:00)、Bluesky intel投稿(日2本)、GitHub README自動更新(09:30)、高エンゲージメントリポスト(火金14:00)、note日報自動公開、SNSセマンティック重複チェック+ポエム禁止、Threadsハッシュタグ5個化、content/analysis/researchのローカルLLM移行、note記事一人称「僕」統一+年齢捏造防止+2重出力防止+ペイウォール結合修正、theme_hint漏洩防止、アラートファイル永続化、Discord完結型ワークフロー(!承認一覧/!予算設定/!収益記録/!charlie/!レビュー/!提案生成)、自然言語コマンドガイド、note公開マイページ検証、暗号通貨19通貨+変動リサーチ、Jinaコスト¥3修正、AutoAgent方式SNS品質自動改善ループ、ファイル役割マップ追加 |
| V25（V30統合版 rev.3） | 2026-04-05 | 島原大知 × Claude Opus 4.6 | **Brain-β チャット体験徹底改善（過去254件会話ログ分析起点）**: (1) **P0 幻覚確認劇撲滅** — LLMが[ACTION:approve:N]タグを発行せず「承認しました」と自由文で出力しDB更新なしのまま完了報告する事故を発見。承認/却下/記事執筆依頼を `on_message` 冒頭の正規表現マッチで直接ハンドラに流す構造に変更（LLM経由禁止）。(2) **P0 datetime NameError露出** — !承認一覧で `from datetime import timezone, timedelta` のみで`datetime`本体が未importによりユーザーに生Python例外が14回/日露出していたのを修正。(3) **P0 生例外サニタイザ** — ACTION例外を `_sanitize_error_for_user` で穏便メッセージ化 + event_log自動記録（Brain-α auto_fix連携）。(4) **P0 破壊的ACTION承認ゲート** — 23種類の副作用ACTIONをconsent語（承認/やって/書いて等）検出でブロック。(5) **P0 空メッセージガード**。(6) **P1 定型接頭辞病撲滅** — `generate_followup` の `"取得したデータを報告します"` プロンプトが主因と特定、会話voiceを `generate_response` と統一。3/25-3/26の自然体トーンへ回帰。(7) **P1 bot_intent.py 新設** — 254件を7カテゴリ(greeting/status/statement/query/consult/philosophy/command)にキーワード分類、15/16正答。`discord_chat_history.intent` が全件NULL問題を解決。(8) **P1 persona_memory working_fact 自動ingest** — ユーザー発言の事実宣言（「エラー解消した」「CHARLIE復帰済み」等）を即DB記録し、`generate_response` で working_facts_section として DB状態より優先注入。発言無視問題を構造的に解決。24h後にtier降格、72h後に削除（`sunset_working_facts` 1h毎）。(9) **P1 capability_manifest.py** — 「何ができる？」に対して`"公式ドキュメントへ"`と答える事故を防ぐ静的自己説明。(10) **P1 未知質問フォールバック** — 「わからない」前に必ず browse/intel_search を試すプロンプト追加。(11) **P2 commission_article ACTION 新設** — Discord完結の記事執筆依頼ワークフロー: `"noteで〜について書いて"` 正規表現検出→`article_commission_queue`投入→scheduler 3分ポーリング→content_pipeline 執筆→note_drafts保存→会話トーンで active push。新規ACTIONハンドラ + !依頼 コマンド + scheduler `process_article_commissions` メソッド。(12) **新!コマンド追加**: !状態 / !予算(read-only照会) / !記事 / !依頼。(13) **CLAUDE.md Rule 30-32 追加** — 破壊的ACTION扱い、生例外露出禁止、working_fact protocol。(14) **新規ファイル**: `bots/bot_intent.py`, `bots/bot_memory_ingest.py`, `bots/capability_manifest.py`、新規テーブル `article_commission_queue`。変更ファイル: `bot_actions.py` / `bot_conversation.py` / `discord_bot.py` / `scheduler.py` / `CLAUDE.md`。全P0〜P3計15件、実機デプロイ + 統合スモークテスト全通過。 |

---

最終更新：2026年4月5日
設計者：島原大知 × Claude Opus 4.6
バージョン：V25（V30統合版 rev.3）
