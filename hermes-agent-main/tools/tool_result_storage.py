"""
tools/tool_result_storage.py — Tool result storage and budgeting helpers.
"""
from typing import Any, Optional


def maybe_persist_tool_result(result: Any = None, *args: Any, content: Any = None, **kwargs: Any) -> Any:
    if content is not None:
        return content
    return result if result is not None else ""


def enforce_turn_budget(*args: Any, **kwargs: Any) -> None:
    pass


def extract_persisted_path(result: Any, *args: Any, **kwargs: Any) -> Optional[str]:
    return None
