# SYUTAINβ 運用ログ 2026-03-20
> 自動生成: 2026-03-21 00:00:00 JST

## 24時間サマリー
| 指標 | 件数 |
|------|------|
| ゴール作成 | 2 (完了: 2) |
| タスク実行 | 12 (成功: 41) |
| LLM呼び出し | 266 (ローカル: 180, コスト: ¥55.43) |
| 情報収集 | 250 |
| 提案生成 | 3 |
| 承認処理 | 19 |
| イベント | 1406 (エラー: 14) |

## コスト分析
| モデル | 呼出数 | コスト |
|--------|--------|--------|
| qwen3.5-9b | | | ¥176 |  0.00 |
| jina-reader | | | ¥40 | 20.00 |
| tavily-search | | | ¥16 | 32.00 |
| deepseek-v3.2 | | | ¥13 |  1.24 |
| gemini-2.5-flash | | | ¥10 |  2.13 |
| gemini-2.5-pro | | | ¥3 |  0.01 |
| gpt-5-mini | | | ¥2 |  0.05 |
| qwen3.5:4b | | | ¥2 |  0.00 |
| qwen3.5:9b | | | ¥2 |  0.00 |
| claude-haiku-4-5-20251001 | | | ¥2 |  0.01 |

## エラー一覧
- 03:55 [llm.error] |: | alpha       | Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', '
- 03:55 [llm.error] |: | alpha       | Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', '
- 04:07 [llm.error] |: | alpha       | cannot import name 'genai' from 'google' (unknown location)
- 04:07 [llm.error] |: | alpha       | No module named 'openai'
- 04:07 [llm.error] |: | alpha       | cannot import name 'genai' from 'google' (unknown location)
- 04:08 [llm.error] |: | alpha       | No module named 'openai'
- 04:08 [llm.error] |: | alpha       | No module named 'anthropic'
- 04:08 [llm.error] |: | alpha       | cannot import name 'genai' from 'google' (unknown location)
- 04:09 [llm.error] |: | alpha       | 404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model models/gemini-2.5-
- 04:09 [llm.error] |: | alpha       | Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', '
- 20:54 [llm.error] |: | alpha       | Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', '
- 22:58 [sns.post_failed] |: | alpha       | Failed to decrypt
- 23:36 [sns.post_failed] |: | alpha       | Failed to decrypt
- 23:45 [llm.error] |: | alpha       | Client error '404 Not Found' for url 'http://100.82.81.105:11434/api/generate'  +
- | [|] |: F

## イベント内訳
| カテゴリ | 件数 |
|----------|------|
| node | |  1080 |
| llm | |   229 |
| task | |    39 |
| system | |    32 |
| sns | |    13 |
| approval | |     7 |
| goal | |     5 |
| content | |     1 |

---
*自動生成完了: 2026-03-21 00:00:00 JST (      57行)*
