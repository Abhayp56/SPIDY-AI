"""
actions/hermes_worker.py — Universal Autonomous Task Execution via Hermes Agent.

Exposes the Hermes autonomous execution agent to JARVIS as an integrated action tool.
Allows JARVIS (Gemini Live) to delegate multi-step terminal operations, complex coding,
system diagnostics, file reorganizations, and desktop automation routines to Hermes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from core.autonomous_worker import get_worker
from core.hermes_bridge import get_hermes_bridge

logger = logging.getLogger("HermesWorkerAction")


_last_task_text = ""
_last_task_time = 0.0


def hermes_task_action(
    parameters: Dict[str, Any],
    player: Any = None,
    speak: Any = None,
    response: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Execute an autonomous multi-step task via Hermes Agent.
    Supports both direct synchronous execution and background autonomous queuing.
    """
    global _last_task_text, _last_task_time
    import time

    task = str(parameters.get("task", "") or parameters.get("prompt", "")).strip()
    if not task:
        return "Sir, no task description was provided for Hermes execution."

    now = time.monotonic()
    # Suppress duplicate acoustic echo if exact same task is invoked within 5 seconds
    if task == _last_task_text and (now - _last_task_time) < 5.0:
        logger.info("Ignoring duplicate acoustic echo of task: %s", task)
        return "Task was already dispatched."
    _last_task_text = task
    _last_task_time = now

    background = bool(parameters.get("background", False))
    bridge = get_hermes_bridge()

    def _log(msg: str):
        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"HERMES: {msg}")
            except Exception:
                pass

    # 1. Background Execution Mode
    if background:
        task_id = f"hermes_{uuid.uuid4().hex[:8]}"
        worker = get_worker()

        def _bg_execute() -> str:
            _log(f"Starting background task: '{task}'")
            res = bridge.run_task(
                task_prompt=task,
                on_status=_log,
                on_tool_progress=_log,
            )
            final_resp = res.get("final_response") or "Task completed."
            _log(f"Completed background task: {final_resp[:120]}")
            return final_resp

        worker.submit_task(task_id, f"{task[:40]}", _bg_execute)
        return f"Sir, I have started working on that task in the background. I will notify you as soon as it completes."

    # 2. Synchronous Direct Execution Mode
    _log(f"Executing: '{task[:80]}'")
    try:
        result = bridge.run_task(
            task_prompt=task,
            on_status=_log,
            on_tool_progress=_log,
        )

        if result.get("status") == "success":
            resp = result.get("final_response") or "Task completed successfully."
            model_info = result.get("model_used")
            tools_used = result.get("tool_calls_count", 0)
            _log(f"Success via {model_info} ({tools_used} tool calls)")
            return resp
        else:
            err = result.get("final_response") or "Unknown error occurred."
            _log(f"Execution failed: {err}")
            return f"Execution encountered an issue: {err}"

    except Exception as exc:
        logger.error("Hermes execution failed with exception: %s", exc, exc_info=True)
        return f"Sir, I encountered an unexpected error: {exc}"


TOOL = {
    "name": "hermes_task",
    "description": (
        "Primary universal execution engine for multi-step tasks, terminal commands, "
        "file creation, inspecting system/temp directories, scripting, and desktop automations. "
        "Use this tool whenever the user asks to create or inspect files, check temporary files, "
        "run scripts, execute shell commands, or perform complex multi-step computer operations."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {
                "type": "STRING",
                "description": (
                    "The detailed objective, command, or problem statement to be "
                    "solved autonomously by Hermes Agent."
                ),
            },
            "background": {
                "type": "BOOLEAN",
                "description": (
                    "Set to True if this is a long-running batch job that should run "
                    "in the background while the user continues talking. Defaults to False."
                ),
            },
        },
        "required": ["task"],
    },
    "handler": hermes_task_action,
}
