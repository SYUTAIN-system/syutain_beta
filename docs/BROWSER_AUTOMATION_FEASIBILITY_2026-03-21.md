# Browser Automation Feasibility Report

**Date:** 2026-03-21
**Target:** note.com, booth.pm
**Test Environment:** BRAVO (shimahara@100.75.146.9, Ubuntu 24.04, x86_64)

---

## 1. BRAVO Environment Status

| Item | Status |
|------|--------|
| Playwright | v1.58.0 (新規インストール済) |
| Chromium | HeadlessChrome/145.0.7632.6 (playwright install済) |
| Python | 3.12 (system, venvなし) |
| Xvfb | インストール済 |
| 日本語フォント | fonts-ipafont-gothic インストール済 |

**Note:** `--break-system-packages` でインストール。PATH警告あり (`/home/shimahara/.local/bin`)。

---

## 2. note.com

### アクセス結果

| テスト項目 | 結果 |
|-----------|------|
| トップページ | アクセス可能 (title: "note -- つくる、つながる、とどける。") |
| ログインページ (`/login`) | アクセス可能 (title: "ログイン｜note（ノート）") |
| メール入力欄 | あり (`input[type="text"]`, placeholder="mail@example.com or note ID") |
| パスワード入力欄 | あり (`input[type="password"]`) |
| input要素数 | 2 |

### Bot検出リスク

| 検出項目 | 値 | リスク |
|---------|---|--------|
| User-Agent | `HeadlessChrome/145.0.7632.6` | 高 -- "Headless"文字列が含まれる |
| `navigator.webdriver` | `true` | 高 -- Seleniumと同じフラグ |
| `navigator.plugins.length` | 0 | 中 -- 通常ブラウザは複数プラグインあり |

### 対策

- `playwright-stealth` または `playwright-extra` でwebdriver検出回避
- User-Agentを通常Chromeに偽装 (既存 `playwright_tools.py` でカスタムUA設定済)
- `--disable-blink-features=AutomationControlled` フラグ追加

### note.com 既存実績

- `browser_action_log` に note.com への `extract` 成功記録あり (11件中に含まれる)
- 既存コードベースに4層ブラウザアーキテクチャが実装済 (Layer 1-4)

### 認証情報

- `NOTE_EMAIL` -- .envに設定済
- `NOTE_PASSWORD` -- .envに設定済

### 自動化実現性: **中**

- ログインフォームはシンプル (2 input要素)
- ただしBot検出対策が必要 (webdriver=true, HeadlessChrome UA)
- note.comはReact SPAのため、ページ遷移後のDOM待機が必要
- 記事投稿フォームは未検証 (ログインが前提)

---

## 3. booth.pm

### アクセス結果

| テスト項目 | 結果 |
|-----------|------|
| トップページ (`booth.pm`) | アクセス可能 (title: "BOOTH - 創作物の総合マーケット") |
| 管理画面 (`manage.booth.pm`) | ログインページへリダイレクト |
| リダイレクト先 | `https://manage.booth.pm/users/sign_in` |
| ログインページ title | "ログイン - BOOTH" |

### ログインフォーム構造

- `authenticity_token` (hidden) -- CSRFトークン、Rails標準
- `submit` ボタン x2 (通常ログイン + 外部認証)
- メール/パスワード入力欄は初期表示のinput一覧に含まれず (5件表示中に未検出)
- pixivアカウント連携ログインの可能性が高い

### Bot検出リスク

- booth.pmはpixiv系列のためCloudflare/reCAPTCHA使用の可能性
- `authenticity_token` によるCSRF保護あり (セッション管理が必要)

### 認証情報

- `BOOTH_EMAIL` -- .envに未設定
- `BOOTH_PASSWORD` -- .envに未設定
- `PIXIV_*` -- .envに未設定

### 自動化実現性: **低**

- ログインフォームがpixiv OAuth経由の可能性 (メール/パスワード直接入力欄が不明)
- CSRF保護あり
- 認証情報が未設定
- Cloudflare等のBot対策が入っている可能性

---

## 4. 既存コードベース資産

`~/syutain_beta/` には4層ブラウザ自動操作アーキテクチャが既に実装済:

| Layer | ツール | ファイル | 用途 |
|-------|-------|---------|------|
| 1 | Lightpanda (CDP) | `tools/lightpanda_tools.py` | 高速データ抽出 |
| 2 | Stagehand v3 | `tools/stagehand_tools.py` | AI駆動、自己修復 |
| 3 | Playwright + Chromium | `tools/playwright_tools.py` | 重いSPAフォールバック |
| 4 | GPT-5.4 Computer Use | `tools/computer_use_tools.py` | CAPTCHA、ログイン |

**BrowserAgent** (`agents/browser_agent.py`) がサイト特性に基づく自動レイヤー選択とフォールバックを担当。

**browser_action_log** 実績: extract 266件 (成功11件、失敗255件) -- 成功率4.1%で改善余地あり。

---

## 5. 必要な .env 追加

```bash
# booth.pm (自動化する場合)
BOOTH_EMAIL=<booth/pixivログインメール>
BOOTH_PASSWORD=<booth/pixivパスワード>

# Playwright stealth (推奨)
PLAYWRIGHT_STEALTH=true

# note.com (既に設定済)
# NOTE_EMAIL=***
# NOTE_PASSWORD=***
```

---

## 6. Next Steps

### 短期 (すぐ実行可能)

1. **note.com ログインテスト**: stealth設定を入れた上でログイン成功を確認
   - `playwright-stealth` パッケージをBRAVOにインストール
   - `playwright_tools.py` の `PlaywrightBrowser.launch()` にstealth適用
   - `--disable-blink-features=AutomationControlled` を `CHROMIUM_ARGS` に追加
2. **note.com 投稿フォーム調査**: ログイン後の記事作成ページのDOM構造を確認
3. **browser_action_log 失敗分析**: 255件の失敗原因を調査し成功率改善

### 中期 (1-2日)

4. **booth.pm ログイン方式調査**: pixiv OAuth フローの解析
5. **BOOTH認証情報の.env登録**: pixivアカウント情報の設定
6. **Computer Use (Layer 4) 活用検討**: CAPTCHA/複雑UIはGPT-5.4 Computer Useで対応

### 注意事項

- note.com の利用規約で自動投稿が禁止されていないか確認必要
- booth.pm の管理画面操作は商品登録/在庫管理等、誤操作リスクが高いため慎重に
- Bot検出でアカウントBANのリスクがあるため、本番アカウントでのテストは最小限に
- rate limit を意識した操作間隔の設定が必要
