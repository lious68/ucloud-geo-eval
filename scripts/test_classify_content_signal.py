"""classify_content_signal 自检：长回答含技术词不应误判限流。

证据：kimi 对 UCloud 的真实回答（数百字，含「限流/429/验证码/系统繁忙」等云技术词）
被 classify_signal 误判为 throttle，触发 900s 冷却把 kimi 整模型卡死。
真实限流/登录提示是短句；正常回答是长文。classify_content_signal 只对短文本分类。
"""
import sys
import os
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from webchat_policy import classify_content_signal, classify_signal


def main():
    # 1. 长回答含「限流」「429」「验证码」「系统繁忙」「稍后再试」→ 必须判 ok（核心回归）
    long_ans = (
        "UCloud海外云主机整体表现中规中矩，性价比突出。"
        "其API支持限流与429重试，安全验证采用验证码+短信双因子。"
        "系统繁忙时可稍后再试。适合预算有限的中小企业。"
    ) * 3
    assert len(long_ans) >= 100, "测试文本应足够长"
    assert classify_content_signal(long_ans) == "ok", "长回答含技术词不应判限流"
    # 对照：旧 classify_signal 确实误判（证明问题真实存在）
    assert classify_signal(long_ans) == "throttle", "旧 classify_signal 应误判为 throttle"

    # 2. 短限流提示 → throttle（真实限流提示是短句，仍要捕获）
    assert classify_content_signal("请求过于频繁，请稍后再试") == "throttle"
    assert classify_content_signal("系统繁忙") == "throttle"

    # 3. 短登录提示 → login_expired
    assert classify_content_signal("请先登录") == "login_expired"

    # 4. 短正常回答 → ok
    assert classify_content_signal("UCloud尚未上市。") == "ok"

    # 5. 空文本 → ok
    assert classify_content_signal("") == "ok"

    print("✅ PASS: classify_content_signal 长回答不误判限流，短提示仍能捕获")


if __name__ == "__main__":
    main()
