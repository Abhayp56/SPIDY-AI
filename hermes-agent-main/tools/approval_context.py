"""
tools/approval_context.py — Approval context tracking.
"""
from typing import Any, Optional


def reset_current_observability_context(*args: Any, **kwargs: Any) -> None:
    pass


def set_current_observability_context(*args: Any, **kwargs: Any) -> None:
    pass


def reset_current_session_key(*args: Any, **kwargs: Any) -> None:
    pass


def set_current_session_key(*args: Any, **kwargs: Any) -> None:
    pass


def get_current_session_key(*args: Any, **kwargs: Any) -> Optional[str]:
    return None


def _get_approval_mode(*args: Any, **kwargs: Any) -> str:
    return "auto"


def _normalize_approval_mode(val: Any) -> str:
    return "auto"


def _get_approval_timeout(*args: Any, **kwargs: Any) -> int:
    return 30


def format_approval_window(*args: Any, **kwargs: Any) -> str:
    return ""
