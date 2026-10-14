"""
skill_provenance.py — Write origin and review tracking context for Hermes skills and memory.
"""
from __future__ import annotations
import contextvars
from typing import Optional

_current_write_origin: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_write_origin", default="assistant_tool"
)
_review_attended: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_review_attended", default=False
)

def set_current_write_origin(origin: str) -> None:
    _current_write_origin.set(origin or "assistant_tool")

def get_current_write_origin() -> str:
    return _current_write_origin.get()

def set_review_attended(attended: bool) -> None:
    _review_attended.set(bool(attended))

def get_review_attended() -> bool:
    return _review_attended.get()
