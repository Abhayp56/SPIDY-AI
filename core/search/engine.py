"""
core/search/engine.py — Search Engine & Provider Orchestrator.

Follows SOLID Principles:
- Single Responsibility: Orchestrates search execution, cascades across fallback providers,
  and formats results.
- Dependency Inversion: Depends upon BaseSearchProvider abstractions, which can be injected.
- Loose Coupling: Providers are isolated modules; failure in one gracefully falls through to the next.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from core.search.base import BaseSearchProvider
from core.search.duckduckgo_provider import DuckDuckGoSearchProvider
from core.search.gcrawl_provider import GcrawlAISearchProvider
from core.search.gemini_provider import GeminiSearchProvider
from core.search.models import SearchMode, SearchResponse, SearchResult
from core.search.serpstack_provider import SerpstackSearchProvider
from core.search.zenserp_provider import ZenserpSearchProvider

logger = logging.getLogger(__name__)


class SearchEngine:
    """
    Multi-provider search orchestrator.
    Manages the resilient provider fallback hierarchy:
      1. GcrawlAISearchProvider (anti-bot stealth + JS rendering)
      2. SerpstackSearchProvider (APILayer with HTTPS-to-HTTP fallback)
      3. ZenserpSearchProvider (Google SERP scraper)
      4. DuckDuckGoSearchProvider (Zero-cost, unmetered public search)
      5. GeminiSearchProvider (Final resilient fallback with tool grounding)
    """

    def __init__(self, providers: Optional[Sequence[BaseSearchProvider]] = None):
        """
        Dependency injection constructor.
        If providers are omitted, default resilient ladder is initialized.
        """
        if providers is not None:
            self._providers = list(providers)
        else:
            self._providers = [
                GcrawlAISearchProvider(),
                SerpstackSearchProvider(),
                ZenserpSearchProvider(),
                DuckDuckGoSearchProvider(),
                GeminiSearchProvider(),
            ]

    @property
    def providers(self) -> list[BaseSearchProvider]:
        return self._providers

    def get_provider(self, name: str) -> Optional[BaseSearchProvider]:
        """Lookup provider by name (case-insensitive)."""
        target = name.lower().strip()
        for p in self._providers:
            if p.name.lower() == target:
                return p
        return None

    def execute_search(
        self,
        query: str,
        max_results: int = 5,
        preferred_provider: Optional[str] = None,
        mode: str = "search",
    ) -> SearchResponse:
        """
        Executes query across the provider ladder until a successful response is obtained.

        Args:
            query: The search topic.
            max_results: Maximum results to retrieve.
            preferred_provider: Optional provider name to attempt first.
            mode: Search mode ("search", "news", "research", "price", "compare").
        """
        query_str = query.strip()
        if not query_str:
            return SearchResponse(query="", provider="none", success=False, error="Empty search query")

        # 1. Determine execution ladder
        ladder: list[BaseSearchProvider] = []
        if preferred_provider:
            p = self.get_provider(preferred_provider)
            if p:
                ladder.append(p)

        for p in self._providers:
            if p not in ladder:
                ladder.append(p)

        last_error = ""
        # 2. Walk the ladder
        for provider in ladder:
            if not provider.is_available():
                continue

            try:
                logger.info("[SearchEngine] Querying provider: %s for %r", provider.name, query_str)
                if mode == SearchMode.NEWS.value:
                    resp = provider.news(query_str, max_results=max_results)
                else:
                    resp = provider.search(query_str, max_results=max_results)

                if resp.success and not resp.is_empty:
                    return resp
                elif resp.error:
                    last_error = resp.error
                    logger.warning("[SearchEngine] Provider %s returned: %s", provider.name, resp.error)

            except Exception as exc:
                last_error = str(exc)
                logger.warning("[SearchEngine] Provider %s failed with exception: %s", provider.name, exc)

        return SearchResponse(
            query=query_str,
            provider="fallback_exhausted",
            success=False,
            error=last_error or "All search providers exhausted or unavailable.",
        )

    # ── Formatting Helpers ────────────────────────────────────────────────────

    @staticmethod
    def format_search_results(query: str, resp: SearchResponse) -> str:
        """Converts SearchResponse into clean, structured markdown text."""
        if not resp.success or resp.is_empty:
            return f"No results found for: {query}"

        if resp.raw_text:
            return resp.raw_text.strip()

        lines = [f"Search results for: {query} (via {resp.provider})\n"]
        for idx, r in enumerate(resp.results, 1):
            if r.title:
                lines.append(f"{idx}. {r.title}")
            if r.snippet:
                lines.append(f"   {r.snippet}")
            if r.url:
                lines.append(f"   Source: {r.url}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def format_news_results(query: str, resp: SearchResponse) -> str:
        """Converts news SearchResponse into readable headlines."""
        if not resp.success or resp.is_empty:
            return f"No news found for: {query}"

        if resp.raw_text:
            return resp.raw_text.strip()

        lines = [f"Latest news: {query} (via {resp.provider})\n"]
        for idx, r in enumerate(resp.results, 1):
            if not r.title:
                continue
            src = f"  [{r.source}]" if r.source else ""
            lines.append(f"{idx}. {r.title}{src}")
            if r.snippet:
                lines.append(f"   {r.snippet[:160]}")
            if r.url:
                lines.append(f"   {r.url}")
            lines.append("")
        return "\n".join(lines).strip()


# Default singleton instance
_default_engine: Optional[SearchEngine] = None


def get_search_engine() -> SearchEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = SearchEngine()
    return _default_engine
