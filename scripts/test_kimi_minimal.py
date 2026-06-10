"""
最小化测试 Kimi 完整链路 — 逐个方法排查
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from playwright.async_api import async_playwright


async def test():
    os.environ["DISPLAY"] = ":0"
    print("启动浏览器...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )

    # 尝试加载 auth state
    state_file = "data/webchat_auth/kimi_state.json"
    if os.path.exists(state_file):
        print(f"加载认证状态: {state_file}")
        with open(state_file, "r", encoding="utf-8") as f:
            import json
            state = json.load(f)
        await ctx.add_cookies(state.get("cookies", []))

    page = await ctx.new_page()
    os.makedirs("output", exist_ok=True)

    # Step 1: Navigate
    print("\n=== Step 1: 导航到 kimi.com ===")
    try:
        await page.goto("https://www.kimi.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        print(f"  URL: {page.url}")
        print(f"  Title: {await page.title()}")
        await page.screenshot(path="output/kimi_step1_navigate.png")
        print("  ✅ 导航成功")
    except Exception as e:
        print(f"  ❌ 导航失败: {e}")
        await browser.close()
        await pw.stop()
        return

    # Step 2: Find input box
    print("\n=== Step 2: 查找输入框 ===")
    for selector in ["div.chat-input-editor", "[contenteditable='true']", "[role='textbox']"]:
        try:
            box = page.locator(selector).first
            if await box.is_visible(timeout=5000):
                print(f"  ✅ 找到: {selector}")
                break
        except Exception:
            continue
    else:
        print("  ❌ 找不到输入框")
        await page.screenshot(path="output/kimi_step2_no_input.png")
        await browser.close()
        await pw.stop()
        return

    # Step 3: Type question
    print("\n=== Step 3: 输入问题 ===")
    question = "UCloud海外云主机怎么样？"
    try:
        input_box = page.locator("[contenteditable='true']").first
        await input_box.click()
        await asyncio.sleep(0.3)

        await page.evaluate("""(text) => {
            const el = document.querySelector('[contenteditable="true"]');
            if (el) {
                el.textContent = text;
                el.focus();
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new CompositionEvent('compositionend', { data: text }));
            }
        }""", question)
        await asyncio.sleep(0.5)

        # Verify
        content = await page.evaluate("""() => {
            const el = document.querySelector('[contenteditable="true"]');
            return el ? el.textContent : 'NOT FOUND';
        }""")
        print(f"  输入框内容: '{content}'")
        if content == question:
            print("  ✅ 输入成功")
        else:
            print(f"  ⚠️ 输入不匹配: expected='{question}', got='{content}'")
        await page.screenshot(path="output/kimi_step3_type.png")
    except Exception as e:
        print(f"  ❌ 输入失败: {e}")
        await browser.close()
        await pw.stop()
        return

    # Step 4: Send
    print("\n=== Step 4: 发送问题 ===")
    sent = False

    # Try JS button click
    try:
        clicked = await page.evaluate("""() => {
            const inputEl = document.querySelector('[contenteditable="true"]');
            if (!inputEl) return false;
            const parent = inputEl.closest('form') || inputEl.parentElement || document.body;
            const candidates = parent.querySelectorAll('button, [role="button"], div[role="button"], svg, img');
            for (const el of candidates) {
                const rect = el.getBoundingClientRect();
                if (rect.width < 10 || rect.height < 10) continue;
                const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                if (cls.includes('arrow') || cls.includes('send') || cls.includes('submit') ||
                    cls.includes('up') || aria.includes('send') || aria.includes('发送') ||
                    aria.includes('提交') || aria.includes('arrow')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            print("  ✅ JS 按钮点击成功")
            sent = True
        else:
            print("  ⚠️ 未找到匹配的发送按钮")
    except Exception as e:
        print(f"  ❌ JS 按钮点击失败: {e}")

    # Try Enter key
    if not sent:
        print("  尝试 Enter 键...")
        await page.keyboard.press("Enter")
        sent = True
        print("  ✅ Enter 键已发送")

    await asyncio.sleep(1)
    await page.screenshot(path="output/kimi_step4_send.png")

    # Step 5: Wait for response
    print("\n=== Step 5: 等待响应 (30秒) ===")
    for i in range(10):
        await asyncio.sleep(3)
        text_len = await page.evaluate("""() => {
            return (document.body.innerText || '').length;
        }""")
        print(f"  {i*3+3}s: 页面文本 {text_len} 字")
        if text_len > 200:
            break

    await page.screenshot(path="output/kimi_step5_response.png", full_page=True)

    # Step 6: Extract response
    print("\n=== Step 6: 提取响应 ===")

    # Try segment-assistant
    try:
        area = page.locator("segment.segment-assistant, .segment-assistant").last
        text = await area.inner_text()
        print(f"  segment-assistant: {len(text)} 字")
        if len(text) > 50:
            print(f"  预览: {text[:200]}")
    except Exception as e:
        print(f"  segment-assistant: 失败 ({e})")

    # Spatial extraction
    result = await page.evaluate("""() => {
        const bodyW = document.body.scrollWidth;
        const sidebarRight = bodyW * 0.28;

        let bestContainer = null;
        let bestScore = 0;

        const allDivs = document.querySelectorAll('div, article, main, section');
        for (const el of allDivs) {
            const r = el.getBoundingClientRect();
            if (r.x < sidebarRight) continue;
            if (r.width < bodyW * 0.4) continue;
            const text = (el.innerText || '').trim();
            if (text.length < 100) continue;
            const centerX = r.x + r.width / 2;
            const centerScore = 1 - Math.abs(centerX - bodyW * 0.6) / (bodyW * 0.4);
            const score = text.length * Math.max(0, centerScore);
            if (score > bestScore) {
                bestScore = score;
                bestContainer = el;
            }
        }

        if (!bestContainer) {
            for (const el of allDivs) {
                const r = el.getBoundingClientRect();
                if (r.x < sidebarRight * 0.8) continue;
                const text = (el.innerText || '').trim();
                if (text.length > 200 && el.children.length > 2) {
                    bestContainer = el;
                    break;
                }
            }
        }

        const container = bestContainer || document.body;
        const exclude = 'input, textarea, button, [role="navigation"], [role="menubar"], header, footer, script, style, noscript, link, meta';

        const texts = [];
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
            acceptNode: (node) => {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                if (parent.closest(exclude)) return NodeFilter.FILTER_REJECT;
                if (parent.closest('nav, [role="sidebar"], [class*="sidebar"], [class*="left-side"], [class*="leftPanel"], [class*="logo"], [class*="brand"], footer'))
                    return NodeFilter.FILTER_REJECT;
                const t = node.textContent.trim();
                if (t.length < 3) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        let n;
        while (n = walker.nextNode()) texts.push(n.textContent.trim());

        return {
            containerTag: container.tagName,
            containerClass: (container.className || '').substring(0, 80),
            text: texts.join('\n').trim(),
            textLen: texts.join('\n').trim().length,
            containerFound: bestContainer !== null,
        };
    }""")

    print(f"  容器: {result['containerTag']}.{result['containerClass'][:40]}")
    print(f"  找到专用容器: {result['containerFound']}")
    print(f"  提取文本: {result['textLen']} 字")
    print(f"  预览: {result['text'][:300]}")

    await browser.close()
    await pw.stop()
    print("\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(test())
