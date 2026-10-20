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
from core import confirm as confirm_gate

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

    # Approval must return to the Live receiver immediately so it can hear a
    # later spoken yes/no. Run only after the interface-issued gate resolves.
    task_id = f"hermes_{uuid.uuid4().hex[:8]}"
    worker = get_worker()

    def _progress(msg: str):
        _log(msg)
        worker.update_progress(task_id, msg)

    def _execute() -> str:
        _progress(f"Starting: {task[:180]}")
        result = bridge.run_task(
            task_prompt=task,
            on_status=_progress,
            on_tool_progress=_progress,
        )
        if result.get("status") != "success":
            message = result.get("final_response") or "Hermes task failed."
            _progress(f"Failed: {message[:180]}")
            raise RuntimeError(message)
        final_resp = result.get("final_response") or "Task completed."
        _progress(f"Finished: {final_resp[:180]}")
        return final_resp

    def _start_after_approval() -> str:
        mode = "background" if background else "approved"
        worker.submit_task(task_id, f"Hermes: {task[:100]} ({mode})", _execute)
        _log("Voice approval received. Starting the approved task.")
        return "Task queued after voice approval."

    if confirm_gate.requires_voice_approval(task):
        # Critical or clearly deep work waits for a spoken decision.
        return confirm_gate.request(
            key=f"hermes-{uuid.uuid4().hex[:8]}",
            title="Approve Hermes task?",
            detail=f"Hermes will carry out this task:\n\n{task[:900]}",
            run=_start_after_approval,
        )

    # Routine and moderate tasks keep the quick path without an approval prompt.
    if background:
        worker.submit_task(task_id, f"Hermes: {task[:100]}", _execute)
        return "I have started that task in the background and will report when it finishes."
    try:
        return _execute()
    except Exception as exc:
        logger.error("Hermes execution failed: %s", exc, exc_info=True)
        return f"Execution encountered an issue: {exc}"


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
