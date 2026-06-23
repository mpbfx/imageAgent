"""Graph 节点实现(plan task 11)。

每个节点都是普通函数 ``GenClawState -> GenClawState``,不直接依赖 langgraph,
所以在没装编排栈的环境下 pipeline 也能跑也能测(懒加载策略)。LangGraph
(``builder.py``)把这同一套函数接进 ``StateGraph``;Pipeline 也可直接顺序调
它们。

每个节点执行后会追一条 trace 事件(节点名、输入摘要、输出 artifact 路径、
错误摘要)——遵循 artifact-first 原则;provider / backend 失败会落一条结构化
error artifact,而不是被吞掉(ADR 0001)。
"""

# 中文补充说明：
# 节点类把 providers 集中放在实例上,这样每个节点函数对 state 来说是「纯
# 函数」,但可协作对象是可注入的(fixture / external 互换)。
# 两个小工厂:
#   - _renderer_for(backend): 按 plan 选对应 backend 的 renderer
#   - _renderer_for_plan(plan): 先看 plan.source,「code-as-brush」走
#     CodeRenderer(ADR 0005),其它按 backend 分派
# ``revise`` 在 fixture 模式下是「明确不支持」的占位:递增 revision_count,
# 记 error,但不死循环——phase 2 再接真 LLM 修订。

from __future__ import annotations

from typing import Callable, Optional

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
        from genclaw.renderers.three import ThreeRenderer
        return ThreeRenderer()
    if backend in (CanvasBackend.python, CanvasBackend.canvas):
        from genclaw.renderers.physics import PhysicsRenderer
        return PhysicsRenderer(backend)
    if backend is CanvasBackend.passthrough:
        from genclaw.renderers.passthrough import PassthroughRenderer
        return PassthroughRenderer()
    raise ValueError(f"no renderer for backend {backend!r}")


def _renderer_for_plan(plan: CanvasPlan) -> Renderer:
    """先按 plan.source 选,再按 backend 选。

    ``source="code"`` 是「code-as-brush」(ADR 0005):LLM 直接写 canvas 源
    代码,走 CodeRenderer(校验 + 光栅化),不再看 backend。其余按
    structured template + backend 分派。
    """
    if plan.source is CanvasSource.code:
        from genclaw.renderers.code import CodeRenderer

        # passthrough 后端即使被标成 code,也不编译代码——它本就是"不画草图"。
        if plan.backend is CanvasBackend.passthrough:
            from genclaw.renderers.passthrough import PassthroughRenderer

            return PassthroughRenderer()
        return CodeRenderer()
    return _renderer_for(plan.backend)


def _download_reference_image(plan: CanvasPlan, run_dir) -> tuple[Optional[Path], Optional[str]]:
    """从 plan.knowledge 取第一张参考图 URL,下载到 run_dir/reference.png。

    返回 (path, None) 成功;(None, error_msg) 失败。
    """
    if run_dir is None:
        return None, "no run_dir"
    image_url = next((k.image_url for k in plan.knowledge if k.image_url), None)
    if not image_url:
        return None, "no image_url in knowledge"
    try:
        import urllib.request

        dest = Path(run_dir) / "reference.png"
        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if not data:
            return None, f"empty response from {image_url}"
        dest.write_bytes(data)
        return dest, None
    except Exception as exc:
        return None, f"download failed ({image_url}): {exc}"


class GraphNodes:
    """节点函数用到的所有 providers 都放这里。

    协作对象是构造时注入的——这样节点函数对 ``state`` 仍表现为「纯」,
    但 fixture ↔ external 切换不需要改函数体。
    """

    def __init__(
        self,
        agent: AgentProvider,
        generator: ImageGenerator,
        reviewer: Reviewer,
        *,
        search: Optional[SearchProvider] = None,
        timestamp: str = "",
        on_progress: Optional[Callable[[str, str, Optional[dict]], None]] = None,
    ):
        self.agent = agent
        self.generator = generator
        self.reviewer = reviewer
        # 默认是 NullSearchProvider:对外协议有,但不做网络 I/O
        self.search = search or NullSearchProvider()
        self.timestamp = timestamp
        self.on_progress = on_progress

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
        """第一节点:把用户 prompt 变 :class:`CanvasPlan`,并把 plan artifact 落盘。

        ``search_node`` 已在本节点之前跑过(论文 §3.1-3.2:先搜索补全认知空白
        再画),所以这里把 ``state.knowledge`` 回传给 agent,让 LLM 写代码时
        能看到检索到的事实,并在 plan 落盘前合进 ``plan.knowledge``。
        """
        if self.on_progress:
            self.on_progress("conceptualize", "starting", None)
        try:
            plan = self.agent.conceptualize(
                state.prompt,
                state.task_type,
                request_id=state.request_id,
                knowledge=state.knowledge or None,
            )
        except Exception as exc:
            return self._fail(state, "conceptualize", exc)

        # 把 pre-search 检索到的事实合进 plan(去重靠 source+claim),让
        # knowledge 成为 plan artifact 的一部分,reviewer 可追溯。
        if state.knowledge:
            seen = {(k.source, k.claim) for k in plan.knowledge}
            for ref in state.knowledge:
                if (ref.source, ref.claim) not in seen:
                    plan.knowledge.append(ref)

        state.plan = plan
        # 用 agent 给的 task_type 反向校正 state.task_type(单一真值原则)
        state.task_type = plan.task_type
        if state.artifacts is not None:
            state.artifacts.write_json(state.artifacts.plan_path, plan.model_dump(mode="json"))
        self._record(
            state,
            "conceptualize",
            input_summary=state.prompt,
            artifacts=[state.artifacts.plan_path] if state.artifacts else None,
        )
        if self.on_progress:
            self.on_progress(
                "conceptualize",
                "done",
                {"objects": len(plan.objects), "backend": plan.backend.value},
            )
        return state

    def search_node(self, state: GenClawState) -> GenClawState:
        """用 search provider 补齐知识缺口(论文 §3.1-3.2)。

        在 ``conceptualize`` *之前*运行:先把检索到的事实存进 ``state.knowledge``,
        conceptualize 再带着这些事实写代码——这样搜索结果真正参与生成,而不是
        画完才补一份用不上的知识。

        Gated:只有判定需要知识接地的 prompt 才检索(prompt 启发式 + task_type,
        此时 task_type 可能为 None,gate 主要靠 prompt 里的具名实体)。
        NullSearchProvider 是「真但不取数」,所以这一步协议存在、行为 no-op,
        fixture / 离线环境都能跑。
        """
        if not self.search.should_search(state.prompt, state.task_type):
            if self.on_progress:
                self.on_progress("search", "skipped", None)
            self._record(state, "search", input_summary="skipped (not knowledge-grounded)")
            return state

        if self.on_progress:
            self.on_progress("search", "starting", {"provider": self.search.name})

        try:
            refs = self.search.search(state.prompt)
        except Exception as exc:
            # search 失败不能让整个 run 挂掉:记错,继续往下走(还有 agent 自己的 knowledge)
            return self._fail(state, "search", exc, fatal=False)

        state.knowledge = list(state.knowledge) + refs
        self._record(
            state,
            "search",
            input_summary=f"provider={self.search.name} facts={len(refs)}",
        )
        if self.on_progress:
            self.on_progress("search", "done", {"facts": len(refs), "provider": self.search.name})
        return state

    def render(self, state: GenClawState) -> GenClawState:
        """把 CanvasPlan 编译成可执行 canvas 代码并光栅化。"""
        if self.on_progress:
            self.on_progress("render", "starting", None)
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
        if self.on_progress:
            self.on_progress(
                "render",
                "done",
                {"backend": state.plan.backend.value, "has_png": rendered.png_path is not None},
            )
        return state

    def generate(self, state: GenClawState) -> GenClawState:
        """把 code sketch 当视觉条件喂给 :class:`ImageGenerator` 出 final。

        如果 plan.knowledge 里有图片 URL(通过 Serper 图片搜索取得的真实参考图),
        优先把第一张参考图下载下来作为 img2img 的视觉条件——真实照片比代码草图
        更接近真实外观,对写实实体类任务更有帮助。没有参考图时退回 code sketch。
        """
        if self.on_progress:
            self.on_progress("generate", "starting", None)
        if state.rendered_canvas is None or state.artifacts is None:
            return self._fail(state, "generate", ValueError("nothing to generate from"))
        sketch = state.rendered_canvas.png_path or state.artifacts.sketch_path
        # 若 knowledge 里有真实参考图,下载并替换 sketch;记录结果进 trace
        if state.plan is not None:
            ref, ref_err = _download_reference_image(state.plan, state.artifacts.run_dir)
            if ref is not None:
                sketch = ref
                self._record(state, "generate", input_summary=f"reference_image={ref.name}")
            elif ref_err and "no image_url" not in ref_err and "no run_dir" not in ref_err:
                # 有 URL 但下载失败时才记录警告,避免对无参考图任务也刷日志
                state.errors.append(f"reference_image: {ref_err}")
        # 透传 task_type 给生成器,让生成器按任务族选 rerender 强度:
        # 文字密集 -> 温柔(保字形);材质/场景 -> 强写实
        constraints = {}
        if state.plan is not None:
            constraints["task_type"] = state.plan.task_type.value
        try:
            result = self.generator.generate(
                state.prompt, sketch, state.artifacts.final_path, constraints
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
        if self.on_progress:
            self.on_progress(
                "generate",
                "done",
                {"provider": result.provider},
            )
        return state

    def review(self, state: GenClawState) -> GenClawState:
        """对照 CanvasPlan 检查最终成图,落 :class:`ReviewResult` artifact。"""
        if self.on_progress:
            self.on_progress("review", "starting", None)
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
        if self.on_progress:
            self.on_progress(
                "review",
                "done",
                {"passed": result.passed, "score": float(result.score)},
            )
        return state

    def revise(self, state: GenClawState) -> GenClawState:
        """Fixture 模式下的 revise:递增计数 + 明确记录「不支持」。

        真正的修订(用 review 反馈重 prompt agent)是 phase 2 范围;这里
        显式把限制说清楚,而不是让图默默死循环。
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
        """把节点失败记成结构化 error artifact + state 字段。

        ``fatal=False`` 时只记录、继续往下走(给 search 节点用:检索失败
        不应该把整个生成链拉爆)。
        """
        message = f"{type(exc).__name__}: {exc}"
        state.errors.append(f"{node}: {message}")
        if state.artifacts is not None:
            state.artifacts.write_error(node, message)
        self._record(state, node, error=message)
        return state
