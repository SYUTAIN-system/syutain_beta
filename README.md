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

- **バックエンド**: Python 3.12 + FastAPI（ALPHA）
- **フロントエンド**: Next.js 16 + React 19 + Tailwind CSS v4（PWA対応）
- **データベース**: PostgreSQL（共有15テーブル）+ SQLite（ノード別ローカル4テーブル）
- **メッセージング**: NATS v2.12.5 + JetStream（4ノードRAFTクラスタ）
- **ローカルLLM**: Ollama + Qwen3.5-9B（BRAVO/CHARLIE）、Qwen3.5-4B（DELTA）
- **外部API**: OpenAI, Anthropic, DeepSeek, Google Gemini, OpenRouter

## セットアップ

### 1. ALPHAの起動

```bash
cd /Users/daichi/syutain_beta

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

各ノードにSSHして：

```bash
cd /home/daichi/syutain_beta
source venv/bin/activate
python worker_main.py
```

### 3. 環境変数

`.env.example` をコピーして `.env` を作成し、各APIキーとTailscale IPを設定してください。

## ディレクトリ構成

```
syutain_beta/
├── app.py              # FastAPIメインサーバー
├── scheduler.py        # 定期タスクスケジューラ
├── worker_main.py      # リモートノード用ワーカー
├── start.sh            # ALPHA起動スクリプト
├── agents/             # 18個のAIエージェント
│   ├── os_kernel.py    #   自律ループの中核
│   ├── planner.py      #   タスク計画
│   ├── executor.py     #   タスク実行
│   └── ...
├── tools/              # 25個のツールモジュール
│   ├── llm_router.py   #   LLMモデル選択・呼び出し
│   ├── nats_client.py  #   ノード間通信
│   ├── loop_guard.py   #   9層ループ防止
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
- **承認フロー**: SNS投稿・商品公開・価格設定・暗号通貨取引は必ず人間が承認してから実行
- **Emergency Kill**: 日次予算90%超過、同一エラー5回、2時間超過などで自動停止
- **Discord通知**: 重要な判断・提案・エラーをDiscord Webhookで通知

## ライセンス

プライベートプロジェクト。無断複製・配布禁止。
