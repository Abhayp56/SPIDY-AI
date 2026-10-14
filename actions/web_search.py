# actions/web_search.py
"""
actions/web_search.py — Web Intelligence & Search Action for Mark-LV.

Supports multi-provider resilient search with background execution:
1. GcrawlAISearchProvider: Anti-bot stealth & JS rendering (gcrawl_api_key).
2. SerpstackSearchProvider: APILayer Serpstack with auto HTTPS-to-HTTP fallback (serpstack_api_key).
3. ZenserpSearchProvider: Google SERP search API (zenserp_api_key).
4. DuckDuckGoSearchProvider: Zero-cost, unmetered public search without API keys.
5. GeminiSearchProvider: Final resilient fallback with Google Search tool grounding.

Backward-Compatible: Preserves all existing exported functions (_news, _ddg_news, _gemini_headlines, etc.).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from core.search import (
    DuckDuckGoSearchProvider,
    GcrawlAISearchProvider,
    GeminiSearchProvider,
    SerpstackSearchProvider,
    ZenserpSearchProvider,
    get_background_search_manager,
    get_search_engine,
)

logger = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("gemini_api_key", "")


# ── Backward-compatible helper functions ──────────────────────────────────────

def _gemini_available() -> bool:
    return GeminiSearchProvider.is_quota_available()


def _gemini_search(query: str) -> str:
    """Invokes GeminiSearchProvider grounded search."""
    provider = GeminiSearchProvider()
    resp = provider.search(query)
    if not resp.success:
        raise RuntimeError(resp.error or "Gemini search failed")
    return resp.raw_text or ""


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    """Preserves legacy signature returning list of dicts with title, snippet, url."""
    provider = DuckDuckGoSearchProvider()
    resp = provider.search(query, max_results=max_results)
    return [
        {"title": r.title, "snippet": r.snippet, "url": r.url}
        for r in resp.results
    ]


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """Preserves legacy signature returning list of dicts with title, snippet, url, source."""
    provider = DuckDuckGoSearchProvider()
    resp = provider.news(query, max_results=max_results)
    return [
        {"title": r.title, "snippet": r.snippet, "url": r.url, "source": r.source}
        for r in resp.results
    ]


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"
    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from core import gemini

    response = gemini.call(
        f"Current world news: {n} headlines. Numbered list, titles only.",
        tier=gemini.SEARCH,
        config={"tools": [{"google_search": {}}]},
        timeout_ms=30_000,
    )
    if response is None:
        return [], ""

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Search Modes ──────────────────────────────────────────────────────────────

def _search(query: str, provider: Optional[str] = None) -> str:
    """Standard search across the provider ladder."""
    engine = get_search_engine()
    resp = engine.execute_search(query, preferred_provider=provider, mode="search")
    return engine.format_search_results(query, resp)


def _news(query: str, provider: Optional[str] = None) -> str:
    """News search across the provider ladder."""
    engine = get_search_engine()
    resp = engine.execute_search(query, preferred_provider=provider, mode="news")
    return engine.format_news_results(query, resp)


def _research(query: str, provider: Optional[str] = None) -> str:
    """Deep research query."""
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    engine = get_search_engine()
    resp = engine.execute_search(research_query, max_results=8, preferred_provider=provider, mode="research")
    return engine.format_search_results(query, resp)


def _price(query: str, provider: Optional[str] = None) -> str:
    """Product price lookup."""
    price_query = f"current price of {query} — how much does it cost today"
    engine = get_search_engine()
    resp = engine.execute_search(price_query, max_results=6, preferred_provider=provider, mode="price")
    return engine.format_search_results(query, resp)


def _compare(items: list[str], aspect: str, provider: Optional[str] = None) -> str:
    """Side-by-side comparison across items."""
    engine = get_search_engine()
    query = f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data."
    resp = engine.execute_search(query, max_results=6, preferred_provider=provider, mode="compare")
    if resp.success and resp.raw_text:
        return resp.raw_text

    all_results: dict[str, list] = {}
    for item in items:
        item_resp = engine.execute_search(f"{item} {aspect}", max_results=3, preferred_provider=provider)
        all_results[item] = item_resp.results

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.snippet:
                lines.append(f"  • {r.snippet}")
            if r.url:
                lines.append(f"    {r.url}")
    return "\n".join(lines)


# ── Public Entry Point ────────────────────────────────────────────────────────

def web_search(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Main tool handler for web search.
    Supports immediate synchronous execution or non-blocking background execution.
    """
    params = parameters or {}
    query = str(params.get("query", "")).strip()
    mode = str(params.get("mode", "search")).lower().strip() or "search"
    items = params.get("items", [])
    aspect = str(params.get("aspect", "general")).strip() or "general"
    background = bool(params.get("background", False))
    provider = str(params.get("provider", "")).strip().lower() or None
    if provider in ("auto", "none", ""):
        provider = None

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    search_target = query or ", ".join(items)

    if player and hasattr(player, "write_log"):
        player.write_log(f"[Search:{mode}{':bg' if background else ''}] {search_target}")

    print(f"[WebSearch] [Search] mode={mode!r}  query={search_target!r}  bg={background}  provider={provider!r}")

    # 1. Asynchronous background execution
    if background:
        bg_mgr = get_background_search_manager()
        return bg_mgr.dispatch_background_search(
            query=search_target,
            mode=mode,
            preferred_provider=provider,
            player=player,
            speak_fn=speak,
        )

    # 2. Synchronous foreground execution
    try:
        if mode == "compare" and items:
            return _compare(items, aspect, provider=provider)
        if mode == "news":
            return _news(query, provider=provider)
        if mode == "research":
            return _research(query, provider=provider)
        if mode == "price":
            return _price(query, provider=provider)
        return _search(query, provider=provider)

    except Exception as e:
        logger.error("[WebSearch] Search execution failed: %s", e)
        return f"Search failed: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────

TOOL = {
    "name": "web_search",
    "description": (
        "Searches the web using multi-provider intelligence (GcrawlAI, Serpstack, Zenserp, "
        "DuckDuckGo, and Gemini Grounding). Use for questions about current facts, live news, "
        "prices, technical research, or comparisons. Set background=True when the user asks "
        "to search or monitor in the background without waiting for speech."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Search query or topic to look up",
            },
            "mode": {
                "type": "STRING",
                "description": "Operation mode: search (default) | news | research | price | compare",
            },
            "background": {
                "type": "BOOLEAN",
                "description": "Set to true to execute search asynchronously in the background and notify when complete",
            },
            "provider": {
                "type": "STRING",
                "description": "Optional search provider preference: auto | gcrawl | serpstack | zenserp | duckduckgo | gemini",
            },
            "items": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING",
                },
                "description": "Items to compare (used in compare mode)",
            },
            "aspect": {
                "type": "STRING",
                "description": "Comparison aspect: price | specs | reviews | features",
            },
        },
        "required": [
            "query",
        ],
    },
    "handler": web_search,
}
