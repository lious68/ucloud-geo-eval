"""task 评分重算接口自检：POST /api/tasks/{id}/recalculate 与 /api/tasks/recalculate-all。

验证：导入带有效引用的结果后，重算接口能刷新 citation_rate（修复历史 0 值数据）。
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


def _url(content, is_ucloud=False):
    return {"citation_type": "url", "content": content, "position": 0,
            "source_channel": "", "is_ucloud": is_ucloud}


def _mk(qid, citations):
    return {
        "question_id": qid, "model_key": "kimi", "model_name": "KIMI",
        "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
        "has_citation": bool(citations), "citation_count": len(citations),
        "ucloud_recommended": True, "recommendation_strength": "strong",
        "sentiment_score": 0.6, "sentiment_label": "positive",
        "position_weight": 0.5, "response_length": 5,
        "raw_content": "UCloud 是云服务商" + (" 参考 " + " ".join(c["content"] for c in citations) if citations else ""),
        "competitor_mentions": {}, "error_message": None,
        "citations": citations, "all_cited_urls": citations,
    }


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

    # 建 task + 导入 2 题（Q1 官方引用有效、Q2 无引用无效）→ citation_rate 应 1/2=0.5
    r = client.post("/api/tasks", json={"name": "RT", "categories": ["对比词"]})
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["id"]
    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1", "Q2"]}, "delay": 8})
    cfg = r.json()["data"]
    payload = {"meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
               "questions": [],
               "analysis_results": {"kimi": [
                   _mk("Q1", [_url("https://www.ucloud.cn/product/uaio.html", is_ucloud=True)]),
                   _mk("Q2", []),
               ]}}
    r = client.post(f"/api/tasks/{task_id}/batches/{cfg['batch_id']}/import-results",
                    files={"file": ("a.json", json.dumps(payload).encode(), "application/json")})
    assert r.status_code == 200, r.text

    def kimi_citation_rate():
        sc = client.get(f"/api/tasks/{task_id}/scores").json()["data"]
        return next(s for s in sc if s["model_key"] == "kimi")["citation_rate"]

    assert kimi_citation_rate() == 0.5, "导入后引用率应 0.5"

    # ── 单 task 重算接口 ──
    r = client.post(f"/api/tasks/{task_id}/recalculate")
    assert r.status_code == 200, r.text
    assert kimi_citation_rate() == 0.5, "重算后引用率仍应 0.5"

    # 不存在的 task → 404
    r = client.post("/api/tasks/task_none/recalculate")
    assert r.status_code == 404, r.text

    # ── 全量重算接口 ──
    r = client.post("/api/tasks/recalculate-all")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["recalculated"] >= 1, r.text
    assert kimi_citation_rate() == 0.5, "全量重算后引用率仍应 0.5"

    print("✅ PASS: task 评分重算接口（单 task 重算=0.5、不存在=404、全量重算≥1）")


async def _seed():
    conn = await db.get_db()
    try:
        for i in range(1, 3):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (f"Q{i}", "对比词", "对比词", f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()


if __name__ == "__main__":
    main()
