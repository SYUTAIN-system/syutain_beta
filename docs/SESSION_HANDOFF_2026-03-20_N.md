# SYUTAINβ セッション引き継ぎ資料

**作成日**: 2026-03-20
**最終更新**: 2026-03-20 23:00 JST
**作成者**: Claude Opus 4.6 (1M context)

---

## 1. Threads API自動投稿実装

### 実装済み
- **`.env`にThreads認証情報追加**: THREADS_ACCESS_TOKEN + THREADS_USER_ID
- **`post_to_threads()`**: 承認チェック付きThreads投稿（500文字制限、NGワードチェック）
- **`execute_approved_threads()`**: 承認済み投稿実行（Meta Graph API 2ステップ: create→publish）
- **`app.py`承認ハンドラ**: `threads_post`承認時にexecute_approved_threads()自動呼び出し
- **`threads_auto_draft()`**: ドラフト自動生成ジョブ（8時間間隔、1日3投稿）
  - パターンローテーション: 途中経過/VTuber経験/技術チャレンジ/失敗記録/設計仮説
  - strategy_identity + bluesky_worldview + anti_ai_writing注入
  - 全プラットフォーム重複チェック
- **`content_multiplier.py`**: Threads3本を追加（1素材→17件: BS5+XS3+XY2+TH3+Booth1+Note3）
- **`feature_flags.yaml`**: threads_auto_post=true

### ドラフト生成テスト結果
- ドラフト生成→承認キューID=70に投入→Discord通知成功
- 内容: 「プログラミングが全然できない僕が、4台のPCでAI事業OSを作っているのは...」（VTuber経験ベース）

### 未完了: Threads実投稿
- **エラー**: `OAuthException code 190: Failed to decrypt` — アクセストークンが無効/期限切れ
- **対応**: 島原さんがMeta Developer Portalで新しいアクセストークンを生成し、.envに設定すれば即動作
- 実装自体は全て完了しており、有効トークンで即座に投稿可能

### トークン再取得手順
1. https://developers.facebook.com/ → アプリダッシュボード
2. Threads API → Generate Token
3. `.env`更新: `sed -i '' 's/^THREADS_ACCESS_TOKEN=.*/THREADS_ACCESS_TOKEN=新トークン/' ~/syutain_beta/.env`
4. FastAPI再起動: `~/syutain_beta/start.sh restart`

## 2. スケジューラージョブ: 35ジョブ（+1）
- Threads投稿ドラフト生成（8時間）

## 3. 現在のSNSチャネル体制
| プラットフォーム | アカウント | 投稿間隔 | 状態 |
|---|---|---|---|
| Bluesky | @syutain_beta | 6時間 | ✅ 稼働中 |
| X | @syutain_beta | 8時間 | ✅ 稼働中 |
| X | @Sima_daichi | 12時間 | ✅ 稼働中 |
| Threads | @syutain_beta | 8時間 | ⚠️ トークン要更新 |

## 4. 接続情報

```
HTTPS: https://100.70.34.67:8443/
API:   http://localhost:8000/
```

---

*2026-03-20 Threads API実装完了。ドラフト生成+承認キュー投入成功。実投稿はトークン再取得待ち。35ジョブ稼働中。*
