"""Agent provider contract.

The cognitive structuring layer (paper §3.1) turns a natural-language prompt
into a schema-validated :class:`~genclaw.schemas.CanvasPlan`. ``AgentProvider``
is the pluggable boundary: the fixture provider (task 4) is deterministic and
credential-free; external LLM providers (task 14, default Claude-Opus per
ADR 0004) implement the same contract behind structured-output validation.
"""

from __future__ import annotations

import abc
from typing import Optional

from genclaw.schemas import CanvasPlan, TaskType


class AgentProvider(abc.ABC):
    """Turns a prompt into a validated CanvasPlan."""

    @abc.abstractmethod
    def conceptualize(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        request_id: Optional[str] = None,
    ) -> CanvasPlan:
        """Structure ``prompt`` into a :class:`CanvasPlan`."""
        raise NotImplementedError
