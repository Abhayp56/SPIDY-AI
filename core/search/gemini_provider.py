"""
core/search/gemini_provider.py — Gemini Grounded Search Provider (Final Resilient Fallback).

Single Responsibility: Uses Gemini with Google Search tool grounding (tools: [{"google_search": {}}]).
Queries Google directly and produces a synthesized factual answer.
Includes quota circuit breaker to protect against 429 rate limit errors.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from core.search.base import BaseSearchProvider
from core.search.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)

# Grounding quota cooldown circuit breaker
_QUOTA_COOLDOWN_SEC = 900  # 15 minutes
_quota_blocked_until = 0.0
_quota_lock = threading.Lock()


class _QuotaCooldown(RuntimeError):
    """Raised when Gemini grounding quota circuit breaker is open."""


class GeminiSearchProvider(BaseSearchProvider):
    """
    Final resilient search fallback using Gemini grounded search.
    Invokes Google Search directly via tool grounding and synthesizes factually verified answers.
    """

    def __init__(self, timeout_ms: int = 30_000):
        self._timeout_ms = timeout_ms

    @property
    def name(self) -> str:
        return "gemini"

    @classmethod
    def is_quota_available(cls) -> bool:
        with _quota_lock:
            return time.monotonic() >= _quota_blocked_until

    @classmethod
    def trip_quota_breaker(cls, exc: Exception) -> None:
        global _quota_blocked_until
        msg = str(exc)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            with _quota_lock:
                already = time.monotonic() < _quota_blocked_until
                _quota_blocked_until = time.monotonic() + _QUOTA_COOLDOWN_SEC
            if not already:
                logger.warning(
                    "[GeminiSearch] Gemini grounding quota exhausted — circuit breaker active for %d min.",
                    _QUOTA_COOLDOWN_SEC // 60,
                )

    def is_available(self) -> bool:
        if not self.is_quota_available():
            return False
        # Verify gemini client is accessible
        try:
            from core import gemini
            key_fn = getattr(gemini, "api_key", getattr(gemini, "get_api_key", None))
            return bool(key_fn() if key_fn else False)
        except Exception:
            return False

    def search(self, query: str, max_results: int = 5, **kwargs) -> SearchResponse:
        if not self.is_quota_available():
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error="Gemini grounding is currently in quota cooldown",
            )

        try:
            from core import gemini

            response = gemini.call(
                query,
                tier=gemini.SEARCH,
                config={"tools": [{"google_search": {}}]},
                timeout_ms=self._timeout_ms,
            )

            if response is None:
                raise RuntimeError("All Gemini models on the fallback ladder failed.")

            text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

            text = text.strip()
            if not text:
                raise ValueError("Gemini grounded search returned empty text.")

            # Grounding metadata (URLs/sources) if present
            results: list[SearchResult] = []
            try:
                candidate = response.candidates[0]
                grounding_meta = getattr(candidate, "grounding_metadata", None)
                if grounding_meta:
                    chunks = getattr(grounding_meta, "grounding_chunks", []) or []
                    for idx, chunk in enumerate(chunks[:max_results], 1):
                        web_info = getattr(chunk, "web", None)
                        if web_info:
                            uri = getattr(web_info, "uri", "")
                            title = getattr(web_info, "title", "")
                            if uri:
                                results.append(
                                    SearchResult(
                                        title=title or uri,
                                        url=uri,
                                        snippet=title or "Google Search Grounding Source",
                                        position=idx,
                                    )
                                )
            except Exception:
                pass

            return SearchResponse(
                query=query,
                provider=self.name,
                results=results,
                raw_text=text,
                success=True,
            )

        except Exception as exc:
            self.trip_quota_breaker(exc)
            logger.warning("[GeminiSearch] Grounded search failed: %s", exc)
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error=f"Gemini grounded search error: {exc}",
            )
