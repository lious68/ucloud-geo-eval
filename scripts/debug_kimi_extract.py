"""
调试 Kimi 响应提取 — 精确找出 AI 回答所在的 DOM 元素

用法:
    python scripts/debug_kimi_extract.py
"""
import asyncio
import json
import os
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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

    # 发送测试问题
    question = "UCloud海外云主机怎么样？和AWS有什么区别？"
    print(f"发送问题: {question}")
    await client._type_question(client._page, question)
    await client._send_question(client._page)

    print("等待响应...")
    await client._wait_for_response(client._page, timeout=120)

    page = client._page
    os.makedirs("output", exist_ok=True)

    # 1. 列出页面上所有可能的消息容器
    print("\n=== 消息容器分析 ===")
    containers = await page.evaluate("""() => {
        const results = [];
        // 找所有可能包含消息的容器
        const selectors = [
            'segment.segment-assistant',
            '.segment-assistant',
            '[class*="message"]',
            '[class*="bubble"]',
            '[class*="answer"]',
            '[class*="response"]',
            '[class*="assistant"]',
            '[class*="ai-reply"]',
            '[class*="bot-message"]',
            '[class*="chat-message"]',
            '[role="article"]',
            '[class*="markdown"]',
            'main',
            'article',
        ];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.width < 100 || rect.height < 50) continue;
                const text = (el.innerText || '').substring(0, 200);
                results.push({
                    selector: sel,
                    tag: el.tagName,
                    class: (el.className || '').substring(0, 80),
                    id: el.id,
                    textLen: (el.innerText || '').length,
                    textPreview: text.replace(/\n/g, ' ').substring(0, 100),
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
                    childCount: el.children.length,
                });
            }
        }
        return results;
    }""")

    for c in containers:
        print(f"  [{c['selector']}] tag={c['tag']} class='{c['class'][:40]}' "
              f"pos=({c['rect']['x']},{c['rect']['y']}) size=({c['rect']['w']}x{c['rect']['h']}) "
              f"textLen={c['textLen']} preview='{c['textPreview']}'")

    # 2. 截图
    await page.screenshot(path="output/kimi_extract_analysis.png", full_page=True)
    print(f"\n截图已保存: output/kimi_extract_analysis.png")

    # 3. 分析页面布局（区分侧边栏 vs 主内容区）
    print("\n=== 页面布局分析 ===")
    layout = await page.evaluate("""() => {
        const info = { body: { w: document.body.scrollWidth, h: document.body.scrollHeight } };
        // 找侧边栏
        const sidebars = document.querySelectorAll(
            '[role="sidebar"], [class*="sidebar"], [class*="left-side"], [class*="leftPanel"], '
            '[class*="nav"], header, footer'
        );
        info.sidebars = [];
        sidebars.forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width > 50 && r.height > 50) {
                info.sidebars.push({
                    tag: el.tagName,
                    class: (el.className || '').substring(0, 60),
                    rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
                });
            }
        });
        // 找主内容区域（排除侧边栏）
        const main = document.querySelector('main, [role="main"], [class*="main-content"], [class*="content-area"]');
        if (main) {
            const r = main.getBoundingClientRect();
            info.main = {
                tag: main.tagName,
                class: (main.className || '').substring(0, 60),
                rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
                textLen: (main.innerText || '').length,
            };
        }
        return info;
    }""")
    print(json.dumps(layout, ensure_ascii=False, indent=2))

    # 4. 用改进的方法提取 — 只取右侧主内容区，排除侧边栏和footer
    print("\n=== 改进的提取方法 ===")
    improved = await page.evaluate("""() => {
        const bodyW = document.body.scrollWidth;
        // 策略：找页面右半部分的内容（侧边栏通常在左边）
        const candidates = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
            acceptNode: (node) => {
                const r = node.getBoundingClientRect();
                if (r.width < 200 || r.height < 50) return NodeFilter.FILTER_REJECT;
                // 只取右半屏的元素（x > body宽度的 25%）
                if (r.x < bodyW * 0.25) return NodeFilter.FILTER_REJECT;
                // 排除 header/footer
                const tag = node.tagName.toLowerCase();
                if (tag === 'header' || tag === 'footer') return NodeFilter.FILTER_REJECT;
                // 排除侧边栏相关
                const cls = (node.className || '').toLowerCase();
                if (cls.includes('sidebar') || cls.includes('left') || cls.includes('nav')) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        let n;
        while (n = walker.nextNode()) {
            const text = (n.innerText || '').trim();
            if (text.length > 100) {
                candidates.push({
                    tag: n.tagName,
                    class: (n.className || '').substring(0, 60),
                    textLen: text.length,
                    preview: text.substring(0, 150).replace(/\n/g, ' | '),
                });
            }
        }
        return candidates;
    }""")
    for c in improved[:10]:
        print(f"  [{c['tag']}.{c['class'][:30]}] len={c['textLen']} | {c['preview'][:100]}")

    # 5. 保存完整分析
    with open("output/kimi_extract_analysis.json", "w", encoding="utf-8") as f:
        json.dump({
            "containers": containers,
            "layout": layout,
            "improved_candidates": improved[:20],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n完整分析已保存: output/kimi_extract_analysis.json")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
