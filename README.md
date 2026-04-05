# SYUTAINβ V25 — 自律型ビジネスOS

4台のPC（ALPHA / BRAVO / CHARLIE / DELTA）が連携して動く、自律型のビジネス運営システムです。
AIが提案→承認→実行→検証のサイクルを自動で回し、コンテンツ制作・SNS運用・EC管理・情報収集を行います。

## どんなことができるか

- **コンテンツ自動生成**: ブログ記事、SNS投稿、商品説明文をAIが下書き→品質チェック→仕上げ
- **SNS運用**: X(Twitter)、Instagram、note への自動投稿（人間の承認後に実行）
- **EC管理**: Shopify / BASE の商品登録・在庫監視・価格最適化
- **情報収集**: Web検索・ニュース監視・競合分析を自動で実行
- **ブラウザ操作**: Webサイトの自動操作（4段階のフォールバック付き）
- **暗号通貨**: BTC/ETHの自動売買シグナル生成（承認後に実行）

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
| LLM Calls | 11,692 |
| Total Cost | ¥1,186 |
| Events Logged | 38,715 |
| SNS Posts | 552 |
| Last Updated | 2026-04-06 02:00 JST |
