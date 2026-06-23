"""确定性 fixture agent(plan task 4)。

对已知 prompt 返回固定的、schema 校验过的 :class:`~genclaw.schemas.CanvasPlan`,
不调任何模型、不需要凭据。这是 ADR 0004 要求的「无凭据冒烟路径」:
用它能端到端跑通编排、artifact、渲染、review,代价是不做写实。

按关键词路由:

* ``three red circles`` -> 3 个红圆的 SVG 构图(GenEval++ 风格)
* ``poster``            -> HTML 长文海报(LongText-Bench 风格)
* ``mirror``            -> Three.js 物理推理场景
* ``菜单`` 或 ``menu``  -> HTML 菜单,knowledge_grounded 任务(搜索测试)

未知 prompt 抛错,绝不悄悄返回一个空白画布——让上层立即看到 fixture 范围
不足。所有 plan 都是 ``source="structured"``(phase 1)。
"""

# 中文补充说明:
# Fixture agent 是整个系统的「对照样本」:
#   - 不依赖 LLM/网络 -> CI、冒烟、本地开发都能跑
#   - 三个固定 prompt 覆盖了 svg / html / three 三种 backend
#   - 任何扩展的 prompt 路径(real agent)都必须能跑通同一个 pipeline
#     才能说「系统端到端可用」——这是 fixture 的隐性契约。

from __future__ import annotations

from typing import Optional

from genclaw.agent.base import AgentProvider
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    CanvasSource,
    LayerSpec,
    ObjectSpec,
    RelationSpec,
    ReviewCheck,
    TaskType,
    TextSpec,
)


class FixtureAgentError(ValueError):
    """没有任何 fixture 与 prompt 匹配时抛出。"""


class FixtureAgent(AgentProvider):
    """确定性的、不需要凭据的 plan 来源（仅对已知 prompt 有效）。"""

    def conceptualize(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        request_id: Optional[str] = None,
        knowledge: Optional[list] = None,
    ) -> CanvasPlan:
        rid = request_id or "fixture"
        low = prompt.lower()
        # 关键词匹配是这种 agent 的唯一「认知」,清晰列出能匹配的关键词,
        # 让「未知 prompt」一定走 FixtureAgentError 分支。
        if "three red circles" in low:
            return _three_red_circles(prompt, rid)
        if "poster" in low:
            return _poster(prompt, rid)
        if "mirror" in low:
            return _mirror(prompt, rid)
        if "菜单" in prompt or "menu" in low:
            return _menu(prompt, rid)
        raise FixtureAgentError(
            f"no fixture plan for prompt {prompt!r}; "
            "known keywords: 'three red circles', 'poster', 'mirror', 'menu'"
        )


def _three_red_circles(prompt: str, request_id: str) -> CanvasPlan:
    """「三个红圆」-> SVG 构图,演示 object_count 与 spatial relation 检查。

    关键设计: 三个圆 object 都挂同一个 layer,relative position 通过显式
    y 坐标 (+130 间距) 实现; 关系用 relation 字段描述「上下」——review
    可以用这些字段做语义校验而不依赖像素级图像比对。
    """
    base = LayerSpec(id="base", name="base", order=0)
    circles = [
        ObjectSpec(
            id=f"circle-{i}",
            kind="circle",
            label="red circle",
            layer_id="base",
            x=100.0,
            y=120.0 + i * 130.0,
            width=80.0,
            height=80.0,
            fill="#d62828",
            attributes={"radius": 40.0},
        )
        for i in range(3)
    ]
    return CanvasPlan(
        request_id=request_id,
        prompt=prompt,
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        source=CanvasSource.structured,
        size=CanvasSize(width=512, height=512),
        layers=[base],
        objects=circles,
        relations=[
            RelationSpec(subject_id="circle-0", relation="above", object_id="circle-1"),
            RelationSpec(subject_id="circle-1", relation="above", object_id="circle-2"),
        ],
        # checks 是 plan 自带的「验收标准」,reviewer 会按它跑规则检查:
        # 1) backend 必须是 svg; 2) 圆的数量等于 3; 3) 渲染产物 512x512。
        checks=[
            ReviewCheck(kind="backend", expected="svg"),
            ReviewCheck(kind="object_count", target="circle", expected=3),
            ReviewCheck(kind="image_size", expected="512x512"),
        ],
    )


def _poster(prompt: str, request_id: str) -> CanvasPlan:
    """「海报」-> HTML 长文 plan,要求保留原文字。

    关键设计: 文字放在 ``text`` 字段而不是塞进 ``objects``,这样 reviewer
    的 ``contains_text`` 检查能直接在源码里搜到原文字符串(精确匹配),
    不会因为 HTML 实体编码或 CSS 拼接而漏判。
    """
    base = LayerSpec(id="base", name="poster", order=0)
    title = "Code as Brush"
    subtitle = "代码即画笔"
    body = (
        "GenClaw renders structured plans as executable canvas code, "
        "then completes them with a generative image provider."
    )
    texts = [
        TextSpec(id="title", text=title, layer_id="base", x=64, y=80,
                 width=640, height=120, font_size=56.0, color="#1d3557", align="center"),
        TextSpec(id="subtitle", text=subtitle, layer_id="base", x=64, y=210,
                 width=640, height=80, font_size=36.0, color="#457b9d", align="center"),
        TextSpec(id="body", text=body, layer_id="base", x=64, y=320,
                 width=640, height=240, font_size=22.0, color="#1d1d1d", align="left"),
    ]
    return CanvasPlan(
        request_id=request_id,
        prompt=prompt,
        task_type=TaskType.long_text,
        backend=CanvasBackend.html,
        source=CanvasSource.structured,
        size=CanvasSize(width=768, height=1024),
        layers=[base],
        text=texts,
        checks=[
            ReviewCheck(kind="backend", expected="html"),
            ReviewCheck(kind="contains_text", expected=title),
            ReviewCheck(kind="contains_text", expected=subtitle),
        ],
    )


def _mirror(prompt: str, request_id: str) -> CanvasPlan:
    """「镜面反射」-> Three.js 物理推理 plan。

    关键设计: object 的 3D 坐标统一塞进 ``attributes``(position / rotation
    / size / color / radius / look_at / fov),而不是污染 ObjectSpec 的通用
    字段。这样 Three.js renderer (task 8) 直接读 attributes 就能搭出稳定的
    场景,包括地面、镜面、球、平行光、相机,确定性强、可复现。
    """
    base = LayerSpec(id="scene", name="scene", order=0)
    objects = [
        ObjectSpec(id="ground", kind="plane", label="ground plane", layer_id="scene",
                   attributes={"position": [0, 0, 0], "rotation": [-1.5708, 0, 0],
                               "size": [10, 10], "color": "#cccccc"}),
        ObjectSpec(id="mirror", kind="mirror", label="mirror plane", layer_id="scene",
                   attributes={"position": [0, 2, -3], "rotation": [0, 0, 0],
                               "size": [6, 4], "color": "#aaccff"}),
        ObjectSpec(id="ball", kind="sphere", label="small ball", layer_id="scene",
                   attributes={"position": [0, 1, 1], "radius": 0.8, "color": "#e63946"}),
        ObjectSpec(id="key-light", kind="directional_light", label="key light",
                   layer_id="scene",
                   attributes={"position": [5, 8, 5], "intensity": 1.0}),
        ObjectSpec(id="camera", kind="camera", label="camera", layer_id="scene",
                   attributes={"position": [0, 3, 8], "look_at": [0, 1, 0],
                               "fov": 50}),
    ]
    return CanvasPlan(
        request_id=request_id,
        prompt=prompt,
        task_type=TaskType.physical_reasoning,
        backend=CanvasBackend.three,
        source=CanvasSource.structured,
        size=CanvasSize(width=640, height=480),
        layers=[base],
        objects=objects,
        relations=[
            RelationSpec(subject_id="ball", relation="in_front_of", object_id="mirror"),
        ],
        checks=[
            ReviewCheck(kind="backend", expected="three"),
            ReviewCheck(kind="object_count", target="sphere", expected=1),
        ],
    )


def _menu(prompt: str, request_id: str) -> CanvasPlan:
    """「菜单」-> HTML 菜单布局，knowledge_grounded 任务(搜索测试)。

    设计特点：task_type=knowledge_grounded，用于演示搜索节点的知识补齐。
    """
    base = LayerSpec(id="menu", name="menu", order=0)
    title = "Restaurant Menu"
    texts = [
        TextSpec(id="title", text=title, layer_id="menu", x=40, y=40,
                 width=400, height=60, font_size=32.0, color="#8B4513", align="center"),
    ]
    return CanvasPlan(
        request_id=request_id,
        prompt=prompt,
        task_type=TaskType.knowledge_grounded,
        backend=CanvasBackend.html,
        source=CanvasSource.structured,
        size=CanvasSize(width=480, height=640),
        layers=[base],
        text=texts,
        checks=[
            ReviewCheck(kind="backend", expected="html"),
            ReviewCheck(kind="contains_text", expected=title),
        ],
    )
