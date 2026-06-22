"""Pipeline orchestration (plan task 11).

``Pipeline.run`` constructs the initial state and run artifacts, then drives the
workflow either through the compiled LangGraph graph (``builder.py``) or by
sequencing the same node functions directly. The direct path lets the full
pipeline run and test without langgraph installed (phase-1 lazy-import
strategy); both paths use the identical node callables and route function, so
behavior matches.

All artifacts and the trace are written as a side effect of the nodes. A
provider/backend failure leaves a structured error artifact and is surfaced on
``state.errors`` -- never swallowed (ADR 0001).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.agent.base import AgentProvider
from genclaw.agent.fixture import FixtureAgent
from genclaw.artifacts import RunArtifacts
from genclaw.config import ProviderConfig
from genclaw.generators.base import ImageGenerator
from genclaw.generators.mock import MockImageGenerator
from genclaw.graph.nodes import GraphNodes
from genclaw.graph.routes import REVISE, route_after_review
from genclaw.graph.state import GenClawState
from genclaw.review.base import Reviewer
from genclaw.review.rules import RuleReviewer
from genclaw.schemas import TaskType
from genclaw.search import NullSearchProvider, SearchProvider, TavilySearchProvider


def _new_request_id(prompt: str, counter: int) -> str:
    """Deterministic request id (no clock/random; reproducible)."""
    slug = "".join(c if c.isalnum() else "-" for c in prompt.lower())[:24].strip("-")
    return f"{slug or 'run'}-{counter:03d}"


def build_providers(mode: str):
    """Build (agent, generator, reviewer, search) for a mode.

    * ``fixture``  -- deterministic, credential-free (FixtureAgent + mock + rules
      + null search).
    * ``external`` -- paper-aligned stack (ADR 0004) with **code-as-brush** by
      default: the LLM writes free-form SVG/HTML/Three.js source (the paper's
      core mechanism). Claude-Opus agent, image generator, VLM reviewer, Tavily
      search. Adapters raise ProviderNotConfiguredError if credentials missing.
    * ``external-template`` -- same stack but the agent emits a *structured*
      template plan instead of free-form code. The deterministic fallback /
      baseline; does not execute model-authored code.
    * ``external-code`` -- explicit alias for ``external`` (code-as-brush).

    Returns a 4-tuple; raises ValueError for an unknown mode.
    """
    if mode == "fixture":
        return (
            FixtureAgent(),
            MockImageGenerator(),
            RuleReviewer(),
            NullSearchProvider(),
        )
    if mode in ("external", "external-code", "external-template"):
        from genclaw.agent.external import ExternalLLMAgent
        from genclaw.generators.external import (
            GeminiImageGenerator,
            OpenAICompatImageGenerator,
        )
        from genclaw.review.composite import CompositeReviewer
        from genclaw.review.vlm import VLMReviewer

        # A custom GOOGLE_BASE_URL almost always means an OpenAI-style image
        # gateway (the native google-genai generate_content API is rejected by
        # such proxies). Use the native Gemini SDK only against Google's own
        # endpoint.
        cfg = ProviderConfig.from_env()
        generator = (
            OpenAICompatImageGenerator()
            if cfg.google_base_url
            else GeminiImageGenerator()
        )
        # Structural checks run on the canvas source; the VLM judges only the
        # final image's perceptual fidelity (see CompositeReviewer).
        reviewer = CompositeReviewer(perceptual=VLMReviewer())
        # code-as-brush is the DEFAULT for real models (ADR 0003/0005): the paper
        # is "code-driven", so external == code-as-brush. Only external-template
        # opts out to the structured template path.
        code_mode = mode != "external-template"
        agent = ExternalLLMAgent(code_mode=code_mode)
        return (
            agent,
            generator,
            reviewer,
            TavilySearchProvider(),
        )
    raise ValueError(
        f"unknown mode {mode!r}; expected 'fixture', 'external', "
        "'external-code', or 'external-template'"
    )


class Pipeline:
    """Runs the GenClaw pipeline end to end."""

    def __init__(
        self,
        agent: Optional[AgentProvider] = None,
        generator: Optional[ImageGenerator] = None,
        reviewer: Optional[Reviewer] = None,
        *,
        search: Optional["SearchProvider"] = None,
        base_dir: str | Path = "outputs/runs",
        use_langgraph: bool = False,
    ):
        self.agent = agent or FixtureAgent()
        self.generator = generator or MockImageGenerator()
        self.reviewer = reviewer or RuleReviewer()
        self.search = search  # None -> GraphNodes defaults to NullSearchProvider
        self.base_dir = Path(base_dir)
        self.use_langgraph = use_langgraph
        self._counter = 0

    @classmethod
    def for_mode(
        cls,
        mode: str = "fixture",
        *,
        base_dir: str | Path = "outputs/runs",
        use_langgraph: bool = False,
    ) -> "Pipeline":
        """Construct a Pipeline with the provider stack for ``mode``."""
        agent, generator, reviewer, search = build_providers(mode)
        return cls(
            agent,
            generator,
            reviewer,
            search=search,
            base_dir=base_dir,
            use_langgraph=use_langgraph,
        )

    def run(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        max_revisions: int = 1,
        *,
        request_id: Optional[str] = None,
        timestamp: str = "00000000-000000",
    ) -> GenClawState:
        """Run the pipeline for ``prompt`` and return the final state.

        ``timestamp`` is injected (not read from the clock) for reproducible run
        directories; callers that want wall-clock names pass one in.
        """
        self._counter += 1
        rid = request_id or _new_request_id(prompt, self._counter)

        state = GenClawState.from_prompt(rid, prompt, task_type, max_revisions)
        artifacts = RunArtifacts.create(self.base_dir, rid, timestamp)
        state.artifacts = artifacts
        state.run_dir = artifacts.run_dir
        artifacts.write_json(
            artifacts.request_path,
            {
                "request_id": rid,
                "prompt": prompt,
                "task_type": task_type.value if task_type else None,
                "max_revisions": max_revisions,
            },
        )

        nodes = GraphNodes(
            self.agent,
            self.generator,
            self.reviewer,
            search=self.search,
            timestamp=timestamp,
        )
        if self.use_langgraph:
            final = self._run_langgraph(nodes, state)
        else:
            final = self._run_direct(nodes, state)
        return final

    def _run_direct(self, nodes: GraphNodes, state: GenClawState) -> GenClawState:
        """Sequence nodes directly, mirroring the LangGraph edges and routing."""
        state = nodes.conceptualize(state)
        if state.plan is None:  # conceptualize failed; stop, error already recorded.
            return state
        state = nodes.search_node(state)  # ground knowledge before sketching

        while True:
            state = nodes.render(state)
            state = nodes.generate(state)
            state = nodes.review(state)
            if route_after_review(state) == REVISE:
                state = nodes.revise(state)
                continue
            break
        return state

    def _run_langgraph(self, nodes: GraphNodes, state: GenClawState) -> GenClawState:
        from genclaw.graph.builder import build_graph

        graph = build_graph(nodes)
        result = graph.invoke(state)
        # langgraph may return a dict-like; normalize back to GenClawState.
        if isinstance(result, GenClawState):
            return result
        return GenClawState.model_validate(result)
