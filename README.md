# SYUTAINβ V25 — 自律型ビジネスOS

4台のPC（ALPHA / BRAVO / CHARLIE / DELTA）が連携して動く、自律型のビジネス運営システムです。
AIが提案→承認→実行→検証のサイクルを自動で回し、コンテンツ制作・SNS運用・EC管理・情報収集を行います。
**Build in Public**方針で、システム自身が自分の運用データから note 記事を生成して公開しています。

## 今のシステムで出来ること（2026-04-06 現在、実機能）

### コンテンツ生成・公開
- **note 記事自動生成**: SYUTAINβ の実運用データ（エラー・コスト・判断記録）を素材に、Build in Public ドキュメンタリー記事を 5段階パイプラインで生成。6層品質防御（機械15項目 / 外部検索ファクト検証 / Haiku / GPT-5.4 / factbook / fact_density スコア）を通過したもののみ公開。Playwright で note.com に自動公開（日次上限5本）
- **SNS 投稿自動生成**: 8軸スコア（事実密度・人間味・ペルソナ・完結性・エンゲージメント・AI臭の無さ・構造性・情報密度）で評価、品質0.75以上は自動承認、それ未満は人間承認。ポエム化防止の構造的防御あり
- **ドキュメンタリー記事**: 週次（水曜/土曜10:00）に SYUTAINβ自身の運用データから note 記事を生成
- **海外 AI トレンド取り込み**: 英語一次情報を取得 → 要約 → 日本語記事化
- **Discord 経由の記事執筆依頼**: Discord で「noteで〜について書いて」と言うだけで `article_commission_queue` に投入 → 3分以内に執筆開始 → 完成したら会話トーンで通知（2026-04-05 新設）

### SNS 運用（実装済みプラットフォーム）
- **X (Twitter)**: `execute_approved_x` — @syutain_beta / @Sima_daichi アカウント
- **Bluesky**: `execute_approved_bluesky` — AT Protocol 経由
- **Threads**: `execute_approved_threads` — Meta Graph API 経由
- **note.com**: Playwright 経由の自動公開
- **Bluesky 自動フォロー/アンフォロー**: 日次14:00 に関連ユーザーを最大30人フォロー、日曜15:00 に7日間フォローバックなしをアンフォロー
- **エンゲージメント収集**: 投稿後のいいね/リポスト/返信を48時間ウィンドウで収集・分析

### 情報収集・インテル
- **xAI Grok リアルタイム X 検索** (2026-04-06 新設): Responses API + Agent Tools API (x_search/web_search) で X (Twitter) の空気感をリアルタイム抽出。島原関連分野（映像/VTuber/ドローン/広告/メディア/映画/経営/文化/起業 + AI/テック）に最適化した4モード（balanced/tech/creator/business）。朝08:30 と 夕19:30 の定期ジョブで 1日約20素材を intel_items に自動蓄積、sns_batch と content_pipeline が自動参照して「今話題性があること」を投稿・記事に反映。Discord から `!xリサーチ <topic>` / 「Xで〜を調べて」で即実行可能。コスト ~¥0.02-0.5/call（xAI `cost_in_usd_ticks` で実測）
- **24 ソース横断バズ検出**: HackerNews / Reddit 16サブレディット / GitHub Trending / Zenn / Yahoo!Realtime 代替 / Togetter / はてなブックマーク 8 カテゴリ / Bluesky Popular 等
- **Web 検索**: Tavily Search API（日本語対応）
- **URL → テキスト**: Jina Reader API
- **RSS / YouTube**: テック・ビジネス系、YouTube Data API v3
- **週次インテルダイジェスト**: 日曜20:00 に収集した情報を自動整理
- **X AI速報投稿**: 毎日11:30 に intel から速報抽出して X に投稿

### ブラウザ自動化（BRAVO の 4層スタック）
1. Lightpanda (CDP) — 軽量サイトの高速抽出
2. Stagehand v3 — AI 駆動の自然言語操作（自己修復・アクションキャッシュ）
3. Chromium — 重い SPA のフォールバック
4. GPT-5.4 Computer Use — ログイン画面・CAPTCHA・複雑UI

### EC / 決済（実装済み）
- **Stripe**: 商品作成・価格設定・Checkout セッション（承認必須）
- **Booth**: デジタル商品販売（Booth セッションクッキー経由）
- **収益記録**: `commerce_transactions` テーブルに売上を記録・可視化

### 暗号通貨監視（取引は承認必須）
- **監視対象: 19通貨** — BTC/ETH/XRP/SOL/DOGE/LTC/BCH/DOT/LINK/ATOM/ADA/SUI + XLM/XTZ/ASTR/DAI/FCR/NAC/WILD
- **取引所**: GMOコイン + bitbank（ccxt 経由）
- **30分毎の価格スナップショット**、3% 以上の変動で異常アラート → リサーチ自動実行
- 取引安全設定: 1回最大¥50,000 / 日次上限¥100,000

### Discord Brain-β（対話エージェント、2026-04-05 徹底改善）
- **7カテゴリ意図分類**: greeting / status / statement / query / consult / philosophy / command を軽量パターンマッチで即時判定
- **破壊的ACTION直接ルート**: 承認/却下/記事執筆依頼は正規表現マッチで LLM を一切経由せず直接ハンドラに流す（幻覚確認劇防止）
- **working_fact protocol**: ユーザーの事実宣言（「エラー解消した」等）を自動で persona_memory に記録し、以降の応答で DB状態より優先して注入
- **`!` コマンド**: `!承認一覧 / !承認 / !却下 / !状態 / !予算 / !記事 / !依頼 / !charlie / !レビュー / !提案生成 / !予算設定 / !収益記録`
- **毎時健全性監査**: `brain_beta_health_audit` が幻覚確認劇再発・定型接頭辞率・生Python例外露出・working_fact注入実績・コマンド発動頻度を測定、critical で Discord アラート

### 自律運用・ガバナンス
- **5段階自律ループ**: Perception → Plan → Execute → Verify → Stop Decide（OS Kernel 統括）
- **3層提案エンジン**: 提案 → 反論 → 代替案 → 収益スコアリング
- **9層 LoopGuard + 6条件 Emergency Kill**（下記「安全装置」参照）
- **4 tier 承認ポリシー**（下記「安全装置」参照、`docs/approval_policy.md` に詳細）
- **Brain-α / Brain-β 交差評価**: 毎日06:00 に 2モデルで相互評価

## 4台のPC構成

| ノード | マシン | 役割 |
|--------|--------|------|
| ALPHA | Mac mini M4 Pro | 司令塔。FastAPIサーバー、PostgreSQL、NATS、Web UI |
| BRAVO | RTX 5070搭載PC | 実行役。ローカルLLM推論、ブラウザ操作 |
| CHARLIE | RTX 3080搭載PC | 推論役。ローカルLLM推論、並列処理 |
| DELTA | GTX 980Ti + RAM 48GB | 監視役。品質チェック、モニタリング、学習記録 |

4台はTailscale VPNで接続され、NATS JetStreamでメッセージをやり取りします。

## 技術スタック

- **バックエンド**: Python 3.14 + FastAPI（ALPHA）
- **フロントエンド**: Next.js 16 + React 19 + Tailwind CSS v4（PWA対応）
- **データベース**: PostgreSQL + pgvector（共有49テーブル）+ SQLite（ノード別ローカル4テーブル）
- **メッセージング**: NATS JetStream（ALPHA中心 + BRAVO/CHARLIE/DELTA）
- **ローカルLLM (Ollama, KV Cache Q8 + KEEP_ALIVE=-1)**:
  - BRAVO: Qwen3.5-9B + Qwen3.5-27B（quality="highest_local"時のみ）+ Nemotron-Nano-9B-Japanese
  - CHARLIE: Qwen3.5-9B + Nemotron-Nano-9B-Japanese
  - DELTA: Qwen3.5-4B
  - ALPHA: LLMなし（オーケストレーター専任）
- **外部API**: OpenRouter (Qwen 3.6 Plus 無料枠), Anthropic Claude, OpenAI, DeepSeek, Google Gemini

## セットアップ

### 1. ALPHAの起動

```bash
cd ~/syutain_beta

# Python環境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Web UI
cd web && pnpm install && pnpm build && cd ..

# 起動
bash start.sh
```

### 2. BRAVO / CHARLIE / DELTA の起動

各ノードは Ubuntu で、systemd の `syutain-worker-{node}.service` で自動起動します。
手動で起動・確認する場合は SSH して：

```bash
cd /home/shimahara/syutain_beta
sudo systemctl status syutain-worker-bravo    # （ノード名は bravo/charlie/delta）
sudo systemctl restart syutain-worker-bravo   # 再起動
```

Ollama と NATS も同様に system-level サービスで管理されます（`ollama.service`, `syutain-nats.service`）。

### 3. 環境変数

`.env.example` をコピーして `.env` を作成し、各APIキーとTailscale IPを設定してください。

## ディレクトリ構成

```
syutain_beta/
├── app.py              # FastAPIメインサーバー
├── scheduler.py        # 定期タスクスケジューラ
├── worker_main.py      # リモートノード用ワーカー
├── start.sh            # ALPHA起動スクリプト
├── agents/             # 20個のAIエージェント
│   ├── os_kernel.py    #   自律ループの中核
│   ├── approval_manager.py  # 承認ゲート（4ポリシー）
│   ├── executor.py     #   タスク実行
│   └── ...
├── brain_alpha/        # Brain-α（コンテンツ生成・品質ゲート・persona）
├── bots/               # Discord Brain-β（対話エージェント）
├── tools/              # 70+個のツールモジュール
│   ├── llm_router.py   #   choose_best_model_v6（18分岐ルーティング）
│   ├── nats_client.py  #   ノード間通信
│   ├── loop_guard.py   #   9層ループ防止
│   ├── brain_beta_health_audit.py  # Brain-β健全性監査（毎時）
│   └── ...
├── web/                # Next.js ダッシュボード
├── config/             # ノード別設定YAML
├── prompts/            # エージェント用プロンプト
├── scripts/            # 運用スクリプト
├── strategy/           # 戦略定義ファイル
└── docs/               # 設計ドキュメント
```

## 安全装置

- **9層ループガード**: ステップ数・予算・時間・エラー回数・出力類似度・進捗停滞・リソース枯渇・セマンティックループ・Cross-Goal干渉を監視
- **承認フロー (4 tier)**:
  - **Tier 1 (人間必須)**: 商品公開、価格設定、暗号通貨取引、外部アカウント変更、課金発生
  - **Tier 2 (自動承認+通知)**: SNS投稿は品質スコア0.75以上で自動承認、情報収集パイプライン、モデル切替、コンテンツ下書き、記事執筆依頼
  - **Tier 3 (完全自動)**: ヘルスチェック、ログローテーション、キャッシュクリーンアップ、メトリクス収集
  - 品質0.75未満のSNS投稿、金銭言及や他者メンション含む投稿は Tier 1 に自動エスカレーション
- **Emergency Kill（6条件）**: 50ステップ超過 / 日次予算90%超過 / 同一エラー5回 / 2時間超過 / セマンティックループ検出 / Cross-Goal干渉検出
- **破壊的ACTION直接ルート**: 承認・却下・SNS投稿・記事執筆依頼などはLLMを一切経由せず、Discord on_message 冒頭の正規表現マッチで直接ハンドラに流す設計（2026-04-05 幻覚確認劇対策以降）
- **Brain-β健全性監査**: 毎時 brain_beta_health_audit を実行、幻覚確認劇・定型接頭辞再発・生例外露出・working_fact注入実績・commissionキュー状態を監視、critical検出で Discord 即アラート
- **Discord通知**: 重要な判断・提案・エラーをDiscord Webhookで通知

## ライセンス

プライベートプロジェクト。無断複製・配布禁止。

---

## Live Stats (auto-updated)

| Metric | Value |
|--------|-------|
| LLM Calls | 20,463 |
| Total Cost | ¥3,771 |
| Events Logged | 83,538 |
| SNS Posts | 1,006 |
| Last Updated | 2026-04-20 09:30 JST |
