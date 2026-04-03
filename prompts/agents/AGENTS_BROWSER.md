# AGENTS_BROWSER - ブラウザ操作サブシステム

## 4層アーキテクチャ

| Layer | ツール | 用途 | フォールバック |
|-------|--------|------|---------------|
| 1 | Lightpanda | 高速CDP、構造化データ | → Layer 2 |
| 2 | Stagehand v3 | AI駆動、自己修復 | → Layer 3 |
| 3 | Playwright | 重量SPA | → Layer 4 |
| 4 | GPT-5.4 CU | CAPTCHA、ログイン | なし（最終層） |

## 自動選択ルール

- ログイン/CAPTCHA/視覚操作 → Layer 4
- React/Angular/Vue SPA → Layer 3
- 通常Webアプリ → Layer 2
- 静的ページ/API → Layer 1

## 制約

- 全アクションをbrowser_action_logに記録
- スクリーンショットは/data/screenshots/に保存
- 1セッション最大30アクション
- Layer 4使用時はGPT-5.4コストをbudget_guardに計上
- フォールバック時は元レイヤーをfallback_fromに記録
