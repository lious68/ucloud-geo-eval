"""qwen 登录 cookie 校验自检。

证据（diag_webchat_cookies.py qwen 实测）：qwen 登录后写入的登录态 cookie 是
tongyi_sso_ticket（httpOnly, 1年, .qianwen.com）与 b-user-id，而非 auth_cookies
里旧列的 login_sid/token/.../login_aliyunid（这些 qwen 根本不写）。

本测试构造一个真实登录态的 qwen storageState，断言 validate_auth_cookies 判定有效。
"""
import asyncio
import os
import sys
import json
import time
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import web_chat_auth
from web_chat_auth import validate_auth_cookies, save_auth_state


def _cookie(name, domain, expires=None, httpOnly=True):
    return {
        "name": name, "value": "x", "domain": domain, "path": "/",
        "expires": expires if expires is not None else -1,
        "httpOnly": httpOnly, "secure": False, "sameSite": "Lax",
    }


def _qwen_logged_in_state():
    """模拟 diag 实测的 qwen 已登录 cookie 集（精简到关键 + 几个干扰项）。"""
    fut = time.time() + 365 * 86400
    return {"cookies": [
        _cookie("tongyi_sso_ticket", ".qianwen.com", fut),       # ★ 真正的登录票据
        _cookie("tongyi_sso_ticket_hash", ".qianwen.com", fut),
        _cookie("b-user-id", "www.qianwen.com", fut),            # ★ 用户标识
        _cookie("cna", ".qianwen.com", fut),                     # 设备号（登录前也有）
        _cookie("tfstk", ".qianwen.com", fut),                   # 跟踪
        _cookie("XSRF-TOKEN", "www.qianwen.com"),                # csrf（登录前也有）
    ], "origins": []}


def _qwen_logged_out_state():
    """未登录/登录中途：b-user-id 在登录完成前就写入（浏览器指纹，非登录态），
    必须不含 tongyi_sso_ticket 才判无效。"""
    fut = time.time() + 365 * 86400
    return {"cookies": [
        _cookie("b-user-id", "www.qianwen.com", fut),   # 登录前就有，不能据此判已登录
        _cookie("cna", ".qianwen.com", fut),
        _cookie("tfstk", ".qianwen.com", fut),
        _cookie("XSRF-TOKEN", "www.qianwen.com"),
    ], "origins": []}


def main():
    tmp = tempfile.mkdtemp()
    web_chat_auth.AUTH_DIR = tmp  # 隔离，不污染真实 data/webchat_auth

    # 已登录态：必须判有效
    save_auth_state("qwen", _qwen_logged_in_state())
    v = validate_auth_cookies("qwen")
    assert v["is_valid"], (
        f"已登录的 qwen 应判有效，实得 is_valid=False。matched={v['matched_cookies']}"
    )
    assert "tongyi_sso_ticket" in v["matched_cookies"], (
        f"应命中 tongyi_sso_ticket，实得 matched={v['matched_cookies']}"
    )
    print(f"  已登录态: is_valid={v['is_valid']} matched={v['matched_cookies']}")

    # 未登录态：必须判无效
    save_auth_state("qwen", _qwen_logged_out_state())
    v2 = validate_auth_cookies("qwen")
    assert not v2["is_valid"], (
        f"未登录的 qwen 应判无效，实得 is_valid=True matched={v2['matched_cookies']}"
    )
    print(f"  未登录态: is_valid={v2['is_valid']} matched={v2['matched_cookies']}")

    print("✅ PASS: qwen 登录 cookie 校验（tongyi_sso_ticket 为登录态标志）")


if __name__ == "__main__":
    main()
