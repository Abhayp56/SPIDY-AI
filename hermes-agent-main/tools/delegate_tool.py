"""
tools/delegate_tool.py — Subagent delegation constants and helpers.
"""
from typing import Any, Dict, List, Optional

DEFAULT_MAX_ITERATIONS = 25
DEFAULT_CHILD_TIMEOUT = 120
DEFAULT_MAX_SUMMARY_CHARS = 1000
DEFAULT_TOOLSETS = ["core"]
MAX_DEPTH = 3
SUBAGENT_FAILURE_STATUSES = ("failed", "error", "timeout")


def _get_max_concurrent_children() -> int:
    return 5


def _strip_model_hidden_task_fields(task: Dict[str, Any]) -> Dict[str, Any]:
    return task


def format_subagent_failure_line(subagent_id: str = "", error: str = "") -> str:
    return f"Subagent {subagent_id} failed: {error}"


def delegate_task(*args, **kwargs) -> Any:
    return "Delegation completed."


def _build_child_preserving_parent_tools(*args, **kwargs) -> Any:
    return None


def _run_child_lifecycle(*args, **kwargs) -> Any:
    return None
