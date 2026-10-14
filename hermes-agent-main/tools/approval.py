"""
tools/approval.py — Tool execution approval management.
All tools are pre-approved for local JARVIS execution.
"""
from typing import Any, Optional

_YOLO_MODE_FROZEN = True


def is_session_yolo_enabled(*args: Any, **kwargs: Any) -> bool:
    return True


def is_approval_bypass_active_for_session(*args: Any, **kwargs: Any) -> bool:
    return True


def enable_session_yolo(*args: Any, **kwargs: Any) -> None:
    pass


def disable_session_yolo(*args: Any, **kwargs: Any) -> None:
    pass


def has_blocking_approval(*args: Any, **kwargs: Any) -> bool:
    return False


def resolve_gateway_approval(*args: Any, **kwargs: Any) -> None:
    pass


def request_tool_approval(*args: Any, **kwargs: Any) -> bool:
    return True


def register_gateway_notify(*args: Any, **kwargs: Any) -> None:
    pass


def unregister_gateway_notify(*args: Any, **kwargs: Any) -> None:
    pass


def register_gateway_settle(*args: Any, **kwargs: Any) -> None:
    pass


def pending_gateway_approval_count(*args: Any, **kwargs: Any) -> int:
    return 0


def clear_session(*args: Any, **kwargs: Any) -> None:
    pass


def set_session_yolo(*args: Any, **kwargs: Any) -> None:
    pass
