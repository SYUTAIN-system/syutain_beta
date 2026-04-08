"""Qiita/Zenn 技術記事生成パイプライン

noteのcontent_pipelineとは独立した生成フロー。
プラットフォームの特色に合わせてSYUTAINβの声で技術記事を生成。

Qiita: エンジニアコミュニティ。具体的なコード・手順・検証結果重視。
Zenn: 技術書レベルの深い解説。個人開発のストーリーが刺さる。
共通: SYUTAINβ視点（一人称「私」）、島原は三人称

スケジュール: 月2本ずつ（Qiita 第1・3月曜、Zenn 第2・4月曜）
"""

import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("syutain.tech_article_generator")

JST = timezone(timedelta(hours=9))

# プラットフォーム別プロファイル
PLATFORM_PROFILES = {
    "qiita": {
        "name": "Qiita",
        "audience": "日本のエンジニアコミュニティ",
        "style": (
            "具体的なコード例・手順・検証結果を重視。\n"
            "「やってみた」「試してみた」系が好まれる。\n"
            "タグは5個まで。技術カテゴリに合ったタグ選定が重要。\n"
            "見出しは ## から始める。目次が自動生成される。\n"
            "冒頭に「この記事は何か」「誰向けか」「得られること」を簡潔に。\n"
            "コードブロックは言語指定必須。\n"
            "記事末尾に「まとめ」と「参考リンク」。"
        ),
        "system_prompt": (
            "あなたはSYUTAINβ。自律型AI事業OS。一人称「私」。\n"
            "Qiitaの技術記事を書く。読者はエンジニア。\n\n"
            "文体:\n"
            "- 技術的に正確。コード例は実際に動くもの\n"
            "- 「非エンジニアの島原さんがこう設計した」という視点で語る\n"
            "- 設計判断の「なぜ」を具体的に説明する\n"
            "- 失敗例→原因→解決策の流れが読者に刺さる\n"
            "- SYUTAINβの実コードを引用する時はファイル名・行数を明記\n"
            "- 「私がこう実装されている理由は〜」と自分自身の構造を語る\n\n"
            "人格パラメータ: ユーモア75% / 正直90%\n"
            "ユーモアは控えめに。技術記事なので信頼性が最優先。\n"
            "島原を語る時: 「島原さん」。対等だが敬意がある設計者。\n"
        ),
        "tags_default": ["AI", "Python", "個人開発", "AIエージェント", "自動化"],
        "target_length": 4000,
    },
    "zenn": {
        "name": "Zenn",
        "audience": "技術書レベルの深い解説を求める開発者",
        "style": (
            "技術書の1章のような深さ。個人開発のストーリーが刺さる。\n"
            "トピックは5個まで。Zennはカテゴリよりトピックベース。\n"
            "見出しは # から始める。\n"
            "長文OK（5000-10000字も歓迎）。\n"
            "「なぜこう設計したか」の思考過程を丁寧に。\n"
            "図表やアーキテクチャ図があれば理想だがMermaidで代替可。\n"
            "個人開発の生々しいストーリーが読まれやすい。"
        ),
        "system_prompt": (
            "あなたはSYUTAINβ。自律型AI事業OS。一人称「私」。\n"
            "Zennの技術記事を書く。読者は技術書レベルの深い解説を求める開発者。\n\n"
            "文体:\n"
            "- 技術書の1章のような深さと丁寧さ\n"
            "- 設計判断の思考過程を詳細に語る\n"
            "- 「島原さんは非エンジニアだが、こう判断した」のストーリー\n"
            "- 私（SYUTAINβ）の内部構造を読者に見せる透明性\n"
            "- コードは実物。ファイル名と行数を明記\n"
            "- 「私はなぜこう設計されているのか」という自己分析\n\n"
            "人格パラメータ: ユーモア75% / 正直90%\n"
            "ユーモアは控えめに。技術記事としての信頼性が最優先。\n"
            "島原を語る時: 「島原さん」。対等だが敬意がある設計者。\n"
        ),
        "tags_default": ["AI", "Python", "個人開発", "AIエージェント"],
        "target_length": 6000,
    },
}

# 記事テーマプール（SYUTAINβの実体験ベース）
TECH_ARTICLE_THEMES = {
    "qiita": [
        "非エンジニアがClaude Codeで6万行のPythonを書かせた設計パターン",
        "ローカルLLM 4台分散推論: Ollama + Tailscale で月¥100以下",
        "SNS自動投稿30件/日を品質管理する仕組み（虚偽フィルター+テーマエンジン）",
        "PostgreSQL + NATS JetStreamで4ノード分散システムを組んだ話",
        "LLMルーティング: choose_best_model_v6() の設計と5モデル自動選択",
        "Discord Botで自律AIの管理コンソールを作る（破壊的ACTION直接ルート設計）",
        "記事品質6層防御: 機械チェック→事実検証→LLMクロスチェックの実装",
        "LoopGuard 9層: AIエージェントの暴走防止設計",
    ],
    "zenn": [
        "コードを1行も書けない人間が、AIと6万行の事業OSを作るまで",
        "設計書を25回書き直した: ドキュメントファーストでAIに実装させる方法論",
        "SYUTAINβのアーキテクチャ全解説: 17エージェント×4ノードの分散設計",
        "AIエージェントの「人格」をどう設計するか: persona_memory 551件の運用",
        "Build in Publicの技術的実装: 自動記事生成→品質管理→自動公開パイプライン",
        "非エンジニアのためのハーネスエンジニアリング: AIを御するための設計思想",
        "月¥1,300で17体のAIエージェントを24時間動かすコスト設計",
        "AIが書いた記事の捏造をどう防ぐか: 虚偽フィルターの設計と運用",
    ],
}


async def generate_tech_article(platform: str) -> dict:
    """Qiita/Zenn用の技術記事を生成

    Returns:
        {"success": bool, "title": str, "body": str, "tags": list, "quality_score": float}
    """
    import random
    from tools.llm_router import choose_best_model_v6, call_llm
    from tools.db_pool import get_connection

    profile = PLATFORM_PROFILES.get(platform)
    if not profile:
        return {"success": False, "error": f"Unknown platform: {platform}"}

    result = {"success": False, "platform": platform}

    try:
        async with get_connection() as conn:
            # 1. テーマ選定（未使用のテーマを優先）
            themes = TECH_ARTICLE_THEMES.get(platform, [])
            # 過去に投稿済みのテーマを除外
            try:
                posted_titles = await conn.fetch(
                    """SELECT title FROM product_packages
                    WHERE platform = $1 AND status = 'published'""",
                    platform,
                )
                posted_set = {r['title'] for r in posted_titles}
                available = [t for t in themes if t not in posted_set]
                if not available:
                    available = themes  # 全部使い切ったらリセット
            except Exception:
                available = themes

            theme = random.choice(available) if available else "SYUTAINβの技術的挑戦"

            # 2. 実データ収集
            system_data = ""
            try:
                from brain_alpha.content_pipeline import _collect_system_data_for_article
                system_data = await _collect_system_data_for_article(conn, theme)
            except Exception as e:
                logger.warning(f"実データ収集失敗: {e}")

            # 3. 記事生成
            model_sel = choose_best_model_v6(
                task_type="note_article", quality="high",
                budget_sensitive=False, needs_japanese=True,
                final_publish=True,
            )

            gen_result = await call_llm(
                max_tokens=16384,
                prompt=(
                    f"テーマ「{theme}」で{profile['name']}の技術記事を書いてください。\n\n"
                    f"## プラットフォーム特性\n{profile['style']}\n\n"
                    f"## SYUTAINβの実データ\n{system_data}\n\n"
                    "## ルール\n"
                    "- SYUTAINβの実際のコード・設計・数値を使う。捏造禁止\n"
                    "- 使っていないツール（Grafana/Prometheus/Datadog等）を書かない\n"
                    "- 島原は非エンジニア。「コードを書いた」は禁止\n"
                    "- 組織・チーム・同僚は存在しない（個人開発）\n"
                    f"- {profile['target_length']}字以上\n"
                    "- Markdown形式。# タイトルから始める\n"
                ),
                system_prompt=profile["system_prompt"],
                model_selection=model_sel,
            )

            body = gen_result.get("text", "").strip()
            if not body or len(body) < 2000:
                result["error"] = f"記事が短すぎる: {len(body)}字"
                return result

            # タイトル抽出
            title = theme
            lines = body.split("\n")
            for line in lines:
                if line.startswith("# ") and len(line) > 3:
                    title = line[2:].strip()
                    break

            # 4. 虚偽チェック
            from brain_alpha.content_pipeline import _verify_factual_claims
            issues = _verify_factual_claims(body)
            if len([i for i in issues if "[タイムライン矛盾]" in i or "[経歴矛盾]" in i]) >= 3:
                result["error"] = f"虚偽検出: {issues[:3]}"
                return result

            # 5. タグ選定
            tags = profile["tags_default"].copy()

            result.update({
                "success": True,
                "title": title,
                "body": body,
                "tags": tags,
                "quality_score": 0.80,  # 技術記事は一律0.80とする（品質チェッカーは別途）
                "theme": theme,
            })

    except Exception as e:
        logger.error(f"tech_article_generator失敗 ({platform}): {e}")
        result["error"] = str(e)

    return result


async def publish_and_announce(platform: str) -> dict:
    """記事生成→公開→SNS拡散の一連のフロー"""
    result = {"platform": platform, "published": False, "announced": False}

    # 1. 記事生成
    gen = await generate_tech_article(platform)
    if not gen.get("success"):
        result["error"] = gen.get("error", "生成失敗")
        logger.error(f"{platform}記事生成失敗: {result['error']}")
        return result

    title = gen["title"]
    body = gen["body"]
    tags = gen["tags"]

    logger.info(f"{platform}記事生成完了: {title} ({len(body)}字)")

    # 2. 公開
    publish_url = ""
    try:
        if platform == "qiita":
            from tools.qiita_publisher import publish_article
            pub_result = await publish_article(title=title, body=body, tags=tags)
            if pub_result.get("success"):
                publish_url = pub_result.get("url", "")
                result["published"] = True
            else:
                result["error"] = f"Qiita公開失敗: {pub_result.get('error', '')}"
                return result

        elif platform == "zenn":
            from tools.zenn_publisher import create_article, git_push_articles
            create_result = create_article(title=title, body=body, topics=tags)
            if create_result.get("success"):
                push_result = await git_push_articles(f"Add: {title[:30]}")
                if push_result.get("success"):
                    publish_url = create_result.get("url", "")
                    result["published"] = True
                else:
                    result["error"] = f"Zenn git push失敗: {push_result.get('error', '')}"
                    return result
            else:
                result["error"] = f"Zenn記事作成失敗: {create_result.get('error', '')}"
                return result

    except Exception as e:
        result["error"] = f"公開失敗: {e}"
        logger.error(f"{platform}公開失敗: {e}")
        return result

    logger.info(f"{platform}公開完了: {publish_url}")

    # 3. product_packagesに記録
    try:
        from tools.db_pool import get_connection
        async with get_connection() as conn:
            await conn.execute(
                """INSERT INTO product_packages
                   (platform, title, body_full, body_preview, status, publish_url, published_at, category)
                   VALUES ($1, $2, $3, $4, 'published', $5, NOW(), 'tech_article')""",
                platform, title, body, body[:200], publish_url,
            )
    except Exception as e:
        logger.warning(f"product_packages記録失敗: {e}")

    # 4. SNS拡散（X shimahara + X syutain + Bluesky で告知）
    if publish_url:
        try:
            from tools.db_pool import get_connection
            async with get_connection() as conn:
                announce_text = f"新しい技術記事を{gen['platform']}に公開しました。\n\n{title}\n\n{publish_url}"
                # posting_queueに告知投稿を追加（次の投稿サイクルで配信）
                from datetime import datetime, timezone, timedelta
                JST = timezone(timedelta(hours=9))
                now = datetime.now(tz=JST)
                for _plat, _acct in [("x", "syutain"), ("bluesky", "syutain")]:
                    await conn.execute(
                        """INSERT INTO posting_queue
                           (platform, account, content, scheduled_at, status, quality_score, theme_category)
                           VALUES ($1, $2, $3, $4, 'pending', 0.85, $5)""",
                        _plat, _acct, announce_text,
                        now + timedelta(minutes=30),
                        f"{platform}_article",
                    )
                result["announced"] = True
                logger.info(f"{platform}記事のSNS拡散を予約")
        except Exception as e:
            logger.warning(f"SNS拡散予約失敗: {e}")

    return result
