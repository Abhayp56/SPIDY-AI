"""
tools/kanban_toolset_context.py — Kanban Toolset Context Manager
"""

from contextlib import contextmanager
from typing import Generator


@contextmanager
def scoped_kanban_toolset_selection(*args, **kwargs) -> Generator[None, None, None]:
    yield
