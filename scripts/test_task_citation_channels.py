"""task 级引用源聚合自检（TDD RED→GREEN）：
- GET /api/results/0/citation-channels?task_id=  跨批次聚合引用渠道
- GET /api/results/0/citation-drilldown?task_id=&source_channel=  按渠道下钻

镜像 scripts/test_task_drilldown.py：建 task → 建两批次 → 导入带 all_cited_urls/citations 的
analysis_results → 断言跨批次聚合的渠道计数 / sample_urls / url_type 分类 / model_key 过滤 /
下钻按渠道返回问题+URL / run_id 占位不校验 / 不存在渠道=空 / 不存在 task=空 / run 模式 404 保留。
"""
import asyncio
import os
import sys
import io
import tempfile
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())
    asyncio.run(_seed())

    import app as appmod
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/tasks", "/api/results"]
    from routers.auth import require_admin

    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop_admin

    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    # 建 task（题集 Q1..Q4）
    r = client.post("/api/tasks", json={"name": "CiteT", "categories": ["引导型", "对比词"]})
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["id"]

    # 批次 A：kimi 答 Q1（UCloud官网 + 知乎 各一条引用）
    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1"]}, "delay": 8})
    assert r.status_code == 200, r.text
    cfgA = r.json()["data"]
    payloadA = {"meta": {"task_id": task_id, "batch_id": cfgA["batch_id"], "run_id": cfgA["run_id"]},
                "questions": [],
                "analysis_results": {"kimi": [_mk_cited("Q1", "kimi", [
                    {"channel": "UCloud官网", "url": "https://ucloud.cn", "is_ucloud": True},
                    {"channel": "知乎", "url": "https://zhuanlan.zhihu.com/p/123", "is_ucloud": False},
                ])]}}
    r = client.post(f"/api/tasks/{task_id}/batches/{cfgA['batch_id']}/import-results",
                    files={"file": ("a.json", json.dumps(payloadA).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["data"]["results_inserted"] == 1, r.text

    # 批次 B：kimi 答 Q2（知乎）、Q3（UCloud官网，不同 URL）—— 与批次 A 不同题，验证跨批次聚合
    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q2", "Q3"]}, "delay": 8})
    assert r.status_code == 200, r.text
    cfgB = r.json()["data"]
    payloadB = {"meta": {"task_id": task_id, "batch_id": cfgB["batch_id"], "run_id": cfgB["run_id"]},
                "questions": [],
                "analysis_results": {"kimi": [
                    _mk_cited("Q2", "kimi", [{"channel": "知乎", "url": "https://zhuanlan.zhihu.com/p/456", "is_ucloud": False}]),
                    _mk_cited("Q3", "kimi", [{"channel": "UCloud官网", "url": "https://docs.ucloud.cn/api.html", "is_ucloud": True}]),
                ]}}
    r = client.post(f"/api/tasks/{task_id}/batches/{cfgB['batch_id']}/import-results",
                    files={"file": ("b.json", json.dumps(payloadB).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["data"]["results_inserted"] == 2, r.text

    # ── 1. citation-channels 跨批次聚合 ──
    r = client.get(f"/api/results/0/citation-channels?task_id={task_id}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "kimi" in data, f"kimi 应在结果中: {data}"
    channels = {c["channel"]: c for c in data["kimi"]["channels"]}
    assert "UCloud官网" in channels and "知乎" in channels, list(channels.keys())
    # UCloud官网：Q1（批次A）+ Q3（批次B）= 2
    assert channels["UCloud官网"]["count"] == 2, channels["UCloud官网"]["count"]
    # 知乎：Q1（批次A）+ Q2（批次B）= 2
    assert channels["知乎"]["count"] == 2, channels["知乎"]["count"]
    # question_details 跨批次聚合
    ucloud_qids = sorted(d["question_id"] for d in channels["UCloud官网"]["question_details"])
    assert ucloud_qids == ["Q1", "Q3"], ucloud_qids
    # sample_urls 含两条不同的 ucloud URL
    assert "https://ucloud.cn" in channels["UCloud官网"]["sample_urls"], channels["UCloud官网"]["sample_urls"]
    assert "https://docs.ucloud.cn/api.html" in channels["UCloud官网"]["sample_urls"], channels["UCloud官网"]["sample_urls"]
    # url_type 分类：知乎有具体路径 → "可能的信息来源"；ucloud.cn 首页级 → "AI生成的引用"
    zhihu_detail = next(d for d in channels["知乎"]["question_details"] if d["url"] == "https://zhuanlan.zhihu.com/p/123")
    assert zhihu_detail["url_type"] == "可能的信息来源", zhihu_detail["url_type"]
    ucloud_detail = next(d for d in channels["UCloud官网"]["question_details"] if d["url"] == "https://ucloud.cn")
    assert ucloud_detail["url_type"] == "AI生成的引用", ucloud_detail["url_type"]

    # ── 2. model_key 过滤：不存在的模型 → 空 ──
    r = client.get(f"/api/results/0/citation-channels?task_id={task_id}&model_key=ghost")
    assert r.status_code == 200 and r.json()["data"] == {}, r.text
    # 仅 kimi → 只 kimi
    r = client.get(f"/api/results/0/citation-channels?task_id={task_id}&model_key=kimi")
    assert r.status_code == 200 and list(r.json()["data"].keys()) == ["kimi"], r.text

    # ── 3. citation-drilldown 按渠道返回问题 + URL ──
    r = client.get(f"/api/results/0/citation-drilldown?source_channel=知乎&task_id={task_id}")
    assert r.status_code == 200, r.text
    ddata = r.json()["data"]
    assert "kimi" in ddata, ddata
    questions = ddata["kimi"]["questions"]
    assert len(questions) == 2, f"知乎应跨批次聚合 Q1+Q2=2 条: {[q['question_id'] for q in questions]}"
    qids = sorted(q["question_id"] for q in questions)
    assert qids == ["Q1", "Q2"], qids
    all_urls = [u["content"] for q in questions for u in q["urls"]]
    assert "https://zhuanlan.zhihu.com/p/123" in all_urls and "https://zhuanlan.zhihu.com/p/456" in all_urls, all_urls
    assert all(q["ucloud_mentioned"] is True for q in questions), "ucloud_mentioned 应透传 True"

    # ── 4. drilldown + model_key 过滤 ──
    r = client.get(f"/api/results/0/citation-drilldown?source_channel=知乎&task_id={task_id}&model_key=kimi")
    assert r.status_code == 200 and "kimi" in r.json()["data"], r.text

    # ── 5. 不存在的渠道 → 空 ──
    r = client.get(f"/api/results/0/citation-drilldown?source_channel=不存在渠道&task_id={task_id}")
    assert r.status_code == 200 and r.json()["data"] == {}, r.text

    # ── 6. 不存在的 task → 空（不 404）──
    r = client.get(f"/api/results/0/citation-channels?task_id=task_does_not_exist")
    assert r.status_code == 200 and r.json()["data"] == {}, r.text
    r = client.get(f"/api/results/0/citation-drilldown?source_channel=知乎&task_id=task_does_not_exist")
    assert r.status_code == 200 and r.json()["data"] == {}, r.text

    # ── 7. 向后兼容：无 task_id → run 模式，run_id=0 不存在 → 404 ──
    r = client.get(f"/api/results/0/citation-channels")
    assert r.status_code == 404, f"无 task_id 应走 run 模式并 404: {r.status_code}"
    r = client.get(f"/api/results/0/citation-drilldown?source_channel=知乎")
    assert r.status_code == 404, f"无 task_id 应走 run 模式并 404: {r.status_code}"

    print("✅ PASS: task 级引用渠道聚合（跨批次聚合/渠道计数/sample_urls/url_type/model_key过滤/空模型=空/"
          "下钻按渠道返回问题+URL/run_id占位不校验/不存在渠道=空/不存在task=空/run模式404保留）")


async def _seed():
    conn = await db.get_db()
    try:
        # Q1=引导型、Q2/Q3=对比词（自然题）、Q4 备用
        cats = {"Q1": "引导型", "Q2": "对比词", "Q3": "对比词", "Q4": "对比词"}
        for i in range(1, 5):
            qid = f"Q{i}"
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (qid, cats[qid], cats[qid], f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()


def _mk_cited(qid, mk, channels):
    """造一条带引用的分析结果。channels=[{channel,url,is_ucloud}]。
    all_cited_urls / citations 都填 url 型条目（citation-channels 两处都扫）。"""
    urls = [{"citation_type": "url", "source_channel": ch["channel"], "content": ch["url"],
             "is_ucloud": ch["is_ucloud"], "position": -1} for ch in channels]
    return {
        "question_id": qid, "model_key": mk, "model_name": mk.upper(),
        "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
        "has_citation": True, "citation_count": len(channels),
        "ucloud_recommended": True, "recommendation_strength": "strong",
        "sentiment_score": 0.6, "sentiment_label": "positive",
        "position_weight": 0.5, "response_length": 5,
        "raw_content": "UCloud 是云服务商，参考 " + " / ".join(ch["url"] for ch in channels),
        "competitor_mentions": {}, "error_message": None,
        "citations": urls, "all_cited_urls": urls,
    }


if __name__ == "__main__":
    main()
