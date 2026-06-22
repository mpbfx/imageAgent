"""Composite reviewer: deterministic structural checks + VLM perceptual review.

The two review concerns are different and must run against different artifacts
(this separation fixes a real bug where structural checks like ``backend=svg``
were applied to the final *raster* image and always failed):

* **Structural** (backend, image_size, object_count, contains_text, ...) are
  deterministic facts about the *plan* and the *compiled canvas source*. They
  run via :class:`~genclaw.review.rules.RuleReviewer` against the canvas source,
  never the rasterized final image.
* **Perceptual** (does the final image actually show the right objects, counts,
  relations, legible text?) is a judgment about the *final image*, made by a
  VLM via :class:`~genclaw.review.vlm.VLMReviewer`.

The composite passes only if both pass; failures/warnings are merged with a
prefix so a reviewer can see which layer raised each item. The score is the
mean of the two layer scores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.review.base import Reviewer
from genclaw.review.rules import RuleReviewer
from genclaw.schemas import CanvasPlan, ReviewResult


class CompositeReviewer(Reviewer):
    """Runs structural rules on the canvas source and VLM on the final image."""

    def __init__(self, structural: Optional[Reviewer] = None, perceptual: Optional[Reviewer] = None):
        self.structural = structural or RuleReviewer()
        # Perceptual reviewer is optional: when absent (e.g. no credentials) the
        # composite degrades to structural-only rather than failing.
        self.perceptual = perceptual

    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        # Structural checks run against plan + canvas source (NOT the raster
        # image). We deliberately do not pass image_path here, so image_size
        # checks evaluate against the canvas-derived size, and backend checks
        # stay about the plan -- never about whether the final PNG "is SVG".
        structural = self.structural.review(plan, canvas_source_path=canvas_source_path)

        failures = [f"[structural] {f}" for f in structural.failures]
        warnings = [f"[structural] {w}" for w in structural.warnings]
        scores = [structural.score]
        passed = structural.passed

        if self.perceptual is not None and image_path is not None:
            perceptual = self.perceptual.review(
                plan, canvas_source_path=canvas_source_path, image_path=image_path
            )
            failures += [f"[perceptual] {f}" for f in perceptual.failures]
            warnings += [f"[perceptual] {w}" for w in perceptual.warnings]
            scores.append(perceptual.score)
            passed = passed and perceptual.passed
        elif self.perceptual is not None:
            warnings.append("[perceptual] skipped: no final image to review")

        return ReviewResult(
            passed=passed,
            score=sum(scores) / len(scores) if scores else 0.0,
            failures=failures,
            warnings=warnings,
        )
