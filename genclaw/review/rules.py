"""Rule-based reviewer (plan task 10).

Deterministic, browser-free checks over the plan and its rendered artifacts.
Each :class:`~genclaw.schemas.ReviewCheck` ``kind`` maps to a rule:

* ``object_count``   -- count objects of ``target`` kind; compare to ``expected``.
* ``contains_text``  -- the canvas source must contain ``expected`` text.
* ``backend``        -- the plan's backend must equal ``expected``.
* ``artifact_exists``-- the named artifact path must exist and be non-empty.
* ``image_size``     -- the rendered PNG dimensions must match (needs Pillow).

Every failure carries an explicit, human-readable reason. A check that cannot
be evaluated (e.g. image_size with no PNG) records a warning rather than a
silent pass, so missing evidence is never mistaken for success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.review.base import Reviewer
from genclaw.schemas import CanvasPlan, ReviewCheck, ReviewResult


# Tolerant aliases for check kinds an LLM agent might emit under slightly
# different names. The prompt enumerates the canonical kinds; this is a safety
# net so a near-miss is still evaluated instead of failing as "unknown".
_CHECK_ALIASES = {
    "size": "image_size",
    "canvas_size": "image_size",
    "required_text": "contains_text",
    "text": "contains_text",
    "element_count": "object_count",
    "count": "object_count",
}


class RuleReviewer(Reviewer):
    """Runs the plan's declarative checks and aggregates the result."""

    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        source_text = None
        if canvas_source_path is not None and Path(canvas_source_path).exists():
            source_text = Path(canvas_source_path).read_text(encoding="utf-8")

        failures: list[str] = []
        warnings: list[str] = []
        passed_count = 0
        evaluated = 0

        for check in plan.checks:
            ok, reason, evaluable = _run_check(check, plan, source_text, image_path)
            if not evaluable:
                warnings.append(reason)
                continue
            evaluated += 1
            if ok:
                passed_count += 1
            else:
                failures.append(reason)

        score = passed_count / evaluated if evaluated else 0.0
        return ReviewResult(
            passed=not failures and evaluated > 0,
            score=score,
            failures=failures,
            warnings=warnings,
        )


def _run_check(
    check: ReviewCheck,
    plan: CanvasPlan,
    source_text: Optional[str],
    image_path: Optional[Path],
) -> tuple[bool, str, bool]:
    """Return (passed, reason, evaluable) for a single check."""
    kind = _CHECK_ALIASES.get(check.kind, check.kind)

    if kind == "object_count":
        actual = sum(1 for o in plan.objects if o.kind == check.target)
        expected = int(check.expected)
        if actual == expected:
            return True, f"object_count[{check.target}]={actual}", True
        return (
            False,
            f"object_count[{check.target}] expected {expected} but found {actual}",
            True,
        )

    if kind == "contains_text":
        if source_text is None:
            return False, "contains_text: canvas source unavailable", False
        needle = str(check.expected)
        if needle in source_text:
            return True, f"contains_text: found {needle!r}", True
        return False, f"contains_text: missing required text {needle!r}", True

    if kind == "backend":
        actual = plan.backend.value
        if actual == str(check.expected):
            return True, f"backend={actual}", True
        return False, f"backend expected {check.expected!r} but plan uses {actual!r}", True

    if kind == "artifact_exists":
        target = Path(check.target) if check.target else None
        if target is None:
            return False, "artifact_exists: no target path given", True
        if target.exists() and target.stat().st_size > 0:
            return True, f"artifact_exists: {target}", True
        return False, f"artifact_exists: missing or empty {target}", True

    if kind == "image_size":
        return _check_image_size(check, plan, image_path)

    return False, f"unknown check kind {kind!r}", True


def _check_image_size(
    check: ReviewCheck, plan: CanvasPlan, image_path: Optional[Path]
) -> tuple[bool, str, bool]:
    if image_path is None or not Path(image_path).exists():
        return False, "image_size: rendered image unavailable", False
    if Path(image_path).stat().st_size == 0:
        # Placeholder PNG (e.g. browser-free fixture mode): cannot evaluate.
        return False, "image_size: rendered image is empty (no rasterization)", False
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return False, "image_size: Pillow not installed", False

    try:
        with Image.open(image_path) as img:
            actual = f"{img.width}x{img.height}"
    except UnidentifiedImageError:
        return False, "image_size: rendered image is not a valid image", False
    expected = check.expected or f"{plan.size.width}x{plan.size.height}"
    if actual == str(expected):
        return True, f"image_size={actual}", True
    return False, f"image_size expected {expected} but got {actual}", True
