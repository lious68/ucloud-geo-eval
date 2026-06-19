# 批次导入历史记录与展示

## Context（为什么做）

当前「导入结果」已下沉到批次级（`POST /{task_id}/batches/{batch_id}/import-results`），批次行能显示「已导入 N / 未导入」，展开可看题目+模型回答。但**没有导入时间**：

- 每次导入都会按 `(task_id, model_key, question_id)` 覆盖，重新导入后看不出「这批是几点导的、导了几次」。
- 用户回来复盘时，不知道某批次上次是什么时候补的、补的哪份文件。

目标：**记录每次导入**（时间、条数、文件名），在批次行显示最后导入时间，在批次展开面板里列出完整导入历史。

## 关键事实（已确认）

- 导入服务 `task_service.import_batch_results(task_id, data, batch_id=None)` 按 `(task_id, model_key, question_id)` 去重覆盖插入，返回 `{task_id, batch_id, results_inserted}`（`task_service.py:138-168`）。`inserted` 在循环里累加，是本次净写入条数。
- 路由 `POST /{task_id}/batches/{batch_id}/import-results` 读 `file.read()` 成 `content`，`json.loads` 成 `data`，调服务层（`routers/tasks.py:69-83`）。`file.filename` 与 `len(content)` 可在此处拿到，当前未传给服务层。
- `build_task_detail` 已在注入 `result_count`：`result_counts = await db.count_task_results_by_batch(task_id)`，每批次 `b["result_count"] = ...`（`task_service.py:248-252`）。批次行「结果」列读 `b.result_count`。
- 批次展开懒加载：`onBatchExpand` → `loadBatchResults(b)` → `getBatchResults(task_id, batch_id)`（`TaskList.vue:256-276`），结果存 `batchResultsMap[batchId]`。
- DB schema 在 `database.py:147` 的 `SCHEMA_SQL` 字符串里，迁移用 `CREATE TABLE IF NOT EXISTS`（`init_db` 执行），加列用 `_migrate_add_columns`。已有 `_migrate_add_columns` 用 `column_exists` 守卫 ALTER TABLE（`database.py:343-359`）。
- 旧路由 `POST /{task_id}/import-results` 保留供 `TaskDetail.vue` 兼容（`routers/tasks.py:93-107`）。

## 设计（方案 A：独立导入日志表）

### 1. 数据层 — `backend/database.py`

**`SCHEMA_SQL` 末尾（`geo_scores` 建表之后）新增表：**

```sql
CREATE TABLE IF NOT EXISTS batch_import_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    run_id TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    results_inserted INTEGER DEFAULT 0,
    file_name TEXT,
    file_size INTEGER
);
CREATE INDEX IF NOT EXISTS idx_bil_batch ON batch_import_logs(task_id, batch_id, imported_at);
```

`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`，对已有库零风险，无需手动迁移。

**新增三个查询函数（放在 `get_batch_results` 之后）：**

```python
async def add_batch_import_log(task_id: str, batch_id: str, run_id: Optional[str],
                               results_inserted: int, file_name: Optional[str] = None,
                               file_size: Optional[int] = None) -> int:
    """记一条批次导入日志，返回新行 id。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO batch_import_logs "
            "(task_id, batch_id, run_id, results_inserted, file_name, file_size) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, batch_id, run_id, results_inserted, file_name, file_size)
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_batch_import_logs(task_id: str, batch_id: str) -> List[Dict]:
    """取某批次的全部导入日志，按时间倒序。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM batch_import_logs "
            "WHERE task_id=? AND batch_id=? ORDER BY imported_at DESC, id DESC",
            (task_id, batch_id)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def get_last_import_times(task_id: str) -> Dict[str, str]:
    """返回 {batch_id: 最后导入时间}，用于批次行展示。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT batch_id, MAX(imported_at) AS last_at "
            "FROM batch_import_logs WHERE task_id=? GROUP BY batch_id",
            (task_id,)
        )
        rows = await cursor.fetchall()
        return {r["batch_id"]: r["last_at"] for r in rows if r["batch_id"]}
    finally:
        await db.close()
```

### 2. 服务层 — `backend/services/task_service.py`

- `import_batch_results(task_id, data, batch_id=None, file_name=None, file_size=None)`：增两个可选形参。在 `inserted` 算出后、`recalculate_task_scores` 之后，调 `await db.add_batch_import_log(task_id, batch_id, run_id, inserted, file_name, file_size)`。日志写入放在重算之后，保证「记日志」只在该次导入数据已落库后发生；若重算抛异常则不记日志（导入本身已失败，不该留下成功痕迹）。
- `build_task_detail`：`result_counts` 旁边加 `last_imports = await db.get_last_import_times(task_id)`，每批次注入 `b["last_import_at"] = last_imports.get(b.get("batch_id"))`。
- 新增 `async def get_batch_import_logs(task_id, batch_id): return await db.get_batch_import_logs(task_id, batch_id)`。

### 3. 路由层 — `backend/routers/tasks.py`

- `import_batch_results` 路由：把 `file.filename`、`len(content)` 传入 `task_service.import_batch_results(task_id, data, batch_id=batch_id, file_name=file.filename, file_size=len(content))`。
- 旧 `import_results` 路由同理补 `file_name=file.filename, file_size=len(content)`（向后兼容）。
- 新增 `GET /{task_id}/batches/{batch_id}/import-logs` → `task_service.get_batch_import_logs`，返回 `{success: True, data: [...]}`。

### 4. 前端 API — `frontend/src/api/tasks.js`

```js
export function getBatchImportLogs(taskId, batchId) {
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/import-logs`)
}
```

### 5. 前端视图 — `frontend/src/views/TaskList.vue`

- **批次行「结果」列**：`已导入 N` tag 下方加小灰字最后导入时间（`b.last_import_at`），格式化为本地时间 `MM-DD HH:mm`。`未导入` 不显示时间。
- **批次展开面板**：在「共 N 条结果」标题之后、结果卡片列表之后，加「📥 导入历史」区块。`el-collapse` 单项，标题 `导入历史（M 次）`。展开时若未加载则调 `getBatchImportLogs`。
  - 列表每行：导入时间（本地 `YYYY-MM-DD HH:mm:ss`）+ 导入条数 tag + 文件名（`file_name`，灰色小字）+ 文件大小（`file_size` 友好格式 KB/MB）。
- **懒加载**：`onBatchExpand` → `loadBatchResults` 同时并行调 `getBatchImportLogs`，结果存新 `batchImportLogsMap`（batch_id → 日志数组）。
- **`doImport` 成功后**：`loadBatchResults` 之后刷新该批次 import logs（`loadBatchImportLogs`）。
- 新增状态：`batchImportLogsMap = ref({})`、`batchImportLogsLoading = ref({})`；新增 `loadBatchImportLogs(b)`、`batchImportLogsOf(batchId)`。

### 6. 不改 / 兼容

- `analysis_results` 唯一索引、覆盖写入、评分重算全部不动。
- 旧库自动建 `batch_import_logs` 表（`IF NOT EXISTS`）。
- 旧路由 `POST /{task_id}/import-results` 与 `TaskDetail.vue` 任务级导入保留，仅补 file_name/file_size。

## 验证

1. 后端自检：构造 `batch_import_logs` 表存在性、`add_batch_import_log` 插入 + `get_batch_import_logs` 取回、`get_last_import_times` 聚合正确（可用 temp DB `data/geo_selfcheck.db` 走 `init_db`）。
2. 前端构建 `cd frontend && npm run build`（应 ✓ built）。
3. 端到端（http://113.31.106.119/evaluation）：展开任务 → 某批次「结果」列导入前显示「未导入」→ 点「📥 导入」上传 JSON → 该列变「已导入 N」并显示最后导入时间 → 点批次行展开 → 「导入历史」显示 1 条记录（时间/条数/文件名/大小）→ 再导一次 → 历史变 2 条，最后时间更新。
4. 部署：`git push origin master` → 服务器 `cd /opt/ucloud-geo-eval && sudo git pull origin master && cd frontend && npm run build && sudo systemctl restart ucloud-geo`，`curl -o /dev/null -w "%{http_code}" http://localhost/evaluation` 应 200。
