# STEP10: Nemotron-Nano-8B-v2-Japanese 統合

**実施日**: 2026-03-23 18:00〜18:45 JST
**実施者**: Claude Opus 4.6 (Brain-α)

---

## Step A: インストール完了

### 使用リポジトリ
mmnga-o/NVIDIA-Nemotron-Nano-9B-v2-Japanese-GGUF (Q5_K_M, 7.1GB)
HF_TOKEN不要。Ollama Modelfileで直接pullして登録。

### インストール結果

| ノード | モデル名 | サイズ | ステータス |
|--------|---------|--------|-----------|
| BRAVO (100.x.x.x) | nemotron-jp:latest | 7.1 GB | ✅ インストール済み |
| CHARLIE (100.x.x.x) | nemotron-jp:latest | 7.1 GB | ✅ インストール済み |
| DELTA | - | - | 対象外 (6GB VRAM) |

### 日本語テスト結果（BRAVO）
```
入力: 「島原大知のAI事業OSの開発で学んだことを1文で。」
出力: 「AI事業OS開発を通じて、柔軟性とスケーラビリティを両立させる技術設計の重要性を学びました。」
レイテンシ: 10.9秒
品質: 自然な日本語 ✅
```

### .env設定
```
NEMOTRON_JP_ENABLED=true  ← 有効化済み
NEMOTRON_JP_NODES=bravo,charlie
```

## Step B: choose_best_model_v6() 修正

### 新規追加
- `NEMOTRON_JP_ENABLED` 環境変数制御
- `_NEMOTRON_PRIORITY_TASKS`: content, sns_draft, drafting, chat等 → Nemotron第1候補
- `_NEMOTRON_THINK_TASKS`: quality_verification, analysis, strategy等 → Nemotron+/think
- `_pick_nemotron_node()`: Nemotron利用可能ノード選択

### ルーティング検証結果

| タスク | 品質 | Nemotron OFF | Nemotron ON |
|-------|------|-------------|-------------|
| content | medium | gemini-2.5-flash | **nemotron-jp@bravo** |
| chat | medium | qwen3.5-9b@bravo | **nemotron-jp@bravo** |
| classification | low | qwen3.5-4b@delta | qwen3.5-4b@delta（変更なし） |
| content_final | high | deepseek-v3.2 | deepseek-v3.2（変更なし） |
| analysis | high | gemini-2.5-flash | **nemotron-jp@bravo+/think** |

### Nemotron推論制御
- デフォルト: `think=True`（推論ON）
- `/no_think`対象: classification系軽量タスク（DELTAに振られるため実質不使用）

## Step C: agent_reasoning_trace連携

call_llm()実行時にモデル選定根拠をagent_reasoning_traceに自動記録:
```
agent_name: LLMRouter
action: model_selected
reasoning: 選定理由（model_selectionのnote）
context: {model, provider, tier, node, nemotron_enabled}
```

## Step D: Web UI更新

| ページ | 変更 |
|-------|------|
| / (ダッシュボード) | ノードモデル表示更新（ALPHA=推論なし、BRAVO/CHARLIE=Nemotron+Qwen） |
| /node-control | モデル情報更新 |
| /settings | ノード構成更新 |

## 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| scripts/install_nemotron.sh | **新規**: Nemotronインストールスクリプト |
| tools/llm_router.py | Nemotron優先ルーティング追加、/think制御、トレース記録 |
| .env | NEMOTRON_JP_ENABLED/NODES追加 |
| web/src/app/page.tsx | ノードモデル表示更新 |
| web/src/app/settings/page.tsx | ノード構成更新 |
| web/src/app/node-control/page.tsx | モデル情報更新 |

## 完了

全ステップ完了。Nemotron-Nano-9B-v2-JapaneseがBRAVO/CHARLIEで稼働中。
NEMOTRON_JP_ENABLED=trueで全ルーティングが切り替わっている。

---

## 接続先URL

```
HTTPS: https://100.x.x.x:8443/
モデル: https://100.x.x.x:8443/models
設定: https://100.x.x.x:8443/settings
```
