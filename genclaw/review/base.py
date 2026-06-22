"""Reviewer contract.

The review layer (paper §3.3) inspects the output against the plan's declared
``checks`` and produces a :class:`~genclaw.schemas.ReviewResult`. The rule-based
reviewer (task 10) is deterministic and browser-free; a VLM reviewer (task 14,
default Claude-Opus per ADR 0004) implements the same contract for perceptual
checks. Both consume the same central ``CanvasPlan`` contract (ADR 0001).
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Optional

from genclaw.schemas import CanvasPlan, ReviewResult


class Reviewer(abc.ABC):
    """Reviews a rendered run against the plan's checks."""

    @abc.abstractmethod
    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        """Evaluate the plan's ``checks`` and return a result."""
        raise NotImplementedError
