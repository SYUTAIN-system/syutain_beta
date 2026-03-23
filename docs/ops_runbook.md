# 運用手順書（Ops Runbook）

## 日常運用

### 起動手順
1. ALPHA: `./start.sh` を実行（PostgreSQL → NATS → FastAPI → Next.js）
2. BRAVO/CHARLIE/DELTA: systemd で自動起動

### 停止手順
1. ALPHA: `./start.sh stop`
2. 全ノード: NATSクラスタが自動的にグレースフルシャットダウン

## 障害対応

### ノードがダウンした場合
- NATSクラスタは2台同時障害まで耐性あり
- CHARLIE停止時: BRAVO + DELTAでフォールバック
- BRAVO停止時: CHARLIE + DELTAでフォールバック

### Emergency Kill 発動条件
- 50ステップ超過
- 日次予算90%消費
- 同一エラー5回
- 2時間超過
- セマンティックループ検知
- Cross-Goal干渉検知

### ログ確認
- ALPHA: `logs/alpha.log`
- 全ノード: `logs/{node}.log`
- Emergency Kill: `logs/emergency_kill.log`
