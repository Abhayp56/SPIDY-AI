"""
actions/gui_navigator.py
Action tool for vision-guided desktop UI element navigation and clicking.

Architecture & Design Decisions:
- Follows SOLID principles:
  - Single Responsibility: Exposes high-level vision navigation actions to the assistant.
  - Dependency Inversion: Uses get_gui_grounding() singleton/dependency injection.
- Seamlessly auto-discovered by core/action_loader.py.
- Returns concise, descriptive feedback for speech and HUD logging.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from core.gui_grounding import get_gui_grounding


def gui_navigator(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for gui_navigator tool.
    Visually locates and interacts with buttons, icons, menus, and input fields.
    """
    params = parameters or {}
    action = params.get("action", "click").strip().lower()
    description = params.get("description", "").strip()
    text = params.get("text", "")
    submit = bool(params.get("submit", False))
    clear_first = bool(params.get("clear_first", True))
    window = params.get("window", None)

    if not description:
        return "Please provide a description of the UI element to locate or click."

    engine = get_gui_grounding()

    try:
        if action in ("click", "left_click"):
            res = engine.click_element(description, click_type="single", window_query=window)
            return res.summary()

        elif action in ("double_click", "double"):
            res = engine.click_element(description, click_type="double", window_query=window)
            return res.summary()

        elif action in ("right_click", "right"):
            res = engine.click_element(description, click_type="right", window_query=window)
            return res.summary()

        elif action in ("type_in", "type", "input"):
            if not text:
                return f"Located element '{description}', but no text was provided to type."
            res = engine.type_in_element(
                description=description,
                text=text,
                clear_first=clear_first,
                submit=submit,
                window_query=window,
            )
            return res.summary()

        elif action in ("find", "locate", "inspect"):
            res = engine.find_element(description, window_query=window)
            return res.summary()

        elif action in ("hover", "move_to"):
            res = engine.hover_element(description, window_query=window)
            return res.summary()

        else:
            return f"Unknown action '{action}' for gui_navigator. Valid actions: click, double_click, right_click, type_in, find, hover."

    except Exception as e:
        print(f"[gui_navigator] Error: {e}")
        return f"GUI navigation failed: {e}"


# ── Auto-Discovered Tool Declaration ──────────────────────────────────────────
TOOL = {
    "name": "gui_navigator",
    "description": (
        "Visually inspects the screen and clicks or types into UI elements (buttons, icons, "
        "tabs, input boxes, search bars, menus). Use this whenever asked to click on a button or icon on screen, "
        "or fill in a field that requires visual location."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "click | double_click | right_click | type_in | find | hover",
            },
            "description": {
                "type": "STRING",
                "description": "Natural language description of the UI element (e.g. 'Run button', 'Search bar', 'Extensions icon', 'Close tab').",
            },
            "text": {
                "type": "STRING",
                "description": "Text to type if action is 'type_in'.",
            },
            "submit": {
                "type": "BOOLEAN",
                "description": "Whether to press Enter after typing (for 'type_in'). Default is false.",
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Whether to clear existing text before typing (for 'type_in'). Default is true.",
            },
            "window": {
                "type": "STRING",
                "description": "Optional window or application name to focus visual search on (e.g. 'VS Code', 'Chrome').",
            },
        },
        "required": ["description"],
    },
    "handler": gui_navigator,
}
