"""Artifact-first run directory management.

Per the project's artifact-first principle (ADR 0001), every run writes a
complete, self-contained directory so a reviewer can inspect the whole pipeline
without re-running it. A run directory lives at::

    outputs/runs/<timestamp>-<request_id>/
        request.json    # the raw request (prompt, task type, options)
        plan.json       # the validated CanvasPlan
        canvas.svg      # the compiled executable canvas (backend-specific ext)
        canvas.html
        sketch.png      # the code sketch rasterized to PNG
        final.png       # the generator's completion of the sketch
        review.json     # the ReviewResult
        trace.jsonl     # one JSON object per pipeline stage (see tracing.py)

``RunArtifacts`` only owns *paths and IO*; it does not know about the schema,
renderers, or providers. Path accessors are stable for the lifetime of a run so
every node writes to the same place.

This module has no third-party dependency, so it imports without a browser or
provider credentials.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

# Filenames are fixed so reviewers always know where to look (ADR 0001).
REQUEST_JSON = "request.json"
PLAN_JSON = "plan.json"
SKETCH_PNG = "sketch.png"
FINAL_PNG = "final.png"
REVIEW_JSON = "review.json"
TRACE_JSONL = "trace.jsonl"

# Canvas file extension per backend. ``canvas.<ext>`` is the executable source.
_CANVAS_EXT = {"svg": "svg", "html": "html", "three": "html"}


def _sanitize(component: str) -> str:
    """Make a string safe to embed in a directory name.

    Request ids and timestamps land in a filesystem path on Windows, so strip
    anything that is not alphanumeric, dash, dot, or underscore.
    """
    safe = "".join(c if (c.isalnum() or c in "-._") else "-" for c in component)
    return safe.strip("-") or "run"


@dataclass(frozen=True)
class RunArtifacts:
    """Owns the on-disk layout for a single pipeline run.

    Construct with :meth:`create`, which makes the directory. Path properties
    are pure and stable; nothing here re-derives or moves a path after creation.
    """

    run_dir: Path
    request_id: str

    @classmethod
    def create(
        cls,
        base_dir: Union[str, Path],
        request_id: str,
        timestamp: str,
    ) -> "RunArtifacts":
        """Create ``<base_dir>/<timestamp>-<request_id>/`` and return a handle.

        ``timestamp`` is injected by the caller rather than read from the clock
        here so runs are deterministic and reproducible in tests.
        """
        name = f"{_sanitize(timestamp)}-{_sanitize(request_id)}"
        run_dir = Path(base_dir) / name
        run_dir.mkdir(parents=True, exist_ok=True)
        return cls(run_dir=run_dir, request_id=request_id)

    # --- stable path accessors -------------------------------------------------

    @property
    def request_path(self) -> Path:
        return self.run_dir / REQUEST_JSON

    @property
    def plan_path(self) -> Path:
        return self.run_dir / PLAN_JSON

    @property
    def sketch_path(self) -> Path:
        return self.run_dir / SKETCH_PNG

    @property
    def final_path(self) -> Path:
        return self.run_dir / FINAL_PNG

    @property
    def review_path(self) -> Path:
        return self.run_dir / REVIEW_JSON

    @property
    def trace_path(self) -> Path:
        return self.run_dir / TRACE_JSONL

    def canvas_path(self, backend: str) -> Path:
        """Path to the executable canvas source for ``backend``."""
        ext = _CANVAS_EXT.get(backend, backend)
        return self.run_dir / f"canvas.{ext}"

    def error_path(self, stage: str) -> Path:
        """Path for a structured error artifact from a failed ``stage``.

        A failing provider/backend must leave a structured error here rather
        than swallowing the context (ADR 0001).
        """
        return self.run_dir / f"error.{_sanitize(stage)}.json"

    # --- IO helpers ------------------------------------------------------------

    def write_json(self, path: Path, data: Any) -> Path:
        """Write ``data`` as UTF-8 JSON (non-ASCII preserved, not escaped)."""
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        path.write_text(text, encoding="utf-8")
        return path

    def write_text(self, path: Path, text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        return path

    def write_error(self, stage: str, message: str, detail: Optional[Any] = None) -> Path:
        """Persist a structured error artifact for ``stage``."""
        return self.write_json(
            self.error_path(stage),
            {"stage": stage, "error": message, "detail": detail},
        )
