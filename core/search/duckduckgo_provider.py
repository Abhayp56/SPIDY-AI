"""
core/search/duckduckgo_provider.py — DuckDuckGo Search Provider.

Single Responsibility: Zero-cost, unmetered public search using the Python ddgs / duckduckgo_search
library. Requires no API keys.
"""
from __future__ import annotations

import logging
import importlib
from typing import Any, Optional

from core.search.base import BaseSearchProvider
from core.search.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


def _get_ddgs_cls() -> Optional[Any]:
    """Import and return DDGS class, supporting both ddgs and duckduckgo_search."""
    for mod_name in ("ddgs", "duckduckgo_search"):
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, "DDGS", None)
            if cls is not None:
                return cls
        except Exception:
            continue
    return None


class DuckDuckGoSearchProvider(BaseSearchProvider):
    """
    Zero-cost public search provider using DuckDuckGo.
    Requires no API keys and provides unmetered text and news queries.
    """

    def __init__(self, timeout: float = 6.0):
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "duckduckgo"

    def is_available(self) -> bool:
        return _get_ddgs_cls() is not None

    def search(self, query: str, max_results: int = 5, **kwargs) -> SearchResponse:
        DDGS = _get_ddgs_cls()
        if not DDGS:
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error="Neither 'ddgs' nor 'duckduckgo_search' is installed (run: pip install ddgs)",
            )

        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for idx, r in enumerate(ddgs.text(query, max_results=max_results), 1):
                    title = str(r.get("title", "")).strip()
                    url = str(r.get("href", "") or r.get("url", "")).strip()
                    snippet = str(r.get("body", "") or r.get("snippet", "")).strip()

                    if title or url or snippet:
                        results.append(
                            SearchResult(
                                title=title,
                                url=url,
                                snippet=snippet,
                                position=idx,
                            )
                        )

            return SearchResponse(
                query=query,
                provider=self.name,
                results=results,
                success=True,
            )
        except Exception as exc:
            logger.warning("[DuckDuckGo] text search failed: %s", exc)
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error=f"DuckDuckGo search error: {exc}",
            )

    def news(self, query: str, max_results: int = 8, **kwargs) -> SearchResponse:
        DDGS = _get_ddgs_cls()
        if not DDGS:
            return self.search(f"{query} news", max_results=max_results, **kwargs)

        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for idx, r in enumerate(ddgs.news(query, max_results=max_results), 1):
                    title = str(r.get("title", "")).strip()
                    url = str(r.get("url", "") or r.get("href", "")).strip()
                    snippet = str(r.get("body", "") or r.get("snippet", "")).strip()
                    source = str(r.get("source", "")).strip()

                    if title or url or snippet:
                        results.append(
                            SearchResult(
                                title=title,
                                url=url,
                                snippet=snippet,
                                source=source,
                                position=idx,
                            )
                        )

            if results:
                return SearchResponse(
                    query=query,
                    provider=self.name,
                    results=results,
                    success=True,
                )
        except Exception as exc:
            logger.warning("[DuckDuckGo] news search failed (%s) — falling back to text search", exc)

        # Fallback to standard text search
        return self.search(f"{query} latest news", max_results=max_results, **kwargs)
