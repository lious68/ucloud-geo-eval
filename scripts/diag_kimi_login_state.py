"""
诊断 kimi 登录态信号：cookie + localStorage + DOM 登录按钮，登录前→后对比。

目的：找出"只在完整登录后才出现"的强信号，用于 _login_flow 的 _is_logged_in 探测。
kimi-auth cookie 登录中途就出现、输入框落地页就可见，都是弱信号；真实会话凭证
很可能在 localStorage。本脚本每 3s 打印 cookie/localStorage/URL/登录按钮可见性，
让用户看着登录前→后的翻转，定位强信号。

用法:
    python scripts/diag_kimi_login_state.py
    # 浏览器打开后手动登录；登录完成后回终端按 Enter 打印完整快照
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

URL = "https://www.kimi.com"


# 探测 DOM 上"登录入口"是否可见（登录前应可见，登录后应消失）
LOGIN_PROBE_JS = """() => {
    const out = {loginBtnVisible: false, loginBtnText: '', avatarVisible: false, bodyTextSample: ''};
    // 找含"登录/注册/sign in/login"的可点击元素
    const nodes = Array.from(document.querySelectorAll('a, button, [role="button"], div'));
    for (const n of nodes) {
        const t = ((n.textContent || '') + ' ' + (n.getAttribute('aria-label') || '')).trim().toLowerCase();
        const rect = n.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;
        if ((t.includes('登录') || t.includes('注册') || t.includes('sign in') || t.includes('log in') || t === 'login')
            && rect.top < 400) {
            out.loginBtnVisible = true;
            out.loginBtnText = (n.textContent || '').trim().slice(0, 20);
            break;
        }
    }
    // 头像/账号区（img[alt] 含 avatar、class 含 avatar/user）
    const av = document.querySelector('img[class*="avatar"], [class*="avatar"] img, [class*="user-info"], [class*="account"]');
    if (av) {
        const r = av.getBoundingClientRect();
        out.avatarVisible = r.width > 10 && r.height > 10;
    }
    out.bodyTextSample = (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 120);
    return out;
}"""


async def main():
    from playwright.async_api import async_playwright

    print(f"=== 诊断 kimi 登录态信号 ({URL}) ===")
    print("浏览器即将打开（全新 context，无登录态）。请在窗口里完整登录。")
    print("我会每 3s 打印 cookie/localStorage/URL/登录按钮，观察登录前→后的翻转。\n")

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
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass

    async def poll():
        i = 0
        while True:
            await asyncio.sleep(3)
            i += 1
            try:
                ck = await context.cookies()
                cnames = sorted({c["name"] for c in ck})
                ls = await page.evaluate("""() => {
                    const out = {};
                    for (let i=0;i<localStorage.length;i++){
                        const k = localStorage.key(i);
                        let v = localStorage.getItem(k) || '';
                        out[k] = v.length > 40 ? v.slice(0,40)+'...('+v.length+')' : v;
                    }
                    return out;
                }""")
                dom = await page.evaluate(LOGIN_PROBE_JS)
                print(f"  [{i}] url={page.url}")
                print(f"      cookies({len(ck)}): {cnames}")
                print(f"      localStorage keys: {list(ls.keys())}")
                print(f"      loginBtn={dom.get('loginBtnVisible')} ({dom.get('loginBtnText')!r}) avatar={dom.get('avatarVisible')}")
            except Exception as e:
                print(f"  [{i}] poll err: {e}")

    poll_task = asyncio.create_task(poll())
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "  >>> 登录完成后按 Enter 打印完整快照...\n")
    poll_task.cancel()

    # 完整快照
    ck = await context.cookies()
    ls = await page.evaluate("""() => {
        const out = {};
        for (let i=0;i<localStorage.length;i++){
            const k = localStorage.key(i);
            let v = localStorage.getItem(k) || '';
            out[k] = v.length > 80 ? v.slice(0,80)+'...('+v.length+' chars)' : v;
        }
        return out;
    }""")
    dom = await page.evaluate(LOGIN_PROBE_JS)
    state = await context.storage_state()

    print(f"\n=== 完整快照 ===")
    print(f"URL: {page.url}")
    print(f"cookies ({len(ck)}): {sorted(c['name'] for c in ck)}")
    print(f"\nlocalStorage ({len(ls)} keys):")
    for k in sorted(ls):
        print(f"  {k} = {ls[k]}")
    print(f"\nDOM: loginBtn={dom.get('loginBtnVisible')} ({dom.get('loginBtnText')!r}) avatar={dom.get('avatarVisible')}")
    print(f"     body sample: {dom.get('bodyTextSample')!r}")
    print(f"\nstorage_state origins ({len(state.get('origins', []))}):")
    for o in state.get("origins", []):
        print(f"  origin={o.get('origin')} localStorage_keys={list((o.get('localStorage') or {}).keys())}")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
