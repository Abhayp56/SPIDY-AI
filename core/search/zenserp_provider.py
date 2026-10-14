"""
core/search/zenserp_provider.py — Zenserp Search Provider.

Single Responsibility: Queries Google search results via app.zenserp.com/api/v2/search.
Configured via zenserp_api_key in config/api_keys.json or ZENSERP_API_KEY environment variable.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from core.search.base import BaseSearchProvider
from core.search.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class ZenserpSearchProvider(BaseSearchProvider):
    """
    Search provider retrieving structured Google SERP results via Zenserp API.
    Queries https://app.zenserp.com/api/v2/search.
    """

    ENDPOINT = "https://app.zenserp.com/api/v2/search"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 8.0):
        self._explicit_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "zenserp"

    def _get_key(self) -> str:
        return self._explicit_key or self.resolve_credential("zenserp_api_key", "ZENSERP_API_KEY")

    def is_available(self) -> bool:
        return bool(self._get_key())

    def search(self, query: str, max_results: int = 5, **kwargs) -> SearchResponse:
        key = self._get_key()
        if not key:
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error="Zenserp API key not configured (set zenserp_api_key in config/api_keys.json)",
            )

        headers = {
            "apikey": key,
            "User-Agent": "Mark-LV-Agent/1.0",
        }
        params = {
            "apikey": key,
            "q": query,
            "num": max_results,
        }

        try:
            resp = requests.get(self.ENDPOINT, params=params, headers=headers, timeout=self._timeout)
            if resp.status_code != 200:
                err_msg = f"Zenserp returned HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(err_msg)
                return SearchResponse(query=query, provider=self.name, success=False, error=err_msg)

            data = resp.json()
            return self._parse_results(query, data, max_results)

        except Exception as exc:
            err_msg = f"Zenserp request failed: {exc}"
            logger.warning(err_msg)
            return SearchResponse(query=query, provider=self.name, success=False, error=err_msg)

    def _parse_results(self, query: str, data: dict, max_results: int) -> SearchResponse:
        results: list[SearchResult] = []

        # Zenserp puts primary Google organic SERP entries in the 'organic' list
        organics = data.get("organic", [])
        if isinstance(organics, list):
            for idx, item in enumerate(organics[:max_results], 1):
                if isinstance(item, dict):
                    title = str(item.get("title", "")).strip()
                    url = str(item.get("url", "")).strip()
                    snippet = str(item.get("description", "") or item.get("snippet", "")).strip()
                    domain = str(item.get("domain", "")).strip()

                    if title or url or snippet:
                        results.append(
                            SearchResult(
                                title=title,
                                url=url,
                                snippet=snippet,
                                source=domain,
                                position=item.get("position", idx),
                            )
                        )

        # Fallback to 'news' or 'news_results' if organic was empty
        if not results:
            news_items = data.get("news", []) or data.get("news_results", [])
            if isinstance(news_items, list):
                for idx, item in enumerate(news_items[:max_results], 1):
                    if isinstance(item, dict):
                        results.append(
                            SearchResult(
                                title=str(item.get("title", "")).strip(),
                                url=str(item.get("url", "")).strip(),
                                snippet=str(item.get("description", "") or item.get("snippet", "")).strip(),
                                source=str(item.get("source", "")).strip(),
                                position=idx,
                            )
                        )

        return SearchResponse(
            query=query,
            provider=self.name,
            results=results,
            success=True,
        )
