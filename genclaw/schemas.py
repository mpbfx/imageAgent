"""Core schema: the central ``CanvasPlan`` contract.

This module is the single most important contract in the reproduction. Per
ADR 0001 it is the *central contract* that both renderers and the reviewer
consume; per ADR 0003 its fields are derived from the four benchmark task
families (GenEval++ composition, LongText-Bench long text, ImgEdit local
editing, Mind-Bench knowledge/reasoning) rather than the three phase-1
fixtures.

ADR 0003 also requires the schema to distinguish two canvas *sources*:

* ``structured`` -- the canvas is compiled from validated fields by a
  schema-owned template (phase 1).
* ``code`` -- the canvas is free-form source code emitted by an LLM and
  rendered after static validation in a sandbox (phase 2). Phase 1 reserves
  the ``code_source`` / ``code_lang`` fields but does not compile them.

The module has no third-party dependency beyond Pydantic, so it imports and
validates without a browser or any provider credentials.
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
    """Executable canvas backends (paper §3.2).

    The paper lists SVG (composition/layers), HTML/CSS (text-intensive), and
    "Python plotting, Canvas, or a simple 3D script" for physical/geometric
    tasks. We model Python and Canvas as distinct backends from Three.js because
    the paper uses them for *numeric* physical drafts (springs, pressure,
    buoyancy) where Three.js (a 3D scene) is not the right tool.
    """

    svg = "svg"
    html = "html"
    three = "three"
    python = "python"  # Python plotting (e.g. matplotlib) for physical drafts
    canvas = "canvas"  # 2D Canvas script for geometric/physical references


class CanvasSource(str, Enum):
    """Where the canvas code comes from (ADR 0003)."""

    structured = "structured"  # template-compiled from fields (phase 1)
    code = "code"  # free-form source + validation (phase 2)


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
    # Free-form backend-specific attributes (e.g. polygon "points", radius).
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
    """A declarative, deterministic check the reviewer must run.

    ``kind`` selects the rule; ``target`` and ``expected`` parameterize it.
    See :mod:`genclaw.review.rules` for the supported kinds.
    """

    kind: str  # "object_count" | "contains_text" | "backend" | "artifact_exists" | "image_size"
    target: Optional[str] = None
    expected: Union[str, int, float, bool, None] = None


class EditOp(BaseModel):
    """A localized edit instruction (ImgEdit family).

    Phase 1 records edits structurally so the editing fixture and harness have
    a contract; the real VLM-layering + SAM3 + inpainting mechanism is phase 2.
    """

    op: Literal["move", "recolor", "resize", "remove", "add"]
    target_id: Optional[str] = None
    params: dict = Field(default_factory=dict)


class KnowledgeRef(BaseModel):
    """A retrieved fact for knowledge-grounded generation (Mind-Bench).

    Produced by the search node when the cognitive layer fills a knowledge gap
    (paper §3.2: "the agent calls search tools to complete the relevant facts").
    ``source`` records the URL/origin so the Review layer can trace and verify
    the retrieved context (paper §3.1: "verify the accuracy of the URL contents
    retrieved by the search tool").
    """

    claim: str
    source: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ReasoningStep(BaseModel):
    """An explicit intermediate conclusion from the cognitive layer.

    The paper's reasoning pillar (§3.2): for math/geography/physics tasks the
    agent "first explicitly obtains intermediate conclusions ... and then
    converts implicit relations into visual constraints" (e.g. computes a
    geometry answer, or parses physical variables, before rendering). Recording
    these makes the reasoning inspectable and traceable, like KnowledgeRef does
    for retrieved facts.
    """

    question: str  # what had to be reasoned out (e.g. "reflection position")
    conclusion: str  # the derived intermediate result, as text
    # Optional numeric/structured values the conclusion yields, consumed by the
    # canvas layer as visual constraints (e.g. {"angle": 45, "x": 120}).
    values: dict = Field(default_factory=dict)


class CanvasPlan(BaseModel):
    """The central contract shared by renderers and the reviewer.

    A plan is either ``structured`` (template-compiled, phase 1) or ``code``
    (free-form source, phase 2). The discriminant is :attr:`source`.
    """

    request_id: str
    prompt: str
    task_type: TaskType
    backend: CanvasBackend
    size: CanvasSize

    source: CanvasSource = CanvasSource.structured

    # Structured payload (used when source == structured).
    layers: list[LayerSpec] = Field(default_factory=list)
    objects: list[ObjectSpec] = Field(default_factory=list)
    text: list[TextSpec] = Field(default_factory=list)
    relations: list[RelationSpec] = Field(default_factory=list)

    # Edit / knowledge / reasoning payloads for the editing and
    # knowledge-grounded families. ``knowledge`` is filled by the search node;
    # ``reasoning`` records the cognitive layer's intermediate conclusions.
    edits: list[EditOp] = Field(default_factory=list)
    knowledge: list[KnowledgeRef] = Field(default_factory=list)
    reasoning: list[ReasoningStep] = Field(default_factory=list)

    # Free-form code payload (reserved for phase 2; not compiled in phase 1).
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
        """Layers sorted by render order (ascending)."""
        return sorted(self.layers, key=lambda layer: layer.order)


class ReviewResult(BaseModel):
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
