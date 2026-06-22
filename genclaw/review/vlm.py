"""VLM-based reviewer (plan task 14).

Perceptual review of the final image against the plan, complementing the
deterministic rule reviewer (:mod:`genclaw.review.rules`). The default backbone
is Claude-Opus (ADR 0004), used as a vision-language judge that returns a
structured pass/fail with evidence.

Like the other external adapters, the SDK is imported lazily and credentials
are required up front; the structured-output contract is enforced and a parse
failure surfaces as a structured error rather than a silent pass.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

from genclaw.config import ProviderConfig
from genclaw.review.base import Reviewer
from genclaw.schemas import CanvasPlan, ReviewResult

_VLM_SYSTEM = """\
You are the perceptual review layer of GenClaw. You judge ONLY whether the
rendered image visually satisfies the user's intent described in the plan:
correct objects and counts, spatial relations, attributes/colors, and required
text being visibly present and legible.

Do NOT judge implementation details you cannot determine from a photo: do not
fault the image for being a raster photograph "instead of SVG/HTML" (the final
image is always a rasterized render -- that is expected and correct), and do not
try to verify exact pixel dimensions. Backend, file size, and exact dimensions
are checked separately by deterministic rules, not by you.

Reply with ONLY a JSON object: {"passed": bool, "score": 0..1,
"failures": [str], "warnings": [str]}. Put only genuine perceptual mismatches
(wrong count, wrong relation, missing/illegible text) in failures; cite concrete
visual evidence.
"""


class VLMReviewer(Reviewer):
    """Claude-Opus vision reviewer (default paper-aligned reviewer)."""

    name = "claude-opus-vlm"

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig.from_env()

    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        if image_path is None or not Path(image_path).exists():
            return ReviewResult(
                passed=False,
                score=0.0,
                failures=["VLM review requires a rendered image; none was provided"],
            )
        raw = self._complete(plan, Path(image_path))
        return _parse_result(raw)

    def _complete(self, plan: CanvasPlan, image_path: Path) -> str:
        """Call Claude with the image + plan; return raw text. Lazy SDK import."""
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only without SDK
            raise RuntimeError(
                "the 'anthropic' package is required for the VLM reviewer; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        client = anthropic.Anthropic(**self.config.anthropic_kwargs(self.name))
        b64 = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        plan_summary = plan.model_dump_json(
            include={"prompt", "task_type", "backend", "size", "checks"}
        )
        message = client.messages.create(
            model=self.config.reviewer_model,
            max_tokens=1024,
            system=_VLM_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Plan: {plan_summary}"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                    ],
                }
            ],
        )
        return "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        )


def _parse_result(raw: str) -> ReviewResult:
    """Parse the VLM's JSON verdict; a malformed verdict fails closed."""
    s = raw.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return ReviewResult(
            passed=False, score=0.0, failures=[f"VLM returned no JSON verdict: {raw[:200]}"]
        )
    try:
        data = json.loads(s[start : end + 1])
    except json.JSONDecodeError as exc:
        return ReviewResult(
            passed=False, score=0.0, failures=[f"VLM verdict was not valid JSON: {exc}"]
        )
    return ReviewResult(
        passed=bool(data.get("passed", False)),
        score=float(data.get("score", 0.0)),
        failures=list(data.get("failures", [])),
        warnings=list(data.get("warnings", [])),
    )
