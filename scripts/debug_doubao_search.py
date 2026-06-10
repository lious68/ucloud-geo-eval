"""
调试豆包搜索元数据 — 用于抓取"搜索X个关键词 参考XX篇资料"的实际 DOM 结构

用法:
    python scripts/debug_doubao_search.py

说明:
    1. 启动浏览器并导航到豆包
    2. 发送一个测试问题
    3. 等待回答完成后截图 + 提取页面所有文本
    4. 保存调试信息到 output/debug_doubao_search.txt
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
    print("启动豆包客户端...")
    client = create_web_chat_client("doubao")

    ok = await client.initialize()
    if not ok:
        print("浏览器启动失败")
        return

    print("导航到聊天页面...")
    await client._navigate_to_chat(client._page)

    # 发送测试问题（关于云计算，应该触发搜索）
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
    screenshot_path = "output/doubao_search_debug.png"
    await page.screenshot(path=screenshot_path, full_page=True)
    print(f"截图已保存: {screenshot_path}")

    # 2. 提取页面全部文本（按行）
    all_text = await page.evaluate("() => document.body.innerText")
    with open("output/doubao_full_text.txt", "w", encoding="utf-8") as f:
        f.write(all_text)
    print(f"页面全文已保存: output/doubao_full_text.txt ({len(all_text)} 字)")

    # 3. 搜索元数据相关文本
    search_lines = [line for line in all_text.split("\n") if
                    any(kw in line for kw in ["搜索", "关键词", "参考", "资料", "来源", "引用", "篇"])]
    print("\n=== 搜索相关文本 ===")
    for line in search_lines:
        print(f"  {line.strip()}")

    # 4. 搜索元数据提取测试
    search_meta = await page.evaluate("""() => {
        const allText = document.body.innerText || '';
        const meta = { keyword_count: null, reference_count: null, keywords: [], citation_urls: [] };
        const keywordMatch = allText.match(/搜索\s*(\d+)\s*个?关键词/);
        if (keywordMatch) meta.keyword_count = parseInt(keywordMatch[1]);
        const refMatch = allText.match(/参考\s*(?:了)?\s*(\d+)\s*篇\s*(?:资料|来源|文献|文章)/);
        if (refMatch) meta.reference_count = parseInt(refMatch[1]);
        const allLinks = document.querySelectorAll('a[href]');
        allLinks.forEach(a => {
            const href = a.href || '';
            const text = (a.textContent || '').trim();
            if (href && !href.startsWith('javascript:') && !href.startsWith('#')
                && !href.includes('doubao.com') && !href.includes('bytedance.com')
                && href.startsWith('http')) {
                meta.citation_urls.push({ url: href, text: text });
            }
        });
        meta.citation_urls = meta.citation_urls.filter((v, i, a) => a.findIndex(t => t.url === v.url) === i);
        return meta;
    }""")
    print(f"\n=== 提取的搜索元数据 ===")
    print(json.dumps(search_meta, ensure_ascii=False, indent=2))

    # 5. 提取完整的响应区域 HTML（用于分析 DOM 结构）
    response_html = await page.evaluate("""() => {
        // 找到包含搜索关键词的父元素
        const allText = document.body.innerText || '';
        const searchMarkers = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
            acceptNode: (node) => {
                const t = node.textContent || '';
                if (t.includes('搜索') && t.includes('关键词')) return NodeFilter.FILTER_ACCEPT;
                if (t.includes('参考') && t.includes('篇')) return NodeFilter.FILTER_ACCEPT;
                return NodeFilter.FILTER_REJECT;
            }
        });
        let n;
        while (n = walker.nextNode()) {
            searchMarkers.push({
                tag: n.tagName,
                className: n.className,
                id: n.id,
                html: n.innerHTML.substring(0, 500),
                parentTag: n.parentElement?.tagName,
                parentClass: n.parentElement?.className,
            });
        }
        return searchMarkers;
    }""")
    print(f"\n=== 搜索元数据 DOM 元素 ===")
    print(json.dumps(response_html, ensure_ascii=False, indent=2))
    with open("output/doubao_search_dom.json", "w", encoding="utf-8") as f:
        json.dump(response_html, f, ensure_ascii=False, indent=2)
    print(f"DOM 结构已保存: output/doubao_search_dom.json")

    # 6. 提取完整响应文本
    response = await client._extract_response(client._page)
    with open("output/doubao_extracted_response.txt", "w", encoding="utf-8") as f:
        f.write(response)
    print(f"\n提取的响应已保存: output/doubao_extracted_response.txt ({len(response)} 字)")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
