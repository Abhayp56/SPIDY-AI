"""
tools/connectors/turn.py — Connector Surface Context
"""

from contextlib import contextmanager
from typing import Any, Generator, Optional, Set


@contextmanager
def agent_connection_surface(*args, **kwargs) -> Generator[None, None, None]:
    yield


@contextmanager
def scoped_connection_surface(*args, **kwargs) -> Generator[None, None, None]:
    yield


def side_agent_tool_drops(*args, **kwargs) -> Set[str]:
    return set()
