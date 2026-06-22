"""Deterministic fixture agent (plan task 4).

Returns fixed, schema-valid :class:`~genclaw.schemas.CanvasPlan` objects for
known prompts, with no model call or credentials. This is the credential-free
smoke path (ADR 0004): it exercises orchestration, artifacts, rendering, and
review end to end without reproducing photorealism.

Selection is by keyword:

* ``three red circles`` -> 3-circle SVG composition (GenEval++-style).
* ``poster``            -> HTML long-text poster (LongText-Bench-style).
* ``mirror``            -> Three.js physical-reasoning scene.

An unknown prompt raises so callers fail loudly rather than silently producing
an empty canvas. All plans are ``source="structured"`` (phase 1).
"""

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
    """Raised when no fixture matches a prompt."""


class FixtureAgent(AgentProvider):
    """Deterministic, credential-free plan source for known prompts."""

    def conceptualize(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        request_id: Optional[str] = None,
    ) -> CanvasPlan:
        rid = request_id or "fixture"
        low = prompt.lower()
        if "three red circles" in low:
            return _three_red_circles(prompt, rid)
        if "poster" in low:
            return _poster(prompt, rid)
        if "mirror" in low:
            return _mirror(prompt, rid)
        raise FixtureAgentError(
            f"no fixture plan for prompt {prompt!r}; "
            "known keywords: 'three red circles', 'poster', 'mirror'"
        )


def _three_red_circles(prompt: str, request_id: str) -> CanvasPlan:
    """Three red circles on the left -> SVG composition."""
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
        checks=[
            ReviewCheck(kind="backend", expected="svg"),
            ReviewCheck(kind="object_count", target="circle", expected=3),
            ReviewCheck(kind="image_size", expected="512x512"),
        ],
    )


def _poster(prompt: str, request_id: str) -> CanvasPlan:
    """A poster -> HTML long-text plan that preserves exact text."""
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
    """A mirror reflection scene -> Three.js physical reasoning plan.

    Objects use deterministic 3D coordinates carried in ``attributes`` so the
    Three.js renderer (task 8) builds a stable scene: ground, mirror, sphere,
    plus a directional light and camera.
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
