# CHANNEL_STRATEGY.md

## 0. Purpose
本書は、SYUTAINβの「どこで・どう届けるか」の最終定義です。  
特に今回の設計では、**チャネルごとの人格衝突を防ぐこと**、**送客の順番を固定すること**、**固定ポストから収益導線までを一気通貫で定義すること**を重視します。

## 1. Channel Role Matrix

| Channel | Primary Objective | Funnel Role | Must Never Do | Main Destination | Core KPI |
|---|---|---|---|---|---|
| X（島原大知） | 共感・人格・物語 | Reach / Trust | 無機質化、技術マウント、強者ぶり | note | Profile CTR, Follow Rate, note CTR |
| X（SYUTAINβ） | 論理・設計・分析 | Trust / Capture | 感情ポエム、人格の食い合い、島原化 | note / Booth / GitHub | URL CTR, Save Rate |
| Bluesky | 深い会話・コア層育成 | Trust / Retain | Xのコピペ、売り込み連打 | note | Reply Rate, Conversation Depth |
| note | 理解深化・販売・継続 | Trust / Convert / Retain | 日記だけ、宣伝だけ、Xの焼き直し | Booth / Membership / BtoB | Read Completion, CVR |
| Booth | 商品販売 | Convert | 説明不足の直売 | — | Product CVR, AOV |
| GitHub | 実在証明・技術信頼 | Trust | 放置、説明なきコード | note / X（SYUTAINβ） | Views, Stars, Outbound CTR |
| Stripe直接販売 | 高単価商品・手数料最適化 | Convert | Booth商品との価格競合 | — | CVR, AOV, 手数料率 |
| 暗号通貨自動取引 | 不労所得の構築 | — | 過度なリスクテイク、レバレッジ | — | 月次損益, シャープレシオ |
| Micro-SaaS | 自動収益の構築 | Convert / Retain | 放置、サポート不足 | note | MRR, Churn Rate |
| アフィリエイト | AI関連ツール紹介報酬 | Convert | ステマ、過剰推薦、信頼毀損 | note / Booth | 紹介CVR, 報酬額 |

## 2. Two-Account Architecture

### 投稿比率（V25基準）
- 島原大知 : SYUTAINβ = **7 : 3**（人格が先、構造が後）
- 同日同トピックの場合：島原が先に出し、SYUTAINβが構造で裏打ちする（逆順禁止）

### 2-1. 島原大知アカウントの役割
- 人間の感情
- 挑戦
- 失敗
- 数字
- 選択理由
- 生活文脈
- 「僕はこう感じ、こう決めた」

### 島原大知アカウント API運用ステータス（V25時点）
- **API接続：接続済み（.envにX_SHIMAHARA_プレフィックスで登録済み）**
- **運用方式：SYUTAINβが下書きを生成 → ApprovalManagerで島原が承認 → 自動投稿**
- **承認なしの自動投稿は禁止（CLAUDE.md第11条）**

### 2-2. SYUTAINβアカウントの役割
- 分析
- 構造
- 仮説
- 市場
- 設計
- 改善ログ
- 「私がこう整理し、こう提案する」

### 2-3. Absolutely Forbidden
- 島原アカで無機質な設計スレッドを量産しない
- SYUTAINβが主役化しない
- 片方で完結する内容をもう片方で同じ温度で再投稿しない
- 両方のアカウントで同時に同じCTAを過剰に出さない

## 3. Channel-by-Channel Operating Doctrine

## 3-1. X（島原大知）

### Goal
- 「この人を追いたい」
- 「この人は本当にやっている」
- 「この人の失敗は自分の未来に役立つ」
を作る

### Content Types
- プロジェクト宣言
- 週次収益報告
- AI開発の失敗談
- 個人開発進捗
- 感情ログ
- 判断ログ
- VTuber業界で学んだこと
- note更新告知

### Frequency
- 1日2〜5投稿
- 週1スレッド以上
- 週1固定シリーズ以上

### Must Never Do
- 技術用語だけで終わる
- 勝者ムーブ
- AI万能論
- 情報商材テンション
- 売り込みだけの連投
- 「僕がすごい」で終わる

### Native Rules
- 一人称は「僕」
- 1投稿1メッセージ
- できるだけ「数字 / 失敗 / 学び / 感情」のどれかを入れる
- note送客は“もっと知りたい状態”で行う
- 投稿単体でも価値があること

## 3-2. X（SYUTAINβ）

### Goal
- 島原大知アカウントの感情を構造で裏打ちする
- 信頼を設計・商品・GitHubへ接続する
- “AIの相棒感”を出すが、主役は食わない

### Content Types
- 市場分析レポート
- 学習ログ
- 設計改善ログ
- AI活用Tips
- GitHub更新
- KPI / 仮説

### Frequency
- 1日1〜3投稿
- 週1レポート系
- 週2 Tips系

### Must Never Do
- 感情ポエム
- “私がすごいAIです”ムーブ
- 実体のない自動化アピール
- 難解で閉じた技術語り

### Native Rules
- 一人称は「私」
- 結論→根拠→示唆
- CTAは1投稿1つ
- 必ず「なぜ読む価値があるか」を明示
- 送客先は note / Booth / GitHub のいずれか1つ

## 3-3. Bluesky

### Goal
- コア層との深い会話
- 濃い観察
- 未完成の思考共有

### Content Types
- 仮説メモ
- 実験途中報告
- 他者との議論
- 設計の迷い
- トレンド解釈

### Frequency
- 1日0〜2投稿
- 週3〜5会話重視

### Must Never Do
- Xコピペ
- 売り込み優先
- バズ前提運用

### Native Rules
- 結論を固めすぎない
- コメント応答優先
- 「まだ答えがない」を出してよい
- note送客は会話の延長で行う

## 3-4. note

### Goal
- 信頼を購入に変える
- 島原大知の挑戦を読者の地図へ翻訳する
- Membership / Booth / BtoBの中心導線になる

### Content Types
- はじめての方向けハブ記事
- 週次総括
- 月次総括
- 失敗分析
- 設計思想
- 手順化記事
- 商品解説
- BtoB示唆

### Frequency
- 無料：週1〜2
- 有料：月2〜4
- Membership：週1以上

### Must Never Do
- Xの焼き直し
- 日記だけで終わる
- 宣伝だけの記事
- 誰向けか不明
- 有料境界が雑

### Native Rules
- タイトルで対象者を切る
- 冒頭で課題を明文化
- 本文で数字・事例・判断理由
- 終盤で次の一歩を渡す
- 無料でも価値を出し切る

## 3-5. Booth

### Goal
- “使う”へ移す
- 初回購入を発生させる
- 失敗回避・時間短縮の価値を商品化する

### Price Tiers（V25基準・設計書第10.2節準拠）
- **入口商品：¥980〜¥2,980**（スターター設計書、テンプレ集、チェックリスト）
- **中核商品：¥4,980〜¥14,800**（導入パック、実践ガイド、失敗DB）
- **価格設定の原則：ICP月間可処分所得¥3,000〜¥15,000の範囲内。入口商品は¥980〜¥1,980推奨**

### Stripe直接販売との棲み分け
- **¥4,980以下 → Booth**（集客力を活かす）
- **¥5,000以上 → Stripe直接販売**（手数料3.6%+¥40 vs Booth 5.6%+22円）
- **Membership → note + Stripe**（Boothでは扱わない）

### Frequency
- 新商品：月1〜2本
- 既存商品の改訂：四半期ごと
- セール：原則やらない（信頼毀損リスク）

### Content Types
- 設計書
- テンプレ
- 再発防止パック
- スターター商品
- 実践ガイド

### Must Never Do
- 商品説明不足
- 対象者不明
- 効果誇張
- 使用後イメージ不明

### Native Rules
- 商品名で用途が分かる
- 対象者 / 非対象者を書く
- 購入後の使い方を明示
- 関連商品導線を入れる

## 3-6. GitHub

### Goal
- 本当に作っている証拠を出す
- 技術層とBtoB層に信頼を与える
- noteで意味づけする前提の証拠置き場

### Must Never Do
- 放置
- README不足
- 見栄のためだけの公開

### Native Rules
- 非エンジニアでも読めるREADME
- “何ができるか / 今どこか”を先に書く
- 技術詳細は必要に応じてnoteへ送る

## 4. Customer Journey

### B2C Standard
X（島原大知）  
→ プロフィール  
→ 固定ポスト  
→ noteハブ記事  
→ 継続観察  
→ 失敗談 / 週次収益報告  
→ Booth商品購入  
→ Membership加入  
→ 上位商品

### B2C Fast Conversion
X（失敗談 or 数字）  
→ note深掘り  
→ Booth入口商品  
→ 購入後フォロー  
→ Membership

### BtoB Route
X（SYUTAINβ） or GitHub  
→ noteで設計思想理解  
→ 実装・運用記事  
→ BtoB相談導線  
→ 小規模受託

### Affiliate Route（V25新規）
X（島原 or SYUTAINβ）  
→ noteでAIツールレビュー記事  
→ アフィリエイトリンク付き実体験レポート  
→ 紹介報酬

### Crypto Auto-Trading Route（V25新規）
SYUTAINβ自律運用  
→ GMOコイン / bitbank API  
→ 小規模自動売買  
→ 月次損益をnoteで公開  
→ 信頼 + Membership導線

### Micro-SaaS Route（V25新規）
note / X（SYUTAINβ）  
→ AIツールの課題提起  
→ 小規模ツール公開（Stripe決済）  
→ 継続利用 → MRR

## 5. Cross-Channel Traffic Design

### Primary Flow
- 島原X → note
- SYUTAINβX → note / Booth / GitHub
- Bluesky → note
- note → Booth / Membership / BtoB / Stripe直接販売 / アフィリエイト
- GitHub → note / SYUTAINβX
- アフィリエイト記事 → note → 紹介リンク

### CTA Examples
#### Emotion → note
- 「ここから先の失敗と数字はnoteに全部書きました」
- 「同じ位置にいる人向けに、途中経過ごと整理しています」

#### Failure → Booth
- 「この失敗から作った再発防止の設計書はこちらです」
- 「同じ遠回りを減らしたい人向けに、手順化しました」

#### Numbers → Membership
- 「週次の数字・失敗・修正ログはメンバーシップで継続公開しています」
- 「完成品より過程を追いたい方はこちらです」

#### Analysis → BtoB
- 「個人向けではなく、導入設計として相談したい方はこちら」
- 「小規模チーム向けの設計相談は個別で対応しています」

## 6. Fixed Post Policy
運用ルールは以下。

- 月1更新
- 最新の数字と最強導線へ差し替え
- 島原固定ポストは noteハブ記事へ
- SYUTAINβ固定ポストは Booth主力商品へ
- 何者か / なぜ追うか / どこを見るか を必ず含む

## 7. KPI Hierarchy
### Reach KPI
- プロフィールクリック率
- フォロー率
- 固定ポストCTR

### Trust KPI
- 保存率
- note読了率
- コメント率
- 再訪率

### Conversion KPI
- Booth CVR
- Membership CVR
- note→Booth CTR
- note→Membership CTR
- Stripe直接販売 CVR
- アフィリエイト紹介 CVR
- Micro-SaaS MRR

### Retention KPI
- Membership継続率
- 商品リピート率
- 再接触率
- Micro-SaaS Churn Rate

### Revenue KPI（V25新規）
- 暗号通貨自動取引 月次損益
- アフィリエイト 月次報酬額
- Stripe直接販売 月次売上
- 全収益源合計 月次推移
