"""
tools.tool_search — Progressive tool discovery stub.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

TOOL_SEARCH_NAME = "tool_search"
TOOL_DESCRIBE_NAME = "tool_describe"
TOOL_CALL_NAME = "tool_call"
CONNECTOR_BATCH_SENTINEL = "__connector_batch__"


def is_bridge_tool(name: str) -> bool:
    """Returns True if the function name is a tool search bridge tool."""
    return False


@dataclass
class ToolSearchConfig:
    enabled: str = "off"
    tier: int = 0
    deferred_count: int = 0
    deferred_tokens: int = 0
    listing_form: str = "none"


@dataclass
class ToolAssembly:
    tool_defs: List[Any]
    activated: bool = False
    tier: int = 0
    deferred_count: int = 0
    deferred_tokens: int = 0
    listing_form: str = "none"


def load_config() -> ToolSearchConfig:
    return ToolSearchConfig(enabled="off")


def assemble_tool_defs(filtered_tools: List[Any], context_length: int = 128000, config: Optional[ToolSearchConfig] = None) -> ToolAssembly:
    return ToolAssembly(tool_defs=filtered_tools, activated=False)
