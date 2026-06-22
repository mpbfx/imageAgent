"""External LLM agent: prompt -> validated CanvasPlan (plan task 14).

This is the real cognitive structuring layer (paper §3.1) -- genuine intent
recognition over free-form prompts, as opposed to the keyword-matching
:class:`~genclaw.agent.fixture.FixtureAgent`. The default backbone is
Claude-Opus (ADR 0004).

The architecture pivot rests on the prompt->CanvasPlan contract, so reliability
is the point of this module:

* The model is asked for JSON constrained to the CanvasPlan schema (via the
  provider's structured-output / tool mode where available).
* On a validation failure the Pydantic error is fed back and the model is asked
  to repair, bounded to ``max_parse_retries`` attempts.
* If it still fails, a :class:`PlanParseError` carrying the attempt history is
  raised so the caller writes a structured error artifact -- never a silent
  swallow or a half-built plan.

The model call itself is isolated in :meth:`_complete`, so the parse/repair loop
is unit-testable without any SDK or credentials (see the test that injects one
bad JSON response and asserts the retry + final behavior).
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError

from genclaw.agent.base import AgentProvider
from genclaw.agent.prompts import (
    CODE_DEVELOPER_PROMPT,
    CODE_SYSTEM_PROMPT,
    DEVELOPER_PROMPT,
    REPAIR_PROMPT,
    SYSTEM_PROMPT,
)
from genclaw.config import ProviderConfig
from genclaw.schemas import CanvasPlan, TaskType


class PlanParseError(RuntimeError):
    """Raised when the agent cannot produce a valid CanvasPlan within budget."""

    def __init__(self, attempts: list[str], last_error: str):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"agent failed to produce a valid CanvasPlan after {len(attempts)} "
            f"attempt(s); last error: {last_error}"
        )


def _extract_json(text: str) -> str:
    """Best-effort: strip markdown fences and isolate the outermost JSON object."""
    s = text.strip()
    if s.startswith("```"):
        # Drop the opening fence (``` or ```json) and the closing fence.
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1]
    return s


class ExternalLLMAgent(AgentProvider):
    """LLM-backed agent with bounded structured-output repair.

    Subclasses / providers override :meth:`_complete`. The default
    implementation calls Anthropic's Claude (the paper-aligned backbone) and is
    imported lazily so the class is usable in tests without the SDK.
    """

    def __init__(self, config: Optional[ProviderConfig] = None, *, code_mode: bool = False):
        self.config = config or ProviderConfig.from_env()
        # code_mode=True asks the LLM to write free-form SVG source (ADR 0005,
        # code-as-brush) instead of a structured template plan.
        self.code_mode = code_mode

    # --- public contract -------------------------------------------------------

    def conceptualize(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        request_id: Optional[str] = None,
    ) -> CanvasPlan:
        rid = request_id or "llm"
        tt = task_type.value if task_type else "infer the most appropriate one"
        if self.code_mode:
            system = CODE_SYSTEM_PROMPT
            user = CODE_DEVELOPER_PROMPT.format(task_type=tt, request_id=rid, prompt=prompt)
        else:
            system = SYSTEM_PROMPT
            user = DEVELOPER_PROMPT.format(task_type=tt, request_id=rid, prompt=prompt)

        attempts: list[str] = []
        last_error = ""
        # 1 initial attempt + up to max_parse_retries repair attempts.
        for attempt in range(self.config.max_parse_retries + 1):
            if attempt == 0:
                raw = self._complete(system, user)
            else:
                repair = REPAIR_PROMPT.format(errors=last_error, previous=attempts[-1])
                raw = self._complete(system, user + "\n\n" + repair)
            attempts.append(raw)

            try:
                data = json.loads(_extract_json(raw))
            except json.JSONDecodeError as exc:
                last_error = f"response was not valid JSON: {exc}"
                continue

            # Ensure required identity fields are present/consistent even if the
            # model omitted them; the prompt is the source of truth.
            data.setdefault("request_id", rid)
            data.setdefault("prompt", prompt)
            if task_type is not None:
                data["task_type"] = task_type.value

            try:
                return CanvasPlan.model_validate(data)
            except ValidationError as exc:
                last_error = str(exc)
                continue

        raise PlanParseError(attempts, last_error)

    # --- provider boundary -----------------------------------------------------

    def _complete(self, system: str, user: str) -> str:
        """Call the default backbone (Claude-Opus) and return raw text.

        Imported lazily; raises ProviderNotConfiguredError without a key.
        Override in tests or alternative providers.
        """
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only without SDK
            raise RuntimeError(
                "the 'anthropic' package is required for the default LLM agent; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        # anthropic_kwargs() requires the key (raises ProviderNotConfiguredError
        # if missing) and adds base_url when an Anthropic-compatible proxy is set.
        client = anthropic.Anthropic(**self.config.anthropic_kwargs("anthropic-claude-agent"))
        message = client.messages.create(
            model=self.config.agent_model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate text blocks from the response.
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
