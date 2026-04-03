# SYUTAINβ セッション初期化 V2

## 読み込み順序（必ずこの順で読むこと）

### 1. SYSTEM_STATE.md（最重要、100行）
システムの現在の実態。ノード状態、DB統計、パイプライン状態、自動検出された課題。
```bash
cat ~/syutain_beta/SYSTEM_STATE.md
```

### 2. CODE_MAP.md（130行）
ファイル構造と役割。エージェント17本、ツール26本、ページ9本の一覧。
```bash
cat ~/syutain_beta/CODE_MAP.md
```

### 3. CLAUDE.md（22条）
Claude Code絶対ルール。設計書の設計を最優先、段階的実装、LLMルーティング必須、等。
```bash
cat ~/syutain_beta/CLAUDE.md
```

### 4. 直近のOPERATION_LOG（30行）
前日の運用実績。ゴール/タスク/LLM/コスト/エラーの24時間サマリー。
```bash
ls -t ~/syutain_beta/docs/OPERATION_LOG_*.md | head -1 | xargs cat
```

### 5. 直近のSESSION_HANDOFF（任意）
前回セッションの経緯。必要な場合のみ読む。
```bash
ls -t ~/syutain_beta/docs/SESSION_HANDOFF_*.md | head -1 | xargs cat
```

### 6. 設計書V25（参照のみ）
全文読み込みは不要。必要な章のみ参照。
- 第6章: 5段階自律ループ
- 第8章: ループ防止9層
- 第14章: DBスキーマ
```bash
# 必要な章のみ: grep -n "^# 第" ~/syutain_beta/SYUTAINβ_完全設計書_V25.md
```

## セッション開始時の確認コマンド

```bash
cd ~/syutain_beta
# 1. 最新のSYSTEM_STATE.mdを生成（60秒）
bash scripts/generate_system_state.sh
# 2. 内容確認
cat SYSTEM_STATE.md
# 3. 必要ならCODE_MAP.mdも更新
bash scripts/generate_code_map.sh
```

## 注意事項
- SYSTEM_STATE.mdの「自動検出された課題」セクションを必ず確認すること
- 設計書V25は原典だが、SYSTEM_STATE.mdが実態を反映している
- rsyncで.envを上書きしないこと（`--exclude '.env'`必須）
- ローカルLLM使用率が20%未満なら警告が出る
