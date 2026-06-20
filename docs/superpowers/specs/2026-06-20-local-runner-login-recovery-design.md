# 本地 Runner 跑前登录探测 + 登录后保存再跑

## Context（为什么做）

`local_webchat_runner.py` 已有"登录预检"（`local_webchat_runner.py:284-311`），但用 `has_auth_state(mk)`（"文件存在"）判定——kimi 的存档有 `kimi-auth` 但只 6 个 cookie、是不完整/未真正登录的 state，照样通过预检，跑到一半才挂（登录墙 → 提取失败 → 此前还触发 SyntaxError）。

`setup_webchat_auth_auto.py` 的自动保存又依赖 `LOGIN_DETECT_COOKIES` 名单，那份名单脆弱（qwen 走了两轮、kimi 的 `kimi-auth` 会在登录中途提前出现导致过早保存不完整 state）。

目标：**跑前用真实浏览器探测"能不能聊天"**（输入框可见），没真登录就在 `--headed` 下弹浏览器让用户登录、**探测确认登录后才保存**、再继续跑。绕开 cookie 名单脆弱性，直接杜绝"提前保存不完整 state"。范围：仅本地 runner 跑前；不做跑中恢复；不动服务端。

## 关键事实（已确认）

- 预检块在 `local_webchat_runner.py:284-311`：`missing_auth = [mk for mk in model_keys if not has_auth_state(mk)]`；`--headed` 下对每个 missing 调 `setup_auth(mk)`（`setup_webchat_auth.py` 手动按 Enter 版）；全部无态则中止（`local_webchat_runner.py:308-311`）。
- `WebChatClientBase.initialize()`（`web_chat_clients.py:55-110`）：`is_configured`（有存档）才开浏览器，`new_context(storage_state=self._auth_state, ...)`；无存档返回 False。开浏览器后 `self._page` 已建但**不导航**。
- 每个模型客户端有类属性 `INPUT_SELECTOR`（`web_chat_clients.py` 各子类），已是逐模型定义。
- `save_auth_state(model_key, state)`（`web_chat_auth.py:79`）写 `data/webchat_auth/<mk>_state.json`。`create_web_chat_client(mk)`（`web_chat_clients.py:1450`）工厂。
- 调度器在预检**之后**才通过 `client_factory` 懒创建评测客户端（`local_webchat_runner.py:375-393`）。预检用的客户端是临时的，探测/登录完即 `close()`，评测时调度器另建新客户端加载已保存的有效 state。

## 设计

### 1. `WebChatClientBase.initialize()` 增 `fresh` 形参

`web_chat_clients.py:55` 签名改为 `async def initialize(self, fresh: bool = False) -> bool`：

- `fresh=False`（默认，给评测用）：维持现状——`is_configured` 为 False 则返回 False；`new_context(storage_state=self._auth_state)`。
- `fresh=True`（给登录流程用）：**不要求** `is_configured`，`new_context` 不传 `storage_state`（全新 context），其余（stealth、viewport、user_agent、`add_init_script`、`new_page`）不变。返回 True。

这样无存档的模型也能开浏览器登录。

### 2. 新增 `WebChatClientBase._is_logged_in()` 与 `_goto_site()`

`_is_logged_in` **只探测当前页**（不导航）——否则登录轮询时每 3s 重新 goto 会打断用户正在进行的登录。导航由调用方事先做一次。

```python
LOGIN_URL_HINTS = ("login", "passport", "signin", "sso")

async def _goto_site(self, page) -> None:
    """导航到站点首页一次（探测/登录前调用）。失败静默，由 _is_logged_in 兜底。"""
    try:
        await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        try:
            await page.goto(self.url, wait_until="commit", timeout=30000)
        except Exception:
            pass

async def _is_logged_in(self, page, timeout: int = 15) -> bool:
    """真实登录态探测（只看当前页，不导航）：URL 不在登录页 且 聊天输入框可见。

    子类可覆盖以提供更精确的信号（默认用 INPUT_SELECTOR 可见性 + URL 反向信号）。
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

`LOGIN_URL_HINTS` 作类属性。默认实现用 `INPUT_SELECTOR`；ernie 等选择器偏宽的模型可在子类覆盖 `_is_logged_in`（同现有聊天选择器的逐模型微调节奏）。

### 3. 登录流程 `_login_flow()`（runner 内）

```python
async def _login_flow(client, mk: str, max_wait: int = 300) -> bool:
    """--headed 下引导登录：确保浏览器开着 → 提示 → 轮询 _is_logged_in → 确认后才保存。

    只在探测确认登录后调 save_auth_state，杜绝提前保存不完整 state。
    返回是否最终登录成功。
    """
    # 确保浏览器开着（无存档时 initialize(fresh=True)）
    if client._page is None:
        if not await client.initialize(fresh=True):
            return False
    # 导航到站点一次；之后只探测、不重新 goto（否则会打断用户登录）
    await client._goto_site(client._page)
    name = client.name
    print(f"\n  → 请在浏览器窗口登录 {name}（{client.url}）")
    print(f"    登录完成后会自动检测并保存，无需手动按 Enter。")
    elapsed = 0
    while elapsed < max_wait:
        await asyncio.sleep(3)
        elapsed += 3
        if await client._is_logged_in(client._page, timeout=5):
            try:
                state = await client._context.storage_state()
                save_auth_state(mk, state)
                print(f"  ✅ {name} 登录已检测并保存（{len(state.get('cookies', []))} cookies）")
                return True
            except Exception as e:
                print(f"  ❌ {name} 保存登录态失败: {e}")
                return False
        print(f"    ... 等待 {name} 登录（{max_wait - elapsed}s）")
    print(f"  ⚠️ {max_wait}s 未检测到 {name} 登录，不保存、跳过该模型")
    return False
```

### 4. 替换预检块（`local_webchat_runner.py:284-311`）

```python
# ── 登录预检：对每个模型真实探测"能不能聊天"；没登录则 --headed 引导登录后保存 ──
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

if all(mk in not_logged_in for mk in model_keys):
    print("\n❌ 所有模型均未登录，已中止，未生成结果文件。")
    return
```

旧的 `from setup_webchat_auth import setup_auth` 分支被取代（不再依赖手动按 Enter、不再依赖 cookie 名单）。

### 5. 导入

`local_webchat_runner.py` 顶部 import 增 `from web_chat_auth import has_auth_state, save_auth_state`（`save_auth_state` 新增）。`has_auth_state` 保留（中止判定/其它用途）。

## 不改 / 兼容

- 调度器 `EvalScheduler`、`chat()`、限流、封号、`classify_content_signal` 全不动。
- `setup_webchat_auth.py` / `setup_webchat_auth_auto.py` 保留为独立工具，不强制改。
- 服务端 `eval_runner.py` 不动（本特性仅本地 runner）。
- `initialize(fresh=False)` 默认行为与现状一致，评测客户端调用不受影响。

## 测试

1. **`_is_logged_in` 判定逻辑单测**（`scripts/test_is_logged_in.py`）：用 fake page 对象（`url` 可设、`goto`/`sleep` no-op、`locator(...).first.is_visible(timeout)` 返回可控值），断言：
   - URL 含 `passport` → False（即使 is_visible=True）。
   - URL 无关键字 + is_visible=True → True。
   - URL 无关键字 + is_visible=False（超时）→ False。
   - `locator(...).is_visible` 抛错 → False。
2. **登录流程"只在确认登录后才保存"单测**（`scripts/test_login_flow.py`）：fake client（`_is_logged_in` 序列可控、`_context.storage_state()` 记录、`save_auth_state` 用 monkeypatch 到临时目录的计数器）：
   - 探测始终 False → 5 分钟（用小 max_wait 测）超时 → 断言 `save_auth_state` **未被调用**、返回 False。
   - 探测第 2 次 True → 断言 `save_auth_state` 被调用恰好 1 次、返回 True。
3. **手测**：用现有不完整的 `kimi_state.json`，`python scripts/local_webchat_runner.py --config ... --headed` → 应识别 kimi 未登录 → 弹登录 → 登录后自动保存（cookie 数明显多于 6）→ kimi 正常答题不再报错。

## 验证

1. `python scripts/test_is_logged_in.py` → `✅ PASS`。
2. `python scripts/test_login_flow.py` → `✅ PASS`。
3. 手测（见上）kimi 端到端。
4. 不部署到服务器（仅本地 runner）；但代码仍 `git push origin master` 以版本管理。
