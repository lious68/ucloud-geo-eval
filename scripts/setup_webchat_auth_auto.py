"""
WebChat 登录认证设置脚本（自动检测版）
打开可见浏览器窗口让用户手动登录各 AI 模型官网，
自动检测登录成功（通过关键 cookie 出现判断），无需手动按 Enter。

使用方式:
    python scripts/setup_webchat_auth_auto.py deepseek    # 只设置 DeepSeek
    python scripts/setup_webchat_auth_auto.py all         # 设置所有指定的模型
"""
import asyncio
import sys
import os
import json
import time

# Windows UTF-8 输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from web_chat_auth import WEBCHAT_SITES, save_auth_state, ensure_auth_dir, AUTH_DIR

SUPPORTED_MODELS = ["deepseek", "ernie", "doubao", "kimi", "qwen"]

# 各平台的关键登录 cookie（检测到这些即视为已登录）
LOGIN_DETECT_COOKIES = {
    "deepseek": ["user_token", "token", "auth_token", "chat_token", "ds_token"],
    "ernie": ["BDUSS", "STOKEN", "BAIDUID"],
    "doubao": ["sessionid", "sid_tt"],
    "kimi": ["kimi-auth", "token", "access_token"],
    "qwen": ["tongyi_sso_ticket"],
}


async def setup_auth(model_key: str):
    """打开浏览器让用户手动登录，自动检测登录完成后保存"""
    from playwright.async_api import async_playwright

    site = WEBCHAT_SITES.get(model_key)
    if not site:
        print(f"[ERROR] Unknown model: {model_key}")
        return False

    detect_cookies = LOGIN_DETECT_COOKIES.get(model_key, [])
    print(f"\n{'='*50}")
    print(f"  Setting up {site['name']} ({site['url']}) login")
    print(f"  Opening browser - please log in manually")
    print(f"  Script will auto-detect login and save when cookies appear")
    print(f"{'='*50}\n")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)  # visible mode
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()

    # Navigate to login page
    await page.goto(site["url"], wait_until="domcontentloaded")
    print(f"  [OK] Browser opened: {site['url']}")
    print(f"  Please log in in the browser window...")
    print(f"  Detecting login cookies: {', '.join(detect_cookies[:3])}...")

    # Poll for login cookies every 3 seconds, up to 5 minutes
    max_wait = 300  # 5 minutes
    poll_interval = 3
    elapsed = 0
    logged_in = False

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        # Check current cookies
        cookies = await context.cookies()
        cookie_names = [c["name"] for c in cookies]

        # Check if any detect cookie is present
        matched = [name for name in detect_cookies if name in cookie_names]
        if matched:
            logged_in = True
            print(f"\n  [OK] Login detected! Found cookies: {', '.join(matched)}")
            # Wait a bit more for all cookies to settle
            await asyncio.sleep(3)
            break

        # Show progress
        remaining = max_wait - elapsed
        print(f"  ... waiting ({remaining}s remaining, {len(cookie_names)} cookies found)")

    if not logged_in:
        print(f"\n  [WARN] No login cookies detected after {max_wait}s. Saving current state anyway...")
        # Still save whatever we have, user might have logged in with unexpected cookies

    # Save auth state
    ensure_auth_dir()
    state = await context.storage_state()
    path = save_auth_state(model_key, state)

    cookie_count = len(state.get("cookies", []))
    all_cookie_names = [c["name"] for c in state.get("cookies", [])]
    # Show all cookies for this platform's domain
    site_domain = site["url"].split("//")[1].split("/")[0]
    relevant_cookies = [c["name"] for c in state.get("cookies", [])
                       if site_domain in c.get("domain", "") or c.get("domain", "").endswith(site_domain)]

    print(f"\n  [OK] Auth state saved!")
    print(f"  File: {path}")
    print(f"  Total cookies: {cookie_count}")
    print(f"  Site cookies ({site_domain}): {', '.join(relevant_cookies) if relevant_cookies else 'none'}")

    if logged_in:
        print(f"  Status: VALID (login confirmed)")
    else:
        print(f"  Status: UNKNOWN (no key cookie detected - may need manual verification)")

    await browser.close()
    await pw.stop()
    return logged_in


async def setup_multiple(models: list):
    """Set up multiple models sequentially"""
    print(f"\n[WebChat Login Auto Setup]")
    print(f"  Models to set up: {', '.join(models)}")
    print(f"  Each model will open a browser window for you to log in")
    print(f"  Login is auto-detected, no need to press Enter\n")

    results = {}
    for model_key in models:
        success = await setup_auth(model_key)
        results[model_key] = success

    print(f"\n{'='*50}")
    print(f"  Setup Summary")
    print(f"{'='*50}")
    for model_key, success in results.items():
        name = WEBCHAT_SITES.get(model_key, {}).get("name", model_key)
        status = "[OK] Valid" if success else "[??] Needs verification"
        print(f"  {name}: {status}")

    print(f"\n  Auth files saved in: {AUTH_DIR}")
    print(f"  Next step: upload these files to the server's Settings page")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/setup_webchat_auth_auto.py <model_key_or_all>")
        print(f"  Available models: {', '.join(SUPPORTED_MODELS)}, all")
        print("\nExamples:")
        print("  python scripts/setup_webchat_auth_auto.py deepseek")
        print("  python scripts/setup_webchat_auth_auto.py all")
        sys.exit(1)

    model_key = sys.argv[1].lower()

    if model_key == "all":
        asyncio.run(setup_multiple(SUPPORTED_MODELS))
    elif model_key == "remaining":
        # Only set up models that don't have valid auth yet
        from web_chat_auth import validate_auth_cookies
        remaining = []
        for mk in SUPPORTED_MODELS:
            v = validate_auth_cookies(mk)
            if not v["is_valid"]:
                remaining.append(mk)
        if not remaining:
            print("All models already have valid auth!")
        else:
            print(f"Models needing setup: {', '.join(remaining)}")
            asyncio.run(setup_multiple(remaining))
    else:
        asyncio.run(setup_auth(model_key))


if __name__ == "__main__":
    main()