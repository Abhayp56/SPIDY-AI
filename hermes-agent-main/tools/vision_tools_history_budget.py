"""
tools/vision_tools_history_budget.py — Context manager for tracking native turn images.
"""
from __future__ import annotations
import contextlib

@contextlib.contextmanager
def native_turn_images(user_message=None):
    yield
