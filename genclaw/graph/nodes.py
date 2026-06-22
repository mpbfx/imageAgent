"""Graph node implementations (plan task 11).

Each node is a plain function ``GenClawState -> GenClawState`` with no langgraph
dependency, so the pipeline runs and tests without the orchestration stack
installed (lazy-import strategy). LangGraph (``builder.py``) wires these same
functions into a ``StateGraph``; the pipeline can also sequence them directly.

Every node appends a trace event after it executes (node name, input summary,
output artifact paths, error summary) per the artifact-first principle, and a
provider/backend failure leaves a structured error artifact rather than being
swallowed (ADR 0001).
"""

from __future__ import annotations

from typing import Optional

from genclaw.agent.base import AgentProvider
from genclaw.generators.base import ImageGenerator
from genclaw.graph.state import GenClawState
from genclaw.renderers.base import Renderer
from genclaw.renderers.html import HTMLRenderer
from genclaw.renderers.svg import SVGRenderer
from genclaw.review.base import Reviewer
from genclaw.schemas import CanvasBackend, CanvasPlan, CanvasSource, TaskType
from genclaw.search import NullSearchProvider, SearchProvider
from genclaw.tracing import TraceWriter


def _renderer_for(backend: CanvasBackend) -> Renderer:
    if backend is CanvasBackend.svg:
        return SVGRenderer()
    if backend is CanvasBackend.html:
        return HTMLRenderer()
    if backend is CanvasBackend.three:
        # Imported lazily: the Three.js renderer (task 8) reaches for a browser.
        from genclaw.renderers.three import ThreeRenderer

        return ThreeRenderer()
    if backend in (CanvasBackend.python, CanvasBackend.canvas):
        # Numeric physical-draft backends (paper §3.2: Python plotting / Canvas).
        from genclaw.renderers.physics import PhysicsRenderer

        return PhysicsRenderer(backend)
    raise ValueError(f"no renderer for backend {backend!r}")


def _renderer_for_plan(plan: CanvasPlan) -> Renderer:
    """Pick a renderer by plan source first, then backend.

    A ``source="code"`` plan is free-form code-as-brush (ADR 0005): the LLM
    wrote the canvas source directly, so it goes to the CodeRenderer (which
    validates + rasterizes) regardless of backend. Otherwise it's a structured
    template plan dispatched by backend.
    """
    if plan.source is CanvasSource.code:
        from genclaw.renderers.code import CodeRenderer

        return CodeRenderer()
    return _renderer_for(plan.backend)


class GraphNodes:
    """Bundles the providers used by the node functions.

    Holding providers on an instance keeps the node functions pure with respect
    to their ``state`` argument while staying pluggable (fixture vs external).
    """

    def __init__(
        self,
        agent: AgentProvider,
        generator: ImageGenerator,
        reviewer: Reviewer,
        *,
        search: Optional[SearchProvider] = None,
        timestamp: str = "",
    ):
        self.agent = agent
        self.generator = generator
        self.reviewer = reviewer
        self.search = search or NullSearchProvider()
        self.timestamp = timestamp

    def _trace(self, state: GenClawState) -> Optional[TraceWriter]:
        if state.artifacts is None:
            return None
        return TraceWriter(state.artifacts.trace_path)

    def _record(self, state: GenClawState, node: str, **kw) -> None:
        writer = self._trace(state)
        if writer is None:
            return
        event = writer.append_node(node, timestamp=self.timestamp or None, **kw)
        state.trace_events.append(event)

    # --- nodes -----------------------------------------------------------------

    def conceptualize(self, state: GenClawState) -> GenClawState:
        try:
            plan = self.agent.conceptualize(
                state.prompt, state.task_type, request_id=state.request_id
            )
        except Exception as exc:
            return self._fail(state, "conceptualize", exc)

        state.plan = plan
        state.task_type = plan.task_type
        if state.artifacts is not None:
            state.artifacts.write_json(state.artifacts.plan_path, plan.model_dump(mode="json"))
        self._record(
            state,
            "conceptualize",
            input_summary=state.prompt,
            artifacts=[state.artifacts.plan_path] if state.artifacts else None,
        )
        return state

    def search_node(self, state: GenClawState) -> GenClawState:
        """Fill knowledge gaps via the search provider (paper §3.1-3.2).

        Gated: only knowledge-grounded tasks retrieve. Retrieved facts are
        merged into the plan's ``knowledge`` list (each with a traceable
        ``source``) and the plan artifact is rewritten. The default
        NullSearchProvider makes this a real-but-empty step without network I/O.
        """
        if state.plan is None:
            return state  # conceptualize failed; nothing to ground.
        if not self.search.should_search(state.prompt, state.plan.task_type):
            self._record(state, "search", input_summary="skipped (not knowledge-grounded)")
            return state

        try:
            refs = self.search.search(state.prompt)
        except Exception as exc:
            # A search failure must not kill the run; record it and continue
            # with whatever knowledge the agent already had.
            return self._fail(state, "search", exc, fatal=False)

        state.plan.knowledge.extend(refs)
        if state.artifacts is not None:
            state.artifacts.write_json(
                state.artifacts.plan_path, state.plan.model_dump(mode="json")
            )
        self._record(
            state,
            "search",
            input_summary=f"provider={self.search.name} facts={len(refs)}",
            artifacts=[state.artifacts.plan_path] if state.artifacts else None,
        )
        return state

    def render(self, state: GenClawState) -> GenClawState:
        if state.plan is None:
            return self._fail(state, "render", ValueError("no plan to render"))
        try:
            renderer = _renderer_for_plan(state.plan)
            out_dir = state.run_dir or (state.artifacts.run_dir if state.artifacts else None)
            rendered = renderer.render(state.plan, out_dir)
        except Exception as exc:
            return self._fail(state, "render", exc)

        state.rendered_canvas = rendered
        self._record(
            state,
            "render",
            input_summary=f"backend={state.plan.backend.value}",
            artifacts=[rendered.source_path]
            + ([rendered.png_path] if rendered.png_path else []),
        )
        return state

    def generate(self, state: GenClawState) -> GenClawState:
        if state.rendered_canvas is None or state.artifacts is None:
            return self._fail(state, "generate", ValueError("nothing to generate from"))
        sketch = state.rendered_canvas.png_path or state.artifacts.sketch_path
        try:
            result = self.generator.generate(
                state.prompt, sketch, state.artifacts.final_path
            )
        except Exception as exc:
            return self._fail(state, "generate", exc)

        state.generation_result = result
        self._record(
            state,
            "generate",
            input_summary=f"provider={result.provider}",
            artifacts=[result.final_path],
        )
        return state

    def review(self, state: GenClawState) -> GenClawState:
        if state.plan is None:
            return self._fail(state, "review", ValueError("no plan to review"))
        source_path = (
            state.rendered_canvas.source_path if state.rendered_canvas else None
        )
        image_path = (
            state.generation_result.final_path if state.generation_result else None
        )
        try:
            result = self.reviewer.review(
                state.plan, canvas_source_path=source_path, image_path=image_path
            )
        except Exception as exc:
            return self._fail(state, "review", exc)

        state.review_result = result
        if state.artifacts is not None:
            state.artifacts.write_json(
                state.artifacts.review_path, result.model_dump(mode="json")
            )
        self._record(
            state,
            "review",
            input_summary=f"passed={result.passed} score={result.score:.2f}",
            artifacts=[state.artifacts.review_path] if state.artifacts else None,
        )
        return state

    def revise(self, state: GenClawState) -> GenClawState:
        """Fixture-mode revise: increment count and record it is unsupported.

        Real revision (re-prompting the agent with review feedback) is phase 2;
        here we make the limitation explicit rather than silently looping.
        """
        state.revision_count += 1
        msg = (
            "revise is unsupported in fixture mode; "
            f"revision_count={state.revision_count}"
        )
        state.errors.append(msg)
        self._record(state, "revise", input_summary=msg, error=msg)
        return state

    def _fail(
        self, state: GenClawState, node: str, exc: Exception, *, fatal: bool = True
    ) -> GenClawState:
        """Record a node failure as a structured error artifact and on state.

        ``fatal=False`` records the error but lets the run continue (used by the
        search node: a retrieval failure should not abort generation).
        """
        message = f"{type(exc).__name__}: {exc}"
        state.errors.append(f"{node}: {message}")
        if state.artifacts is not None:
            state.artifacts.write_error(node, message)
        self._record(state, node, error=message)
        return state
