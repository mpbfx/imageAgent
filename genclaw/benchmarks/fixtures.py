"""mini-benchmark fixture 族(plan task 13)。

一小撮本地、无凭据的回归 case —— **不**是论文复现 benchmark。它跨
论文各任务族把 pipeline 跑一遍,这样 renderer / review 一旦回退就
能被抓到;官方 benchmark(GenEval++ / LongText / ImgEdit / Mind-Bench
+ 官方指标)是另一项独立、延后的工作(task 13.5,ADR 0004)。summary
里永远不能把这些分数当成论文可比对指标。

每个 case 带 prompt + 期望的、可确定性检查的属性(backend、object
count、必须出现的文本),runner 在没有模型、没有浏览器的情况下也能
打分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class BenchCase:
    """一个 mini-benchmark case,带确定性期望。"""

    case_id: str
    family: str
    prompt: str
    expect_backend: str
    expect_object_kinds: dict = field(default_factory=dict)  # kind -> count
    expect_texts: tuple = ()  # canvas 源码里必须出现的子串
    note: str = ""


# mini 套件和 FixtureAgent 认识的那三个无凭据 fixture 一一对应,
# 每个论文任务族都有一个、phase-1 真正会渲染的。editing / knowledge
# 任务族刻意不在这里:它们的真正机制是 phase 2(见 reproduction-
# notes.md),加假 case 反而会虚高覆盖率。
MINI_SUITE: tuple[BenchCase, ...] = (
    BenchCase(
        case_id="composition-three-circles",
        family="composition",  # GenEval++ 风格:数量 + 布局
        prompt="three red circles on the left",
        expect_backend="svg",
        expect_object_kinds={"circle": 3},
        note="object 数量 + 空间布局",
    ),
    BenchCase(
        case_id="long_text-poster",
        family="long_text",  # LongText-Bench 风格:文字精确呈现
        prompt="poster for GenClaw with title Code as Brush",
        expect_backend="html",
        expect_texts=("Code as Brush", "代码即画笔"),
        note="中英文精确文本",
    ),
    BenchCase(
        case_id="physical-mirror",
        family="physical_reasoning",  # 几何 / 物理预览
        prompt="mirror reflection of a small ball",
        expect_backend="three",
        expect_object_kinds={"sphere": 1},
        note="3D 镜面场景",
    ),
)


def get_suite(name: str = "mini") -> tuple[BenchCase, ...]:
    if name == "mini":
        return MINI_SUITE
    raise ValueError(f"未知 suite {name!r};目前只有 'mini'")
