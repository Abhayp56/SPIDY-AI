"""
core/search package — Modular, Resilient Multi-Provider Web Search Architecture.

Exposes:
- BaseSearchProvider
- GcrawlAISearchProvider
- SerpstackSearchProvider
- ZenserpSearchProvider
- DuckDuckGoSearchProvider
- GeminiSearchProvider
- SearchEngine, get_search_engine
- BackgroundSearchManager, get_background_search_manager
- SearchResult, SearchResponse, SearchMode
"""
from core.search.base import BaseSearchProvider
from core.search.background import BackgroundSearchManager, get_background_search_manager
from core.search.duckduckgo_provider import DuckDuckGoSearchProvider
from core.search.engine import SearchEngine, get_search_engine
from core.search.gcrawl_provider import GcrawlAISearchProvider
from core.search.gemini_provider import GeminiSearchProvider
from core.search.models import SearchMode, SearchResponse, SearchResult
from core.search.serpstack_provider import SerpstackSearchProvider
from core.search.zenserp_provider import ZenserpSearchProvider

__all__ = [
    "BaseSearchProvider",
    "GcrawlAISearchProvider",
    "SerpstackSearchProvider",
    "ZenserpSearchProvider",
    "DuckDuckGoSearchProvider",
    "GeminiSearchProvider",
    "SearchEngine",
    "get_search_engine",
    "BackgroundSearchManager",
    "get_background_search_manager",
    "SearchResult",
    "SearchResponse",
    "SearchMode",
]
