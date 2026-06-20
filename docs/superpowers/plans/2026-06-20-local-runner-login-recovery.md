# 本地 Runner 跑前登录探测 + 登录后保存再跑 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本地 runner 跑前用真实浏览器探测"能不能聊天"，未登录则在 `--headed` 下弹浏览器引导登录、**确认登录后才保存**登录态、再继续跑；杜绝"提前保存不完整 state"和"跑到一半才挂"。

**Architecture:** 给 `WebChatClientBase.initialize()` 增 `fresh` 形参（无存档也能开浏览器）；新增 `_goto_site()`（导航一次）+ `_is_logged_in()`（只探测当前页，不导航）两个方法；在 `local_webchat_runner.py` 内新增 `_login_flow()`（轮询 `_is_logged_in`，确认后才 `save_auth_state`）；用真实 DOM 探测替换旧的 `has_auth_state`/手动按 Enter 预检块。绕开脆弱的 cookie 名单，探测用"URL 不在登录页 且 输入框可见"。

**Tech Stack:** Python 3 + asyncio + Playwright（async API）；自检脚本为 `scripts/test_*.py`（**不用 pytest**，直接 `asyncio.run(main())` + assert + `print("✅ PASS")`）。

## Global Constraints

- 自检脚本约定：放在 `scripts/test_*.py`；顶部 `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))`；`asyncio.run(main())`；assert 失败即抛；通过打印 `✅ PASS: ...`；**不依赖真实浏览器**（用 fake page/client 对象）。Windows 下必要时重定向 stdout 为 UTF-8（参考 `scripts/test_classify_content_signal.py`）。
- `WebChatClientBase.initialize()` 评测路径默认行为**不得改变**：`fresh=False` 时维持"无存档返回 False / 有存档用 `storage_state` 开浏览器"现状，调度器评测客户端调用不受影响。
- `_is_logged_in` **只探测当前页、不导航**（否则登录轮询时每 3s 重新 goto 会打断用户正在进行的登录）。导航由调用方事先 `_goto_site()` 一次。
- `save_auth_state` **只在 `_is_logged_in` 确认后调用**，超时未登录不保存（杜绝提前保存不完整 state）。
- 不改：`EvalScheduler` / `chat()` / 限流 / 封号 / `classify_content_signal` / 服务端 `eval_runner.py` / `setup_webchat_auth*.py`（保留为独立工具）。
- 预检用的客户端是临时的，探测/登录完即 `close()`；评测时调度器通过 `client_factory` 另建新客户端加载已保存 state。
- 模型键固定集合：`deepseek, ernie, doubao, kimi, qwen`；逐模型已定义类属性 `INPUT_SELECTOR`。
- 安全：本特性仅本地 runner，不部署服务器；代码 `git push origin master` 仅作版本管理。`.gitignore` 忽略 `data/`（含真实登录态），不得提交。

---

## File Structure

- **`core/web_chat_clients.py`**（修改）：`WebChatClientBase` 增 `LOGIN_URL_HINTS` 类属性、`initialize(fresh=False)` 形参、`_goto_site(page)`、`_is_logged_in(page, timeout=15)`。职责：浏览器自动化客户端基类。新增方法是登录探测的底层原语，评测路径（`fresh=False`）行为不变。
- **`scripts/local_webchat_runner.py`**（修改）：顶部 import 增 `save_auth_state`；新增 `_login_flow(client, mk, max_wait=300)` 协程；替换 `local_webchat_runner.py:284-311` 预检块为真实 DOM 探测版。职责：本地 runner 入口；登录预检从"文件存在"升级为"DOM 探测 + 确认后保存"。
- **`scripts/test_is_logged_in.py`**（新建）：`_is_logged_in` 判定逻辑单测，fake page。
- **`scripts/test_login_flow.py`**（新建）：`_login_flow` "只在确认登录后才保存"单测，fake client + monkeypatch `save_auth_state`。

---

### Task 1: `WebChatClientBase` 增 `fresh` 形参 + `_goto_site` + `_is_logged_in`

**Files:**
- Modify: `core/web_chat_clients.py:22-110`（类属性区 + `initialize`）、`core/web_chat_clients.py:205` 附近（在子类需实现方法区之前插入新方法）
- Test: `scripts/test_is_logged_in.py`

**Interfaces:**
- Consumes: `WEBCHAT_SITES`（已 import）、子类 `INPUT_SELECTOR`（已存在的类属性）、`self.url`、`self._page`、`self._context`、`self.is_configured`、`self._auth_state`。
- Produces:
  - `async def initialize(self, fresh: bool = False) -> bool` — `fresh=True` 时不要求 `is_configured`、`new_context` 不传 `storage_state`，返回 True；`fresh=False` 维持现状。
  - `async def _goto_site(self, page) -> None` — 导航到 `self.url` 一次，失败静默。
  - `async def _is_logged_in(self, page, timeout: int = 15) -> bool` — 只探测当前页：URL 含 `LOGIN_URL_HINTS` 任一 → False；否则 `INPUT_SELECTOR.first.is_visible(timeout*1000)`，异常 → False。
  - 类属性 `LOGIN_URL_HINTS: tuple = ("login", "passport", "signin", "sso")`。

- [ ] **Step 1: Write the failing test** — `scripts/test_is_logged_in.py`

```python
"""_is_logged_in 判定逻辑自检（fake page，不依赖真实浏览器）。

验证：URL 在登录页 → False；URL 正常 + 输入框可见 → True；
URL 正常 + 输入框不可见 → False；is_visible 抛错 → False。
不导航（_is_logged_in 只看当前页 url，不调 goto）。
"""
import sys
import os
import io
import asyncio

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


class _FakeLocator:
    def __init__(self, visible_value=True, exc=None):
        self._visible = visible_value
        self._exc = exc

    async def is_visible(self, timeout=0):
        if self._exc:
            raise self._exc
        return self._visible


class _FakePage:
    def __init__(self, url="", visible=True, exc=None):
        self.url = url
        self._locator = _FakeLocator(visible, exc)
        self.goto_calls = 0

    def locator(self, selector):
        return self._locator


def _make_client():
    # 用基类即可（INPUT_SELECTOR 是基类级占位，这里覆盖一个确定值）
    from web_chat_clients import WebChatClientBase

    class _Probe(WebChatClientBase):
        INPUT_SELECTOR = "textarea.fake"

    c = _Probe("kimi")  # kimi 站点 url=www.kimi.com，is_configured 可能 False 不影响探测
    return c


async def main():
    c = _make_client()

    # 1. URL 含 passport → False（即使输入框可见）
    page = _FakePage(url="https://passport.kimi.com/login", visible=True)
    assert await c._is_logged_in(page, timeout=1) is False, "登录页 URL 应判未登录"

    # 2. URL 无关键字 + 输入框可见 → True
    page = _FakePage(url="https://www.kimi.com/chat", visible=True)
    assert await c._is_logged_in(page, timeout=1) is True, "正常页+输入框可见应判已登录"

    # 3. URL 无关键字 + 输入框不可见 → False
    page = _FakePage(url="https://www.kimi.com/chat", visible=False)
    assert await c._is_logged_in(page, timeout=1) is False, "输入框不可见应判未登录"

    # 4. is_visible 抛错 → False（不向上抛）
    page = _FakePage(url="https://www.kimi.com/chat", exc=RuntimeError("boom"))
    assert await c._is_logged_in(page, timeout=1) is False, "is_visible 异常应判未登录"

    # 5. 不导航：_is_logged_in 不应调 page.goto
    page = _FakePage(url="https://www.kimi.com/chat", visible=True)
    await c._is_logged_in(page, timeout=1)
    assert page.goto_calls == 0, "_is_logged_in 不应导航"

    print("✅ PASS: _is_logged_in 登录页/正常页/不可见/异常均判定正确，且不导航")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/test_is_logged_in.py`
Expected: FAIL — `AttributeError: 'WebChatClientBase' object has no attribute '_is_logged_in'`（或 `LOGIN_URL_HINTS`）。

- [ ] **Step 3: Add `LOGIN_URL_HINTS` class attribute**

在 `core/web_chat_clients.py` 的 `WebChatClientBase` 类属性区（`is_configured: bool = False` 那一行之后，即 `def __init__` 之前）插入：

```python
    # 登录页 URL 片段（命中任一即视为未登录/登录页，_is_logged_in 反向信号）
    LOGIN_URL_HINTS = ("login", "passport", "signin", "sso")
```

- [ ] **Step 4: Modify `initialize()` to accept `fresh`**

把 `core/web_chat_clients.py:55-110` 的 `initialize` 改为支持 `fresh` 形参。**`fresh=False` 分支逐行保持原样**（包括 `has_display`/headless 判定、launch args、stealth_js、`new_context`、`add_init_script`、`new_page`、return True）。改动点只有三处：

(a) 签名与开头守卫：

```python
    async def initialize(self, fresh: bool = False) -> bool:
        """启动浏览器（在评测开始时调用一次）

        fresh=False（默认，评测用）：无认证状态返回 False；用已存 storage_state 开浏览器。
        fresh=True（登录流程用）：不要求认证状态，开全新 context（不传 storage_state），
            供 _login_flow 引导用户登录后探测保存。
        """
        if not fresh and not self.is_configured:
            logger.warning(f"WebChat {self.model_key}: 无认证状态，无法评测")
            return False
```

(b) `new_context` 调用根据 `fresh` 决定是否传 `storage_state`。把原来的：

```python
        self._context = await self._browser.new_context(
            storage_state=self._auth_state,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
```

改为：

```python
        ctx_kwargs = dict(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        if not fresh and self._auth_state:
            ctx_kwargs["storage_state"] = self._auth_state
        self._context = await self._browser.new_context(**ctx_kwargs)
```

> `fresh=True` 时 `self._auth_state` 可能是 None，绝不能传 `storage_state=None`（Playwright 会当空 state 用，OK 但语义不清晰）；用条件传参更明确。

(c) 末尾 return 不变（仍 `return True`）。headless/launch/stealth/init_script/new_page 全部原样保留。

- [ ] **Step 5: Add `_goto_site` and `_is_logged_in` methods**

在 `core/web_chat_clients.py` 的 `close()` 方法之后、`# ── 子类需要实现的方法 ──` 注释之前（约 `web_chat_clients.py:204` 附近）插入：

```python
    async def _goto_site(self, page: Page) -> None:
        """导航到站点首页一次（探测/登录前由调用方调用）。

        失败静默：导航失败时由 _is_logged_in 的输入框可见性兜底判 False。
        只导航一次，不在 _is_logged_in 内重复 goto（否则会打断用户正在进行的登录）。
        """
        try:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            try:
                await page.goto(self.url, wait_until="commit", timeout=30000)
            except Exception:
                pass

    async def _is_logged_in(self, page: Page, timeout: int = 15) -> bool:
        """真实登录态探测（只看当前页，不导航）。

        URL 含登录页片段 → False；否则看聊天输入框是否可见。
        不导航：登录轮询时每 3s 调用，重复 goto 会打断用户登录。
        子类可覆盖以提供更精确信号（默认用 INPUT_SELECTOR 可见性 + URL 反向信号）。
        """
        url = page.url or ""
        if any(h in url for h in self.LOGIN_URL_HINTS):
            return False
        try:
            loc = page.locator(self.INPUT_SELECTOR).first
            return await loc.is_visible(timeout=timeout * 1000)
        except Exception:
            return False
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python scripts/test_is_logged_in.py`
Expected: `✅ PASS: _is_logged_in 登录页/正常页/不可见/异常均判定正确，且不导航`

- [ ] **Step 7: Regression — confirm evaluation path unchanged**

确认 `initialize(fresh=False)` 默认行为未变（无存档返回 False、有存档用 storage_state）。用 `python` 快速检查不报错即可：

Run: `python -c "import sys; sys.path.insert(0,'core'); from web_chat_clients import WebChatClientBase; import inspect; print(inspect.signature(WebChatClientBase.initialize))"`
Expected: `(self, fresh: bool = False) -> bool`

- [ ] **Step 8: Commit**

```bash
git add core/web_chat_clients.py scripts/test_is_logged_in.py
git commit -m "feat(webchat): 基类增 initialize(fresh)/_goto_site/_is_logged_in 登录探测原语"
```

---

### Task 2: runner 新增 `_login_flow` + 替换预检块为真实 DOM 探测

**Files:**
- Modify: `scripts/local_webchat_runner.py:71`（import 行）、`scripts/local_webchat_runner.py:284-311`（预检块）；新增 `_login_flow` 协程（放在 `run_local_eval` 之前或文件内合适位置）
- Test: `scripts/test_login_flow.py`

**Interfaces:**
- Consumes（来自 Task 1）: `WebChatClientBase.initialize(fresh=True)`、`._goto_site(page)`、`._is_logged_in(page, timeout)`；`create_web_chat_client(mk)`、`has_auth_state(mk)`、`save_auth_state(mk, state)`。
- Produces:
  - `async def _login_flow(client, mk: str, max_wait: int = 300) -> bool`（runner 模块级协程）：确保浏览器开 → `_goto_site` 一次 → 每 3s 轮询 `_is_logged_in`，确认后才 `save_auth_state`；超时不保存返回 False。
  - 预检块：对每个 `mk` 用临时 client 真实探测；未登录 + `--headed` → `_login_flow`；全跳过 → 中止。

- [ ] **Step 1: Write the failing test** — `scripts/test_login_flow.py`

```python
"""_login_flow 自检：只在 _is_logged_in 确认后才 save_auth_state（fake client）。

验证两路：
  A. 探测始终 False（用小 max_wait）→ 超时 → save_auth_state 未被调用、返回 False。
  B. 探测第 2 次起 True → save_auth_state 被调用恰好 1 次、返回 True。
不依赖真实浏览器（fake client + monkeypatch save_auth_state 到计数器）。
"""
import sys
import os
import io
import asyncio

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


class _FakeCtx:
    async def storage_state(self):
        return {"cookies": [{"name": "c1"}, {"name": "c2"}, {"name": "c3"}], "origins": []}


class _FakePage:
    def __init__(self):
        self.url = "https://www.kimi.com/chat"


class _FakeClient:
    """最小 fake：仅暴露 _login_flow 用到的接口。"""

    name = "Kimi"
    url = "https://www.kimi.com"

    def __init__(self, is_logged_in_seq):
        # is_logged_in_seq: 每次调用返回的 bool 序列（True=已登录）
        self._seq = list(is_logged_in_seq)
        self._page = _FakePage()
        self._context = _FakeCtx()
        self.goto_calls = 0
        self.init_calls = 0

    async def initialize(self, fresh=False):
        self.init_calls += 1
        return True

    async def _goto_site(self, page):
        self.goto_calls += 1

    async def _is_logged_in(self, page, timeout=15):
        if self._seq:
            return self._seq.pop(0)
        return False  # 序列耗尽后保持 False（模拟始终未登录）

    async def close(self):
        pass


def _patch_save_auth_state(mod, counter):
    """把 runner 模块里的 save_auth_state 替换为计数器。"""
    counter["calls"] = 0
    counter["args"] = []

    def _fake(mk, state):
        counter["calls"] += 1
        counter["args"].append((mk, state))
        return f"/tmp/fake_{mk}_state.json"

    mod.save_auth_state = _fake


async def main():
    # 用 importlib 导入 runner（它顶层有副作用：path 设置、import，但 main() 不自动跑）
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "local_webchat_runner",
        os.path.join(os.path.dirname(__file__), "local_webchat_runner.py"),
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    # ── A. 始终未登录 → 超时不保存 ──
    counter_a = {}
    _patch_save_auth_state(runner, counter_a)
    client_a = _FakeClient(is_logged_in_seq=[False, False, False, False, False])
    # max_wait 设小（3s 一次，max_wait=6 → 最多 2 轮），加速测试
    ok = await runner._login_flow(client_a, "kimi", max_wait=6)
    assert ok is False, "始终未登录应返回 False"
    assert counter_a["calls"] == 0, "未确认登录不应调用 save_auth_state"
    assert client_a.goto_calls == 1, "应只 _goto_site 一次"
    assert client_a.init_calls == 0, "_page 已存在时不应再 initialize"

    # ── B. 第 2 次探测 True → 保存一次、返回 True ──
    counter_b = {}
    _patch_save_auth_state(runner, counter_b)
    client_b = _FakeClient(is_logged_in_seq=[False, True])
    ok = await runner._login_flow(client_b, "kimi", max_wait=60)
    assert ok is True, "确认登录应返回 True"
    assert counter_b["calls"] == 1, "确认登录应恰好保存一次"
    mk, state = counter_b["args"][0]
    assert mk == "kimi", "save_auth_state 应收到正确 model_key"
    assert len(state.get("cookies", [])) == 3, "应保存 fake context 的 cookies"

    # ── C. _page 为 None 时应 initialize(fresh=True) ──
    counter_c = {}
    _patch_save_auth_state(runner, counter_c)
    client_c = _FakeClient(is_logged_in_seq=[True])
    client_c._page = None  # 强制走 initialize 分支
    ok = await runner._login_flow(client_c, "kimi", max_wait=60)
    assert ok is True, "无 page 时 initialize 后探测成功应返回 True"
    assert client_c.init_calls == 1, "_page=None 应调 initialize(fresh=True)"
    assert counter_c["calls"] == 1

    print("✅ PASS: _login_flow 只在确认登录后保存一次，未登录超时不保存，无 page 时自动 initialize")


if __name__ == "__main__":
    asyncio.run(main())
```

> 注意：`_login_flow` 内部用 `asyncio.sleep(3)` 轮询，测试用 `max_wait=6`（2 轮）和 `max_wait=60` 但序列第 2 个即 True，实际等待约 6s。可接受。

- [ ] **Step 2: Run test to verify it fails**

Run: `python scripts/test_login_flow.py`
Expected: FAIL — `AttributeError: module 'local_webchat_runner' has no attribute '_login_flow'`。

- [ ] **Step 3: Update import to include `save_auth_state`**

把 `scripts/local_webchat_runner.py:71`：

```python
from web_chat_auth import has_auth_state
```

改为：

```python
from web_chat_auth import has_auth_state, save_auth_state
```

- [ ] **Step 4: Add `_login_flow` coroutine**

在 `scripts/local_webchat_runner.py` 中、`async def run_local_eval(...)` 定义之前（或文件内任意模块级函数区，确保在 `run_local_eval` 引用前定义）插入：

```python
async def _login_flow(client, mk: str, max_wait: int = 300) -> bool:
    """--headed 下引导登录：确保浏览器开着 → 导航一次 → 轮询 _is_logged_in → 确认后才保存。

    只在 _is_logged_in 确认登录后调 save_auth_state，杜绝提前保存不完整 state。
    导航只做一次（_goto_site），轮询时不重复 goto（否则会打断用户正在进行的登录）。
    返回是否最终登录成功。
    """
    # 确保浏览器开着（无存档时 initialize(fresh=True) 开全新 context）
    if client._page is None:
        if not await client.initialize(fresh=True):
            print(f"  ❌ {client.name} 无法启动浏览器，跳过登录")
            return False
    # 导航到站点一次；之后只探测、不重新 goto
    await client._goto_site(client._page)
    name = client.name
    print(f"\n  → 请在浏览器窗口登录 {name}（{client.url}）")
    print(f"    登录完成后会自动检测并保存，无需手动按 Enter。")
    elapsed = 0
    while elapsed < max_wait:
        await asyncio.sleep(3)
        elapsed += 3
        try:
            if await client._is_logged_in(client._page, timeout=5):
                try:
                    state = await client._context.storage_state()
                    save_auth_state(mk, state)
                    print(f"  ✅ {name} 登录已检测并保存（{len(state.get('cookies', []))} cookies）")
                    return True
                except Exception as e:
                    print(f"  ❌ {name} 保存登录态失败: {e}")
                    return False
        except Exception as e:
            print(f"    ⚠️ {name} 探测异常（继续等待）: {e}")
        print(f"    ... 等待 {name} 登录（{max_wait - elapsed}s）")
    print(f"  ⚠️ {max_wait}s 未检测到 {name} 登录，不保存、跳过该模型")
    return False
```

> `_login_flow` 的探测包了 try/except：单次探测异常不致命（继续等），避免 fake/真实偶发异常直接中断登录等待。注意测试 C 的 `_FakeClient.initialize` 不校验 `fresh`，真实 `initialize(fresh=True)` 由 Task 1 保证。

- [ ] **Step 5: Replace the pre-check block (`local_webchat_runner.py:284-311`)**

把原预检块（从 `# ── 登录预检` 注释行到 `return` 那行，即 `local_webchat_runner.py:284-311`）整段替换为：

```python
    # ── 登录预检：对每个模型真实探测"能不能聊天"；没登录则 --headed 引导登录后保存 ──
    # 用真实 DOM 探测（输入框可见 + 非登录页 URL），取代旧的 has_auth_state（文件存在）
    # 和手动按 Enter；杜绝"提前保存不完整 state"和"跑到一半才挂"。
    print("\n[登录预检] 逐模型探测登录态...")
    not_logged_in: List[str] = []
    for mk in model_keys:
        client = create_web_chat_client(mk)
        logged_in = False
        try:
            if client.is_configured and await client.initialize():
                await client._goto_site(client._page)
                logged_in = await client._is_logged_in(client._page)
            if not logged_in:
                print(f"  {mk}: 未登录" + ("" if client.is_configured else "（无存档）"))
                if headed:
                    logged_in = await _login_flow(client, mk)
            if not logged_in:
                not_logged_in.append(mk)
            else:
                print(f"  {mk}: 已登录 ✓")
        except Exception as e:
            print(f"  {mk}: 探测异常 {e}，按未登录处理")
            not_logged_in.append(mk)
        finally:
            await client.close()

    if not_logged_in:
        if headed:
            print(f"\n  ⚠️ 以下模型未登录成功，将被跳过: {', '.join(not_logged_in)}")
        else:
            print(f"\n  ⚠️ 以下模型未登录，且非 --headed 无法弹浏览器登录，将被跳过: {', '.join(not_logged_in)}")
            print(f"  （加 --headed 可弹浏览器登录）")

    # 全部模型未登录 → 中止，不产出空结果
    if all(mk in not_logged_in for mk in model_keys):
        print("\n❌ 所有模型均未登录，已中止，未生成结果文件。")
        print("   请用 --headed 模式运行以弹出浏览器登录，或先运行 setup_webchat_auth.py。")
        return
```

> 旧分支 `from setup_webchat_auth import setup_auth` 与 `setup_auth(mk)` 调用被整段取代，不再依赖手动按 Enter、不再依赖 cookie 名单。

- [ ] **Step 6: Run test to verify it passes**

Run: `python scripts/test_login_flow.py`
Expected: `✅ PASS: _login_flow 只在确认登录后保存一次，未登录超时不保存，无 page 时自动 initialize`

- [ ] **Step 7: Re-run Task 1 test to confirm no regression**

Run: `python scripts/test_is_logged_in.py`
Expected: `✅ PASS: ...`

- [ ] **Step 8: Smoke-check runner imports cleanly**

Run: `python -c "import importlib.util,os,sys; spec=importlib.util.spec_from_file_location('r','scripts/local_webchat_runner.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('ok', hasattr(m,'_login_flow'))"`
Expected: `ok True`

- [ ] **Step 9: Commit**

```bash
git add scripts/local_webchat_runner.py scripts/test_login_flow.py
git commit -m "feat(local-runner): 跑前 DOM 探测登录态 + 确认登录后才保存 + 继续跑"
```

---

### Task 3: 全量自检 + 端到端手测说明

**Files:**
- 无新文件；运行现有自检脚本并记录结果。

**Interfaces:**
- Consumes: Task 1 / Task 2 产出的测试脚本与方法。

- [ ] **Step 1: Run all related self-checks**

Run（在仓库根 `C:\Users\Administrator\ucloud-geo-eval`）：

```bash
python scripts/test_is_logged_in.py
python scripts/test_login_flow.py
python scripts/test_classify_content_signal.py
```

Expected: 三个脚本均打印 `✅ PASS: ...`。

- [ ] **Step 2: Commit any remaining changes (if none, skip)**

如果 Step 1 后无代码改动，跳过 commit（Task 1/2 已各自提交）。

- [ ] **Step 3: Document end-to-end manual test (hand to user)**

向用户说明手测步骤（不自动执行，需要真实浏览器+真实登录）：

```
端到端手测（需真实浏览器，交给用户）：
1. 用现有不完整的 kimi 登录态（data/webchat_auth/kimi_state.json，仅 ~6 cookies）
   运行：
   python scripts/local_webchat_runner.py --config <task3_batch_config.json> --headed
2. 预期：[登录预检] 识别 kimi 未登录（输入框不可见/登录页）→ 弹浏览器 → 终端提示
   "请在浏览器窗口登录 Kimi"。
3. 在浏览器手动登录 Kimi → 终端自动检测并保存（cookie 数应明显 >6）→ 打印
   "kimi: 已登录 ✓" → 继续评测，kimi 不再报登录墙/SyntaxError。
4. 若某模型 300s 内未登录 → 不保存、跳过该模型、其余模型继续。
```

- [ ] **Step 4: Commit plan-tracking note to ledger**

在 `.git/sdd/progress.md`（若不存在则创建）追加：

```
local-runner-login-recovery: Task1+Task2 complete (commits 见上), 自检 3/3 PASS, 端到端手测待用户验证。
```

> ledger 是 subagent-driven 恢复地图；Task 1/2 提交后即写入，便于上下文压缩后恢复。

---

## 验证（汇总）

1. `python scripts/test_is_logged_in.py` → `✅ PASS`。
2. `python scripts/test_login_flow.py` → `✅ PASS`。
3. `python scripts/test_classify_content_signal.py` → `✅ PASS`（回归，确保未误改）。
4. `python -c "...inspect..."` 与 smoke-import 检查签名/导入干净。
5. 端到端手测（见 Task 3 Step 3）交给用户：kimi 不完整 state → 识别未登录 → 弹登录 → 确认后保存 → 继续跑。
6. 不部署服务器；`git push origin master` 仅版本管理。
