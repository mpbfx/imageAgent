"""搜索 / 知识检索 provider(论文 §3.1-3.2,plan 增项)。

认知结构化层的"搜索支柱":当 prompt 涉及长尾实体、实时事件、地点、
文化符号或专业对象时,agent 会"调用搜索工具补全相关事实,从而填补
认知空白"(论文 §3.2)。论文的 Mind-Bench 结论依赖一个*多轮*搜索
机制,会从若干候选里挑出最好的(论文 §4)。

这是一个可插拔的 adapter(ADR 0004):默认实现是一个空 stub(节点
存在、契约被调用,但不消耗任何凭据);外部 provider(Tavily / Serper /
自建 SearXNG)实现同样的契约。返回值是 :class:`~genclaw.schemas.KnowledgeRef`
对象,带 ``source``,让 review 层能追溯和核验。
"""

from __future__ import annotations

import abc
from typing import Optional

from genclaw.config import ProviderConfig
from genclaw.schemas import KnowledgeRef, TaskType

# 可选 Tavily 搜索 provider 的环境变量名。
ENV_TAVILY_KEY = "TAVILY_API_KEY"
# 可选 Serper 搜索 provider 的环境变量名。
ENV_SERPER_KEY = "SERPER_API_KEY"
ENV_SERPER_BASE_URL = "SERPER_BASE_URL"


class SearchProvider(abc.ABC):
    """检索事实,为生成提供知识支撑。"""

    name: str

    @abc.abstractmethod
    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        """返回 ``query`` 的检索结果(最相关优先)。"""
        raise NotImplementedError

    def should_search(self, prompt: str, task_type: Optional[TaskType]) -> bool:
        """启发式开关:只有知识驱动型任务才需要检索。

        放在这里(而不是路由函数)是为了让路由保持"纯函数:只看 state"。
        决策权交给 agent / task_type,这里只是廉价的默认值。
        """
        return task_type is TaskType.knowledge_grounded


class NullSearchProvider(SearchProvider):
    """默认空 provider:不检索、无需凭据。

    让 search 节点真存在(能跑、能 trace、能记录空结果),但不发
    起任何网络 I/O——这就是 spec 要求的 phase-1 stub。
    """

    name = "null-search"

    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        return []


class TavilySearchProvider(SearchProvider):
    """Tavily 多轮搜索 provider(与论文对齐的默认外部实现)。

    懒加载 SDK,需要 ``TAVILY_API_KEY``;未配置时抛
    :class:`~genclaw.config.ProviderNotConfiguredError`。
    """

    name = "tavily"

    def __init__(self, config: Optional[ProviderConfig] = None, env: Optional[dict] = None):
        import os

        self.config = config or ProviderConfig.from_env()
        self._api_key = (env or os.environ).get(ENV_TAVILY_KEY)

    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        if not self._api_key:
            from genclaw.config import ProviderNotConfiguredError

            raise ProviderNotConfiguredError(
                self.name,
                ENV_TAVILY_KEY,
                "create a key at https://tavily.com/ and install the 'providers' "
                'extra, or use the default NullSearchProvider.',
            )
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover —— 仅当 SDK 未装时才走这条路径
            raise RuntimeError(
                "the 'tavily-python' package is required for Tavily search"
            ) from exc

        client = TavilyClient(api_key=self._api_key)
        response = client.search(query, max_results=max_results)
        refs = []
        for item in response.get("results", []):
            refs.append(
                KnowledgeRef(
                    claim=item.get("content", ""),
                    source=item.get("url"),
                    confidence=float(item.get("score", 1.0)),
                )
            )
        return refs


class SerperSearchProvider(SearchProvider):
    """Serper.dev 搜索 provider(与 GenEvolve 兼容)。

    支持 Serper 兼容的任何后端(默认 https://google.serper.dev,
    也可自建 SearXNG 等);需要 ``SERPER_API_KEY``。
    """

    name = "serper"

    def __init__(self, config: Optional[ProviderConfig] = None, env: Optional[dict] = None):
        import os

        self.config = config or ProviderConfig.from_env()
        env = env or os.environ
        self._api_key = env.get(ENV_SERPER_KEY)
        self.base_url = (env.get(ENV_SERPER_BASE_URL) or "https://google.serper.dev").rstrip("/")

    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        if not self._api_key:
            from genclaw.config import ProviderNotConfiguredError

            raise ProviderNotConfiguredError(
                self.name,
                ENV_SERPER_KEY,
                "create a key at https://serper.dev/ and set SERPER_API_KEY, "
                "or use the default NullSearchProvider.",
            )
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("the 'requests' package is required for Serper search") from exc

        url = f"{self.base_url}/search"
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": max_results}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Serper search failed: {exc}") from exc

        refs = []
        for item in data.get("organic", []):
            refs.append(
                KnowledgeRef(
                    claim=item.get("snippet", ""),
                    source=item.get("link") or item.get("url"),
                    confidence=1.0,  # Serper 不提供 score,默认满信度
                )
            )
        return refs
