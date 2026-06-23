"""Pipeline 编排(plan task 11)。

``Pipeline.run`` 构造初始 state 与 run artifacts,然后通过两条路径之一
驱动 workflow:编译后的 LangGraph 图(``builder.py``),或直接按顺序
执行同样的 node 函数。直接路径让 pipeline 可以在不安装 langgraph
的情况下跑全流程(phase-1 的懒加载策略);两条路径用完全相同的
node 可调用对象与路由函数,所以行为一致。

所有 artifact 与 trace 都是 node 的副作用写出的。provider / backend
失败会留一条结构化 error artifact,挂到 ``state.errors`` 上——绝不
吞掉(ADR 0001)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

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
from genclaw.search import NullSearchProvider, SearchProvider, SerperSearchProvider, TavilySearchProvider


def _new_request_id(prompt: str, counter: int) -> str:
    """确定性的 request id(不读时钟、不取随机,保证可复现)。"""
    slug = "".join(c if c.isalnum() else "-" for c in prompt.lower())[:24].strip("-")
    return f"{slug or 'run'}-{counter:03d}"


def build_providers(mode: str, search_provider: Optional[str] = None):
    """按 mode 构造 (agent, generator, reviewer, search)。

    * ``fixture``  —— 确定性、无需凭据(FixtureAgent + mock + rules
      + null search,除非指定 search_provider)。
    * ``external`` —— 与论文对齐的栈(ADR 0004),默认 *code-as-brush*:
      LLM 直接写 SVG / HTML / Three.js 源码(论文核心机制)。Claude-Opus
      agent、图像生成器、VLM 审查者、搜索 provider(默认 Tavily,可选 Serper)。
      凭据缺失时 adapter 抛 :class:`ProviderNotConfiguredError`。
    * ``external-template`` —— 同样的栈,但 agent 产*结构化*模板
      plan,不再产自由形式代码。是确定性兜底 / 基线,不会执行模型
      写的代码。
    * ``external-code`` —— ``external`` 的显式别名(code-as-brush)。

    ``search_provider`` 指定搜索后端:'tavily' (默认外部) 或 'serper'。
    在 fixture 模式下省略此参数时仍用 NullSearchProvider。

    返回 4 元组;未知 mode 抛 ValueError。
    """
    if mode == "fixture":
        search = NullSearchProvider()
        if search_provider == "serper":
            search = SerperSearchProvider()
        elif search_provider == "tavily":
            search = TavilySearchProvider()
        return (
            FixtureAgent(),
            MockImageGenerator(),
            RuleReviewer(),
            search,
        )
    if mode in ("external", "external-code", "external-template"):
        from genclaw.agent.external import ExternalLLMAgent
        from genclaw.generators.external import (
            GeminiImageGenerator,
            OpenAICompatImageGenerator,
            UniAPIImageEditGenerator,
        )
        from genclaw.review.composite import CompositeReviewer
        from genclaw.review.vlm import VLMReviewer

        cfg = ProviderConfig.from_env()
        # 根据 provider 配置挑选生成器:
        # 1. 配了 UniAPI(走 Qwen 图像编辑)就用 UniAPI
        # 2. 配了 OpenAI 兼容(自定义 GOOGLE_BASE_URL 或 legacy)就用 OpenAI 兼容
        # 3. 默认 Gemini
        if cfg.uniapi_api_key:
            generator = UniAPIImageEditGenerator()
        elif cfg.google_base_url or cfg.uniapi_api_key:
            generator = OpenAICompatImageGenerator()
        else:
            generator = GeminiImageGenerator()

        # 结构检查跑在 canvas 源码上;VLM 只看最终成图的感知保真度
        # (见 CompositeReviewer)。
        reviewer = CompositeReviewer(perceptual=VLMReviewer())
        # code-as-brush 是真实模型的**默认**(ADR 0003/0005):论文是
        # "code-driven",所以 external == code-as-brush。只有
        # external-template 走结构化模板路径。
        code_mode = mode != "external-template"
        agent = ExternalLLMAgent(code_mode=code_mode)

        # 按 search_provider 参数选搜索后端。未显式指定时,根据已配置的
        # 凭据自动选择;都没配则降级到 NullSearchProvider(ADR 0004:
        # 凭据不可得时退回开源/空实现,而不是硬选一个会报错的 provider)。
        import os

        if search_provider == "serper":
            search = SerperSearchProvider()
        elif search_provider == "tavily":
            search = TavilySearchProvider()
        elif os.environ.get("TAVILY_API_KEY"):
            search = TavilySearchProvider()
        elif os.environ.get("SERPER_API_KEY"):
            search = SerperSearchProvider()
        else:
            search = NullSearchProvider()

        return (
            agent,
            generator,
            reviewer,
            search,
        )
    raise ValueError(
        f"unknown mode {mode!r}; expected 'fixture', 'external', "
        "'external-code', or 'external-template'"
    )


class Pipeline:
    """端到端跑 GenClaw pipeline。"""

    def __init__(
        self,
        agent: Optional[AgentProvider] = None,
        generator: Optional[ImageGenerator] = None,
        reviewer: Optional[Reviewer] = None,
        *,
        search: Optional["SearchProvider"] = None,
        base_dir: str | Path = "outputs/runs",
        use_langgraph: bool = False,
        on_progress: Optional[Callable[[str, str, Optional[dict]], None]] = None,
    ):
        self.agent = agent or FixtureAgent()
        self.generator = generator or MockImageGenerator()
        self.reviewer = reviewer or RuleReviewer()
        self.search = search  # None 时 GraphNodes 默认用 NullSearchProvider
        self.base_dir = Path(base_dir)
        self.use_langgraph = use_langgraph
        self.on_progress = on_progress
        self._counter = 0

    @classmethod
    def for_mode(
        cls,
        mode: str = "fixture",
        *,
        base_dir: str | Path = "outputs/runs",
        use_langgraph: bool = False,
        on_progress: Optional[Callable[[str, str, Optional[dict]], None]] = None,
        search_provider: Optional[str] = None,
    ) -> "Pipeline":
        """按 ``mode`` 选好 provider 栈再构造 Pipeline。

        ``search_provider`` 指定搜索后端:'tavily' (默认) 或 'serper'。
        """
        agent, generator, reviewer, search = build_providers(mode, search_provider=search_provider)
        return cls(
            agent,
            generator,
            reviewer,
            search=search,
            base_dir=base_dir,
            use_langgraph=use_langgraph,
            on_progress=on_progress,
        )

    def run(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        max_revisions: int = 1,
        *,
        request_id: Optional[str] = None,
        timestamp: str = "00000000-000000",
        skip_review: Optional[bool] = None,
    ) -> GenClawState:
        """为 ``prompt`` 跑一次 pipeline,返回最终 state。

        ``timestamp`` 由调用方注入(不读时钟),用于产出可复现的
        run 目录;想要真实时间戳的调用方自己传一个进来。

        ``skip_review`` 控制是否跳过审查阶段。None 时根据 agent 类型
        自动决定（fixture 默认跳过,external 默认运行）。
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
            on_progress=self.on_progress,
        )

        # 默认行为：所有模式都跳过审查，除非显式指定
        if skip_review is None:
            skip_review = True

        if self.use_langgraph:
            final = self._run_langgraph(nodes, state, skip_review=skip_review)
        else:
            final = self._run_direct(nodes, state, skip_review=skip_review)
        return final

    def _run_direct(self, nodes: GraphNodes, state: GenClawState, skip_review: bool = False) -> GenClawState:
        """直接按顺序执行节点,镜像 LangGraph 的边和路由。"""
        state = nodes.conceptualize(state)
        if state.plan is None:  # conceptualize 失败;停,error 已写。
            return state
        state = nodes.search_node(state)  # 在 sketch 之前先做知识接地

        revision = 0
        while True:
            state = nodes.render(state)
            state = nodes.generate(state)
            if skip_review:
                # 跳过审查,直接返回
                break
            state = nodes.review(state)
            if route_after_review(state) == REVISE:
                revision += 1
                if self.on_progress:
                    self.on_progress(
                        "revise",
                        "starting",
                        {"revision": revision, "max_revisions": state.max_revisions},
                    )
                state = nodes.revise(state)
                continue
            break
        return state

    def _run_langgraph(self, nodes: GraphNodes, state: GenClawState, skip_review: bool = False) -> GenClawState:
        from genclaw.graph.builder import build_graph

        graph = build_graph(nodes)
        result = graph.invoke(state)
        # langgraph 可能返回 dict-like;统一回 GenClawState。
        if isinstance(result, GenClawState):
            return result
        return GenClawState.model_validate(result)
