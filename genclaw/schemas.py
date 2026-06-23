"""核心 schema:全系统共享的 ``CanvasPlan`` 契约。

本模块是整个复现项目里**最重要**的契约模块(ADR 0001):renderer 和 reviewer
都消费它,它是连接认知层、渲染层、生成层、审查层的中心节点。其字段不是
按"phase-1 的三个 fixture"来设计,而是按论文里四个 benchmark 任务族
(ADR 0003:GenEval++ 组合、LongText-Bench 长文本、ImgEdit 局部编辑、
Mind-Bench 知识 / 推理)推导得出。

ADR 0003 还要求 schema 区分两种画布*源码来源*:

  * ``structured``——画布由 schema 自带的模板从校验过的字段编译出来
    (phase 1);
  * ``code``——画布是 LLM 直接产出的自由形式源码,在沙箱里经静态校验
    后再渲染(phase 2)。phase 1 预留了 ``code_source`` / ``code_lang``
    字段,但不编译它们。

本模块除 Pydantic 外没有第三方依赖,因此无需浏览器或任何 provider 凭据
即可 import 与校验。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import (
    BaseModel,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


class TaskType(str, Enum):
    """Task families. Derived from the four paper benchmarks (ADR 0003)."""

    # 任务族:对应论文的四个 benchmark(ADR 0003)。新增任务族时要同步 renderer/reviewer 的分支。
    composition = "composition"  # GenEval++: object count, layout, relations
    long_text = "long_text"  # LongText-Bench: posters, cards, pages
    physical_reasoning = "physical_reasoning"  # geometry / physics / viewpoint
    editing = "editing"  # ImgEdit: localized edits over a source plan
    knowledge_grounded = "knowledge_grounded"  # Mind-Bench: search + reasoning


class CanvasBackend(str, Enum):
    """可执行画布后端(论文 §3.2)。

    论文列出了 SVG(组合/图层)、HTML/CSS(文本密集型)、以及用于物理
    /几何任务的"Python 绘图、Canvas 或简单的 3D 脚本"。我们把 Python
    和 Canvas 与 Three.js 建模成不同的后端,是因为论文把它们用于
    *数值型*物理草图(弹簧、压力、浮力),Three.js(3D 场景)不适合那种场景。
    """

    svg = "svg"
    html = "html"
    three = "three"
    python = "python"  # Python 绘图(如 matplotlib)用于物理草图
    canvas = "canvas"  # 2D Canvas 脚本用于几何/物理参考


class CanvasSource(str, Enum):
    """画布代码的来源(ADR 0003)。"""

    structured = "structured"  # 模板从字段编译出来(phase 1)
    code = "code"  # 自由形式源码 + 校验(phase 2)


class CanvasSize(BaseModel):
    width: PositiveInt
    height: PositiveInt


class LayerSpec(BaseModel):
    id: str
    name: str = ""
    order: int = 0
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)


class ObjectSpec(BaseModel):
    id: str
    kind: str  # e.g. "circle", "rectangle", "ellipse", "polygon"
    label: str = ""
    layer_id: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    width: float = Field(default=0.0, ge=0.0)
    height: float = Field(default=0.0, ge=0.0)
    fill: Optional[str] = None
    stroke: Optional[str] = None
    # 后端特定的自由属性(如 polygon 的 "points"、circle 的 radius)。
    attributes: dict = Field(default_factory=dict)


class TextSpec(BaseModel):
    id: str
    text: str
    layer_id: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    width: float = Field(default=0.0, ge=0.0)
    height: float = Field(default=0.0, ge=0.0)
    font_size: float = Field(default=16.0, gt=0.0)
    color: str = "#000000"
    align: Literal["left", "center", "right"] = "left"


class RelationSpec(BaseModel):
    subject_id: str
    relation: str  # e.g. "left_of", "above", "in_front_of", "occludes"
    object_id: str
    strength: float = Field(default=1.0, ge=0.0, le=1.0)


class ReviewCheck(BaseModel):
    """一条声明式、确定性的 check,reviewer 必须跑它。

    ``kind`` 选规则;``target`` / ``expected`` 给出参数。具体支持的
    kind 见 :mod:`genclaw.review.rules`。
    """

    kind: str  # "object_count" | "contains_text" | "backend" | "artifact_exists" | "image_size"
    target: Optional[str] = None
    expected: Union[str, int, float, bool, None] = None


class EditOp(BaseModel):
    """一条局部编辑指令(ImgEdit 族)。

    Phase 1 把编辑以结构化形式记录下来,这样编辑 fixture 与 harness
    都有契约可循;真正的 VLM 叠加 + SAM3 + 局部重绘机制在 phase 2。
    """

    op: Literal["move", "recolor", "resize", "remove", "add"]
    target_id: Optional[str] = None
    params: dict = Field(default_factory=dict)


class KnowledgeRef(BaseModel):
    """一条为知识驱动型生成而检索到的事实(Mind-Bench)。

    由 search 节点产出,用于在认知层补全知识空白(论文 §3.2:"agent
    会调用搜索工具补全相关事实,从而填补认知空白")。``source`` 记录
    URL / 来源,review 层可以据此回溯并核验检索到的内容(论文 §3.1:
    "核验搜索工具所检索 URL 内容的准确性")。
    ``image_url`` 是可选的参考图片 URL,用于图像搜索结果(非论文原始设计,
    用于写实实体类任务的 img2img 参考)。
    """

    claim: str
    source: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    image_url: Optional[str] = None


class ReasoningStep(BaseModel):
    """认知层产出的一条显式中间结论。

    论文的推理支柱(§3.2):对于数学/地理/物理类任务,agent 会"先
    显式获得中间结论,再把隐式关系转成视觉约束"(例如在画图前
    先算几何答案、解析物理变量)。记录这些结论让推理变得可审查、
    可追溯——和 :class:`KnowledgeRef` 给"检索到的事实"做的是同一件事。
    """

    question: str  # 必须推理出的问题(例如"反射点位置")
    conclusion: str  # 推理得到的中间结论,文本形式
    # 该结论产生的可选数值 / 结构化值,canvas 层会把它当作视觉约束
    # 使用(例如 {"angle": 45, "x": 120})。
    values: dict = Field(default_factory=dict)


class CanvasPlan(BaseModel):
    """renderer 与 reviewer 共享的中心契约。

    一个 plan 要么是 ``structured``(模板编译、phase 1),要么是
    ``code``(自由源码、phase 2)。判别字段是 :attr:`source`。
    """

    request_id: str
    prompt: str
    task_type: TaskType
    backend: CanvasBackend
    size: CanvasSize

    source: CanvasSource = CanvasSource.structured

    # 结构化载荷(``source == structured`` 时使用)。
    layers: list[LayerSpec] = Field(default_factory=list)
    objects: list[ObjectSpec] = Field(default_factory=list)
    text: list[TextSpec] = Field(default_factory=list)
    relations: list[RelationSpec] = Field(default_factory=list)

    # editing 与 knowledge-grounded 任务族的载荷。``knowledge`` 由
    # search 节点填充;``reasoning`` 记录认知层的中间结论。
    edits: list[EditOp] = Field(default_factory=list)
    knowledge: list[KnowledgeRef] = Field(default_factory=list)
    reasoning: list[ReasoningStep] = Field(default_factory=list)

    # 自由形式代码载荷(预留给 phase 2;phase 1 不编译)。
    code_source: Optional[str] = None
    code_lang: Optional[Literal["svg", "html", "three", "javascript", "python"]] = None

    style: dict = Field(default_factory=dict)
    checks: list[ReviewCheck] = Field(default_factory=list)

    @field_validator("layers", "objects", "text")
    @classmethod
    def _unique_ids(cls, items, info):
        ids = [item.id for item in items]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(
                f"duplicate id(s) in {info.field_name}: {sorted(dupes)}"
            )
        return items

    @model_validator(mode="after")
    def _check_references(self) -> "CanvasPlan":
        layer_ids = {layer.id for layer in self.layers}
        element_ids = {o.id for o in self.objects} | {t.id for t in self.text}

        for obj in self.objects:
            if obj.layer_id is not None and obj.layer_id not in layer_ids:
                raise ValueError(
                    f"object {obj.id!r} references unknown layer {obj.layer_id!r}"
                )
        for txt in self.text:
            if txt.layer_id is not None and txt.layer_id not in layer_ids:
                raise ValueError(
                    f"text {txt.id!r} references unknown layer {txt.layer_id!r}"
                )
        for rel in self.relations:
            for ref in (rel.subject_id, rel.object_id):
                if ref not in element_ids:
                    raise ValueError(
                        f"relation references unknown element {ref!r}"
                    )
        for edit in self.edits:
            if edit.target_id is not None and edit.target_id not in element_ids:
                raise ValueError(
                    f"edit op {edit.op!r} references unknown element {edit.target_id!r}"
                )

        if self.source is CanvasSource.code and not self.code_source:
            raise ValueError("source='code' requires non-empty code_source")
        return self

    def ordered_layers(self) -> list[LayerSpec]:
        """按渲染顺序(升序)排序后的 layers。"""
        return sorted(self.layers, key=lambda layer: layer.order)


class ReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
