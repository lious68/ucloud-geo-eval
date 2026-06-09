"""
本地 WebChat 评测脚本 — 本地跑浏览器，结果写入服务器

用法:
    python scripts/run_webchat_local.py ernie --server http://113.31.106.119
    python scripts/run_webchat_local.py ernie --server http://113.31.106.119 --categories "自然型,引导型"
    python scripts/run_webchat_local.py ernie --server http://113.31.106.119 --delay 10 --headless

说明:
    - 本地打开浏览器（默认有界面，可观察过程）
    - 每题答完后自动分析并记录结果
    - 全部完成后一次性 POST 到服务器
"""
import argparse
import asyncio
import json
import os
import sys
import time
import logging

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def fetch_questions_from_server(server_url: str, categories: list = None):
    """从服务器 API 获取题目列表"""
    import urllib.request

    url = f"{server_url}/api/questions?limit=999"
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read())
    questions = data.get("data", [])

    if categories:
        questions = [q for q in questions if q.get("category") in categories]
    return questions


async def run_webchat_eval(model_key: str, questions: list, delay: float = 10,
                           headless: bool = False):
    """本地运行 WebChat 评测"""
    from web_chat_clients import create_web_chat_client
    from analyzer import ResponseAnalyzer

    client = create_web_chat_client(model_key)
    if not client.is_configured:
        logger.error(f"{model_key} 未配置登录状态，请先运行 setup_webchat_auth_auto.py")
        return None

    # 初始化浏览器（本地默认有界面）
    client._headless = headless
    from playwright.async_api import async_playwright
    from web_chat_auth import load_auth_state

    auth_state = load_auth_state(model_key)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(
        storage_state=auth_state,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    client._playwright = pw
    client._browser = browser
    client._context = ctx
    client._page = await ctx.new_page()

    logger.info(f"浏览器已启动 (headless={headless})")

    analyzer = ResponseAnalyzer()
    results = []
    total = len(questions)

    for i, q in enumerate(questions):
        q_text = q["question"]
        q_preview = q_text[:40] + ("..." if len(q_text) > 40 else "")
        logger.info(f"[{i+1}/{total}] {q_preview}")

        # 发送问题
        resp = await client.chat(q_text)
        content = resp.get("content", "")
        error = resp.get("error")

        # 分析
        analysis = analyzer.analyze(
            question_id=q["id"],
            model_key=model_key,
            model_name=client.name,
            content=content,
            error=error,
        )

        result = {
            "question_id": q["id"],
            "model_key": model_key,
            "model_name": client.name,
            "ucloud_mentioned": analysis.ucloud_mentioned,
            "ucloud_mention_count": analysis.ucloud_mention_count,
            "ucloud_rank": analysis.ucloud_rank,
            "has_citation": analysis.has_citation,
            "citation_count": analysis.citation_count,
            "ucloud_recommended": analysis.ucloud_recommended,
            "recommendation_strength": analysis.ucloud_recommendation_strength,
            "sentiment_score": analysis.sentiment_score,
            "sentiment_label": analysis.sentiment_label,
            "position_weight": analysis.position_weight,
            "response_length": analysis.response_length,
            "raw_content": analysis.raw_content,
            "competitor_mentions": json.dumps({
                k: [{"keyword": m.keyword, "position": m.position} for m in v]
                for k, v in analysis.competitor_mentions.items()
            }),
            "error_message": analysis.error_message,
            "citations": json.dumps([{
                "citation_type": c.citation_type, "content": c.content,
                "position": c.position, "source_channel": c.source_channel,
                "is_ucloud": c.is_ucloud
            } for c in analysis.citations]),
            "all_cited_urls": json.dumps([{
                "citation_type": c.citation_type, "content": c.content,
                "position": c.position, "source_channel": c.source_channel,
                "is_ucloud": c.is_ucloud
            } for c in analysis.all_cited_urls]),
        }
        results.append(result)

        # 简报
        mention = "✓提及" if analysis.ucloud_mentioned else "✗未提及"
        cite = f"引{analysis.citation_count}" if analysis.has_citation else ""
        logger.info(f"  → {mention} {cite} 长度={analysis.response_length}")

        # 延迟
        if delay > 0 and i < total - 1:
            logger.info(f"  等待 {delay}s...")
            await asyncio.sleep(delay)

    # 关闭浏览器
    await client.close()
    logger.info("浏览器已关闭")

    return results


def upload_results(server_url: str, model_key: str, results: list,
                   eval_name: str = "GEO评估", mode: str = "webchat"):
    """将结果上传到服务器"""
    import urllib.request

    payload = {
        "name": eval_name,
        "model_key": model_key,
        "mode": mode,
        "results": results,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/evaluations/import/results",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    return result


async def main():
    parser = argparse.ArgumentParser(description="本地 WebChat 评测 → 写入服务器")
    parser.add_argument("model_key", help="模型标识: ernie / kimi / deepseek / qwen / doubao")
    parser.add_argument("--server", default="http://113.31.106.119", help="服务器地址")
    parser.add_argument("--name", default="GEO评估", help="评测名称")
    parser.add_argument("--categories", default=None, help="品类筛选，逗号分隔")
    parser.add_argument("--delay", type=float, default=10, help="每题间隔秒数")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器）")
    args = parser.parse_args()

    # 解析品类
    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]

    # 获取题目
    logger.info(f"从服务器 {args.server} 获取题目...")
    questions = await fetch_questions_from_server(args.server, categories)
    if not questions:
        logger.error("没有可评测的题目")
        return
    logger.info(f"共 {len(questions)} 道题目")

    # 运行评测
    logger.info(f"开始 WebChat 评测: {args.model_key}")
    results = await run_webchat_eval(args.model_key, questions, args.delay, args.headless)
    if not results:
        logger.error("评测失败，无结果")
        return

    # 上传结果
    logger.info(f"上传 {len(results)} 条结果到服务器...")
    resp = upload_results(args.server, args.model_key, results, args.name)
    logger.info(f"上传完成! run_id={resp['data']['run_id']}, 完成={resp['data']['completed']} 题")
    logger.info(f"查看结果: {args.server}/history")


if __name__ == "__main__":
    asyncio.run(main())
