"""
诊断脚本：打开某模型官网，用户手动登录后，打印该站点实际写入的全部 cookie
（名称 / 域 / 是否 httpOnly / 过期），用于确认 setup_webchat_auth_auto.py 的
登录探测 cookie 列表是否覆盖了真实登录 cookie。

用法:
    python scripts/diag_webchat_cookies.py qwen
    # 浏览器打开后，手动登录；登录完成后回到终端按 Enter 打印 cookie 清单
"""
import asyncio
import sys
import os
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from web_chat_auth import WEBCHAT_SITES

SUPPORTED = list(WEBCHAT_SITES.keys())


async def main(model_key: str):
    from playwright.async_api import async_playwright

    site = WEBCHAT_SITES.get(model_key)
    if not site:
        print(f"[ERROR] 未知模型: {model_key}；可选: {', '.join(SUPPORTED)}")
        return

    auth_cookies = site.get("auth_cookies", [])
    auth_domains = site.get("auth_domains", [])
    print(f"\n=== 诊断 {site['name']} ({site['url']}) ===")
    print(f"auth_cookies(服务端校验用): {auth_cookies}")
    print(f"auth_domains: {auth_domains}")
    print("浏览器即将打开，请在窗口里登录；登录完成后回此终端按 Enter 打印 cookie。\n")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(channel="chrome", headless=False, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox",
        ])
    except Exception:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])

    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    try:
        await page.goto(site["url"], wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass

    # 后台每 3s 打印一次 cookie 概况，直到用户按 Enter
    async def poll():
        while True:
            await asyncio.sleep(3)
            try:
                ck = await context.cookies()
                names = sorted({c["name"] for c in ck})
                hit = [n for n in names if n in auth_cookies]
                print(f"  [poll] 共 {len(ck)} cookie；命中 auth_cookies: {hit or '无'}；url={page.url}")
            except Exception as e:
                print(f"  [poll] 读取 cookie 失败: {e}")

    poll_task = asyncio.create_task(poll())
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "  >>> 登录完成后按 Enter 打印完整 cookie 清单...\n")
    poll_task.cancel()

    ck = await context.cookies()
    print(f"\n=== 完整 cookie 清单（{len(ck)} 条）===")
    # 按域分组
    from collections import defaultdict
    byd = defaultdict(list)
    for c in ck:
        byd[c.get("domain", "")].append(c)
    for dom in sorted(byd):
        print(f"\n[域] {dom}")
        for c in sorted(byd[dom], key=lambda x: x.get("name", "")):
            name = c.get("name", "")
            exp = c.get("expires", -1)
            exp_s = "session" if exp == -1 else time.strftime("%Y-%m-%d %H:%M", time.localtime(exp)) if exp > 0 else str(exp)
            flag = "★AUTH" if name in auth_cookies else "      "
            print(f"  {flag} {name:32s} httpOnly={int(bool(c.get('httpOnly')))} expires={exp_s}")

    # 结论：哪些 auth_cookies 命中、哪些未命中
    present = {c["name"] for c in ck}
    matched = [n for n in auth_cookies if n in present]
    print(f"\n=== 结论 ===")
    print(f"命中的 auth_cookies: {matched or '无'}")
    print(f"未命中的 auth_cookies: {[n for n in auth_cookies if n not in present]}")
    if not matched:
        print("⚠️  服务端 auth_cookies 一个都没出现——说明校验列表本身可能不对，")
        print("    请把上面 ★AUTH 之外、疑似登录态的 cookie 名称告诉我，我据此修正。")
    else:
        print("✅ 至少一个 auth_cookies 出现；setup_webchat_auth_auto.py 的探测列表应包含这些。")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: python scripts/diag_webchat_cookies.py <{'|'.join(SUPPORTED)}>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1].lower()))
