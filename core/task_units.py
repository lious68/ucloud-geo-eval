"""
UCloud GEO 评估框架 - 任务单元状态层（三级任务架构的「模型/问题」层）

一个 Unit = 一个 (run_id, model_key, question_id) 三元组，自带 status。
它是「任务 → 模型 → 问题」三级中后两级的唯一事实来源：
  - 调度器（core/scheduler.py）每次重新计算「还剩什么」，不做位置记忆；
  - 崩溃重入时跳过 done，仅补跑 pending/failed；
  - 进程启动时把所有 running reset 为 pending，杜绝幽灵单元。

落库顺序对最终评分无影响（analysis_results 唯一性靠三元组，
geo_scores 计算靠 for r in all_results[mk] 重 join，均不依赖顺序）——
所以「交错执行 + 单元恢复」能正确配合。

server 与 local 共用本模块：
  - server  : SqliteUnitStore(data/geo.db)        （与 evaluation_runs 同库）
  - local   : SqliteUnitStore(data/local_runs/<run_id>.db)
用同步 sqlite3：单元操作小而频、亚毫秒级，在 asyncio 事件循环里直接调用即可，
浏览器交互（数秒级）才是瓶颈，不会因同步落库阻塞调度。
"""
import os
import json
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


# ============ 数据模型 ============

# 单元状态机：
#   pending  -> running -> done        （正常）
#                      -> failed       （瞬态错误超 max_attempts）
#   running  -> pending                （崩溃重入 / throttle 冷却后回退）
#   *        -> skipped                （login_expired，需人工重登，整模型跳过）
VALID_STATUS = ("pending", "running", "done", "failed", "skipped")


@dataclass
class Unit:
    run_id: str
    model_key: str
    question_id: str
    status: str = "pending"
    attempts: int = 0
    last_error: str = ""
    content: str = ""           # 提取到的响应文本（done 时写入）
    raw_response: str = ""      # 调试用：原始响应 JSON（可选）
    model_name: str = ""        # 冗余存一份，恢复时无需再查
    updated_at: str = ""

    @property
    def key(self) -> tuple:
        return (self.run_id, self.model_key, self.question_id)

    def to_row(self) -> dict:
        d = asdict(self)
        # raw_response 可能是 dict/任意对象，落库前序列化
        rr = d.get("raw_response", "")
        if rr and not isinstance(rr, str):
            d["raw_response"] = json.dumps(rr, ensure_ascii=False, default=str)
        return d

    @classmethod
    def from_row(cls, row: dict) -> "Unit":
        return cls(
            run_id=row["run_id"],
            model_key=row["model_key"],
            question_id=row["question_id"],
            status=row["status"],
            attempts=row["attempts"],
            last_error=row["last_error"] or "",
            content=row["content"] or "",
            raw_response=row["raw_response"] or "",
            model_name=row["model_name"] or "",
            updated_at=row["updated_at"] or "",
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_units (
    run_id      TEXT NOT NULL,
    model_key   TEXT NOT NULL,
    question_id TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT DEFAULT '',
    content     TEXT DEFAULT '',
    raw_response TEXT DEFAULT '',
    model_name  TEXT DEFAULT '',
    updated_at  TEXT DEFAULT '',
    PRIMARY KEY (run_id, model_key, question_id)
);
CREATE INDEX IF NOT EXISTS idx_task_units_run_status
    ON task_units(run_id, status);
"""


# ============ 存储 ============

class UnitStore:
    """单元存储抽象基类。"""

    def expand_units(self, run_id: str, models: List[str], question_ids: List[str],
                     model_names: Optional[Dict[str, str]] = None) -> int:
        raise NotImplementedError

    def get(self, run_id: str, model_key: str, question_id: str) -> Optional[Unit]:
        raise NotImplementedError

    def upsert(self, unit: Unit) -> None:
        raise NotImplementedError

    def list_units(self, run_id: str, status: Optional[str] = None) -> List[Unit]:
        raise NotImplementedError

    def list_pending(self, run_id: str) -> List[Unit]:
        raise NotImplementedError

    def reset_stale_running(self, run_id: str) -> int:
        raise NotImplementedError

    def set_model_status(self, run_id: str, model_key: str, status: str) -> int:
        """批量改某模型所有未完成单元的状态（用于 login_expired → skipped）。"""
        raise NotImplementedError

    def counts(self, run_id: str) -> Dict[str, int]:
        raise NotImplementedError


class SqliteUnitStore(UnitStore):
    """基于同步 sqlite3 的单元存储。"""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        # 初始化建表
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.OperationalError:
            pass
        return conn

    def expand_units(self, run_id: str, models: List[str], question_ids: List[str],
                     model_names: Optional[Dict[str, str]] = None) -> int:
        """幂等展开：已存在的 (run,model,q) 不重置状态，仅补齐缺失单元。"""
        if not models or not question_ids:
            return 0
        model_names = model_names or {}
        created = 0
        rows = []
        for mk in models:
            for qid in question_ids:
                rows.append((
                    run_id, mk, qid, "pending", 0, "", "", "",
                    model_names.get(mk, mk), "",
                ))
        sql = (
            "INSERT OR IGNORE INTO task_units "
            "(run_id, model_key, question_id, status, attempts, last_error, "
            " content, raw_response, model_name, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        with self._lock:
            with self._conn() as conn:
                conn.executemany(sql, rows)
                cur = conn.execute(
                    "SELECT changes()"
                )  # executemany 的聚合 changes 不可靠，改用计数查询
                cur = conn.execute(
                    "SELECT COUNT(*) AS c FROM task_units WHERE run_id=?", (run_id,)
                )
                total = cur.fetchone()["c"]
        return total

    def get(self, run_id: str, model_key: str, question_id: str) -> Optional[Unit]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT * FROM task_units WHERE run_id=? AND model_key=? AND question_id=?",
                (run_id, model_key, question_id),
            )
            row = cur.fetchone()
        return Unit.from_row(dict(row)) if row else None

    def upsert(self, unit: Unit) -> None:
        if unit.status not in VALID_STATUS:
            raise ValueError(f"invalid unit status: {unit.status}")
        row = unit.to_row()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO task_units
                       (run_id, model_key, question_id, status, attempts, last_error,
                        content, raw_response, model_name, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(run_id, model_key, question_id) DO UPDATE SET
                         status=excluded.status, attempts=excluded.attempts,
                         last_error=excluded.last_error, content=excluded.content,
                         raw_response=excluded.raw_response, model_name=excluded.model_name,
                         updated_at=excluded.updated_at""",
                    (row["run_id"], row["model_key"], row["question_id"], row["status"],
                     row["attempts"], row["last_error"], row["content"], row["raw_response"],
                     row["model_name"], row["updated_at"]),
                )

    def list_units(self, run_id: str, status: Optional[str] = None) -> List[Unit]:
        with self._conn() as conn:
            if status:
                cur = conn.execute(
                    "SELECT * FROM task_units WHERE run_id=? AND status=? ORDER BY question_id, model_key",
                    (run_id, status),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM task_units WHERE run_id=? ORDER BY question_id, model_key",
                    (run_id,),
                )
            rows = cur.fetchall()
        return [Unit.from_row(dict(r)) for r in rows]

    def list_pending(self, run_id: str) -> List[Unit]:
        return self.list_units(run_id, status="pending")

    def reset_stale_running(self, run_id: str) -> int:
        """把残留 running 单元 reset 为 pending（崩溃/进程重启后调用）。"""
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    "UPDATE task_units SET status='pending' WHERE run_id=? AND status='running'",
                    (run_id,),
                )
                return cur.rowcount

    def set_model_status(self, run_id: str, model_key: str, status: str) -> int:
        """把某模型所有「未完成」单元置为 status（login_expired → skipped）。"""
        if status not in VALID_STATUS:
            raise ValueError(f"invalid unit status: {status}")
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """UPDATE task_units SET status=?, updated_at=?
                       WHERE run_id=? AND model_key=? AND status NOT IN ('done','skipped')""",
                    (status, _now(), run_id, model_key),
                )
                return cur.rowcount

    def counts(self, run_id: str) -> Dict[str, int]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT status, COUNT(*) AS c FROM task_units WHERE run_id=? GROUP BY status",
                (run_id,),
            )
            rows = cur.fetchall()
        out = {s: 0 for s in VALID_STATUS}
        for r in rows:
            out[r["status"]] = r["c"]
        return out


def _now() -> str:
    # 不依赖 datetime.now()（在 workflow 脚本里不可用），但普通运行环境可用；
    # 这里是普通模块，datetime 可用。
    from datetime import datetime
    return datetime.now().isoformat()
