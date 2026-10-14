"""
tools/thread_context.py — Propagate contextvars to background threads.
"""
from __future__ import annotations
import contextvars
from functools import wraps
from typing import Callable, Any


def propagate_context_to_thread(func: Callable) -> Callable:
    ctx = contextvars.copy_context()
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return ctx.run(func, *args, **kwargs)
    return wrapper
