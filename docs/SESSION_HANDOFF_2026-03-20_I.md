# SYUTAINβ セッション引き継ぎ資料

**作成日**: 2026-03-20
**最終更新**: 2026-03-20 20:38 JST
**作成者**: Claude Opus 4.6 (1M context)

---

## 1. 修正した重大問題

### A. 【CRITICAL】リモートノードのDATABASE_URLがlocalhost
- **発見**: BRAVO/CHARLIE/DELTAの`.env`で`DATABASE_URL=postgresql://localhost:5432/syutain_beta`
- **影響**: 全リモートノードからのevent_log記録、コスト記録、品質スコア書き戻しが全て失敗
- **原因**: BRAVOのワーカーログに`[Errno 111] Connect call failed ('127.0.0.1', 5432)`が3091件/24h
- **修正**: `postgresql://100.70.34.67:5432/syutain_beta`（ALPHAのTailscale IP）に変更
- **確認**: pg_hba.confで`100.0.0.0/8 trust`が設定済み、listen_addressesに`100.70.34.67`含む
- **ファイル**: BRAVO/CHARLIE/DELTA各`.env`

### B. 【CRITICAL】DELTA Ollamaがゾンビプロセスで無限リスタートループ
- **発見**: `Error: listen tcp 0.0.0.0:11434: bind: address already in use`が80253件
- **原因**: 3/18からのゾンビプロセス(PID 2702, shimahara所有)がポート11434を占有。systemdのollamaサービスが起動できずRestart=alwaysで無限ループ
- **修正**: `sudo kill -9 2702`後にsystemd restart → active、qwen3.5:4bモデル応答確認
- **影響**: DELTAのローカルLLM（qwen3:4b）が2日間使用不能だった

### C. 【CRITICAL】rsyncでvenvがmacOSのものに上書き
- **発見**: rsync実行後、BRAVO/CHARLIEのvenvが`/opt/homebrew/opt/python@3.14/bin/python3.14`（macOSパス）を指す状態に
- **影響**: status=203/EXEC（実行ファイルが見つからない）でワーカーが全滅
- **修正**: systemdのExecStartを`/usr/bin/python3`に変更、依存パッケージ(psutil, asyncpg, httpx, nats-py等)をシステムPythonにインストール
- **注意**: 今後rsyncする際は`--exclude='venv/'`を必ず含めること（現在のrsyncコマンドには含まれていなかった）

### D. 【ERROR】staleタスク2件（2日以上running）
- **修正**: `goal-c6bec7f8ffab-t007-41ee0b`(content)と`goal-c6bec7f8ffab-t008-f233e1`(approval_request)を`cancelled`に更新

### E. 【WARNING】品質スコア0.00が40%
- **現状**: 46/114タスク（40%）が品質スコア0.00。31タスク（27%）がNULL
- **原因推測**: リモートノードのDB接続エラーにより品質スコア書き戻しが失敗していた可能性が高い
- **対応**: DATABASE_URL修正により今後は改善する見込み。継続監視

### F. 【INFO】チャット意図分類に「品質」「コンテンツ」「エラー」キーワード追加
- 「品質の高いコンテンツを見せて」がstatus_queryとして正しく分類されるように修正
- `_handle_status_query`に品質・成果物表示ロジック追加

## 2. 確認済み正常項目

- Python構文エラー: 0件（全ファイル）
- 全モジュールimport: 成功
- FastAPI/Next.js/Caddy/NATS: 全稼働中
- BRAVO/CHARLIE/DELTA: ワーカーactive、Ollama active
- ローカルLLM: BRAVO(qwen3.5-9b)✅, CHARLIE(qwen3.5-9b)✅, DELTA(qwen3.5:4b)✅
- NATS heartbeat: 全3ノードOK
- Web UI: 10/10ページ 200 OK
- API: 10/11エンドポイント正常（`/api/models`は元々存在しない）
- pgvector: 0.8.2稼働中
- persona_memory: 124件

## 3. rsyncの安全なコマンド（次回用）

```bash
rsync -avz \
  --exclude='web/' --exclude='node_modules/' --exclude='__pycache__/' \
  --exclude='.env' --exclude='data/' --exclude='logs/' --exclude='.git/' \
  --exclude='*.md' --exclude='venv/' \
  ~/syutain_beta/ shimahara@$IP:~/syutain_beta/
```

**注意**: `--exclude='venv/'`が必須。macOSのvenvがUbuntuに上書きされて全ワーカーが死ぬ。

## 4. 残存課題

- **品質スコア0.00の割合**: DATABASE_URL修正後に改善するか1-2日監視
- **Bluesky自動投稿の本番テスト**: テスト投稿は成功済み。自動生成ドラフトの品質向上を継続
- **Anthropic APIクレジット補充**: 未対応
- **content_multiplier E2Eテスト**: 未実行
- **競合分析パイプラインテスト**: 日曜03:00に初回実行予定

## 5. 接続情報

```
HTTPS: https://100.70.34.67:8443/
API:   http://localhost:8000/
```

---

*2026-03-20 全システム徹底デバッグ。CRITICAL3件修正（DATABASE_URL/Ollamaゾンビ/venv上書き）。31ジョブ・4ノード全て稼働中。*
