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

from pathlib import Path
from typing import Callable, Optional

from genclaw.agent.base import AgentProvider
from genclaw.agent.external import _format_knowledge
from genclaw.generators.base import ImageGenerator
from genclaw.graph.state import GenClawState
from genclaw.renderers.base import Renderer
from genclaw.renderers.html import HTMLRenderer
from genclaw.renderers.svg import SVGRenderer
from genclaw.review.base import Reviewer
from genclaw.schemas import CanvasBackend, CanvasPlan, CanvasSource, Intent, TaskType
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


def _neutral_canvas(run_dir, width: int, height: int) -> Path:
    """产出中性灰底 PNG,给 img2img 生成器当"空白起步"输入。"""
    from PIL import Image
    dest = Path(run_dir) / "sketch.png"
    Image.new("RGB", (width, height), (128, 128, 128)).save(dest)
    return dest


def _download_reference_image(plan: CanvasPlan, run_dir) -> tuple[Optional[Path], Optional[str]]:
    """从 plan.knowledge 遍历 image_url,下载第一张有效图片到 run_dir/reference.png。

    - 下载后用 Pillow 校验并重编码成 PNG,避免 HTML 错误页/WebP/格式不匹配。
    - 校验失败则跳过,继续尝试下一个 URL。
    返回 (path, None) 成功;(None, error_msg) 失败。
    """
    if run_dir is None:
        return None, "no run_dir"
    image_urls = [k.image_url for k in plan.knowledge if k.image_url]
    if not image_urls:
        return None, "no image_url in knowledge"

    import io
    import urllib.request

    dest = Path(run_dir) / "reference.png"
    errors = []
    for url in image_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.save(dest, format="PNG")
            return dest, None
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return None, "; ".join(errors[:2])  # 只返回头两条错误避免过长


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

    def intent_node(self, state: GenClawState) -> GenClawState:
        """论文 §3.2 意图理解:由 LLM(或 fixture)主动判断要不要搜索。

        这是 *最前面* 的节点(在 search_node 之前):
          - external 模式:agent 调 LLM,返回 {task_type, needs_search, reason}
          - fixture 模式:agent 用关键词查表

        把 task_type 同步到 state.task_type,让后续 search_node / conceptualize
        用一致的任务族;把 needs_search 同步到 state.needs_search,作为
        search_node 的唯一开关(替代原 should_search() 的正则启发式)。

        失败处理:non-fatal——记 error,继续往下走(把 needs_search 设为 False,
        等于「不知道,先不搜」),让 search 节点空跑,conceptualize 仍能写 plan。
        """
        if self.on_progress:
            self.on_progress("intent", "starting", None)
        try:
            intent = self.agent.intent_classify(
                state.prompt, requested_task_type=state.task_type
            )
        except Exception as exc:
            # LLM 挂了也不能让整个 run 挂掉:落一条 error,保守不搜。
            if self.on_progress:
                self.on_progress("intent", "failed", {"error": str(exc)})
            self._record(state, "intent", error=str(exc))
            return self._fail(state, "intent", exc, fatal=False)

        state.intent = intent
        state.needs_search = intent.needs_search
        # 单一真值:intent 判定的 task_type 覆盖 user 传入的(若 user 传了)
        if state.task_type is None:
            state.task_type = intent.task_type

        if state.artifacts is not None:
            state.artifacts.write_json(
                state.artifacts.run_dir / "intent.json",
                intent.model_dump(mode="json"),
            )
        self._record(
            state,
            "intent",
            input_summary=f"task_type={intent.task_type.value} needs_search={intent.needs_search}",
        )
        if self.on_progress:
            self.on_progress(
                "intent",
                "done",
                {
                    "task_type": intent.task_type.value,
                    "needs_search": intent.needs_search,
                    "reason": intent.reason,
                },
            )
        return state

    def search_node(self, state: GenClawState) -> GenClawState:
        """用 search provider 补齐知识缺口(论文 §3.1-3.2)。

        在 ``conceptualize`` *之前*运行:先把检索到的事实存进 ``state.knowledge``,
        conceptualize 再带着这些事实写代码——这样搜索结果真正参与生成,而不是
        画完才补一份用不上的知识。

        Gated:由 *intent_node*(LLM 主动判断)决定是否需要知识接地,不再用
        should_search() 的正则启发式——论文 §3.2 说「智能体会调用搜索工具
        补全相关事实」,意思是 agent 自己判断,不是外部正则。
        NullSearchProvider 是「真但不取数」,所以这一步协议存在、行为 no-op,
        fixture / 离线环境都能跑。
        """
        if not state.needs_search:
            if self.on_progress:
                self.on_progress("search", "skipped", None)
            self._record(state, "search", input_summary="skipped (intent: no search needed)")
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
        # img2img 生成器需要一张输入图。若 sketch 不存在(passthrough 且无参考图),
        # 兜底生成一张中性底图,等价于"从空白起步的文生图"。
        if sketch is None or not Path(sketch).exists():
            sketch = _neutral_canvas(
                state.artifacts.run_dir,
                state.plan.size.width if state.plan else 1024,
                state.plan.size.height if state.plan else 1024,
            )
        # 透传 task_type 给生成器,让生成器按任务族选 rerender 强度:
        # 文字密集 -> 温柔(保字形);材质/场景 -> 强写实
        constraints = {}
        if state.plan is not None:
            constraints["task_type"] = state.plan.task_type.value
            constraints["backend"] = state.plan.backend.value
            constraints["source"] = state.plan.source.value
            if state.plan.code_lang:
                constraints["code_lang"] = state.plan.code_lang
        # 把 search 阶段检索到的文本事实拼到 prompt 里(对应论文 §3.2:
        # "agent 会调用搜索工具补全相关事实"),让图像生成器在最终出图时
        # 能拿到实体的真实外观/属性,而非仅靠 LLM 写 plan 时揣测。
        augmented_prompt = state.prompt
        knowledge_block = _format_knowledge(state.plan.knowledge if state.plan else None)
        if knowledge_block:
            augmented_prompt = state.prompt + "\n" + knowledge_block
        try:
            result = self.generator.generate(
                augmented_prompt, sketch, state.artifacts.final_path, constraints
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
