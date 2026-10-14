"""
actions/developer_autopilot.py
Developer Autopilot action tool for JARVIS.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Exposes the developer diagnostics tool to the JARVIS action execution pipeline.
- Conforms strictly to core/action_loader.py convention:
  Handler accepts (parameters: dict, player=None, speak=None, **kwargs).
- Discovered automatically by core/action_loader.py.
- Integrates with core/developer_autopilot.py for traceback diagnosis,
  git status tracking, and syntax validation.
"""

from typing import Optional, Any, Dict
from core.developer_autopilot import get_developer_autopilot


def developer_autopilot(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Diagnoses developer errors, checks git repository status, and validates python syntax.
    Accepts parameters dict from core/action_loader.py.
    """
    params = parameters or {}
    raw_act = params.get("action") or "diagnose_error"
    act = str(raw_act).strip().lower()
    error_text = params.get("error_text")
    file_path = params.get("file_path")

    print(f"[AutopilotAction] Executing action='{act}'")

    autopilot = get_developer_autopilot()

    if act in ("diagnose_error", "diagnose", "error", "traceback", "fix"):
        report = autopilot.diagnose_error(error_text)
        summary = report.summary()
        if speak and callable(speak):
            speak(f"Diagnosis: {report.error_type}. {report.root_cause}")
        return summary

    elif act in ("git_status", "git", "status"):
        status = autopilot.get_git_status()
        if speak and callable(speak):
            speak(status)
        return status

    elif act in ("check_syntax", "syntax", "verify"):
        res = autopilot.check_python_syntax(file_path)
        if speak and callable(speak):
            speak(res)
        return res

    else:
        # Fallback to diagnosing whatever text or clipboard is present
        report = autopilot.diagnose_error(error_text)
        return report.summary()


TOOL = {
    "name": "developer_autopilot",
    "description": "Diagnoses terminal/Python errors & tracebacks, provides root-cause fixes, checks git status, and validates code syntax.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "diagnose_error | git_status | check_syntax (default: diagnose_error)"
            },
            "error_text": {
                "type": "STRING",
                "description": "The traceback or error message to diagnose (if omitted, inspects active clipboard)"
            },
            "file_path": {
                "type": "STRING",
                "description": "Path to target file for syntax checking"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": developer_autopilot,
}
