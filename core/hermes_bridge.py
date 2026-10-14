"""
core/hermes_bridge.py — Autonomous Execution Bridge for Hermes Agent.

Integrates the autonomous Hermes Agent (hermes-agent-main) as JARVIS's universal
problem-solving and execution engine. Hermes acts as the autonomous "hands and body"
handling multi-step terminal actions, code execution, file system management,
and complex desktop workflows, while JARVIS handles the live voice and 3D Orb interface.

Architecture:
  - Loosely coupled bridge adhering to SOLID principles.
  - Automatic model fallback ladder for Gemini free/paid tier quota resilience.
  - Safe non-blocking execution via worker threads / asyncio.
  - Unified tool registry extension bridging JARVIS desktop actions to Hermes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("HermesBridge")

# Base directory paths
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_HERMES_DIR = _WORKSPACE_ROOT / "hermes-agent-main"
_CONFIG_DIR = _WORKSPACE_ROOT / "config"
_API_KEYS_FILE = _CONFIG_DIR / "api_keys.json"

# Ensure hermes-agent-main is in sys.path
if _HERMES_DIR.exists() and str(_HERMES_DIR) not in sys.path:
    sys.path.insert(0, str(_HERMES_DIR))

# Default model ladder for Gemini (ordered by active quota & speed)
_DEFAULT_MODEL_LADDER = [
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


class HermesBridge:
    """Coordinates execution of autonomous tasks using Hermes Agent."""

    _instance: Optional[HermesBridge] = None
    _lock = threading.Lock()

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_ladder: Optional[List[str]] = None,
        workspace_dir: Optional[Path] = None,
    ):
        self._api_key = api_key or self._resolve_api_key()
        self._model_ladder = list(model_ladder or _DEFAULT_MODEL_LADDER)
        self._workspace_dir = workspace_dir or _WORKSPACE_ROOT
        self._initialized = False
        self._init_hermes()

    @classmethod
    def get_instance(cls) -> HermesBridge:
        """Singleton accessor with thread safety."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @staticmethod
    def _resolve_api_key() -> str:
        """Resolve Gemini API key from config or environment variables."""
        if _API_KEYS_FILE.exists():
            try:
                data = json.loads(_API_KEYS_FILE.read_text(encoding="utf-8"))
                key = data.get("gemini_api_key") or data.get("google_api_key")
                if key:
                    return str(key).strip()
            except Exception as e:
                logger.warning("Failed to parse api_keys.json: %s", e)

        for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
            val = os.environ.get(env_var)
            if val:
                return val.strip()

        return ""

    def _init_hermes(self) -> None:
        """Initialize and verify Hermes imports and register desktop tool helpers."""
        if self._initialized:
            return

        try:
            import importlib
            registry_module = importlib.import_module("tools.registry")
            registry = getattr(registry_module, "registry")
            
            # Register JARVIS desktop extensions if not already present
            self._register_desktop_extensions(registry)
            self._initialized = True
            logger.info("Hermes Agent Bridge initialized successfully.")
        except Exception as e:
            logger.error("Error during Hermes initialization: %s", e, exc_info=True)

    def _register_desktop_extensions(self, registry: Any) -> None:
        """Expose select native desktop helpers to Hermes tool registry."""
        tool_names = registry.get_all_tool_names()

        # 1. Desktop open_app tool
        if "open_app" not in tool_names:
            def _handle_open_app(args: Dict[str, Any]) -> str:
                app_name = args.get("app_name") or args.get("app") or ""
                if not app_name:
                    return "Error: app_name is required."
                try:
                    from actions.open_app import open_app
                    return open_app({"app_name": app_name})
                except Exception as ex:
                    return f"Error opening app: {ex}"

            registry.register(
                name="open_app",
                handler=_handle_open_app,
                description="Launches or brings to focus a desktop application by name (e.g. 'chrome', 'spotify', 'notepad').",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "app_name": {"type": "STRING", "description": "The name or alias of the application to open."}
                    },
                    "required": ["app_name"],
                },
                toolset="desktop",
            )

        # 2. Explorer reveal / copilot tool
        if "open_in_explorer" not in tool_names:
            def _handle_open_in_explorer(args: Dict[str, Any]) -> str:
                target_path = args.get("path") or args.get("target") or str(self._workspace_dir)
                try:
                    from actions.explorer_copilot import explorer_copilot
                    return explorer_copilot({"action": "open", "target": target_path})
                except Exception as ex:
                    return f"Error opening explorer: {ex}"

            registry.register(
                name="open_in_explorer",
                handler=_handle_open_in_explorer,
                description="Opens Windows File Explorer at a specific directory path or highlights a file.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING", "description": "Path to the directory or file to open in Explorer."}
                    },
                    "required": ["path"],
                },
                toolset="desktop",
            )

        # 3. Hands: Desktop Computer Control (PyAutoGUI clicking, typing, hotkeys)
        if "computer_control" not in tool_names:
            def _handle_computer_control(args: Dict[str, Any]) -> str:
                try:
                    from actions.computer_control import computer_control
                    return computer_control(args)
                except Exception as ex:
                    return f"Error in computer_control: {ex}"

            registry.register(
                name="computer_control",
                handler=_handle_computer_control,
                description="Desktop automation hands: clicks coordinates, types text, presses hotkeys (e.g. 'ctrl+c', 'enter'), scrolls, and manages desktop focus.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "click | double_click | right_click | type | hotkey | press | scroll | move | screenshot"},
                        "text": {"type": "STRING", "description": "Text to type"},
                        "keys": {"type": "STRING", "description": "Key combination (e.g. 'ctrl+s', 'alt+tab')"},
                        "key": {"type": "STRING", "description": "Single key (e.g. 'enter', 'esc')"},
                        "x": {"type": "INTEGER", "description": "X screen coordinate"},
                        "y": {"type": "INTEGER", "description": "Y screen coordinate"},
                        "direction": {"type": "STRING", "description": "up | down for scroll"},
                        "amount": {"type": "INTEGER", "description": "Scroll amount"},
                    },
                    "required": ["action"],
                },
                toolset="desktop",
            )

        # 4. Hands: GUI Navigator (Vision-guided element finder and clicker)
        if "gui_navigator" not in tool_names:
            def _handle_gui_navigator(args: Dict[str, Any]) -> str:
                try:
                    from actions.gui_navigator import gui_navigator
                    return gui_navigator(args)
                except Exception as ex:
                    return f"Error in gui_navigator: {ex}"

            registry.register(
                name="gui_navigator",
                handler=_handle_gui_navigator,
                description="Visually locates and clicks or types into UI elements on screen (buttons, icons, search bars, menus) by visual description.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "click | double_click | right_click | type_in | find | hover"},
                        "description": {"type": "STRING", "description": "Visual description of UI element (e.g. 'Save button', 'Search bar', 'Extensions icon')"},
                        "text": {"type": "STRING", "description": "Text to type if action is 'type_in'"},
                        "submit": {"type": "BOOLEAN", "description": "Press enter after typing"},
                    },
                    "required": ["description"],
                },
                toolset="desktop",
            )

        # 5. Live Web Surfing: Headed Browser Control (Playwright)
        if "browser_control" not in tool_names:
            def _handle_browser_control(args: Dict[str, Any]) -> str:
                try:
                    from actions.browser_control import browser_control
                    return browser_control(args)
                except Exception as ex:
                    return f"Error in browser_control: {ex}"

            registry.register(
                name="browser_control",
                handler=_handle_browser_control,
                description="Controls a real web browser: navigate to URLs, click elements, fill web forms, scroll pages, and extract page text.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "go_to | search | click | type | scroll | smart_click | smart_type | get_text | get_url | close"},
                        "url": {"type": "STRING", "description": "URL to visit"},
                        "query": {"type": "STRING", "description": "Search query if action is search"},
                        "selector": {"type": "STRING", "description": "CSS selector or text for element"},
                        "text": {"type": "STRING", "description": "Text to click or type"},
                        "description": {"type": "STRING", "description": "Natural language element description for smart_click/smart_type"},
                        "direction": {"type": "STRING", "description": "up | down for scroll"},
                        "amount": {"type": "INTEGER", "description": "Scroll distance in pixels"},
                    },
                    "required": ["action"],
                },
                toolset="desktop",
            )

        # 6. Eyes: Screen Capture & Inspection
        if "screen_inspect" not in tool_names:
            def _handle_screen_inspect(args: Dict[str, Any]) -> str:
                try:
                    from actions.screen_processor import _capture_screen
                    img_bytes, mime_type = _capture_screen()
                    query = args.get("query") or "Describe the current screen and identify active windows, errors, or elements."
                    
                    import base64
                    b64_img = base64.b64encode(img_bytes).decode("ascii")
                    
                    # Direct inline Gemini vision call
                    from google import genai
                    from google.genai import types
                    client = genai.Client(api_key=self._api_key)
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[
                            types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                            f"Analyze this screenshot and answer: {query}"
                        ],
                    )
                    return resp.text or "Screen captured, but no text description returned."
                except Exception as ex:
                    return f"Screen inspection error: {ex}"

            registry.register(
                name="screen_inspect",
                handler=_handle_screen_inspect,
                description="Captures the current screen and visually analyzes it using vision AI. Use this to read error dialogs, inspect open windows, check charts, or observe application states.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "Specific question or inspection goal (e.g. 'Read the error dialog', 'What is on VS Code')"}
                    },
                    "required": [],
                },
                toolset="desktop",
            )

        # 7. Proactivity: Ambient System & Health Monitor
        if "ambient_monitor" not in tool_names:
            def _handle_ambient_monitor(args: Dict[str, Any]) -> str:
                try:
                    from actions.ambient_monitor import ambient_monitor_action
                    return ambient_monitor_action(args)
                except Exception as ex:
                    return f"Error in ambient_monitor: {ex}"

            registry.register(
                name="ambient_monitor",
                handler=_handle_ambient_monitor,
                description="Audits system health, disk space, battery levels, RAM/CPU load, and detects active system error dialogs.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "audit | check_disk | check_battery | status"}
                    },
                    "required": [],
                },
                toolset="desktop",
            )

    def run_task(
        self,
        task_prompt: str,
        max_iterations: int = 8,
        on_status: Optional[Callable[[str], None]] = None,
        on_tool_progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a multi-step task synchronously using Hermes Agent.
        Tries models along the fallback ladder if quota or transient errors occur.
        """
        if not self._api_key:
            return {
                "status": "error",
                "final_response": "Hermes execution failed: No Gemini API key configured in api_keys.json or environment.",
                "model_used": None,
                "tool_calls_count": 0,
            }

        import importlib
        run_agent_module = importlib.import_module("run_agent")
        AIAgent = getattr(run_agent_module, "AIAgent")

        desktop_dir = str(Path.home() / "Desktop")
        temp_dir = os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))
        username = os.environ.get("USERNAME", "User")
        enriched_prompt = (
            f"[SYSTEM ENVIRONMENT: OS=Windows (win32), Current User='{username}', "
            f"Desktop='{desktop_dir}', Temp Directory='{temp_dir}']\n"
            f"EXECUTION GUIDELINES:\n"
            f"- SPEED & DECISIVENESS: Call the required tool immediately in Turn 1 without conversational chatter or delay.\n"
            f"- EXPLORER: Do NOT open File Explorer unless the user explicitly requested 'open folder' or 'show in explorer'. When creating/listing files or folders, perform the operation quietly.\n"
            f"- RECYCLE BIN: Never run recursive commands like 'Get-ChildItem -Recurse C:\\$Recycle.Bin' as it hangs permissions. For Recycle Bin queries, use PowerShell COM: `powershell -Command \"(New-Object -ComObject Shell.Application).Namespace(0x0a).Items() | Select-Object Name, Size, Path\"`.\n"
            f"- For terminal commands, use Windows CMD or PowerShell (e.g. 'dir', '$env:TEMP'). Never use Unix 'ls' or '$TMPDIR'.\n"
            f"- Available desktop tools: 'open_app', 'open_in_explorer', 'computer_control', 'gui_navigator', 'browser_control', 'screen_inspect', 'ambient_monitor'.\n\n"
            f"Task: {task_prompt}"
        )

        last_error = ""
        for model in self._model_ladder:
            logger.info("Attempting Hermes task with model: %s", model)
            if on_status:
                on_status(f"Running task with {model}...")

            try:
                agent = AIAgent(
                    model=model,
                    api_key=self._api_key,
                    provider="google",
                    base_url=_GEMINI_BASE_URL,
                    max_iterations=max_iterations,
                    status_callback=on_status or (lambda s: None),
                    tool_progress_callback=on_tool_progress or (lambda p: None),
                )

                result = agent.run_conversation(enriched_prompt)
                final_resp = result.get("final_response") or ""

                # Check if turn failed due to provider rate limit or quota exhaustion
                if (
                    "rate-limited" in final_resp.lower()
                    or "quota" in final_resp.lower()
                    or "429" in final_resp
                    or "resource_exhausted" in final_resp.lower()
                    or (result.get("failed") and not final_resp)
                ):
                    logger.warning("Model %s hit rate limit or failed. Falling back...", model)
                    last_error = final_resp
                    continue

                # Count tool calls executed
                messages = result.get("messages", [])
                tool_calls_count = sum(1 for m in messages if m.get("role") == "tool")

                logger.info("Hermes task completed successfully with model %s", model)
                return {
                    "status": "success",
                    "final_response": final_resp,
                    "model_used": model,
                    "tool_calls_count": tool_calls_count,
                    "messages_count": len(messages),
                }

            except Exception as e:
                err_str = str(e)
                logger.warning("Hermes model %s failed: %s", model, err_str)
                last_error = err_str

                # If quota exceeded or 429, continue to next fallback model
                if "429" in err_str or "quota" in err_str.lower() or "exhausted" in err_str.lower():
                    continue
                # For non-recoverable errors, record and continue
                continue

        return {
            "status": "error",
            "final_response": f"Hermes task failed across all models. Last error: {last_error}",
            "model_used": None,
            "tool_calls_count": 0,
        }

    async def run_task_async(
        self,
        task_prompt: str,
        max_iterations: int = 8,
        on_status: Optional[Callable[[str], None]] = None,
        on_tool_progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously execute a task on a worker thread, ensuring the asyncio
        event loop remains responsive for voice/UI.
        """
        return await asyncio.to_thread(
            self.run_task,
            task_prompt,
            max_iterations=max_iterations,
            on_status=on_status,
            on_tool_progress=on_tool_progress,
        )


def get_hermes_bridge() -> HermesBridge:
    """Dependency injection helper returning the global HermesBridge."""
    return HermesBridge.get_instance()
