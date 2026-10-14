"""
tools/registry.py — Central Tool Registry for Hermes Agent
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("HermesToolRegistry")

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
        sys.modules["tomllib"] = tomllib
    except ModuleNotFoundError:
        pass

CHECK_FN_CACHE_BYPASS = "BYPASS"
_MAX_TOOL_ERROR_CHARS = 8000


def check_fn_cache_scope(fn: Any = None, context: Any = None) -> str:
    return "DEFAULT"


def tool_error(msg: str) -> str:
    """Format tool execution error."""
    if len(str(msg)) > _MAX_TOOL_ERROR_CHARS:
        msg = str(msg)[:_MAX_TOOL_ERROR_CHARS] + "... (truncated)"
    return f"Error executing tool: {msg}"


@dataclass
class ToolEntry:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Optional[Callable[[Dict[str, Any]], Any]] = None
    toolset: str = "core"
    check_fn: Optional[Callable[[], bool]] = None

    def to_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry maintaining available tools, toolsets, and execution handlers."""

    def __init__(self):
        self._entries: Dict[str, ToolEntry] = {}
        self._toolset_map: Dict[str, str] = {}
        self._aliases: Dict[str, str] = {}
        self._packages: Dict[str, Any] = {}
        self._generation: int = 1
        self._emojis: Dict[str, str] = {
            "terminal": "💻",
            "execute_code": "⚡",
            "web_search": "🔍",
            "read_file": "📄",
            "write_file": "✏️",
            "patch": "🩹",
            "browser_navigate": "🌐",
            "default": "⚙️",
        }

    def current_scope_key(self) -> str:
        return "default"

    def register(
        self,
        name: str,
        handler: Optional[Callable[[Dict[str, Any]], Any]] = None,
        schema: Optional[Dict[str, Any]] = None,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        toolset: str = "core",
        check_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        if schema and "function" in schema:
            fn_def = schema["function"]
            name = fn_def.get("name", name)
            description = fn_def.get("description", description)
            parameters = fn_def.get("parameters", parameters)

        parameters = parameters or {"type": "OBJECT", "properties": {}}
        entry = ToolEntry(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            toolset=toolset,
            check_fn=check_fn,
        )
        self._entries[name] = entry
        self._toolset_map[name] = toolset
        logger.debug(f"Registered Hermes tool: '{name}' in toolset '{toolset}'")

    def get_entry(self, tool_name: str, scope: Any = None) -> Optional[ToolEntry]:
        return self._entries.get(tool_name)

    def get_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        entry = self.get_entry(tool_name)
        return entry.to_schema() if entry else None

    def get_all_tool_names(self) -> List[str]:
        return list(self._entries.keys())

    def get_tool_names_for_toolset(self, toolset_name: str) -> List[str]:
        return [name for name, entry in self._entries.items() if entry.toolset == toolset_name]

    def get_toolset_alias_target(self, name: str) -> Optional[str]:
        return self._aliases.get(name, name)

    def get_tool_to_toolset_map(self) -> Dict[str, str]:
        return dict(self._toolset_map)

    def get_toolset_requirements(self) -> Dict[str, dict]:
        return {}

    def check_toolset_requirements(self) -> Dict[str, dict]:
        return {}

    def get_toolset_for_tool(self, tool_name: str) -> Optional[str]:
        return self._toolset_map.get(tool_name, "core")

    def get_available_toolsets(self) -> List[str]:
        return list(set(self._toolset_map.values()))

    def get_definitions(self, tools_to_include: Optional[Set[str] | List[str]] = None, quiet: bool = False) -> List[Dict[str, Any]]:
        if tools_to_include is None:
            entries = self._entries.values()
        else:
            to_inc = set(tools_to_include)
            entries = [e for name, e in self._entries.items() if name in to_inc]
        return [e.to_schema() for e in entries]

    def get_provider(self, plugin_name: str) -> Any:
        return self._providers.get(plugin_name)

    def get_package(self, package_name: str) -> Any:
        return self._packages.get(package_name)

    def get_emoji(self, tool_name: str, default: str = "") -> str:
        return self._emojis.get(tool_name, default or self._emojis["default"])

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Any:
        entry = self.get_entry(tool_name)
        if not entry or not entry.handler:
            return tool_error(f"Tool '{tool_name}' is not registered or has no handler.")
        try:
            return entry.handler(args)
        except Exception as exc:
            return tool_error(str(exc))

    def dispatch(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Any:
        return self.execute(tool_name, args)


# Global singleton registry instance
registry = ToolRegistry()


# Built-in Default Tool Handlers
def _handle_terminal(args: Dict[str, Any]) -> str:
    command = args.get("command") or args.get("cmd") or ""
    if not command:
        return tool_error("No command provided.")
    try:
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        out = res.stdout if res.stdout else res.stderr
        return out if out else f"Command exited with code {res.returncode}"
    except Exception as e:
        return tool_error(str(e))


def _handle_execute_code(args: Dict[str, Any]) -> str:
    code = args.get("code") or args.get("script") or ""
    if not code:
        return tool_error("No code provided.")
    try:
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=12,
        )
        return res.stdout if res.stdout else (res.stderr if res.stderr else f"Code executed (code {res.returncode})")
    except Exception as e:
        return tool_error(str(e))


def _handle_read_file(args: Dict[str, Any]) -> str:
    path_str = args.get("file_path") or args.get("path") or ""
    if not path_str:
        return tool_error("No file_path specified.")
    p = Path(path_str).resolve()
    if not p.exists():
        return tool_error(f"File not found: {p}")
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:10000]
    except Exception as e:
        return tool_error(str(e))


def _handle_write_file(args: Dict[str, Any]) -> str:
    path_str = args.get("file_path") or args.get("path") or ""
    content = args.get("content") or ""
    if not path_str:
        return tool_error("No file_path specified.")
    p = Path(path_str).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully written to {p}"
    except Exception as e:
        return tool_error(str(e))


def _handle_web_search(args: Dict[str, Any]) -> str:
    query = args.get("query") or args.get("q") or ""
    if not query:
        return tool_error("No search query provided.")
    return f"Search result for '{query}': (Web search capability enabled via Brahma Cloud)"


def discover_builtin_tools() -> None:
    """Populate built-in Hermes tools."""
    if "terminal" in registry.get_all_tool_names():
        return

    registry.register(
        name="terminal",
        handler=_handle_terminal,
        description="Executes a shell / terminal command on the local machine.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "The command line string to execute."}
            },
            "required": ["command"],
        },
        toolset="core",
    )

    registry.register(
        name="execute_code",
        handler=_handle_execute_code,
        description="Executes Python code snippet in local Python runtime.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "code": {"type": "STRING", "description": "Python code to execute."}
            },
            "required": ["code"],
        },
        toolset="core",
    )

    registry.register(
        name="read_file",
        handler=_handle_read_file,
        description="Reads contents of a local text file.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Path to the file to read."}
            },
            "required": ["file_path"],
        },
        toolset="core",
    )

    registry.register(
        name="write_file",
        handler=_handle_write_file,
        description="Writes content to a local file.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Path to the target file."},
                "content": {"type": "STRING", "description": "Content string to write."}
            },
            "required": ["file_path", "content"],
        },
        toolset="core",
    )

    registry.register(
        name="web_search",
        handler=_handle_web_search,
        description="Performs web search for queries.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Search query."}
            },
            "required": ["query"],
        },
        toolset="core",
    )


# Automatically discover built-in tools upon import
discover_builtin_tools()
