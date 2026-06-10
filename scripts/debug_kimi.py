"""
调试 Kimi 搜索元数据 — 用于抓取 Kimi 页面的实际 DOM 结构

用法:
    python scripts/debug_kimi.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client


async def debug():
    os.environ["DISPLAY"] = ":0"
    print("启动 Kimi 客户端...")
    client = create_web_chat_client("kimi")

    ok = await client.initialize()
    if not ok:
        print("浏览器启动失败")
        return

    print("导航到聊天页面...")
    await client._navigate_to_chat(client._page)

    # 打印当前 URL 和页面信息
    current_url = client._page.url
    print(f"当前 URL: {current_url}")
    page_title = await client._page.title()
    print(f"页面标题: {page_title}")

    # 列出页面上所有 contenteditable 和 button 元素（用于调试输入/发送）
    elements_info = await client._page.evaluate("""() => {
        const info = { contenteditable: [], buttons: [] };
        document.querySelectorAll('[contenteditable]').forEach(el => {
            info.contenteditable.push({
                tag: el.tagName,
                className: el.className,
                role: el.getAttribute('role'),
                text: (el.textContent || '').substring(0, 100),
                visible: el.offsetParent !== null,
            });
        });
        document.querySelectorAll('button, [role="button"]').forEach(el => {
            const cls = (el.className || '').toLowerCase();
            if (cls.includes('send') || cls.includes('submit') || el.textContent?.includes('发送') || el.getAttribute('aria-label')?.includes('send')) {
                info.buttons.push({
                    tag: el.tagName,
                    className: el.className,
                    ariaLabel: el.getAttribute('aria-label'),
                    text: (el.textContent || '').substring(0, 50),
                    disabled: el.disabled,
                    visible: el.offsetParent !== null,
                });
            }
        });
        return info;
    }""")
    print(f"\n=== contenteditable 元素 ===")
    for el in elements_info["contenteditable"]:
        print(f"  {el['tag']}.{el['className'][:50]} role={el['role']} visible={el['visible']} text='{el['text'][:50]}'")
    print(f"\n=== 发送相关按钮 ===")
    for el in elements_info["buttons"]:
        print(f"  {el['tag']} class='{el['className'][:50]}' aria='{el['ariaLabel']}' text='{el['text']}' disabled={el['disabled']} visible={el['visible']}")

    # 发送测试问题
    question = "UCloud海外云主机怎么样？和AWS有什么区别？"
    print(f"发送问题: {question}")
    await client._type_question(client._page, question)
    await client._send_question(client._page)

    # 等待响应
    print("等待响应...")
    await client._wait_for_response(client._page, timeout=120)

    page = client._page

    # 1. 截图
    os.makedirs("output", exist_ok=True)
    screenshot_path = "output/kimi_debug.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"截图已保存: {screenshot_path}")

    # 2. 提取页面全部文本
    all_text = await page.evaluate("() => document.body.innerText")
    with open("output/kimi_full_text.txt", "w", encoding="utf-8") as f:
        f.write(all_text)
    print(f"页面全文已保存: output/kimi_full_text.txt ({len(all_text)} 字)")

    # 3. 搜索相关文本
    search_lines = [line for line in all_text.split("\n") if
                    any(kw in line for kw in ["搜索", "引用", "参考", "来源", "联网"])]
    print("\n=== 搜索相关文本 ===")
    for line in search_lines[:20]:
        print(f"  {line.strip()}")

    # 4. 提取聊天区域 HTML 结构（用于调试选择器）
    dom_info = await page.evaluate("""() => {
        const info = {};
        // 检查各种可能的选择器
        for (const sel of [
            'segment.segment-assistant', '.segment-assistant',
            '.chat-content', '[class*="chat-content"]',
            '.conversation', '[class*="conversation"]',
            '.markdown-container', '[class*="markdown"]',
            'main', 'article'
        ]) {
            const el = document.querySelector(sel);
            info[sel] = el ? {
                found: true,
                textLen: (el.innerText || '').length,
                tag: el.tagName,
                className: el.className,
                innerHTML: (el.innerHTML || '').substring(0, 200)
            } : { found: false };
        }
        return info;
    }""")
    print(f"\n=== 选择器匹配情况 ===")
    for sel, data in dom_info.items():
        if data["found"]:
            print(f"  ✅ {sel} → textLen={data['textLen']} chars, tag={data['tag']}")
        else:
            print(f"  ❌ {sel} → 未找到")

    # 5. 提取响应
    response = await client._extract_response(client._page)
    with open("output/kimi_extracted_response.txt", "w", encoding="utf-8") as f:
        f.write(response)
    print(f"\n提取的响应: {len(response)} 字")
    print(response[:200])

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
