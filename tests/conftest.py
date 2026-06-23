"""GenClaw 复现测试的共享 pytest fixture 与辅助函数。"""

import importlib.util

import pytest

# 确定性核心(schema、源码编译、review 规则、fixture agent、graph state)
# 必须在不装浏览器或 langgraph 的情况下也能 import 和测试。
# 真正需要它们的测试会被这些 skip 屏蔽掉。

_HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
_HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


def pytest_collection_modifyitems(config, items):
    skip_render = pytest.mark.skip(reason="playwright 未安装(无法光栅化 PNG)")
    skip_lg = pytest.mark.skip(reason="langgraph 未安装")
    for item in items:
        if "render" in item.keywords and not _HAS_PLAYWRIGHT:
            item.add_marker(skip_render)
        if "langgraph" in item.keywords and not _HAS_LANGGRAPH:
            item.add_marker(skip_lg)


@pytest.fixture
def tmp_run_dir(tmp_path):
    """为 artifact 测试准备一份干净的输出根目录。"""
    d = tmp_path / "outputs" / "runs"
    d.mkdir(parents=True)
    return d
