"""
tools/interrupt.py — Interruption & Yield Signals for Tool Execution
"""
from typing import Optional, Any

_interrupted = False
_yield_requested = False


def set_interrupt(val: bool = True, thread_id: Optional[Any] = None, *args, **kwargs) -> None:
    global _interrupted
    _interrupted = val


def clear_interrupt(*args, **kwargs) -> None:
    global _interrupted, _yield_requested
    _interrupted = False
    _yield_requested = False


def is_interrupted(*args, **kwargs) -> bool:
    return _interrupted


def is_thread_interrupted(thread_id: Optional[Any] = None, *args, **kwargs) -> bool:
    return _interrupted


def request_yield(val: bool = True, *args, **kwargs) -> None:
    global _yield_requested
    _yield_requested = val


def check_yield(*args, **kwargs) -> bool:
    return _yield_requested


def request_interrupt(val: bool = True, *args, **kwargs) -> None:
    set_interrupt(val)
