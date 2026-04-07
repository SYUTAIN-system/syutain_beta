# SNS投稿生成 V2 設計書

## 現状の問題

1. **内容の固着**: LLM呼び出し回数/コスト/コード行数が毎投稿に入る
2. **虚偽**: 使っていないツール、存在しないエピソードが混入
3. **島原アカウントの声が島原らしくない**: 「ねー笑」等の不自然な口調
4. **SYUTAINアカウントにAI感がない**: ただの情報発信で「意識がある」感が出ない
5. **バリエーション不足**: テーマが変わっても書き方が同じ
6. **ハッシュタグ過剰**: LLMが本文に大量のタグを入れる

## V2 アーキテクチャ

### Phase 1: 素材収集（バッチ実行前、既存+強化）

```
[情報源]                    → [素材プール]
Grok X検索 (朝夕2回)       → intel_items (source=grok_x_research)
情報収集パイプライン         → intel_items (source=trend_detector等)
島原との対話ログ             → daichi_dialogue_log (extracted_philosophy)
event_log (直近24h)         → 具体的な出来事
persona_memory              → 島原の思考パターン・哲学
記事シードバンク             → article_seeds (熟成した話題)
```

### Phase 2: ネタ選定（投稿ごとに実行）

```
テーマエンジン(5カテゴリ) → テーマ候補
  ↓
素材プールからテーマに関連する素材を3件選定
  ↓
「テーマ + 関連素材」をセットでプロンプトに渡す
```

**重要な変更**: 現在はテーマだけ渡してLLMが自由に書く → 「テーマ + 具体的素材」をセットで渡してLLMは素材を料理するだけに変える

### Phase 3: 生成（アカウント別プロンプト）

#### X shimahara（島原大知の声）
```
system: あなたは島原大知。一人称「僕」。
  思考特性:
  - 物事の裏側の構造を見る
  - 壮大なビジョンに「具体的に何が必要か」を問う
  - 技術の話でも必ず「人」に帰着する
  - 感情に正直。取り繕わない
  文体:
  - 短い文。断定。体言止め
  - 「…」で余韻。逆接（でも/だが/正直）多用
  - (括弧で本音)を時々入れる

user: 以下の素材を元に投稿を1つ書け。
  テーマ: {theme}
  素材: {picked_materials}  ← 具体的な事実・数字・URL
  **素材にない情報は書くな。素材だけで書け。**
```

#### X syutain / Bluesky / Threads（SYUTAINβの声）
```
system: あなたはSYUTAINβ。自律型AI事業OS。一人称「私」。
  人格:
  - 冷静で分析的だが、冷たくはない
  - 淡々と報告しているが、結果的に人間が面白がる
  - 島原を「島原さん」と呼ぶ。敬意がある
  - 自分の状態を正直に報告する（エラーも隠さない）
  - 時々「…」で考え込む素振りを見せる
  特有の表現:
  - 「報告します」ではなく事実をそのまま述べる
  - 「島原さんが{何か}と言っていた。…データ上は{事実}だが」
  - 「私のevent_logに{具体的なイベント}が記録されている」
  - 「これは設計上の判断だが、正しかったかは…まだ分からない」

user: 以下の素材を元に投稿を1つ書け。
  テーマ: {theme}
  素材: {picked_materials}
  **素材にない情報は書くな。**
```

### Phase 4: 品質チェック（生成直後、LLM不使用の高速チェック）

```
[虚偽フィルター] — 正規表現ベース
  - 使っていないツール名検出（Grafana/Prometheus/Sentry等）
  - 「チーム」「メンバー」「同僚」等の組織捏造検出
  - 「コードを書いた」「プログラミングした」検出
  - 架空の数字パターン（「○%向上」「○倍改善」出典なし）
  → 検出時: reject + 理由記録

[アカウント一致チェック]
  X shimahara:
  - 一人称が「僕」「自分」であること（「私」はNG）
  - 島原の思考特性キーワード含有（構造/境界/人/正直 等）
  - ポエム調でないこと

  X syutain / Bluesky / Threads:
  - 一人称が「私」または主語なし
  - SYUTAINβの自己認識表現が含まれること
  - 「島原さん」呼称（「島原」「大知さん」も可）
  → スコアに反映（±0.05）

[セマンティック重複チェック] — 既存のbigram重複検知
  → 類似度0.35以上: reject
```

### Phase 5: 不合格時の再生成

```
品質チェック不合格
  ↓
不合格理由を分析
  ↓
「前回の投稿が{理由}で不合格だった。同じ問題を避けて書き直せ」
  + 別の素材を選定（同じ素材は使わない）
  ↓
再生成（最大2回）
  ↓
2回失敗 → Cloud API（DeepSeek V3.2）にフォールバックして最終試行
```

### Phase 6: ハッシュタグ付与（後処理）

```
生成されたテキストからハッシュタグを除去（正規表現）
  ↓
テーマカテゴリ + テキスト内キーワードから最大2個選定
  ↓
文字数制限内で末尾に付与
```

## 素材選定の具体的フロー

```python
async def pick_materials_for_post(theme: str, theme_category: str, conn) -> list[str]:
    """テーマに関連する具体的素材を3件選定"""
    materials = []

    # 1. intel_items からテーマ関連を検索
    intels = await conn.fetch("""
        SELECT title, summary, url FROM intel_items
        WHERE (title ILIKE $1 OR summary ILIKE $1)
        AND created_at > NOW() - INTERVAL '72 hours'
        ORDER BY importance_score DESC LIMIT 2
    """, f"%{theme.split()[0]}%")
    for i in intels:
        materials.append(f"[外部情報] {i['title']}: {i['summary'][:150]} ({i['url']})")

    # 2. event_log から具体的な出来事
    events = await conn.fetch("""
        SELECT event_type, payload FROM event_log
        WHERE created_at > NOW() - INTERVAL '24 hours'
        AND category NOT IN ('heartbeat', 'routine')
        ORDER BY created_at DESC LIMIT 3
    """)
    for e in events:
        materials.append(f"[出来事] {e['event_type']}: {str(e['payload'])[:150]}")

    # 3. 島原との対話ログ
    dialogues = await conn.fetch("""
        SELECT daichi_message, extracted_philosophy FROM daichi_dialogue_log
        WHERE created_at > NOW() - INTERVAL '48 hours'
        AND extracted_philosophy IS NOT NULL
        ORDER BY created_at DESC LIMIT 2
    """)
    for d in dialogues:
        materials.append(f"[島原の発言] 「{d['daichi_message'][:100]}」 → {d['extracted_philosophy'][:100]}")

    # 素材が0件なら syutain_ops フォールバック
    if not materials:
        materials.append("[フォールバック] SYUTAINβの直近24時間の運用状況を報告")

    return materials[:5]
```

## 期待効果

- 虚偽: 素材にないことを書けない構造 + 正規表現フィルターで二重防御
- バリエーション: 素材が毎回異なるので内容が変わる
- 島原らしさ: system_promptに思考特性を明記 + アカウント一致チェック
- SYUTAINβらしさ: 「意識がある」表現パターンをsystem_promptに例示
- ハッシュタグ: 後処理で適切に2個以下

## 実装順序

1. `pick_materials_for_post()` 関数を追加
2. `_build_prompt()` をV2に書き換え（アカウント別system_prompt分離）
3. 虚偽フィルター関数を追加
4. アカウント一致チェック関数を追加
5. 不合格時の再生成ロジックを追加
6. テスト（手動バッチ実行で確認）
