#!/usr/bin/env python3
"""
note.com記事公開スクリプト（Playwright直接実行）
BRAVOで実行される。ALPHAからSSH経由で呼び出し。

Usage:
    python3 note_publish_playwright.py --title "記事タイトル" --body-file /path/to/body.md --price 980

Environment:
    NOTE_EMAIL, NOTE_PASSWORD from .env
"""
import os
import sys
import json
import argparse
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

NOTE_EMAIL = os.getenv("NOTE_EMAIL", "")
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "")


async def publish_article(title: str, body: str, price: int = 0, tags: list = None):
    """Playwrightでnote.comに記事を公開する"""
    from playwright.async_api import async_playwright

    result = {"success": False, "url": "", "error": ""}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0"
        )
        page = await context.new_page()

        try:
            # 1. ログインページ
            print("[1/6] ログインページに遷移...")
            await page.goto("https://note.com/login", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # 2. メールアドレス入力
            print("[2/6] メールアドレス入力...")
            email_selectors = [
                'input[name="login"]',
                'input[type="email"]',
                'input[placeholder*="メール"]',
                'input[name="email"]',
                '#email',
            ]
            email_filled = False
            for sel in email_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.fill(NOTE_EMAIL)
                        email_filled = True
                        print(f"  → セレクタ '{sel}' で入力成功")
                        break
                except Exception:
                    continue
            if not email_filled:
                # フォールバック: 最初のinputに入力
                inputs = page.locator('input[type="text"], input[type="email"]')
                count = await inputs.count()
                if count > 0:
                    await inputs.first.fill(NOTE_EMAIL)
                    email_filled = True
                    print("  → フォールバック: 最初のinputに入力")
            if not email_filled:
                result["error"] = "メールアドレス入力フィールドが見つからない"
                return result

            # 3. パスワード入力
            print("[3/6] パスワード入力...")
            pw_el = page.locator('input[type="password"]').first
            await pw_el.fill(NOTE_PASSWORD)

            # 4. ログインボタンクリック
            print("[4/6] ログインボタンクリック...")
            btn_selectors = [
                'button[type="submit"]',
                'button:has-text("ログイン")',
                'input[type="submit"]',
                'button:has-text("Login")',
            ]
            clicked = False
            for sel in btn_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        clicked = True
                        print(f"  → セレクタ '{sel}' でクリック成功")
                        break
                except Exception:
                    continue
            if not clicked:
                result["error"] = "ログインボタンが見つからない"
                return result

            await asyncio.sleep(4)  # ログイン処理待ち

            # ログイン確認
            current_url = page.url
            if "login" in current_url.lower():
                # スクリーンショットを保存してデバッグ
                ss_path = "/tmp/note_login_fail.png"
                await page.screenshot(path=ss_path)
                result["error"] = f"ログインに失敗（URL: {current_url}）。スクリーンショット: {ss_path}"
                return result

            print(f"  → ログイン成功 (URL: {current_url[:50]})")

            # 5. 記事作成ページに遷移
            print("[5/6] 記事作成...")
            await page.goto("https://note.com/new", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # タイトル入力
            title_selectors = [
                'textarea[placeholder*="タイトル"]',
                'input[placeholder*="タイトル"]',
                '[data-testid="title-input"]',
                '.note-title textarea',
                'textarea:first-of-type',
            ]
            for sel in title_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.fill(title)
                        print(f"  → タイトル入力: '{sel}'")
                        break
                except Exception:
                    continue

            await asyncio.sleep(1)

            # 本文入力（note.comのエディタはcontenteditable div）
            body_selectors = [
                '[contenteditable="true"]',
                '.ProseMirror',
                '[data-testid="body-editor"]',
                '.note-body',
            ]
            for sel in body_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        # クリップボード経由で貼り付け（大量テキスト対応）
                        await page.evaluate(f"navigator.clipboard.writeText({json.dumps(body)})")
                        await page.keyboard.press("Control+a")
                        await page.keyboard.press("Control+v")
                        print(f"  → 本文入力: '{sel}' ({len(body)}文字)")
                        break
                except Exception:
                    # フォールバック: キーボード入力
                    try:
                        el = page.locator(sel).first
                        await el.click()
                        await el.type(body[:5000], delay=5)  # 遅延入力（5000文字まで）
                        print(f"  → 本文入力(タイプ): '{sel}'")
                        break
                    except Exception:
                        continue

            await asyncio.sleep(2)

            # 6. 公開（3段階: 公開ボタン → 公開設定 → 投稿する）
            print("[6/6] 記事公開...")

            # デバッグ用スクリーンショット（公開前）
            try:
                await page.screenshot(path="/tmp/note_before_publish.png")
            except Exception:
                pass

            # Step 6a: 最初の「公開」ボタンをクリック
            publish_btn_selectors = [
                'button:has-text("公開")',
                'button:has-text("投稿")',
                '[data-testid="publish-button"]',
            ]
            first_click = False
            for sel in publish_btn_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=3000):
                        await btn.click()
                        print(f"  → 公開ボタン: '{sel}'")
                        first_click = True
                        break
                except Exception:
                    continue

            if first_click:
                await asyncio.sleep(3)  # 確認ダイアログ/設定画面表示待ち

                # デバッグ: 公開ボタン押下後の画面
                try:
                    await page.screenshot(path="/tmp/note_after_publish_btn.png")
                    print("  → スクリーンショット保存: /tmp/note_after_publish_btn.png")
                except Exception:
                    pass

                # Step 6b: 公開設定画面で「無料」を選択（表示されてる場合）
                free_selectors = [
                    'label:has-text("無料")',
                    'input[value="free"]',
                    'button:has-text("無料")',
                    '[data-testid="free-option"]',
                ]
                for sel in free_selectors:
                    try:
                        el = page.locator(sel).first
                        if await el.is_visible(timeout=1500):
                            await el.click()
                            print(f"  → 無料設定: '{sel}'")
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        continue

                # Step 6c: 公開設定画面の「投稿する」ボタン + 確認ダイアログ
                confirm_selectors = [
                    # ヘッダー右上の「投稿する」ボタン（公開設定画面）
                    'button:has-text("投稿する")',
                    'button:has-text("公開する")',
                    # ヘッダー/ナビ内のボタン
                    'header button:has-text("投稿")',
                    'nav button:has-text("投稿")',
                    '[class*="header"] button:has-text("投稿")',
                    # ダイアログ内の公開ボタン
                    'button:has-text("OK")',
                    'button:has-text("はい")',
                    'dialog button:has-text("公開")',
                    '[role="dialog"] button:has-text("公開")',
                    '.modal button:has-text("公開")',
                ]
                for sel in confirm_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=3000):
                            await btn.click()
                            print(f"  → 確認: '{sel}'")
                            await asyncio.sleep(3)
                            break
                    except Exception:
                        continue

                # 有料設定が必要な場合（価格 > 0）
                if price and price > 0:
                    try:
                        price_input = page.locator('input[name="price"], input[type="number"]').first
                        if await price_input.is_visible(timeout=2000):
                            await price_input.fill(str(price))
                            print(f"  → 価格設定: ¥{price}")
                            # 再度公開ボタン
                            for sel in confirm_selectors[:3]:
                                try:
                                    btn = page.locator(sel).first
                                    if await btn.is_visible(timeout=2000):
                                        await btn.click()
                                        print(f"  → 最終公開: '{sel}'")
                                        await asyncio.sleep(3)
                                        break
                                except Exception:
                                    continue
                    except Exception:
                        pass
            else:
                # 公開ボタンが見つからない場合は下書き保存
                print("  ⚠ 公開ボタンが見つからない → 下書き保存にフォールバック")
                try:
                    draft_btn = page.locator('button:has-text("下書き保存")').first
                    if await draft_btn.is_visible(timeout=3000):
                        await draft_btn.click()
                        await asyncio.sleep(2)
                except Exception:
                    pass

            await asyncio.sleep(2)

            # スクリーンショット保存（デバッグ用）
            try:
                await page.screenshot(path="/tmp/note_publish_result.png")
            except Exception:
                pass

            # 公開後の最終確認
            await asyncio.sleep(3)
            final_url = page.url

            # デバッグ: 最終画面
            try:
                await page.screenshot(path="/tmp/note_final_result.png")
                print(f"  → 最終スクリーンショット: /tmp/note_final_result.png")
            except Exception:
                pass

            # === 公開成功の判定（3段階） ===
            import re as _re

            # 判定1: ページ内テキストで「記事が公開されました」を検出
            has_publish_success_text = False
            try:
                page_text = await page.inner_text("body")
                has_publish_success_text = "記事が公開されました" in page_text
                if has_publish_success_text:
                    print("  → 「記事が公開されました」テキスト検出 ✓")
            except Exception:
                pass

            # 判定2: URLが公開URLか
            is_published_url = bool(_re.match(r'https://note\.com/[^/]+/n/[a-z0-9]+', final_url))
            is_editor_url = "editor.note.com" in final_url or "/edit/" in final_url or "/publish/" in final_url

            # まだエディタで、成功テキストもない場合は再試行
            if is_editor_url and not has_publish_success_text:
                print(f"  ⚠ エディタ画面のまま: {final_url}")
                print("  → 公開ボタン再試行...")
                retry_selectors = [
                    'button:has-text("投稿する")',
                    'button:has-text("公開する")',
                    'header button:has-text("投稿")',
                    '[role="dialog"] button:has-text("公開")',
                    'button:has-text("公開")',
                ]
                retry_clicked = False
                for sel in retry_selectors:
                    if retry_clicked:
                        break
                    try:
                        btns = page.locator(sel)
                        count = await btns.count()
                        for i in range(count):
                            btn = btns.nth(i)
                            if await btn.is_visible(timeout=1000):
                                text = await btn.text_content()
                                print(f"  → 再試行クリック: '{text}' ({sel})")
                                await btn.click()
                                await asyncio.sleep(5)
                                retry_clicked = True
                                break
                    except Exception:
                        continue

                await asyncio.sleep(3)
                try:
                    page_text2 = await page.inner_text("body")
                    if "記事が公開されました" in page_text2:
                        has_publish_success_text = True
                        print("  → 再試行後「記事が公開されました」テキスト検出 ✓")
                except Exception:
                    pass
                final_url = page.url
                is_published_url = bool(_re.match(r'https://note\.com/[^/]+/n/[a-z0-9]+', final_url))

                try:
                    await page.screenshot(path="/tmp/note_retry_result.png")
                except Exception:
                    pass

            # === 判定3（最終確認）: マイページに遷移して記事の存在を確認 ===
            verified_url = ""
            if is_published_url or has_publish_success_text:
                # note IDを取得（URLまたはエディタURLから）
                note_id = ""
                if is_published_url:
                    m = _re.search(r'/n/([a-z0-9]+)', final_url)
                    note_id = m.group(1) if m else ""
                else:
                    m = _re.search(r'/notes/([a-z0-9]+)', final_url)
                    note_id = m.group(1) if m else ""

                if note_id:
                    # マイページの記事一覧から公開されているか確認
                    print(f"  → マイページで公開確認中... (note_id: {note_id})")
                    try:
                        await page.goto("https://note.com/5070", wait_until="networkidle", timeout=15000)
                        await asyncio.sleep(2)
                        # マイページのHTML内にnote_idが含まれるか
                        mypage_html = await page.content()
                        if note_id in mypage_html:
                            verified_url = f"https://note.com/5070/n/{note_id}"
                            print(f"  → マイページで記事確認成功 ✓: {verified_url}")
                        else:
                            print(f"  ⚠ マイページでnote_id '{note_id}' が見つからず")
                            # 直接URLにアクセスして確認
                            test_url = f"https://note.com/5070/n/{note_id}"
                            try:
                                resp = await page.goto(test_url, wait_until="domcontentloaded", timeout=10000)
                                if resp and resp.status == 200:
                                    verified_url = test_url
                                    print(f"  → 直接URL確認成功 ✓: {verified_url}")
                                else:
                                    print(f"  ⚠ 直接URLアクセス: status={resp.status if resp else 'N/A'}")
                            except Exception as url_err:
                                print(f"  ⚠ 直接URLアクセス失敗: {url_err}")
                    except Exception as mypage_err:
                        print(f"  ⚠ マイページ確認失敗: {mypage_err}")
                        # フォールバック: note_idからURL構築
                        verified_url = f"https://note.com/5070/n/{note_id}"

                    try:
                        await page.screenshot(path="/tmp/note_verify_result.png")
                    except Exception:
                        pass

            # === 最終判定 ===
            if verified_url:
                result["success"] = True
                result["url"] = verified_url
                print(f"\n公開確認完了: {verified_url}")
            elif is_published_url:
                result["success"] = True
                result["url"] = final_url
                print(f"\n公開成功（URL確認）: {final_url}")
            elif has_publish_success_text:
                # テキストで成功確認だがURL取得できず
                note_id_match = _re.search(r'/notes/([a-z0-9]+)', final_url)
                if note_id_match:
                    constructed_url = f"https://note.com/5070/n/{note_id_match.group(1)}"
                    result["success"] = True
                    result["url"] = constructed_url
                    print(f"\n公開成功（テキスト検出、URL構築）: {constructed_url}")
                else:
                    result["success"] = True
                    result["url"] = final_url
                    result["warning"] = "公開成功だが正式URL未取得"
                    print(f"\n公開成功（テキスト検出）: {final_url}")
            else:
                result["success"] = False
                result["url"] = final_url
                result["error"] = f"公開を確認できませんでした: {final_url}"
                print(f"\n公開失敗: {final_url}")

        except Exception as e:
            result["error"] = str(e)
            try:
                await page.screenshot(path="/tmp/note_error.png")
            except Exception:
                pass
        finally:
            await browser.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="note.com記事公開")
    parser.add_argument("--title", required=True, help="記事タイトル")
    parser.add_argument("--body-file", required=True, help="本文ファイルパス")
    parser.add_argument("--price", type=int, default=0, help="価格（0=無料）")
    parser.add_argument("--tags", nargs="*", default=[], help="タグ")
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")

    result = asyncio.run(publish_article(
        title=args.title,
        body=body,
        price=args.price,
        tags=args.tags,
    ))

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
