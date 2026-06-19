# 批次导入历史（审计日志）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次导入批次结果时写一条审计日志（时间、条数、文件名、大小），在批次行显示最后导入时间，在批次展开面板里列出完整导入历史。

**Architecture:** 新增独立 `batch_import_logs` 表（`CREATE TABLE IF NOT EXISTS`，对已有库零风险），每次导入写一行；服务层在导入成功后记日志；批次行展示 `MAX(imported_at)`，展开面板懒加载该批次的全部日志。导入仍按 `(task_id, model_key, question_id)` 覆盖（回答内容只留最新），日志只做审计——不回溯历史回答内容。

**Tech Stack:** Python / FastAPI / aiosqlite（后端）；Vue 3 + Element Plus 2.14.1（前端）；自检脚本放在 `scripts/test_*.py`（无 pytest，手写 async 脚本 + assert + 打印 ✅ PASS）。

## Global Constraints

- 自检脚本模式：`scripts/test_*.py`，`sys.path.insert` 加 `backend` 与 `core`，`db.DB_PATH = tempfile`，`asyncio.run(main())`，断言失败抛异常，成功打印 `✅ PASS`。**不要引入 pytest。**
- DB schema 在 `backend/database.py:147` 的 `SCHEMA_SQL` 字符串里；新表用 `CREATE TABLE IF NOT EXISTS` 加在 `geo_scores` 之后（`database.py:202` 行尾），`init_db` 自动执行。
- `analysis_results` 唯一索引 `(task_id, model_key, question_id)`、覆盖写入、`recalculate_task_scores` 全部不动。
- 旧路由 `POST /api/tasks/{task_id}/import-results` 与 `TaskDetail.vue` 保留，仅补 `file_name/file_size`。
- 安全：`.gitignore` 忽略 `data/`、`output/`；不提交 `data/geo.db`；不在代码里硬编码密钥。
- 前端构建：`cd C:/Users/Administrator/ucloud-geo-eval/frontend && npm run build`。
- 服务器部署：`/opt/ucloud-geo-eval`，`sudo git pull` + `npm run build` + `sudo systemctl restart ucloud-geo`。

## File Structure

- `backend/database.py` — 加 `batch_import_logs` 建表 + 3 个查询函数。
- `backend/services/task_service.py` — `import_batch_results` 增 `file_name/file_size` 形参并记日志；`build_task_detail` 注入 `last_import_at`；新增 `get_batch_import_logs`。
- `backend/routers/tasks.py` — 两个导入路由传 `file_name/file_size`；新增 `GET import-logs` 路由。
- `frontend/src/api/tasks.js` — 新增 `getBatchImportLogs`。
- `frontend/src/views/TaskList.vue` — 批次行显示最后导入时间；展开面板加「导入历史」区块；懒加载 + 导入后刷新。
- `scripts/test_batch_import_logs.py` — 新建自检脚本。

---

### Task 1: 新增 batch_import_logs 表 + 三个查询函数

**Files:**
- Modify: `backend/database.py:202`（`geo_scores` 建表 `);` 之后插入新表）
- Modify: `backend/database.py`（`get_batch_results` 函数之后，约 `database.py:1136` 追加 3 个函数）
- Test: `scripts/test_batch_import_logs.py`（新建）

**Interfaces:**
- Produces:
  - `async def add_batch_import_log(task_id: str, batch_id: str, run_id: Optional[str], results_inserted: int, file_name: Optional[str] = None, file_size: Optional[int] = None) -> int`
  - `async def get_batch_import_logs(task_id: str, batch_id: str) -> List[Dict]`
  - `async def get_last_import_times(task_id: str) -> Dict[str, str]`

- [ ] **Step 1: 在 SCHEMA_SQL 的 geo_scores 建表之后追加新表**

在 `backend/database.py` 的 `SCHEMA_SQL` 字符串里，`geo_scores` 表的 `);`（约第 202 行）之后、`admin_sessions` 之前插入：

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

- [ ] **Step 2: 在 get_batch_results 函数之后追加三个查询函数**

在 `backend/database.py` 的 `get_batch_results` 函数（约第 1122-1136 行）之后追加：

```python
async def add_batch_import_log(task_id: str, batch_id: str, run_id: Optional[str],
                               results_inserted: int, file_name: Optional[str] = None,
                               file_size: Optional[int] = None) -> int:
    """记一条批次导入审计日志，返回新行 id。"""
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

- [ ] **Step 3: 写自检脚本**

新建 `scripts/test_batch_import_logs.py`：

```python
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
```

- [ ] **Step 4: 运行自检，确认通过**

Run: `cd C:/Users/Administrator/ucloud-geo-eval && python scripts/test_batch_import_logs.py`
Expected: `✅ PASS: batch_import_logs 建表/插入/查询/聚合`

- [ ] **Step 5: 提交**

```bash
cd C:/Users/Administrator/ucloud-geo-eval
git add backend/database.py scripts/test_batch_import_logs.py
git commit -m "feat(db): batch_import_logs 审计日志表 + 查询函数"
```

---

### Task 2: 服务层记日志 + build_task_detail 注入最后导入时间

**Files:**
- Modify: `backend/services/task_service.py:138-168`（`import_batch_results`）
- Modify: `backend/services/task_service.py:248-252`（`build_task_detail` 注入 result_count 处）
- Modify: `backend/services/task_service.py`（`get_batch_results` 之后追加 `get_batch_import_logs`）
- Test: 复用 `scripts/test_tasks_service.py`（在其末尾加断言）

**Interfaces:**
- Consumes: `db.add_batch_import_log`, `db.get_last_import_times`, `db.get_batch_import_logs`（Task 1 产出）
- Produces:
  - `import_batch_results(task_id, data, batch_id=None, file_name=None, file_size=None)` — 末尾记日志
  - `build_task_detail` 返回的每个 batch 多 `last_import_at` 字段
  - `async def get_batch_import_logs(task_id, batch_id) -> List[Dict]`

- [ ] **Step 1: 修改 import_batch_results 签名并在末尾记日志**

在 `backend/services/task_service.py` 找到 `async def import_batch_results(task_id: str, data: Dict, batch_id: Optional[str] = None) -> Dict:`，把签名改为：

```python
async def import_batch_results(task_id: str, data: Dict, batch_id: Optional[str] = None,
                               file_name: Optional[str] = None,
                               file_size: Optional[int] = None) -> Dict:
```

在该函数的 `await recalculate_task_scores(task_id)` 之后、`return` 之前插入记日志行：

```python
    # 重算 task 评分（覆盖）
    await recalculate_task_scores(task_id)

    # 记一条导入审计日志（数据已落库，记成功痕迹）
    try:
        await db.add_batch_import_log(task_id, batch_id, run_id, inserted, file_name, file_size)
    except Exception:
        pass  # 审计日志写失败不影响导入结果

    return {"task_id": task_id, "batch_id": batch_id, "results_inserted": inserted}
```

- [ ] **Step 2: build_task_detail 注入 last_import_at**

在 `backend/services/task_service.py` 的 `build_task_detail` 里，找到：

```python
    result_counts = await db.count_task_results_by_batch(task_id)
    for b in batches:
        b["result_count"] = result_counts.get(b.get("batch_id"), 0)
```

改为：

```python
    result_counts = await db.count_task_results_by_batch(task_id)
    last_imports = await db.get_last_import_times(task_id)
    for b in batches:
        b["result_count"] = result_counts.get(b.get("batch_id"), 0)
        b["last_import_at"] = last_imports.get(b.get("batch_id"))
```

- [ ] **Step 3: 新增 get_batch_import_logs 服务函数**

在 `backend/services/task_service.py` 的 `get_batch_results` 函数（约第 171-173 行）之后追加：

```python
async def get_batch_import_logs(task_id: str, batch_id: str) -> List[Dict]:
    """取某批次的导入审计日志（时间倒序）。"""
    return await db.get_batch_import_logs(task_id, batch_id)
```

- [ ] **Step 4: 在 test_tasks_service.py 末尾加断言**

在 `scripts/test_tasks_service.py` 的 `main()` 里、`print("✅ PASS...")` 之前插入（验证两次导入都记了日志，且最后一次导入 batch_3 也记了）：

```python
    # 7. 导入审计日志：每次导入都记一条
    logs = await task_service.get_batch_import_logs(task_id, cfg["batch_id"])
    assert len(logs) == 1, f"批次 {cfg['batch_id']} 应有 1 条日志，实得 {len(logs)}"
    assert logs[0]["results_inserted"] == 2, f"首导应记 2 条，实得 {logs[0]['results_inserted']}"
    logs2 = await task_service.get_batch_import_logs(task_id, "batch_2")
    assert len(logs2) == 1 and logs2[0]["results_inserted"] == 4, "batch_2 应记 4 条"
    logs3 = await task_service.get_batch_import_logs(task_id, "batch_3")
    assert len(logs3) == 1 and logs3[0]["results_inserted"] == 0, "batch_3 题集外应记 0 条"

    # 8. build_task_detail 注入 last_import_at
    detail2 = await task_service.build_task_detail(task_id)
    b1 = next(b for b in detail2["batches"] if b["batch_id"] == cfg["batch_id"])
    assert b1["last_import_at"] is not None, "已导入批次应有 last_import_at"
```

- [ ] **Step 5: 运行两个自检脚本**

Run: `cd C:/Users/Administrator/ucloud-geo-eval && python scripts/test_tasks_service.py && python scripts/test_batch_import_logs.py`
Expected: 两行 `✅ PASS: ...`

- [ ] **Step 6: 提交**

```bash
cd C:/Users/Administrator/ucloud-geo-eval
git add backend/services/task_service.py scripts/test_tasks_service.py
git commit -m "feat(svc): 导入记审计日志 + build_task_detail 注入最后导入时间"
```

---

### Task 3: 路由层传 file_name/file_size + 新增 import-logs 路由

**Files:**
- Modify: `backend/routers/tasks.py:69-83`（`import_batch_results` 路由）
- Modify: `backend/routers/tasks.py:93-107`（旧 `import_results` 路由）
- Modify: `backend/routers/tasks.py`（`get_batch_results` 路由之后新增）

**Interfaces:**
- Consumes: `task_service.import_batch_results(..., file_name, file_size)`、`task_service.get_batch_import_logs`（Task 2 产出）
- Produces: `POST .../import-results` 与 `POST .../import-results`（旧）写日志；`GET /api/tasks/{task_id}/batches/{batch_id}/import-logs` 返回 `{success, data:[...]}`

- [ ] **Step 1: import_batch_results 路由传 file_name/file_size**

在 `backend/routers/tasks.py` 的 `import_batch_results` 路由里，把：

```python
        result = await task_service.import_batch_results(task_id, data, batch_id=batch_id)
```

改为：

```python
        result = await task_service.import_batch_results(
            task_id, data, batch_id=batch_id,
            file_name=file.filename, file_size=len(content)
        )
```

- [ ] **Step 2: 旧 import_results 路由传 file_name/file_size**

在 `backend/routers/tasks.py` 的 `import_results` 路由里，把：

```python
        result = await task_service.import_batch_results(task_id, data)
```

改为：

```python
        result = await task_service.import_batch_results(
            task_id, data, file_name=file.filename, file_size=len(content)
        )
```

- [ ] **Step 3: 新增 import-logs 路由**

在 `backend/routers/tasks.py` 的 `get_batch_results` 路由（约第 86-90 行）之后追加：

```python
@router.get("/{task_id}/batches/{batch_id}/import-logs")
async def get_batch_import_logs(task_id: str, batch_id: str):
    """取某批次的导入审计日志（时间倒序）。"""
    rows = await task_service.get_batch_import_logs(task_id, batch_id)
    return {"success": True, "data": rows}
```

- [ ] **Step 4: 启动后端，curl 验证路由存在**

Run（后台启动后端）:
```
cd C:/Users/Administrator/ucloud-geo-eval/backend && python app.py
```
然后另开终端：
```
curl -s http://localhost:8000/api/tasks/nonexist/batches/B1/import-logs
```
Expected: JSON 含 `success: true`（`data: []`，因任务不存在时 service 层 `get_batch_import_logs` 仍返回空列表；若返回 422/500 则路由有错）。停止后端。

> 注：`get_batch_import_logs` 不校验 task 存在性，对不存在的 task 返回 `[]`，符合只读查询预期。

- [ ] **Step 5: 提交**

```bash
cd C:/Users/Administrator/ucloud-geo-eval
git add backend/routers/tasks.py
git commit -m "feat(api): 导入路由传文件信息 + 新增 import-logs 路由"
```

---

### Task 4: 前端 API + 批次行显示最后导入时间 + 展开面板导入历史

**Files:**
- Modify: `frontend/src/api/tasks.js:43`（`getBatchResults` 之后追加）
- Modify: `frontend/src/views/TaskList.vue`（模板「结果」列、展开面板、script 状态与函数、style）

**Interfaces:**
- Consumes: `GET /api/tasks/{task_id}/batches/{batch_id}/import-logs`（Task 3 产出）；批次行的 `b.last_import_at`（Task 2 产出）
- Produces: 批次行显示「已导入 N · MM-DD HH:mm」；展开面板「导入历史（M 次）」折叠区列出每次导入。

- [ ] **Step 1: api/tasks.js 加 getBatchImportLogs**

在 `frontend/src/api/tasks.js` 的 `getBatchResults` 函数之后追加：

```js
export function getBatchImportLogs(taskId, batchId) {
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/import-logs`)
}
```

- [ ] **Step 2: TaskList.vue 导入 getBatchImportLogs**

在 `frontend/src/views/TaskList.vue` 的 import 语句（第 193 行）里，把：

```js
import { listTasks, createTask, deleteTask, getTask, importBatchResults, getBatchResults } from '../api/tasks'
```

改为：

```js
import { listTasks, createTask, deleteTask, getTask, importBatchResults, getBatchResults, getBatchImportLogs } from '../api/tasks'
```

- [ ] **Step 3: TaskList.vue 加状态与函数**

在 `frontend/src/views/TaskList.vue` 的 `const batchResultsLoading = ref({})` 之后（约第 220 行）追加：

```js
const batchImportLogsMap = ref({})       // batch_id -> 日志数组
const batchImportLogsLoading = ref({})   // batch_id -> bool

function batchImportLogsOf(batchId) { return batchImportLogsMap.value[batchId] }

async function loadBatchImportLogs(b) {
  const taskId = b.task_id
  const batchId = b.batch_id
  if (!taskId || !batchId) return
  batchImportLogsLoading.value = { ...batchImportLogsLoading.value, [batchId]: true }
  try {
    const res = await getBatchImportLogs(taskId, batchId)
    if (res?.success) batchImportLogsMap.value = { ...batchImportLogsMap.value, [batchId]: res.data || [] }
  } catch (e) {
    /* 静默：审计日志加载失败不阻断结果展示 */
  } finally {
    batchImportLogsLoading.value = { ...batchImportLogsLoading.value, [batchId]: false }
  }
}

function fmtImportTime(s) {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  if (isNaN(d.getTime())) return String(s)
  const p = n => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function fmtImportTimeFull(s) {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  if (isNaN(d.getTime())) return String(s)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function fmtFileSize(n) {
  if (!n && n !== 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
```

- [ ] **Step 4: loadBatchResults 改为同时加载日志**

把 `frontend/src/views/TaskList.vue` 的 `loadBatchResults` 函数改为并行加载日志：

```js
async function loadBatchResults(b) {
  const taskId = b.task_id
  const batchId = b.batch_id
  if (!taskId || !batchId) return
  batchResultsLoading.value = { ...batchResultsLoading.value, [batchId]: true }
  try {
    const [res, logs] = await Promise.all([
      getBatchResults(taskId, batchId),
      getBatchImportLogs(taskId, batchId),
    ])
    if (res?.success) batchResultsMap.value = { ...batchResultsMap.value, [batchId]: res.data || [] }
    if (logs?.success) batchImportLogsMap.value = { ...batchImportLogsMap.value, [batchId]: logs.data || [] }
  } catch (e) {
    ElMessage.error(`加载批次结果失败: ${e.message || e}`)
  } finally {
    batchResultsLoading.value = { ...batchResultsLoading.value, [batchId]: false }
  }
}
```

- [ ] **Step 5: doImport 成功后刷新日志**

把 `frontend/src/views/TaskList.vue` 的 `doImport` 里：

```js
    // 若该批次已展开，刷新其结果
    await loadBatchResults({ task_id, batch_id })
```

保持不变（`loadBatchResults` 现在已会顺带刷新日志）。无需额外改动。

- [ ] **Step 6: 批次行「结果」列显示最后导入时间**

把 `frontend/src/views/TaskList.vue` 的「结果」列模板：

```html
                <el-table-column label="结果" width="120">
                  <template #default="{ row: b }">
                    <el-tag v-if="(b.result_count || 0) > 0" size="small" type="success">已导入 {{ b.result_count }}</el-tag>
                    <el-tag v-else size="small" type="info" effect="plain">未导入</el-tag>
                  </template>
                </el-table-column>
```

改为：

```html
                <el-table-column label="结果" width="150">
                  <template #default="{ row: b }">
                    <el-tag v-if="(b.result_count || 0) > 0" size="small" type="success">已导入 {{ b.result_count }}</el-tag>
                    <el-tag v-else size="small" type="info" effect="plain">未导入</el-tag>
                    <div v-if="b.last_import_at" class="last-import-time">{{ fmtImportTime(b.last_import_at) }}</div>
                  </template>
                </el-table-column>
```

- [ ] **Step 7: 展开面板加导入历史区块**

把 `frontend/src/views/TaskList.vue` 展开面板里的 `batch-results-head` 之后的结果卡片列表区域，在 `</div>` 闭合 `batch-results-box` 之前追加导入历史区块。找到 `<div class="batch-results-box">` 内的末尾（结果卡片 `v-for` 的 `</div>` 之后、`batch-results-box` 闭合 `</div>` 之前）追加：

```html
                      <div class="import-logs-box">
                        <div class="import-logs-head">
                          📥 导入历史（{{ (batchImportLogsOf(b.batch_id) || []).length }} 次）
                        </div>
                        <div v-if="batchImportLogsLoading[b.batch_id]" class="batch-results-tip">加载中…</div>
                        <div v-else-if="!(batchImportLogsOf(b.batch_id) || []).length" class="batch-results-tip">暂无导入记录</div>
                        <div v-else class="import-log-list">
                          <div v-for="lg in (batchImportLogsOf(b.batch_id) || [])" :key="lg.id" class="import-log-item">
                            <span class="il-time">{{ fmtImportTimeFull(lg.imported_at) }}</span>
                            <el-tag size="small" type="success">{{ lg.results_inserted }} 条</el-tag>
                            <span class="il-file">{{ lg.file_name || '(未命名)' }}</span>
                            <span v-if="lg.file_size != null" class="il-size">{{ fmtFileSize(lg.file_size) }}</span>
                          </div>
                        </div>
                      </div>
```

- [ ] **Step 8: 加样式**

在 `frontend/src/views/TaskList.vue` 的 `<style scoped>` 里（`.result-pre` 规则之后）追加：

```css
.last-import-time { font-size: 11px; color: #a8abb2; margin-top: 2px; }
.import-logs-box { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ebeef5; }
.import-logs-head { font-size: 13px; color: #555; font-weight: 600; margin-bottom: 8px; }
.import-log-list { display: flex; flex-direction: column; gap: 6px; }
.import-log-item { display: flex; align-items: center; gap: 8px; font-size: 12px; flex-wrap: wrap; }
.il-time { font-family: monospace; color: #333; }
.il-file { color: #888; }
.il-size { color: #bbb; }
```

- [ ] **Step 9: 构建前端**

Run: `cd C:/Users/Administrator/ucloud-geo-eval/frontend && npm run build`
Expected: `✓ built`，无错误。

- [ ] **Step 10: 提交**

```bash
cd C:/Users/Administrator/ucloud-geo-eval
git add frontend/src/api/tasks.js frontend/src/views/TaskList.vue
git commit -m "feat(ui): 批次行显示最后导入时间 + 展开面板导入历史"
```

---

### Task 5: 部署到服务器 + 端到端验证

**Files:** 无代码改动；部署 + 验证。

- [ ] **Step 1: 推送到远程**

```bash
cd C:/Users/Administrator/ucloud-geo-eval
git -c credential.helper=manager push origin master
```

- [ ] **Step 2: 服务器拉取 + 构建 + 重启**

SSH 到 `ubuntu@113.31.106.119`（key `C:/Users/Administrator/.ssh/las20260523.pem`）后执行：

```bash
cd /opt/ucloud-geo-eval
sudo git pull origin master
cd frontend
# 若 node_modules/.vite-temp 权限报错：sudo chown -R ubuntu:ubuntu node_modules dist
npm run build
sudo systemctl restart ucloud-geo
curl -o /dev/null -w "%{http_code}\n" http://localhost/evaluation
```
Expected: `200`

- [ ] **Step 3: 端到端验证（浏览器）**

打开 http://113.31.106.119/evaluation ：
1. 展开任务 → 某批次「结果」列：导入前显示「未导入」无时间。
2. 点该批次「📥 导入」上传本地 runner 产出的 JSON。
3. 导入后：「结果」列变「已导入 N」并显示「MM-DD HH:mm」。
4. 点该批次行展开 → 滚到底部「📥 导入历史（1 次）」显示 1 条：时间 / N 条 / 文件名 / 大小。
5. 同批次再导一次 → 历史变「2 次」，最后时间更新为最新。

- [ ] **Step 4: （可选）提交自检脚本到服务器跑一遍**

```bash
cd /opt/ucloud-geo-eval
python scripts/test_batch_import_logs.py
python scripts/test_tasks_service.py
```
Expected: 两行 `✅ PASS`。

---

## Self-Review

**1. Spec coverage:**
- 新表 + 3 查询函数 → Task 1 ✓
- import_batch_results 记日志 → Task 2 Step 1 ✓
- build_task_detail 注入 last_import_at → Task 2 Step 2 ✓
- get_batch_import_logs 服务函数 → Task 2 Step 3 ✓
- 两路由传 file_name/file_size → Task 3 Step 1-2 ✓
- 新增 import-logs 路由 → Task 3 Step 3 ✓
- 前端 getBatchImportLogs → Task 4 Step 1 ✓
- 批次行最后导入时间 → Task 4 Step 6 ✓
- 展开面板导入历史 → Task 4 Step 7 ✓
- 懒加载 + 导入后刷新 → Task 4 Step 4-5 ✓
- 兼容旧路由/旧库 → Global Constraints + Task 1 IF NOT EXISTS ✓
- 端到端验证 + 部署 → Task 5 ✓

**2. Placeholder scan:** 无 TODO/TBD；每步含完整代码与命令。✓

**3. Type consistency:** `add_batch_import_log` / `get_batch_import_logs` / `get_last_import_times` 在 Task 1 定义、Task 2/3 消费，签名一致；前端 `getBatchImportLogs`、`batchImportLogsOf`、`loadBatchImportLogs`、`fmtImportTime` 等命名前后一致。✓
