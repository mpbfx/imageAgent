"""Mini-benchmark fixture families (plan task 13).

A small, local, credential-free regression set -- NOT a reproduction benchmark.
It exercises the pipeline across the paper's task families so renderer/review
regressions are caught; the official benchmarks (GenEval++/LongText/ImgEdit/
Mind-Bench with official metrics) are a separate, deferred effort (task 13.5,
ADR 0004). The summary must never present these as paper-comparable scores.

Each case carries the prompt plus the expected, deterministically-checkable
properties (backend, object counts, required text) so the runner can score it
without a model or a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class BenchCase:
    """One mini-benchmark case with deterministic expectations."""

    case_id: str
    family: str
    prompt: str
    expect_backend: str
    expect_object_kinds: dict = field(default_factory=dict)  # kind -> count
    expect_texts: tuple = ()  # substrings required in the canvas source
    note: str = ""


# The mini set maps onto the three credential-free fixtures the FixtureAgent
# knows, one per paper family that phase-1 actually renders. Editing/knowledge
# families are intentionally omitted here because their real mechanisms are
# phase 2 (see reproduction-notes.md); adding fake cases would overstate
# coverage.
MINI_SUITE: tuple[BenchCase, ...] = (
    BenchCase(
        case_id="composition-three-circles",
        family="composition",  # GenEval++-style: count + layout
        prompt="three red circles on the left",
        expect_backend="svg",
        expect_object_kinds={"circle": 3},
        note="object count + spatial layout",
    ),
    BenchCase(
        case_id="long_text-poster",
        family="long_text",  # LongText-Bench-style: exact text rendering
        prompt="poster for GenClaw with title Code as Brush",
        expect_backend="html",
        expect_texts=("Code as Brush", "代码即画笔"),
        note="Chinese + English exact text",
    ),
    BenchCase(
        case_id="physical-mirror",
        family="physical_reasoning",  # geometry/physics preview
        prompt="mirror reflection of a small ball",
        expect_backend="three",
        expect_object_kinds={"sphere": 1},
        note="3D mirror scene",
    ),
)


def get_suite(name: str = "mini") -> tuple[BenchCase, ...]:
    if name == "mini":
        return MINI_SUITE
    raise ValueError(f"unknown suite {name!r}; available: 'mini'")
