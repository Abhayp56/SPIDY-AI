"""
core/search/gcrawl_provider.py — GcrawlAI Search Provider.

Single Responsibility: Interfaces with GcrawlAI search API (https://gcrawlai.com/gc/api/v1/search)
utilizing anti-bot stealth and JavaScript rendering.
Configured via gcrawl_api_key (in config/api_keys.json or GCRAWL_API_KEY environment variable).
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from core.search.base import BaseSearchProvider
from core.search.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class GcrawlAISearchProvider(BaseSearchProvider):
    """
    Search provider leveraging GcrawlAI's stealth crawling and search infrastructure.
    Uses https://gcrawlai.com/gc/api/v1/search with anti-bot stealth and JS rendering.
    """

    ENDPOINT = "https://gcrawlai.com/gc/api/v1/search"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 8.0):
        self._explicit_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "gcrawl"

    def _get_key(self) -> str:
        return self._explicit_key or self.resolve_credential("gcrawl_api_key", "GCRAWL_API_KEY")

    def is_available(self) -> bool:
        return bool(self._get_key())

    def search(self, query: str, max_results: int = 5, **kwargs) -> SearchResponse:
        key = self._get_key()
        if not key:
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error="GcrawlAI API key not configured (set gcrawl_api_key in config/api_keys.json)",
            )

        headers = {
            "X-API-Key": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mark-LV-Agent/1.0",
        }

        # Gcrawl search body schema strictly requires {"query": ...}.
        # Anti-bot stealth & JS rendering flags are supplied via query parameters.
        payload = {
            "query": query,
        }
        params = {
            "stealth": "true",
            "render_js": "true",
            "limit": str(max_results),
        }

        try:
            resp = requests.post(
                self.ENDPOINT,
                json=payload,
                params=params,
                headers=headers,
                timeout=self._timeout,
            )

            # Fallback to GET if method not supported
            if resp.status_code in (404, 405):
                params = {
                    "query": query,
                    "stealth": "true",
                    "render_js": "true",
                    "limit": max_results,
                }
                resp = requests.get(
                    self.ENDPOINT,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )

            if resp.status_code != 200:
                err_msg = f"GcrawlAI returned HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(err_msg)
                return SearchResponse(query=query, provider=self.name, success=False, error=err_msg)

            data = resp.json()
            return self._parse_response(query, data, max_results)

        except Exception as exc:
            err_msg = f"GcrawlAI request failed: {exc}"
            logger.warning(err_msg)
            return SearchResponse(query=query, provider=self.name, success=False, error=err_msg)

    def _parse_response(self, query: str, data: dict | list, max_results: int) -> SearchResponse:
        results: list[SearchResult] = []

        raw_items = []
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            raw_items = (
                data.get("results")
                or data.get("data")
                or data.get("organic_results")
                or data.get("items")
                or []
            )

        for idx, item in enumerate(raw_items[:max_results], 1):
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("name") or "").strip()
                url = str(item.get("url") or item.get("link") or item.get("href") or "").strip()
                snippet = str(
                    item.get("snippet")
                    or item.get("description")
                    or item.get("content")
                    or item.get("markdown")
                    or ""
                ).strip()
                source = str(item.get("source") or item.get("domain") or "").strip()

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

        return SearchResponse(
            query=query,
            provider=self.name,
            results=results,
            success=True,
        )
