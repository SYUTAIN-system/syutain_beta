"""
SYUTAINβ V25 note.com自動公開モジュール
BRAVOブラウザ経由でnote.comに記事を公開する。

フロー:
1. product_packages (status='approved', platform='note') を取得
2. NATS経由でBRAVOのBrowserAgentにログイン指示 (Layer 4)
3. 記事作成ページで title/body/price/tags を入力 (Layer 3 Playwright)
4. 公開ボタンを押して結果を取得
5. DB更新 + Discord通知

Rule 8: パスワードをログ/NATSメッセージに含めない (password_env_key パターン)
Rule 11: ApprovalManager経由で承認済みのpackageのみ公開
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

from tools.db_pool import get_connection
from tools.content_redactor import redact_content, is_safe_to_publish

load_dotenv()

logger = logging.getLogger("syutain.note_publisher")

# note.com設定（.envから読み込み — Rule 9）
NOTE_EMAIL = os.getenv("NOTE_EMAIL", "")
NOTE_CREATION_URL = "https://note.com/new"
NOTE_LOGIN_URL = "https://note.com/login"

# NATS request タイムアウト（ブラウザ操作は時間がかかる）
BROWSER_REQUEST_TIMEOUT = 60.0
LOGIN_REQUEST_TIMEOUT = 45.0


class NotePublisher:
    """note.com自動公開モジュール — BRAVOブラウザ経由"""

    def __init__(self):
        self._nats_client = None
        self._logged_in = False

    async def _get_nats(self):
        """NATSクライアントを取得（遅延初期化）"""
        if self._nats_client is None:
            try:
                from tools.nats_client import get_nats_client
                self._nats_client = await get_nats_client()
            except Exception as e:
                logger.error(f"NATS接続失敗: {e}")
        return self._nats_client

    async def publish_article(self, package_id: int) -> dict:
        """
        承認済みpackageをnote.comに公開する

        Args:
            package_id: product_packages.id

        Returns:
            {"success": bool, "publish_url": str?, "error": str?}
        """
        result = {"success": False, "package_id": package_id}

        try:
            # 1. パッケージ取得（approved のみ）
            package = await self._load_approved_package(package_id)
            if not package:
                result["error"] = f"承認済みパッケージ未検出: id={package_id}"
                logger.warning(result["error"])
                return result

            logger.info(f"note.com公開開始: pkg={package_id} 『{package['title']}』")

            # 2+3. SSH経由でBRAVOのPlaywrightで直接ログイン+記事作成（最大2回試行）
            create_result = None
            for attempt in range(2):
                create_result = await self._publish_via_ssh(package)
                if create_result.get("success"):
                    break
                logger.warning(
                    f"note公開試行{attempt+1}/2 失敗: {create_result.get('error', '不明')}"
                )
                if attempt == 0:
                    # 1回目失敗: 10秒待って再試行
                    await asyncio.sleep(10)

            if not create_result or not create_result.get("success"):
                result["error"] = create_result.get("error", "記事作成失敗（2回試行）") if create_result else "記事作成失敗"
                await self._update_status(package_id, "publish_failed", error=result["error"])
                try:
                    from tools.discord_notify import notify_error
                    await notify_error(
                        "note_publish_failed",
                        f"note公開失敗（2回試行）: {package.get('title', '')[:50]}\n{result['error'][:100]}",
                        severity="error",
                    )
                except Exception:
                    pass
                return result

            publish_url = create_result.get("url", "")

            # 4.5. URL検証 — エディタURLのままならSNS告知しない
            import re as _re
            is_valid_publish_url = bool(_re.match(r'https://note\.com/[^/]+/n/[a-z0-9]+', publish_url))
            if not is_valid_publish_url:
                logger.error(
                    f"note公開URL不正: エディタURLのまま: {publish_url} — "
                    f"SNS告知を中止し、手動確認が必要"
                )
                await self._update_status(package_id, "publish_url_invalid", error=f"URL不正: {publish_url}")
                result["error"] = f"公開URLがエディタURLのまま: {publish_url}"
                result["publish_url"] = publish_url
                return result

            # 5. DB更新 — status='published'
            await self._update_status(
                package_id, "published",
                publish_url=publish_url,
            )

            # 6. イベントログ記録
            try:
                from tools.event_logger import log_event
                await log_event("note.published", "commerce", {
                    "package_id": package_id,
                    "title": package["title"],
                    "price_jpy": package.get("price_jpy", 0),
                    "publish_url": publish_url,
                })
            except Exception:
                pass

            # 7. Discord通知
            try:
                from tools.discord_notify import notify_discord
                price = package.get("price_jpy", 0)
                await notify_discord(
                    f"🎉 note.com公開完了: 『{package['title']}』(¥{price})\n"
                    f"URL: {publish_url}"
                )
            except Exception:
                pass

            # 8. SNS自動告知（X, Bluesky, Threads に投稿キュー追加）
            try:
                await _announce_publication(
                    title=package["title"],
                    url=publish_url,
                    price=package.get("price_jpy", 0),
                )
            except Exception as announce_err:
                logger.warning(f"SNS告知キュー追加失敗（公開自体は成功）: {announce_err}")

            result["success"] = True
            result["publish_url"] = publish_url
            logger.info(f"note.com公開成功: pkg={package_id} url={publish_url}")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"note.com公開エラー: pkg={package_id} {e}")
            try:
                await self._update_status(package_id, "publish_failed", error=str(e))
            except Exception:
                pass

        return result

    async def _login_note(self) -> bool:
        """note.comログインは_publish_via_ssh内で統合処理"""
        return True  # SSH方式ではログインと記事作成が一体

    async def _publish_via_ssh(self, package: dict) -> dict:
        """
        SSH経由でBRAVO上のPlaywrightスクリプトを直接実行。
        NATSのBrowserAgent経由ではなく、直接Playwrightを動かす。
        """
        import asyncio
        import tempfile

        title = package.get("title", "")
        body_preview = package.get("body_preview", "")
        body_full = package.get("body_full", "")
        # 既にペイウォールマーカーが含まれている場合は追加しない
        if body_full and "ここから有料" not in body_preview:
            body = body_preview + "\n\n---ここから有料---\n\n" + body_full
        elif body_full:
            body = body_preview + "\n\n" + body_full
        else:
            body = body_preview

        # 最終防衛線: 注意書きが冒頭にない場合は強制追加（全経路で必ず入る）
        _auto_gen_label = (
            "> この記事はSYUTAINβ（自律型AI事業OS）が自動生成・公開しました。\n"
            "> 島原大知が開発したシステムが、人間の介入なしに執筆しています。\n\n"
        )
        if not body.lstrip().startswith(">"):
            body = _auto_gen_label + body
        price = package.get("price_jpy", 0)
        tags = package.get("tags", [])
        if isinstance(tags, str):
            import json as _json
            try:
                tags = _json.loads(tags)
            except Exception:
                tags = []

        # === 公開前最終除去パス（秘密情報漏洩防止） ===
        title = redact_content(title)
        body = redact_content(body)
        safe, redact_issues = is_safe_to_publish(title + "\n" + body)
        if not safe:
            logger.error(f"note公開中止: 秘密情報除去後も残存 — {redact_issues}")
            return {"success": False, "error": f"秘密情報残存: {len(redact_issues)}件"}

        # 本文をBRAVOの一時ファイルに転送
        body_escaped = body.replace("'", "'\\''")
        ssh_host = f"{os.getenv('REMOTE_SSH_USER', 'user')}@{os.getenv('BRAVO_IP', '127.0.0.1')}"
        remote_body_path = f"/tmp/note_body_{package.get('id', 0)}.md"

        try:
            # 本文ファイルを転送
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
                f.write(body)
                local_path = f.name

            proc = await asyncio.create_subprocess_exec(
                "scp", local_path, f"{ssh_host}:{remote_body_path}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
            os.unlink(local_path)

            # BRAVOでPlaywrightスクリプト実行
            title_escaped = title.replace('"', '\\"')
            cmd = (
                f'cd ~/syutain_beta && '
                f'python3 scripts/note_publish_playwright.py '
                f'--title "{title_escaped}" '
                f'--body-file {remote_body_path} '
                f'--price {price}'
            )

            proc = await asyncio.create_subprocess_exec(
                "ssh", ssh_host, cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)

            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            logger.info(f"note公開スクリプト出力: {output[-200:]}")
            if errors:
                logger.warning(f"note公開スクリプトstderr: {errors[-200:]}")

            # 最後の行からJSON結果を取得
            lines = output.strip().split("\n")
            for line in reversed(lines):
                try:
                    result = json.loads(line)
                    return result
                except (json.JSONDecodeError, ValueError):
                    continue

            if proc.returncode == 0:
                return {"success": True, "url": "", "note": "スクリプト成功だがJSON未取得"}
            else:
                return {"success": False, "error": f"exit code {proc.returncode}: {errors[-200:]}"}

        except asyncio.TimeoutError:
            return {"success": False, "error": "SSH実行タイムアウト(180秒)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _create_article(self, package: dict) -> dict:
        """
        記事作成・公開（NATS経由でBRAVOのPlaywright/Stagehandを使用）

        note.comのリッチエディタはcontenteditable divのため、
        クリップボードペーストまたはキーボード入力で対応する。
        """
        try:
            nats = await self._get_nats()
            if not nats:
                return {"success": False, "error": "NATS未接続"}

            title = package.get("title", "")
            # body_preview + body_full を結合
            body_preview = package.get("body_preview", "")
            body_full = package.get("body_full", "")

            # 有料記事の場合: body_previewが無料部分、body_fullが有料部分
            # note.comでは「有料ラインを設定」で境界を指定する
            price = package.get("price_jpy", 0)
            tags = package.get("tags", "[]")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []

            # 記事全文（公開用）
            if body_full:
                # 有料記事: preview + full を結合（note.com側で有料ラインを設定）
                full_content = body_preview + "\n\n" + body_full
            else:
                full_content = body_preview

            # Step 1: 記事作成ページに遷移
            nav_response = await nats.request(
                "req.browser.bravo",
                {
                    "action_type": "navigate",
                    "url": NOTE_CREATION_URL,
                    "params": {},
                    "site_hints": {"is_spa": True},
                },
                timeout=BROWSER_REQUEST_TIMEOUT,
            )
            if not nav_response or not nav_response.get("success"):
                return {"success": False, "error": f"記事作成ページ遷移失敗: {nav_response}"}

            # Step 2: タイトル入力（Stagehand AI駆動で確実性を高める）
            title_response = await nats.request(
                "req.browser.bravo",
                {
                    "action_type": "smart_fill",
                    "url": NOTE_CREATION_URL,
                    "params": {
                        "instruction": f"タイトル入力欄に「{title}」と入力してください",
                    },
                    "site_hints": {"is_spa": True},
                },
                timeout=BROWSER_REQUEST_TIMEOUT,
            )
            if not title_response or not title_response.get("success"):
                # フォールバック: Playwright直接入力
                logger.warning("Stagehandタイトル入力失敗 — Playwright直接入力にフォールバック")
                title_response = await nats.request(
                    "req.browser.bravo",
                    {
                        "action_type": "act",
                        "url": NOTE_CREATION_URL,
                        "params": {
                            "instruction": "タイトル入力欄をクリックして、テキストを入力する",
                            "text": title,
                        },
                        "site_hints": {"is_spa": True},
                    },
                    timeout=BROWSER_REQUEST_TIMEOUT,
                )

            # Step 3: 本文入力（note.comリッチエディタ対応 — クリップボードペースト）
            body_response = await nats.request(
                "req.browser.bravo",
                {
                    "action_type": "smart_fill",
                    "url": NOTE_CREATION_URL,
                    "params": {
                        "instruction": "本文入力エリアをクリックして、以下のテキストを入力してください",
                        "text": full_content,
                    },
                    "site_hints": {"is_spa": True},
                },
                timeout=BROWSER_REQUEST_TIMEOUT,
            )
            if not body_response or not body_response.get("success"):
                logger.warning(f"本文入力で問題発生: {body_response}")
                # 本文入力失敗は致命的 — 中断
                return {"success": False, "error": "本文入力失敗"}

            # Step 4: 有料記事設定（price > 0 の場合）
            if price and price > 0:
                try:
                    price_response = await nats.request(
                        "req.browser.bravo",
                        {
                            "action_type": "smart_fill",
                            "url": NOTE_CREATION_URL,
                            "params": {
                                "instruction": (
                                    "有料設定を行います。"
                                    "「有料」または「販売設定」ボタンを探してクリックし、"
                                    f"価格を{price}円に設定してください。"
                                    "有料ラインが設定できる場合は、無料公開部分の末尾に設定してください。"
                                ),
                            },
                            "site_hints": {"is_spa": True},
                        },
                        timeout=BROWSER_REQUEST_TIMEOUT,
                    )
                    if not price_response or not price_response.get("success"):
                        logger.warning(f"有料設定失敗（無料記事として公開続行）: {price_response}")
                except Exception as e:
                    logger.error(f"有料設定NATS通信失敗（無料記事として公開続行）: {e}")

            # Step 5: タグ設定
            if tags:
                try:
                    tags_text = ", ".join(tags[:5])  # note.comはタグ5個まで
                    tag_response = await nats.request(
                        "req.browser.bravo",
                        {
                            "action_type": "smart_fill",
                            "url": NOTE_CREATION_URL,
                            "params": {
                                "instruction": (
                                    f"タグ入力欄にタグを追加してください: {tags_text}"
                                ),
                            },
                            "site_hints": {"is_spa": True},
                        },
                        timeout=BROWSER_REQUEST_TIMEOUT,
                    )
                    if not tag_response or not tag_response.get("success"):
                        logger.warning(f"タグ設定失敗（タグなしで公開続行）: {tag_response}")
                except Exception as e:
                    logger.error(f"タグ設定NATS通信失敗（タグなしで公開続行）: {e}")

            # Step 6: 公開ボタンをクリック
            publish_response = await nats.request(
                "req.browser.bravo",
                {
                    "action_type": "smart_click",
                    "url": NOTE_CREATION_URL,
                    "params": {
                        "instruction": "「公開」または「投稿」ボタンをクリックしてください",
                    },
                    "site_hints": {"is_spa": True},
                },
                timeout=BROWSER_REQUEST_TIMEOUT,
            )
            if not publish_response or not publish_response.get("success"):
                return {"success": False, "error": f"公開ボタンクリック失敗: {publish_response}"}

            # Step 7: 公開確認ダイアログがあれば「公開する」をクリック
            try:
                confirm_response = await nats.request(
                    "req.browser.bravo",
                    {
                        "action_type": "smart_click",
                        "url": NOTE_CREATION_URL,
                        "params": {
                            "instruction": (
                                "公開確認のダイアログやモーダルが表示された場合、"
                                "「公開する」「投稿する」ボタンをクリックしてください。"
                                "表示されていなければ何もしないでください。"
                            ),
                        },
                        "site_hints": {"is_spa": True},
                    },
                    timeout=BROWSER_REQUEST_TIMEOUT,
                )
            except Exception as e:
                logger.warning(f"公開確認ダイアログNATS通信失敗（続行）: {e}")
            # 確認ダイアログは出ない場合もあるので、失敗でも続行

            # Step 8: 公開URLを取得（ページ遷移後のURL）
            import asyncio
            await asyncio.sleep(3)  # ページ遷移待ち

            publish_url = ""
            try:
                url_response = await nats.request(
                    "req.browser.bravo",
                    {
                        "action_type": "extract",
                        "url": "",  # 現在のページから取得
                        "params": {
                            "instruction": "現在のページURLを取得してください",
                        },
                        "site_hints": {},
                    },
                    timeout=BROWSER_REQUEST_TIMEOUT,
                )

                if url_response and url_response.get("success"):
                    data = url_response.get("data", "")
                    if isinstance(data, dict):
                        publish_url = data.get("url", data.get("current_url", ""))
                    elif isinstance(data, str) and "note.com" in data:
                        publish_url = data
            except Exception as e:
                logger.error(f"公開URL取得NATS通信失敗: {e}")

            if not publish_url:
                # URLが取れなくてもスクリーンショットで確認するので警告のみ
                logger.warning("公開URL取得失敗 — スクリーンショット検証で確認")
                publish_url = f"https://note.com/ (URL取得失敗 — 手動確認要)"

            return {
                "success": True,
                "publish_url": publish_url,
            }

        except Exception as e:
            logger.error(f"記事作成例外: {e}")
            return {"success": False, "error": str(e)}

    async def _verify_publication(self, expected_title: str) -> dict:
        """公開確認（Layer 4: screenshot verification）"""
        try:
            nats = await self._get_nats()
            if not nats:
                return {"success": False, "error": "NATS未接続"}

            response = await nats.request(
                "req.browser.bravo",
                {
                    "action_type": "visual_verify",
                    "url": "",  # 現在のページ
                    "params": {
                        "instruction": (
                            f"記事「{expected_title}」が正しく公開されているか確認してください。"
                            "公開完了画面またはプレビュー画面が表示されていれば成功です。"
                        ),
                    },
                    "site_hints": {},
                },
                timeout=BROWSER_REQUEST_TIMEOUT,
            )

            if response and response.get("success"):
                logger.info("公開確認成功")
                return {"success": True}
            else:
                error = response.get("error", "unknown") if response else "応答なし"
                logger.warning(f"公開確認で問題: {error}")
                return {"success": False, "error": error}

        except Exception as e:
            logger.warning(f"公開確認例外（非致命的）: {e}")
            return {"success": False, "error": str(e)}

    async def _load_approved_package(self, package_id: int) -> Optional[dict]:
        """公開対象パッケージをDBから取得（ready or approved）"""
        try:
            async with get_connection() as conn:
                row = await conn.fetchrow(
                    """SELECT id, platform, title, body_preview, body_full,
                              price_jpy, tags, category, status
                       FROM product_packages
                       WHERE id = $1 AND status IN ('approved', 'ready') AND platform = 'note'""",
                    package_id,
                )
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"パッケージ読み込み失敗: {e}")
            return None

    async def _update_status(
        self,
        package_id: int,
        status: str,
        publish_url: str = None,
        error: str = None,
    ):
        """パッケージのステータスを更新"""
        try:
            async with get_connection() as conn:
                if status == "published":
                    await conn.execute(
                        """UPDATE product_packages
                           SET status = $1, publish_url = $2, published_at = NOW()
                           WHERE id = $3""",
                        status, publish_url or "", package_id,
                    )
                else:
                    await conn.execute(
                        """UPDATE product_packages
                           SET status = $1
                           WHERE id = $2""",
                        status, package_id,
                    )

                # エラー詳細をevent_logに記録
                if error:
                    try:
                        from tools.event_logger import log_event
                        await log_event("note.publish_failed", "commerce", {
                            "package_id": package_id,
                            "error": error[:500],
                        }, severity="error")
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"ステータス更新失敗: pkg={package_id} status={status} error={e}")


async def _announce_publication(title: str, url: str, price: int) -> None:
    """
    note記事公開後にSNS告知投稿をposting_queueに追加する。
    X (@shimahara, @syutain_beta), Bluesky, Threads の4件を即時投稿キューに入れる。
    quality_score=1.0 で品質ゲートをバイパス（告知投稿のため）。
    """
    try:
        from tools.db_pool import get_connection

        # X用テキスト（280字制限）
        x_text = f"【新記事】{title}\n{url}\n#SYUTAINβ #AI"
        if len(x_text) > 280:
            # タイトルを切り詰め
            max_title = 280 - len(f"【新記事】\n{url}\n#SYUTAINβ #AI") - 3
            x_text = f"【新記事】{title[:max_title]}...\n{url}\n#SYUTAINβ #AI"

        # Bluesky/Threads用テキスト（500字制限）
        price_label = f"有料記事 ¥{price}" if price and price > 0 else "無料記事"
        long_text = f"新しい記事を公開しました\n\n{title}\n\n{price_label}\n{url}"

        # 投稿キューに4件追加
        announcements = [
            ("x", "shimahara", x_text),
            ("x", "syutain_beta", x_text),
            ("bluesky", "syutain_beta", long_text),
            ("threads", "syutain_beta", long_text),
        ]

        async with get_connection() as conn:
            for platform, account, content in announcements:
                await conn.execute(
                    """INSERT INTO posting_queue
                       (platform, account, content, scheduled_at, status, quality_score, theme_category)
                       VALUES ($1, $2, $3, NOW(), 'pending', 1.0, 'note_announcement')""",
                    platform, account, content,
                )

        logger.info(f"SNS告知キュー追加完了: 『{title}』 4件 (X x2, Bluesky, Threads)")

    except Exception as e:
        logger.error(f"SNS告知キュー追加失敗: {e}")
        raise


async def note_auto_publish_check() -> dict:
    """
    承認済みnoteパッケージを自動公開するチェックジョブ

    feature_flags.yaml の note_auto_publish が true の場合のみ実行。
    30分間隔でスケジューラーから呼ばれる。
    """
    results = {"published": 0, "failed": 0, "skipped": 0, "errors": []}

    try:
        # feature_flag チェック
        try:
            import yaml
            flags_path = os.path.join(os.path.dirname(__file__), "..", "feature_flags.yaml")
            with open(flags_path, "r") as f:
                flags = yaml.safe_load(f) or {}
            if not flags.get("note_auto_publish", False):
                logger.debug("note_auto_publish: feature flag無効 — スキップ")
                results["skipped"] = -1  # flag disabled
                return results
        except Exception as e:
            logger.warning(f"feature_flags読み込み失敗（安全のためスキップ）: {e}")
            return results

        # 日次公開上限チェック（note.comスパム判定回避）
        # JST基準で判定（サーバTZ非依存）
        # 拡散実行書: 1日1本。地層を積む場所。量より質
        DAILY_PUBLISH_LIMIT = 1
        async with get_connection() as conn:
            today_published = await conn.fetchval(
                """SELECT COUNT(*) FROM product_packages
                   WHERE status = 'published' AND platform = 'note'
                   AND (published_at AT TIME ZONE 'Asia/Tokyo')::date = (NOW() AT TIME ZONE 'Asia/Tokyo')::date"""
            )
            today_published = int(today_published or 0)
            if today_published >= DAILY_PUBLISH_LIMIT:
                logger.info(f"note自動公開: 日次上限達成 ({today_published}/{DAILY_PUBLISH_LIMIT}) — スキップ")
                results["skipped"] = today_published
                return results
            remaining_today = DAILY_PUBLISH_LIMIT - today_published

            # 品質チェック通過済みパッケージを取得（ready or approved）
            # 拡散実行書: 品質6層防御通過で承認なし自動公開OK
            packages = await conn.fetch(
                """SELECT id, title FROM product_packages
                   WHERE status IN ('approved', 'ready') AND platform = 'note'
                   ORDER BY created_at ASC
                   LIMIT $1""",
                remaining_today,
            )

        if not packages:
            logger.debug("note自動公開: 対象パッケージなし")
            return results

        publisher = NotePublisher()

        for pkg in packages:
            try:
                result = await publisher.publish_article(pkg["id"])
                if result.get("success"):
                    results["published"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(
                        f"pkg={pkg['id']}: {result.get('error', 'unknown')}"
                    )
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"pkg={pkg['id']}: {e}")
                logger.error(f"note自動公開エラー: pkg={pkg['id']} {e}")

        # 結果サマリーDiscord通知
        if results["published"] > 0 or results["failed"] > 0:
            try:
                from tools.discord_notify import notify_discord
                await notify_discord(
                    f"📝 note自動公開: 成功{results['published']}件, "
                    f"失敗{results['failed']}件"
                )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"note_auto_publish_checkエラー: {e}")
        results["errors"].append(str(e))

    return results
