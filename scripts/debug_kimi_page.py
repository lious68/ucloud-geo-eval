"""
Kimi 输入/发送/响应 完整链路测试 v2
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from playwright.async_api import async_playwright


async def main():
    os.environ["DISPLAY"] = ":0"
    print("启动浏览器...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = await ctx.new_page()
    os.makedirs("output", exist_ok=True)

    # 1. 导航
    print("1. 导航到 kimi.com")
    await page.goto("https://www.kimi.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    # 2. 输入问题
    print("2. 输入问题")
    input_el = page.locator('div.chat-input-editor, [contenteditable="true"]').first
    await input_el.click()
    await asyncio.sleep(0.5)
    await page.keyboard.type("UCloud海外云主机怎么样？", delay=30)
    await asyncio.sleep(1)

    # 验证输入成功
    content = await page.evaluate("""() => {
        const el = document.querySelector('[contenteditable="true"]');
        return el ? el.textContent : 'NOT FOUND';
    }""")
    print(f"   输入内容: '{content}'")
    await page.screenshot(path="output/kimi_v2_type.png")

    # 3. 找发送按钮 — 用安全的方式
    print("\n3. 查找发送按钮")
    send_info = await page.evaluate("""() => {
        const safeClass = (el) => {
            if (!el.className) return '';
            return typeof el.className === 'string' ? el.className : (el.className.baseVal || '');
        };
        // 找输入框附近的按钮
        const inputEl = document.querySelector('[contenteditable="true"]');
        if (!inputEl) return { error: 'no input' };
        const parent = inputEl.closest('form') || inputEl.parentElement?.parentElement || document.body;
        const allBtns = parent.querySelectorAll('button, [role="button"], img, svg');
        const results = [];
        allBtns.forEach(el => {
            const cls = safeClass(el).toLowerCase();
            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
            const visible = el.offsetParent !== null;
            const disabled = el.disabled === true || el.getAttribute('aria-disabled') === 'true';
            if (visible && (cls.includes('send') || aria.includes('send') || aria.includes('发送') || cls.includes('submit') || cls.includes('arrow') || cls.includes('up'))) {
                results.push({
                    tag: el.tagName,
                    class: safeClass(el).substring(0, 100),
                    aria: el.getAttribute('aria-label'),
                    disabled: disabled,
                    rect: (() => { const r = el.getBoundingClientRect(); return {x: r.x.toFixed(0), y: r.y.toFixed(0), w: r.width.toFixed(0), h: r.height.toFixed(0)}; })(),
                });
            }
        });
        return { buttons: results };
    }""")
    if "buttons" in send_info:
        print(f"   找到 {len(send_info['buttons'])} 个发送相关按钮")
        for b in send_info["buttons"]:
            print(f"   - {b['tag']} class='{b['class'][:50]}' aria='{b['aria']}' disabled={b['disabled']} rect={b['rect']}")

    # 4. 尝试发送
    print("\n4. 发送")
    sent = False

    # 方式A: 用 locator 找发送按钮
    try:
        send_locator = page.locator(
            'button[class*="send"]:not([disabled]), '
            '[role="button"][class*="send"]:not([disabled]), '
            'button[aria-label*="发送"]:not([disabled]), '
            '[aria-label="发送"]:not([disabled])'
        ).first
        if await send_locator.is_visible(timeout=3000):
            await send_locator.click()
            print("   方式A: 按钮点击成功")
            sent = True
    except Exception as e:
        print(f"   方式A: {e}")

    # 方式B: JS 点击
    if not sent:
        try:
            clicked = await page.evaluate("""() => {
                const safeClass = (el) => typeof el.className === 'string' ? el.className : '';
                const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
                for (const btn of btns) {
                    const cls = safeClass(btn).toLowerCase();
                    const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const visible = btn.offsetParent !== null;
                    const disabled = btn.disabled === true;
                    if (visible && !disabled && (cls.includes('send') || aria.includes('send') || aria.includes('发送'))) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                print("   方式B: JS点击成功")
                sent = True
        except Exception as e:
            print(f"   方式B: {e}")

    # 方式C: Enter 键
    if not sent:
        print("   方式C: Enter 键")
        await page.keyboard.press("Enter")
        sent = True

    await asyncio.sleep(2)
    await page.screenshot(path="output/kimi_v2_after_send.png")

    # 5. 等待响应
    print("\n5. 等待响应 (15秒)...")
    await asyncio.sleep(15)

    # 检查页面
    page_text = await page.evaluate("() => document.body.innerText")
    print(f"   页面文本: {len(page_text)} 字")
    print(f"   预览: {page_text[:500]}")

    # 检测响应区域
    resp_info = await page.evaluate("""() => {
        const safeClass = (el) => typeof el.className === 'string' ? el.className : '';
        const selectors = [
            '.segment-assistant', 'segment.segment-assistant',
            '.chat-content', '[class*="chat-content"]',
            '.conversation', '[class*="conversation"]',
            '.markdown', '[class*="markdown"]',
            'main', 'article', '[role="article"]'
        ];
        const result = {};
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            result[sel] = el ? {
                found: true, textLen: (el.innerText || '').length,
                tag: el.tagName, class: safeClass(el).substring(0, 80),
            } : { found: false };
        }
        return result;
    }""")
    print("\n   响应区域:")
    for sel, info in resp_info.items():
        if info["found"]:
            print(f"   ✅ {sel} → {info['textLen']}字 tag={info['tag']}")
        else:
            print(f"   ❌ {sel}")

    await page.screenshot(path="output/kimi_v2_response.png", full_page=True)

    await browser.close()
    await pw.stop()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(main())
