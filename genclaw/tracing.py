"""Append-only JSONL trace writer.

Every LangGraph node must append a trace event after it executes (plan task 3),
recording at least the node name, an input summary, the output artifact paths,
and any error summary. Traces are written as JSON Lines so a run can be
inspected incrementally and is robust to a crash mid-pipeline: whatever
completed is already on disk.

The writer is deliberately tiny and dependency-free. It does not interpret the
``data`` payload beyond JSON-serializing it, so callers own the event shape.
Timestamps are injected by the caller (not read from the clock) to keep runs
deterministic and reproducible in tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union


@dataclass
class TraceWriter:
    """Appends one JSON object per line to a trace file.

    The parent directory is created on first write if missing, so the writer is
    safe to construct before the run directory exists.
    """

    path: Path
    # Monotonic per-run sequence number, so events have a total order even when
    # timestamps collide or are not provided.
    _seq: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def append(
        self,
        stage: str,
        data: Optional[dict] = None,
        *,
        timestamp: Optional[str] = None,
    ) -> dict:
        """Append a trace event for ``stage`` and return the written record.

        ``data`` is merged into the record; reserved keys (``seq``, ``stage``,
        ``ts``) always win so the event envelope stays consistent.
        """
        record: dict[str, Any] = dict(data or {})
        record["seq"] = self._seq
        record["stage"] = stage
        if timestamp is not None:
            record["ts"] = timestamp
        self._seq += 1

        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record

    def append_node(
        self,
        node: str,
        *,
        input_summary: Any = None,
        artifacts: Optional[Union[list, dict]] = None,
        error: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> dict:
        """Convenience wrapper for the canonical node-trace shape (plan task 3).

        Records the node name, an input summary, output artifact paths, and an
        error summary. ``artifacts`` paths are stringified for portability.
        """
        if isinstance(artifacts, dict):
            arts: Any = {k: str(v) for k, v in artifacts.items()}
        elif artifacts is not None:
            arts = [str(p) for p in artifacts]
        else:
            arts = None
        return self.append(
            node,
            {
                "node": node,
                "input_summary": input_summary,
                "artifacts": arts,
                "error": error,
            },
            timestamp=timestamp,
        )

    def read_events(self) -> list[dict]:
        """Parse the trace file back into a list of records (for inspection)."""
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events
