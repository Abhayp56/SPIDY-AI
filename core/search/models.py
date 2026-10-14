"""
core/search/models.py — Data models for the Web Search subsystem.

Follows Single Responsibility Principle (SRP): Isolates data transfer objects
and representations used across all search providers and consumers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SearchMode(str, Enum):
    """Supported search operation modes."""
    SEARCH = "search"
    NEWS = "news"
    RESEARCH = "research"
    PRICE = "price"
    COMPARE = "compare"


@dataclass
class SearchResult:
    """Represents an individual organic or news search item."""
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""
    position: int = 0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "position": self.position,
        }


@dataclass
class SearchResponse:
    """Unified container for results returned by any SearchProvider."""
    query: str
    provider: str
    results: list[SearchResult] = field(default_factory=list)
    raw_text: Optional[str] = None
    success: bool = True
    error: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """True if the provider returned no usable snippet/result or synthesized text."""
        return not bool(self.results) and not bool(self.raw_text and self.raw_text.strip())
