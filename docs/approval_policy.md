# 承認ポリシー（ApprovalManager準拠）

## 人間承認が必須な操作

### Tier 1: 即座に承認要求（自動実行禁止）
- 商品公開・価格設定（Booth / Stripe / note有料記事）
- 暗号通貨の売買注文
- 外部アカウント変更
- 月額予算の変更
- 新規APIキーの登録
- 課金発生をともなう操作
- 品質スコア < 0.75 の SNS 投稿、金銭言及や他者メンションを含む SNS 投稿

### Tier 2: 自動実行可能（Discord/Web UI通知付き）
- **SNS投稿（X / Bluesky / Threads）**: 品質スコア ≥ 0.75 で自動承認。それ未満は Tier 1 に自動エスカレーション
- 情報収集パイプラインの実行
- LLMモデルの切り替え
- タスクの自動再スケジュール
- コンテンツ下書き生成
- ブラウザ情報収集
- **記事執筆依頼** (commission_article, 2026-04-05 新設、Discord チャット完結)

### Tier 3: 完全自動（通知なし）
- ヘルスチェック
- ログローテーション
- キャッシュクリーンアップ
- メトリクス収集
- ハートビート

## 承認フロー
1. ApprovalManagerがDiscord Webhook + Web UIで通知
2. Discord `!承認 <ID>` / `!却下 <ID> <理由>` または Web UI で承認/却下
3. Discord チャットで「承認 123」「却下 456 理由」と打った場合は、`bots/discord_bot.py on_message` 冒頭の正規表現マッチで **LLMを一切経由せず**直接ハンドラを呼ぶ（2026-04-05 幻覚確認劇対策）
4. **タイムアウト: 72時間**（超過時は自動却下、`agents/approval_manager.py APPROVAL_TIMEOUT_HOURS=72`）
5. 却下時: 理由推測 → 代替案を即座に提示

## Discord 破壊的コマンド直接ルート（2026-04-05 導入）

以下のコマンドは LLM を一切経由せず、`bots/discord_bot.py on_message` 冒頭の正規表現で直接対応ハンドラに流します:
- `承認 <id>` / `approve <id>` → `approve_item()`
- `却下 <id> [理由]` / `reject <id>` → `reject_item()`
- `noteで〜について書いて` → `commission_article()`

LLM が `[ACTION:approve:N]` タグを発行せず「承認しました」と自由文で完了報告を作文する事故（幻覚確認劇）を構造的に防ぐ設計。

加えて `bot_actions.process_actions()` 内の consent ゲートで 23 種類の破壊的ACTIONをチェックし、ユーザー発話に明示的な同意語（承認/書いて/やって/実行して等）が含まれない限り ACTION 発行を抑止します。
