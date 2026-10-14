"""
core/search/base.py — Abstract Base Class for Search Providers.

Adheres to:
- Open/Closed Principle (OCP): New search backends can be added by implementing
  BaseSearchProvider without altering existing provider logic.
- Liskov Substitution Principle (LSP): Every provider subtype can be used interchangeably
  by the SearchEngine orchestrator.
- Interface Segregation Principle (ISP): Minimal, clean contract focused exclusively
  on querying web intelligence.
"""
from __future__ import annotations

import abc
import os
from typing import Optional

from core.search.models import SearchResponse, SearchResult
from memory import config_manager


class BaseSearchProvider(abc.ABC):
    """Abstract interface that all search providers must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. 'gcrawl', 'serpstack', 'zenserp', 'duckduckgo', 'gemini')."""
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        """
        Cheap, non-network check to verify if this provider has required credentials or dependencies.
        Returns True if the provider is ready to execute queries.
        """
        pass

    @abc.abstractmethod
    def search(self, query: str, max_results: int = 5, **kwargs) -> SearchResponse:
        """
        Execute a standard web search.

        Args:
            query: The search term or topic.
            max_results: Upper bound on the number of organic results to extract.

        Returns:
            SearchResponse containing structured SearchResult items or synthesized text.
        """
        pass

    def news(self, query: str, max_results: int = 8, **kwargs) -> SearchResponse:
        """
        Execute a news search. Providers with a native news API override this;
        default implementation appends news intent to the standard query.
        """
        news_query = f"{query} news" if query else "latest news"
        return self.search(news_query, max_results=max_results, **kwargs)

    @staticmethod
    def resolve_credential(config_key: str, env_var: Optional[str] = None) -> str:
        """
        Dependency helper: Reads API key from config/api_keys.json or environment variable.
        Loose coupling: does not hardcode filesystem paths or environmental assumptions.
        """
        env_val = os.environ.get(env_var, "").strip() if env_var else ""
        if env_val:
            return env_val

        try:
            cfg = config_manager.load_api_keys()
            val = cfg.get(config_key, "")
            if isinstance(val, str) and val.strip():
                return val.strip()
        except Exception:
            pass

        return ""
