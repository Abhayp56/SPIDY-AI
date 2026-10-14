"""
tools/mcp_tool_agent.py — Helper for tool name pinning and preservation across sessions.
"""
from __future__ import annotations
from typing import List, Any

def agent_tool_names(agent: Any) -> List[str]:
    tools = getattr(agent, "tools", []) or []
    names = []
    for t in tools:
        if isinstance(t, dict):
            fn = t.get("function", {})
            name = fn.get("name") or t.get("name")
            if name:
                names.append(name)
        elif hasattr(t, "name"):
            names.append(t.name)
    return names

def persist_agent_tool_names(agent: Any) -> None:
    pass

def restore_agent_tool_prefix(agent: Any, pin: Any) -> None:
    pass
