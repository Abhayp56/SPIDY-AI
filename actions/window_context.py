"""
actions/window_context.py
Action tool for real-time window tracking and ambient desktop context.

Architecture & Design Decisions:
- Follows SOLID principles:
  - Single Responsibility: Mediates between the assistant and the underlying WindowTracker.
  - Dependency Inversion: Uses get_window_tracker() singleton/dependency injection.
- Seamlessly auto-discovered by core/action_loader.py without hardcoded dispatch in main.py.
- Backward-compatible and production-ready.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from core.window_tracker import get_window_tracker, WindowTracker


def window_context(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for window_context tool.
    Supports querying active window, listing open windows, focusing, and closing.
    """
    params = parameters or {}
    action = params.get("action", "get_active").strip().lower()
    query = params.get("query", "").strip()

    tracker = get_window_tracker()

    try:
        if action in ("get_active", "current", "active"):
            active = tracker.get_active_window()
            if not active or not active.title:
                return "The desktop or background is currently active (no focused application window)."
            
            lines = [
                f"Active Application: {active.app_name or active.process_name}",
                f"Window Title: '{active.title}'",
                f"Process: {active.process_name} (PID: {active.pid})",
            ]
            if active.focus_duration > 0:
                lines.append(f"Focused Duration: {int(active.focus_duration)} seconds")
            if active.bounds and active.bounds.get("width", 0) > 0:
                b = active.bounds
                lines.append(f"Window Size: {b['width']}x{b['height']} at ({b['left']},{b['top']})")
            return "\n".join(lines)

        elif action in ("list_windows", "list", "open_apps", "running_apps"):
            windows = tracker.list_visible_windows()
            if not windows:
                windows = tracker.find_all_desktop_windows(include_minimized=True)
            if not windows:
                return "No open application windows were detected."
            
            lines = [f"Found {len(windows)} application window(s):"]
            for i, w in enumerate(windows, 1):
                marker = " [ACTIVE]" if w.is_active else ""
                lines.append(f"{i}. {w.format_summary()}{marker}")
            return "\n".join(lines)

        elif action in ("focus_window", "focus", "switch_to"):
            if not query:
                return "Please specify an application name or window title to focus."
            ok = tracker.focus_window(query)
            if ok:
                # Retrieve the newly active window
                new_active = tracker.get_active_window()
                summary = new_active.format_summary() if new_active and new_active.title else f"[{query}]"
                return f"Switched focus to {summary}."
            return f"Could not find or focus window matching '{query}'."

        elif action in ("close_window", "close", "close_active"):
            target = query if query else "active"
            ok = tracker.close_window(target)
            if ok:
                return f"Sent close signal to {target} window."
            return f"Failed to close window for query '{target}'."

        elif action in ("minimize", "minimize_window", "minimize_current", "minimize_active"):
            ok = tracker.minimize_window(query or None)
            return "Window minimized." if ok else "Failed to minimize window."

        elif action in ("maximize", "maximize_window", "maximize_current", "maximize_active"):
            ok = tracker.maximize_window(query or None)
            return "Window maximized." if ok else "Failed to maximize window."

        elif action in ("get_history", "history"):
            history = tracker.get_history()
            if not history:
                return "No window switch history recorded yet."
            lines = ["Recent window focus history:"]
            for i, h in enumerate(history, 1):
                lines.append(f"{i}. {h.format_summary()}")
            return "\n".join(lines)

        else:
            return f"Unknown window_context action: '{action}'. Valid actions are: get_active, list_windows, focus_window, close_window, minimize, maximize, get_history."

    except Exception as e:
        print(f"[window_context] Error: {e}")
        return f"Window context operation failed: {e}"


# ── Auto-Discovered Tool Declaration ──────────────────────────────────────────
TOOL = {
    "name": "window_context",
    "description": (
        "Inspect and control desktop windows and applications. "
        "Use this whenever the user asks what app/window they are using ('what window is this?', "
        "'what am I looking at?', 'what apps are open?'), or asks to switch/focus to an application "
        "or close/minimize/maximize windows."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "The action to execute: 'get_active' (current window), 'list_windows' (all open visible windows), "
                    "'focus_window' (switch focus to app), 'close_window' (close target or active window), "
                    "'minimize', 'maximize', or 'get_history'."
                ),
            },
            "query": {
                "type": "STRING",
                "description": (
                    "Application name or window title for 'focus_window' or 'close_window' (e.g. 'Chrome', 'VS Code', 'Spotify')."
                ),
            },
        },
        "required": ["action"],
    },
    "handler": window_context,
}
