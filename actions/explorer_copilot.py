"""
actions/explorer_copilot.py
Windows File Explorer Copilot and Autonomous File Butler action tool for JARVIS.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Exposes File Explorer control, active selection query, semantic content search,
  folder auto-organization, batch renaming, and instant file summaries to the JARVIS action pipeline.
- Conforms strictly to core/action_loader.py convention:
  Handler accepts (parameters: Optional[Dict[str, Any]], player=None, speak=None, **kwargs).
- Discovered automatically by core/action_loader.py.
- Integrates with core/explorer_copilot.py for Windows COM automation and AI operations.
"""

from typing import Optional, Any, Dict
from pathlib import Path
from core.explorer_copilot import get_explorer_copilot


def explorer_copilot(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for explorer_copilot tool.
    Accepts parameters dict from core/action_loader.py.
    """
    params = parameters or {}
    raw_act = params.get("action") or "open"
    act = str(raw_act).strip().lower()

    # Extract target from any possible parameter name Gemini might supply
    target = (
        params.get("file_path")
        or params.get("path")
        or params.get("folder")
        or params.get("target")
        or params.get("name")
    )

    target_p: Optional[Path] = None
    if target:
        try:
            target_p = Path(str(target)).expanduser()
        except Exception:
            target_p = None

    folder = params.get("folder") or params.get("path")
    if not folder and target_p and target_p.exists() and target_p.is_dir():
        folder = str(target_p)

    query = params.get("query")
    instruction = params.get("instruction") or params.get("prompt")
    file_path = params.get("file_path")
    if not file_path and target_p and target_p.exists() and target_p.is_file():
        file_path = str(target_p)

    app = (
        params.get("app")
        or params.get("application")
        or params.get("preferred_app")
        or params.get("with_app")
    )

    print(f"[ExplorerAction] Executing action='{act}', target='{target}', folder='{folder}', app='{app}'")

    copilot = get_explorer_copilot()

    if act in ("open", "open_folder", "open_file", "launch", "show"):
        target_item = target or folder or file_path
        msg = copilot.open_item(target_item, app=app)
        if speak and callable(speak):
            name_label = Path(str(target_item)).name if target_item else "item"
            if app:
                speak(f"Opening {name_label} in {app}.")
            else:
                speak(f"Opening {name_label} on screen.")
        return msg

    elif act in ("reveal", "select", "show_in_folder", "highlight"):
        target_item = target or folder or file_path
        msg = copilot.reveal_in_explorer(target_item)
        if speak and callable(speak):
            name_label = Path(str(target_item)).name if target_item else "file"
            speak(f"Showing {name_label} in File Explorer.")
        return msg

    elif act in ("selected", "get_selected", "selection", "current"):
        selected = copilot.get_selected_files()
        if not selected:
            msg = "No files are currently selected in File Explorer."
            if speak and callable(speak):
                speak(msg)
            return msg
        res = f"Currently selected ({len(selected)} item(s)):\n" + "\n".join(f"- {p}" for p in selected)
        if speak and callable(speak):
            speak(f"You have selected {len(selected)} item(s).")
        return res

    elif act in ("search", "find", "semantic_search"):
        search_query = (
            query
            or instruction
            or params.get("name")
            or params.get("search_query")
            or params.get("pattern")
            or ""
        )
        search_root = folder or params.get("folder")

        if not search_query and target:
            if target_p and target_p.exists() and target_p.is_dir():
                search_root = str(target_p)
            else:
                search_query = str(target)

        if not search_query:
            return "Please specify what file or content to search for."

        matches = copilot.semantic_search(search_query, search_root=search_root)
        if not matches:
            msg = f"No matching files found for: \"{search_query}\"."
            if speak and callable(speak):
                speak(msg)
            return msg
        lines = [f"Found {len(matches)} matching file(s):"]
        for m in matches:
            lines.append(f"- {m['path']}\n  Reason: {m.get('reason', 'Matched content')}")
        res = "\n".join(lines)
        if speak and callable(speak):
            speak(f"Found {len(matches)} matching files.")
        return res

    elif act in ("organize", "clean", "clean_up", "sort"):
        target_dir = folder or (str(target_p.parent) if target_p and target_p.is_file() else target) or "downloads"
        res = copilot.auto_organize_folder(str(target_dir))
        msg = res.get("message", "Organization complete.")
        if speak and callable(speak):
            speak(msg)
        return msg

    elif act in ("rename", "smart_rename", "batch_rename"):
        if not instruction:
            return "Please provide renaming instructions (e.g. 'Format by date', 'Convert to snake_case')."
        target_dir = folder or (str(target_p.parent) if target_p and target_p.is_file() else target) or "downloads"
        res = copilot.smart_rename_files(str(target_dir), instruction)
        msg = res.get("message", "Renaming complete.")
        if speak and callable(speak):
            speak(msg)
        return msg

    elif act in ("summarize", "summary", "explain_file"):
        target_file = file_path or target or folder
        summary = copilot.summarize_file(target_file)
        if speak and callable(speak):
            speak(summary[:120])
        return summary

    elif act in ("list_windows", "windows"):
        wins = copilot.get_open_explorer_windows()
        if not wins:
            return "No File Explorer windows are currently open."
        if speak and callable(speak):
            speak(f"Found {len(wins)} open Explorer window(s).")
        return "Open File Explorer directories:\n" + "\n".join(f"- {w}" for w in wins)

    else:
        # Default fallback: open the target item
        target_item = target or folder or file_path
        msg = copilot.open_item(target_item, app=app)
        if speak and callable(speak):
            name_label = Path(str(target_item)).name if target_item else "item"
            if app:
                speak(f"Opening {name_label} in {app}.")
            else:
                speak(f"Opening {name_label} on screen.")
        return msg


TOOL = {
    "name": "explorer_copilot",
    "description": (
        "Controls Windows File Explorer and launches/reveals files or folders on screen. "
        "Actions: 'open' (opens a file or folder on screen; if 'app' is specified, e.g. 'anti gravity', 'vscode', 'notepad', 'word', "
        "opens the file/folder in that preferred application; if 'app' is omitted, folders open in File Explorer and files in their default application), "
        "'reveal' (opens File Explorer with file highlighted), 'get_selected' (gets selected files in File Explorer), "
        "'search' (semantic content search), 'organize' (categorizes messy folders with undo), 'rename' (AI batch renamer), 'summarize' (explains file content)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "open | reveal | get_selected | search | organize | rename | summarize | list_windows (default: open)"
            },
            "file_path": {
                "type": "STRING",
                "description": "Path to specific file to open, launch, reveal, or summarize on screen"
            },
            "folder": {
                "type": "STRING",
                "description": "Folder path or shortcut: 'downloads', 'desktop', 'documents', 'pictures', 'workspace'"
            },
            "app": {
                "type": "STRING",
                "description": "Optional preferred application to open the file or folder in (e.g. 'anti gravity', 'antigravity ide', 'vscode', 'notepad', 'pycharm', 'sublime', 'word', 'chrome'). If omitted, folders open in File Explorer and files open in their default application."
            },
            "query": {
                "type": "STRING",
                "description": "Natural language query for semantic file search"
            },
            "instruction": {
                "type": "STRING",
                "description": "Instructions for batch renaming or file transformation"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": explorer_copilot,
}
