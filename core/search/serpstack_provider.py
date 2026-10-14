"""
core/search/serpstack_provider.py — Serpstack Search Provider.

Single Responsibility: Interfaces with APILayer Serpstack API (api.serpstack.com/search).
Automatically handles SSL/HTTPS restrictions on free plans with an HTTP retry fallback
when APILayer rejects HTTPS queries (code 105 / https_access_restricted).
Configured via serpstack_api_key in config/api_keys.json or SERPSTACK_API_KEY environment variable.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from core.search.base import BaseSearchProvider
from core.search.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class SerpstackSearchProvider(BaseSearchProvider):
    """
    Search provider querying APILayer Serpstack API.
    Handles HTTPS encryption restrictions on free subscription tiers by catching
    code 105 / SSLError and automatically re-executing via plaintext HTTP fallback.
    """

    HTTPS_ENDPOINT = "https://api.serpstack.com/search"
    HTTP_ENDPOINT = "http://api.serpstack.com/search"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 8.0):
        self._explicit_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "serpstack"

    def _get_key(self) -> str:
        return (
            self._explicit_key
            or self.resolve_credential("serpstack_api_key", "SERPSTACK_API_KEY")
            or self.resolve_credential("serpstack_access_key", "SERPSTACK_ACCESS_KEY")
        )

    def is_available(self) -> bool:
        return bool(self._get_key())

    def search(self, query: str, max_results: int = 5, **kwargs) -> SearchResponse:
        key = self._get_key()
        if not key:
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error="Serpstack API key not configured (set serpstack_api_key in config/api_keys.json)",
            )

        params = {
            "access_key": key,
            "query": query,
            "num": max_results,
        }

        # 1. Attempt HTTPS endpoint first
        use_http_fallback = False
        data = None

        try:
            resp = requests.get(self.HTTPS_ENDPOINT, params=params, timeout=self._timeout)
            if resp.status_code == 200:
                payload = resp.json()
                # Check for APILayer error response (e.g. Code 105: https_access_restricted)
                if isinstance(payload, dict) and "error" in payload:
                    err = payload.get("error", {})
                    code = err.get("code")
                    err_type = str(err.get("type", ""))
                    if code == 105 or "https_access_restricted" in err_type:
                        logger.info("[Serpstack] Free plan HTTPS restriction detected (Code 105) — switching to HTTP fallback.")
                        use_http_fallback = True
                    else:
                        err_info = err.get("info", f"Error {code}: {err_type}")
                        return SearchResponse(query=query, provider=self.name, success=False, error=err_info)
                else:
                    data = payload
            elif resp.status_code in (403, 400):
                use_http_fallback = True
            else:
                return SearchResponse(
                    query=query,
                    provider=self.name,
                    success=False,
                    error=f"Serpstack returned HTTP {resp.status_code}",
                )

        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as ssl_err:
            logger.info("[Serpstack] SSL/Connection error encountered (%s) — retrying over HTTP.", ssl_err)
            use_http_fallback = True
        except Exception as exc:
            logger.warning("[Serpstack] Unexpected HTTPS failure: %s", exc)
            use_http_fallback = True

        # 2. Execute HTTP fallback if HTTPS was rejected due to plan limitations
        if use_http_fallback:
            try:
                resp_http = requests.get(self.HTTP_ENDPOINT, params=params, timeout=self._timeout)
                if resp_http.status_code != 200:
                    return SearchResponse(
                        query=query,
                        provider=self.name,
                        success=False,
                        error=f"Serpstack HTTP fallback returned {resp_http.status_code}: {resp_http.text[:150]}",
                    )
                payload = resp_http.json()
                if isinstance(payload, dict) and "error" in payload:
                    err = payload.get("error", {})
                    return SearchResponse(
                        query=query,
                        provider=self.name,
                        success=False,
                        error=str(err.get("info") or err),
                    )
                data = payload
            except Exception as http_err:
                return SearchResponse(
                    query=query,
                    provider=self.name,
                    success=False,
                    error=f"Serpstack HTTP fallback failed: {http_err}",
                )

        if not data:
            return SearchResponse(
                query=query,
                provider=self.name,
                success=False,
                error="Serpstack returned no data.",
            )

        return self._parse_results(query, data, max_results)

    def _parse_results(self, query: str, data: dict, max_results: int) -> SearchResponse:
        results: list[SearchResult] = []

        # Organic search results
        organics = data.get("organic_results", [])
        for idx, item in enumerate(organics[:max_results], 1):
            if isinstance(item, dict):
                title = str(item.get("title", "")).strip()
                url = str(item.get("url", "")).strip()
                snippet = str(item.get("snippet", "")).strip()
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

        # News results if present
        if not results and "news_results" in data:
            for idx, item in enumerate(data.get("news_results", [])[:max_results], 1):
                if isinstance(item, dict):
                    results.append(
                        SearchResult(
                            title=str(item.get("title", "")).strip(),
                            url=str(item.get("url", "")).strip(),
                            snippet=str(item.get("snippet", "")).strip(),
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
