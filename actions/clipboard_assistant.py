"""
actions/clipboard_assistant.py
Semantic Clipboard Assistant action tool for JARVIS.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Exposes semantic clipboard operations (fix, paste, fix_and_paste, format, explain, read, history, copy)
  to the JARVIS tool execution framework.
- Conforms strictly to core/action_loader.py convention:
  Handler accepts (parameters: dict, player=None, speak=None, **kwargs).
- Discovered automatically by core/action_loader.py.
- Integrates with core/clipboard_engine.py for smart categorization, JSON formatting,
  and AI error repair.
"""

import time
from typing import Optional, Any, Dict
from core.clipboard_engine import get_clipboard_engine


def clipboard_assistant(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for clipboard_assistant tool.
    Accepts parameters dict from core/action_loader.py.
    """
    params = parameters or {}
    raw_act = params.get("action") or "read"
    act = str(raw_act).strip().lower()
    text = params.get("text")
    auto_paste = bool(params.get("auto_paste", False))

    print(f"[ClipboardAction] Executing action='{act}', auto_paste={auto_paste}")

    engine = get_clipboard_engine()

    # If explicit text was supplied by the model/caller, seed it into clipboard
    if text and str(text).strip() and act in ("copy", "set", "write", "fix", "repair", "format"):
        engine.set_content(str(text).strip())

    if act in ("read", "inspect", "check", "current"):
        item = engine.get_current()
        if not item:
            msg = "The clipboard is currently empty."
            if speak and callable(speak):
                speak(msg)
            return msg
        res = (
            f"Clipboard content [{item.category.upper()}] ({item.lines_count} lines, {item.char_count} chars):\n"
            f"{item.content[:400]}"
            + ("..." if len(item.content) > 400 else "")
        )
        if speak and callable(speak):
            speak(f"Clipboard contains {item.category}: {item.preview[:40]}")
        return res

    elif act in ("explain", "describe", "summary"):
        explanation = engine.explain_content()
        if speak and callable(speak):
            speak(explanation[:120])
        return explanation

    elif act in ("format", "prettify", "format_json"):
        success, msg = engine.format_json()
        if success and auto_paste:
            time.sleep(0.2)
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "v")
            except Exception:
                pass
        if speak and callable(speak):
            speak(msg)
        return msg

    elif act in ("fix", "repair", "debug", "fix_code", "fix_and_paste"):
        success, msg = engine.fix_code_or_error()
        should_paste = auto_paste or (act == "fix_and_paste")
        if success and should_paste:
            time.sleep(0.3)
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "v")
                msg += " (Auto-pasted into active window)"
            except Exception:
                pass
        if speak and callable(speak):
            speak("Fixed code copied to clipboard. Press Control V to paste." if success else msg)
        return msg

    elif act in ("paste", "paste_clipboard"):
        time.sleep(0.2)
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "v")
            msg = "Pasted clipboard content into active window."
            if speak and callable(speak):
                speak(msg)
            return msg
        except Exception as e:
            return f"Failed to paste: {e}"

    elif act in ("history", "recent", "list"):
        history = engine.get_history(limit=5)
        if not history:
            return "No recent clipboard history recorded."
        lines = ["Recent Clipboard History:"]
        for idx, it in enumerate(history, 1):
            lines.append(f"{idx}. [{it['timestamp']}] ({it['category']}): {it['preview']}")
        res = "\n".join(lines)
        if speak and callable(speak):
            speak(f"You have {len(history)} recent items in clipboard history.")
        return res

    elif act in ("copy", "set", "write"):
        if not text:
            return "No text provided to copy."
        ok = engine.set_content(str(text))
        msg = f"Copied {len(str(text))} characters to clipboard." if ok else "Failed to set clipboard."
        if speak and callable(speak):
            speak(msg)
        return msg

    else:
        # Fallback: if user asked to fix something, try fix_code_or_error
        if "fix" in act or "debug" in act:
            success, msg = engine.fix_code_or_error()
            return msg
        item = engine.get_current()
        return f"Clipboard ({item.category if item else 'empty'}): {item.preview if item else 'none'}"


TOOL = {
    "name": "clipboard_assistant",
    "description": (
        "Smart semantic clipboard controller: reads, explains, formats JSON, "
        "fixes copied errors/code, and pastes clipboard content into the active window. "
        "Use action='fix' when user asks to fix code/errors in clipboard. "
        "Use action='paste' when user asks to paste the clipboard or paste the fix. "
        "Use action='fix_and_paste' when user asks to fix and paste."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "fix | paste | fix_and_paste | format | explain | read | history | copy (default: fix)"
            },
            "text": {
                "type": "STRING",
                "description": "Optional text or code to write to clipboard or fix directly"
            },
            "auto_paste": {
                "type": "BOOLEAN",
                "description": "If true, automatically simulates Ctrl+V into active window after fixing or formatting"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": clipboard_assistant,
}
