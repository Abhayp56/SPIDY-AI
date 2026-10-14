"""
core/search/background.py — Background Search Coordinator.

Single Responsibility: Executes web searches asynchronously in background worker threads,
integrating with AutonomousWorkerManager to prevent blocking real-time voice conversations,
updating the HUD/UI content panel upon completion, and verbally announcing findings.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from core.autonomous_worker import get_worker
from core.search.engine import SearchEngine, get_search_engine

logger = logging.getLogger(__name__)


class BackgroundSearchManager:
    """Coordinates asynchronous background search jobs."""

    def __init__(self, engine: Optional[SearchEngine] = None):
        self._engine = engine or get_search_engine()

    def dispatch_background_search(
        self,
        query: str,
        mode: str = "search",
        max_results: int = 5,
        preferred_provider: Optional[str] = None,
        player: Any = None,
        speak_fn: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Submits web search as an autonomous background worker task.

        Returns an immediate acknowledgment string for the real-time dialogue loop,
        while the actual query executes concurrently in the background thread.
        """
        task_id = f"search_{int(time.time() * 1000)}"
        clean_query = query.strip()
        desc = f"Web Search: {clean_query[:40]}"

        def _worker_fn() -> str:
            logger.info("[BackgroundSearch] Beginning background query: %r (mode=%s)", clean_query, mode)
            resp = self._engine.execute_search(
                query=clean_query,
                max_results=max_results,
                preferred_provider=preferred_provider,
                mode=mode,
            )

            if mode == "news":
                formatted = self._engine.format_news_results(clean_query, resp)
            else:
                formatted = self._engine.format_search_results(clean_query, resp)

            # Update UI content panel if player is available
            if player and hasattr(player, "show_content"):
                try:
                    label = f"{mode.upper()} — {clean_query[:35]}"
                    player.show_content(label, formatted)
                except Exception as ui_err:
                    logger.debug("[BackgroundSearch] Failed updating UI content: %s", ui_err)

            if player and hasattr(player, "write_log"):
                try:
                    player.write_log(f"SYS: Background search completed for '{clean_query}' via {resp.provider}")
                except Exception:
                    pass

            # Provide summary for verbal notification
            if resp.success and not resp.is_empty:
                first_snippet = resp.results[0].title if resp.results else (resp.raw_text[:120] if resp.raw_text else "")
                return f"I found results for '{clean_query}': {first_snippet}"
            else:
                return f"Background search for '{clean_query}' finished with no conclusive results."

        # Submit task to autonomous worker pipeline
        worker = get_worker()
        worker.submit_task(task_id, desc, _worker_fn)

        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: Queued background search for '{clean_query}'")
            except Exception:
                pass

        return f"I have started searching the web for '{clean_query}' in the background. I will notify you with the findings as soon as it completes."


# Singleton instance
_bg_search_manager: Optional[BackgroundSearchManager] = None


def get_background_search_manager() -> BackgroundSearchManager:
    global _bg_search_manager
    if _bg_search_manager is None:
        _bg_search_manager = BackgroundSearchManager()
    return _bg_search_manager
