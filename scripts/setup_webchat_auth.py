"""
WebChat 登录认证设置脚本
在本机 Windows 上运行，打开可见浏览器窗口让用户手动登录各 AI 模型官网，
登录完成后保存认证状态（Playwright storageState JSON 文件）

使用方式:
    python scripts/setup_webchat_auth.py kimi     # 只设置 Kimi
    python scripts/setup_webchat_auth.py all       # 设置所有支持的模型
"""
import asyncio
import sys
import os
import json

# Windows 控制台 UTF-8 支持
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from web_chat_auth import WEBCHAT_SITES, save_auth_state, ensure_auth_dir, AUTH_DIR, load_auth_state

SUPPORTED_MODELS = ["kimi", "deepseek", "ernie", "doubao", "qwen"]


async def setup_auth(model_key: str):
    """打开浏览器让用户手动登录，然后保存认证状态"""
    from playwright.async_api import async_playwright

    site = WEBCHAT_SITES.get(model_key)
    if not site:
        print(f"❌ 未知模型: {model_key}")
        return False

    # 检查是否已有认证状态（用于增量更新）
    existing_state = load_auth_state(model_key)

    print(f"\n{'='*50}")
    print(f"  设置 {site['name']} ({site['url']}) 的登录认证")
    if existing_state:
        cookie_count = len(existing_state.get("cookies", []))
        print(f"  ℹ️ 已有 {cookie_count} 个 cookie，将在此基础上更新")
    print(f"{'='*50}")
    print(f"  即将打开浏览器窗口，请手动登录 {site['name']}")
    print(f"  登录完成后，回到此终端按 Enter 键保存登录状态")
    print(f"{'='*50}\n")

    pw = await async_playwright().start()

    # 优先使用系统 Chrome（更难被网站检测为自动化）
    try:
        browser = await pw.chromium.launch(channel="chrome", headless=False, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox",
        ])
        print(f"  🌐 使用系统 Chrome 浏览器")
    except Exception:
        browser = await pw.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox",
        ])
        print(f"  ⚠️ 未检测到系统 Chrome，使用 Playwright Chromium")

    # 反自动化检测
    stealth_js = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
    """
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

    # 尝试加载旧 cookie 访问，如果触发验证码则自动切换干净模式
    load_old_cookies = existing_state is not None

    for attempt in range(2):
        ctx_kwargs = {"viewport": {"width": 1280, "height": 800}, "user_agent": user_agent}
        if load_old_cookies and existing_state:
            ctx_kwargs["storage_state"] = existing_state
            print(f"  📋 尝试加载旧 cookie 访问...")
        else:
            print(f"  🆕 不加载旧 cookie，全新打开页面...")

        context = await browser.new_context(**ctx_kwargs)
        await context.add_init_script(stealth_js)
        page = await context.new_page()

        try:
            await page.goto(site["url"], wait_until="networkidle", timeout=30000)
        except Exception:
            try:
                await page.goto(site["url"], wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass

        await asyncio.sleep(5)

        # 检测是否触发验证码/页面空白（旧 cookie 失效的标志）
        url = page.url
        element_count = await page.evaluate("() => document.querySelectorAll('*').length")
        if ("svcp_stk" in url or element_count < 20) and load_old_cookies:
            print(f"  ⚠️ 旧 cookie 已失效，触发验证码/页面空白，自动切换为全新模式")
            await context.close()
            load_old_cookies = False
            continue
        break

    if load_old_cookies and existing_state:
        print(f"  ✅ 已加载现有认证状态，浏览器将以已登录状态打开")
    else:
        print(f"  ✅ 页面已打开（全新模式）")

    print(f"  请确认登录状态是否有效（如已登录可直接按 Enter；如未登录请先登录）")

    # 等待用户确认：支持交互式 input 或创建信号文件
    signal_file = os.path.join(os.path.dirname(__file__), ".webchat_done")
    print(f"\n  确认登录有效后，请按 Enter 键保存状态...")
    print(f"  （或在项目 scripts/ 目录下创建 .webchat_done 文件）")
    try:
        input()
        print("  [DEBUG] Enter 已接收")
    except EOFError:
        # 非交互式环境，等待信号文件
        print(f"  非交互式环境，等待信号文件: {signal_file}")
        while not os.path.exists(signal_file):
            await asyncio.sleep(1)
        os.remove(signal_file)
        print(f"  ✅ 检测到确认信号")

    # 保存认证状态
    try:
        print("  [DEBUG] 正在保存认证状态...")
        ensure_auth_dir()
        print("  [DEBUG] ensure_auth_dir 完成")
        state = await context.storage_state()
        print(f"  [DEBUG] storage_state 获取成功，cookie数={len(state.get('cookies', []))}")
        path = save_auth_state(model_key, state)
        print(f"  [DEBUG] 文件已写入: {path}")

        cookie_count = len(state.get("cookies", []))
        origin_count = len(state.get("origins", []))
        print(f"\n  ✅ 认证状态已保存!")
        print(f"  文件: {path}")
        print(f"  Cookie 数: {cookie_count}")
        print(f"  LocalStorage 项: {origin_count}")
        print(f"\n  下一步: 将此文件上传到服务器的「系统设置 → WebChat 登录状态」页面")
        print(f"  文件路径: {path}")
    except Exception as e:
        print(f"  ❌ 保存失败: {e}")

    try:
        print("  [DEBUG] 正在关闭浏览器...")
        await browser.close()
        await pw.stop()
        print("  [DEBUG] 浏览器已关闭")
    except Exception as e:
        print(f"  ⚠️ 关闭浏览器异常: {e}")

    return True


async def setup_all():
    """设置所有支持的模型"""
    print("\n🌐 WebChat 登录认证批量设置")
    print(f"  当前支持的模型: {', '.join(SUPPORTED_MODELS)}")

    for model_key in SUPPORTED_MODELS:
        success = await setup_auth(model_key)
        if not success:
            continue

    print("\n✅ 全部设置完成!")
    print(f"  认证文件保存在: {AUTH_DIR}")
    print(f"  请将这些文件上传到服务器")


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/setup_webchat_auth.py <model_key>")
        print(f"  可选模型: {', '.join(SUPPORTED_MODELS)}, all")
        print("\n示例:")
        print("  python scripts/setup_webchat_auth.py kimi    # 设置 Kimi")
        print("  python scripts/setup_webchat_auth.py all      # 设置所有支持的模型")
        sys.exit(1)

    model_key = sys.argv[1].lower()

    if model_key == "all":
        asyncio.run(setup_all())
    else:
        asyncio.run(setup_auth(model_key))


if __name__ == "__main__":
    main()