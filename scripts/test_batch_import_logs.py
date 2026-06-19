"""batch_import_logs 自检：建表 + 插入 + 查询 + 聚合。"""
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    task_id = "T1"
    # 两条不同批次、B1 导入两次
    id1 = await db.add_batch_import_log(task_id, "B1", "run_1", 4, "a.json", 1024)
    await db.add_batch_import_log(task_id, "B1", "run_1b", 2, "b.json", 512)
    await db.add_batch_import_log(task_id, "B2", "run_2", 3, "c.json", 100)

    assert isinstance(id1, int) and id1 > 0, f"add 应返回行 id，实得 {id1}"

    logs_b1 = await db.get_batch_import_logs(task_id, "B1")
    assert len(logs_b1) == 2, f"B1 应有 2 条日志，实得 {len(logs_b1)}"
    assert logs_b1[0]["results_inserted"] == 2, "应按时间倒序，最新在前"
    assert logs_b1[0]["file_name"] == "b.json"

    last = await db.get_last_import_times(task_id)
    assert "B1" in last and "B2" in last, f"聚合应含 B1/B2，实得 {last}"
    assert last["B1"] == logs_b1[0]["imported_at"], "B1 最后时间应=最新一条"

    # 其它任务不应混入
    await db.add_batch_import_log("OTHER", "B1", "run_x", 9)
    assert len(await db.get_batch_import_logs(task_id, "B1")) == 2, "task_id 隔离应生效"

    print("✅ PASS: batch_import_logs 建表/插入/查询/聚合")


if __name__ == "__main__":
    asyncio.run(main())
