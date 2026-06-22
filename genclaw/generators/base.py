"""Image generator contract and the ``GenerationResult`` data carrier.

The visual generation layer (paper §3.3) takes the code sketch as a visual
condition and calls an image generation/editing provider to complete materials,
texture, and lighting. This module defines only the contract and result type;
the mock generator (task 9) and external providers (task 14) live in sibling
modules. External provider configuration never lands in core (ADR 0004).
"""

from __future__ import annotations

import abc
from pathlib import Path

from pydantic import BaseModel, Field


class GenerationResult(BaseModel):
    """The output of the generation step.

    ``final_path`` is the completed image. ``metadata`` records the provider
    and inputs so a reviewer can see how the final image was produced; the mock
    provider also notes that fixture mode provides no photorealism.
    """

    final_path: Path
    provider: str
    sketch_path: Path
    metadata: dict = Field(default_factory=dict)


class ImageGenerator(abc.ABC):
    """Completes a code sketch into a final image via a provider."""

    name: str

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        """Produce ``output_path`` from ``sketch_path`` and return the result."""
        raise NotImplementedError
