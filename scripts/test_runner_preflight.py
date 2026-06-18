"""runner 登录预检自检（不真开浏览器，mock setup_auth / EvalScheduler）：

  A. headless + 全无登录态 → 中止，不构造调度器，不写结果文件
  B. headed + 全无登录态 → 对每个模型调用 setup_auth(mock)，mock 不真正建态 → 仍中止
  C. 有登录态 → 不调 setup_auth，构造调度器并 run(mock)
"""
import asyncio
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import local_webchat_runner as R


def _fake_questions(n=2):
    return [{"id": f"Q{i+1}", "question": f"Q{i+1}", "category": "test",
             "question_type": "direct", "tags": [], "difficulty": "medium"} for i in range(n)]


class FakeScheduler:
    constructed = 0
    ran = 0

    def __init__(self, **kw):
        FakeScheduler.constructed += 1

    async def run(self):
        FakeScheduler.ran += 1
        return {"done": 0}


def main():
    tmp = tempfile.mkdtemp()
    R.EvalScheduler = FakeScheduler
    R._save_manifest = lambda *a, **k: None
    R.SqliteUnitStore = lambda path: object()  # 避免落盘

    # --- A. headless + 全无登录态 → 中止 ---
    FakeScheduler.constructed = FakeScheduler.ran = 0
    R.has_auth_state = lambda mk: False
    out = os.path.join(tmp, "a.json")
    asyncio.run(R.run_local_eval(
        model_keys=["deepseek"], questions=_fake_questions(2),
        output_path=out, headed=False, name="t",
    ))
    assert FakeScheduler.constructed == 0, "headless 全无登录态不应构造调度器"
    assert not os.path.exists(out), "中止不应写结果文件"
    print("✅ PASS: A. headless 全无登录态 → 中止")

    # --- B. headed + 全无登录态 → 逐个调 setup_auth(mock)，仍中止 ---
    FakeScheduler.constructed = FakeScheduler.ran = 0
    calls = []

    async def fake_setup(mk):
        calls.append(mk)
        return True

    fake_mod = types.ModuleType("setup_webchat_auth")
    fake_mod.setup_auth = fake_setup
    sys.modules["setup_webchat_auth"] = fake_mod
    R.has_auth_state = lambda mk: False  # mock setup_auth 不真正建态
    out = os.path.join(tmp, "b.json")
    asyncio.run(R.run_local_eval(
        model_keys=["deepseek", "doubao"], questions=_fake_questions(2),
        output_path=out, headed=True, name="t",
    ))
    assert set(calls) == {"deepseek", "doubao"}, f"应对每个无态模型调 setup_auth: {calls}"
    assert FakeScheduler.constructed == 0, "setup_auth(mock) 未真正建态 → 仍应中止"
    assert not os.path.exists(out), "中止不应写结果文件"
    print("✅ PASS: B. headed 全无登录态 → 逐个弹登录后中止")

    # --- C. 有登录态 → 不调 setup_auth，构造调度器并 run ---
    FakeScheduler.constructed = FakeScheduler.ran = 0
    calls.clear()
    R.has_auth_state = lambda mk: True
    out = os.path.join(tmp, "c.json")
    asyncio.run(R.run_local_eval(
        model_keys=["deepseek"], questions=_fake_questions(2),
        output_path=out, headed=True, name="t",
    ))
    assert calls == [], "有登录态不应调 setup_auth"
    assert FakeScheduler.constructed == 1 and FakeScheduler.ran == 1, "有登录态应构造并运行调度器"
    print("✅ PASS: C. 有登录态 → 直接调度（不弹登录）")

    print("\n🎉 全部预检自检通过")


if __name__ == "__main__":
    main()
