"""Search / knowledge-retrieval providers (paper §3.1-3.2, plan addition).

The cognitive structuring layer's search pillar: when a prompt involves
long-tail entities, real-time events, locations, cultural symbols, or
professional objects, the agent "calls search tools to complete the relevant
facts, thereby filling the cognitive gap" (paper §3.2). The paper's Mind-Bench
results rely on a *multi-round* search mechanism that filters the best of
several retrieved candidates (paper §4).

This is a pluggable adapter (ADR 0004): the default is a no-op stub (so the
node exists and the contract is exercised without credentials); external
providers (Tavily / self-hosted SearXNG) implement the same contract. Results
are returned as :class:`~genclaw.schemas.KnowledgeRef` objects with a ``source``
so the Review layer can trace and verify them.
"""

from __future__ import annotations

import abc
from typing import Optional

from genclaw.config import ProviderConfig
from genclaw.schemas import KnowledgeRef, TaskType

# Env var for the optional Tavily search provider.
ENV_TAVILY_KEY = "TAVILY_API_KEY"


class SearchProvider(abc.ABC):
    """Retrieves facts to ground generation."""

    name: str

    @abc.abstractmethod
    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        """Return retrieved facts for ``query`` (most relevant first)."""
        raise NotImplementedError

    def should_search(self, prompt: str, task_type: Optional[TaskType]) -> bool:
        """Heuristic gate: only knowledge-grounded tasks need retrieval.

        Kept here (not in the route function) so routing stays a pure function
        of state. The agent/task_type decides; this is the cheap default.
        """
        return task_type is TaskType.knowledge_grounded


class NullSearchProvider(SearchProvider):
    """Default no-op provider: retrieves nothing, credential-free.

    Makes the search node real (it runs, traces, and records an empty result)
    without performing network I/O -- the phase-1 stub the spec requires.
    """

    name = "null-search"

    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        return []


class TavilySearchProvider(SearchProvider):
    """Tavily-backed multi-round search (paper-aligned default external).

    Imports the SDK lazily and requires ``TAVILY_API_KEY``; raises
    :class:`~genclaw.config.ProviderNotConfiguredError` when unconfigured.
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
        except ImportError as exc:  # pragma: no cover - exercised only without SDK
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
