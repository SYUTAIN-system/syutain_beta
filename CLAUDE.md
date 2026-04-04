# SYUTAINβ V25（V30統合版）- Claude Code 絶対ルール28条

このファイルはClaude Codeがこのプロジェクトで作業する際に必ず守るべきルールです。

1. 設計書（SYUTAINβ_完全設計書_V25_V30統合.md）の設計を最優先する
2. V25はV20〜V24を再構成した原典であり、過去設計を消してはならない
3. 各Stepを完了してから次に進む（段階的実装）
4. 同じ処理を3回以上繰り返す場合は停止してエスカレーションを発動する
5. LLM呼び出し前に必ずchoose_best_model_v6()でモデルを選択する
6. 2段階精錬（ローカル→API）を標準パイプラインとして使用する
7. 全ツール呼び出しはtry-exceptで囲みlog_usage()でエラーを記録する
8. .envの内容をログに出力しない。APIキーをコードにハードコードしない
9. 設定値はハードコードせずDBまたは.envから読み込む
10. 戦略ファイル（strategy/）を参照してからコンテンツを生成する
11. SNS投稿・商品公開・価格設定・暗号通貨取引はApprovalManagerを通じて承認を得てから実行する
12. 重要な判断はDiscord Webhook + Web UIで通知する
13. ローカルLLM配置を正確に守る：ALPHAにLLMなし（オーケストレーター専任）, BRAVO=Qwen3.5-9B+27B+Nemotron-JP, CHARLIE=Qwen3.5-9B+Nemotron-JP, DELTA=Qwen3.5-4B。ローカル推論はBRAVO/CHARLIEの最大2台で実行。27Bはquality="highest_local"時のみBRAVOで使用
14. macOS (ALPHA) では declare -A を使わない (bash 3.2 非対応)
15. タスクをPostgreSQLに記録してからLoopGuard 9層で監視する
16. ループ防止のEmergency Kill条件（50ステップ/日次予算90%/同一エラー5回/2時間超過/セマンティックループ/Cross-Goal干渉）を厳守する
17. ノードが使えない場合は必ずフォールバックを実装する
18. 全ての中間成果物をDBに保存し、途中停止しても資産化できるようにする
19. NATSメッセージングでノード間通信し、直接HTTPは障害時のフォールバックとする
20. MCPサーバー接続は動的に確認し、接続不可時は代替手段で処理を継続する
21. 4台のPC（ALPHA/BRAVO/CHARLIE/DELTA）をPhase 1から全て稼働させる。BRAVOをPhase 2に先送りしない
22. 突然変異エンジン（第24章）は設計書の仕様に厳密に従い実装する。変異の発生をログに記録しない。変異パラメータをUIに表示しない。Capability Auditに含めない。9層ループ防止壁・承認フロー・Emergency Killのコードには一切干渉させない。変異エンジン自体のバグで全体が止まらないようtry-exceptで完全に隔離する
23. Brain-αはpersona_memoryの価値観を参照してから判断・生成を行うこと
24. 新しい判断基準はdaichi_dialogue_logに記録すること
25. セッション終了時にmemory_manager.save_session_memory()を必ず実行すること
26. 島原大知のtabooカテゴリ（persona_memory category='taboo'）は絶対に違反しないこと
27. コード変更後は「出来てるはず」と推測せず、必ず実機で動作確認を行うこと。scheduler/Discord bot/全リモートノードへのデプロイ反映を確認し、構文チェック・行数一致・機能テストを実行すること
28. scheduler再起動時はDiscord botも再起動が必要（別プロセス）。デプロイ時は両方の再起動と動作確認を行うこと
