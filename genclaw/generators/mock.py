"""Mock image generator (plan task 9).

Copies the code sketch to ``final.png`` and records metadata. The fixture path
explicitly does NOT provide photorealism -- it exercises the generation step's
contract and artifacts without any provider credentials (ADR 0004). External
providers (default Gemini-Flash-Image per ADR 0004) live in
``genclaw.generators.external`` and are never imported by core.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from genclaw.generators.base import GenerationResult, ImageGenerator


class MockImageGenerator(ImageGenerator):
    """Returns the sketch unchanged as the 'final' image."""

    name = "mock"

    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if sketch_path.exists():
            shutil.copyfile(sketch_path, output_path)
        else:
            # No PNG (e.g. browser-free phase-1): leave a placeholder so the
            # artifact exists and the failure mode is explicit, not silent.
            output_path.write_bytes(b"")

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "prompt": prompt,
                "constraints": constraints or {},
                "note": (
                    "fixture/mock mode: final image is a copy of the code sketch; "
                    "no photorealistic generation is performed"
                ),
                "sketch_existed": sketch_path.exists(),
            },
        )
