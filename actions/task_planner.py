"""
actions/task_planner.py
Action tool for multi-step task planning and background autonomous execution.

Architecture & Design Decisions:
- Follows SOLID principles:
  - Single Responsibility: Translates Gemini tool calls into background planned workflows.
  - Dependency Inversion: Uses get_task_planner() singleton.
- Non-blocking: Triggers background execution without stalling Gemini Live real-time audio.
- Auto-discovered by core/action_loader.py.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from core.task_planner import get_task_planner


def task_planner_action(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for task_planner tool.
    Decomposes multi-step desktop tasks and executes them asynchronously.
    """
    params = parameters or {}
    action = params.get("action", "plan_and_execute").strip().lower()
    goal = params.get("goal", "").strip()
    plan_id = params.get("plan_id", "").strip()

    planner = get_task_planner()

    if action in ("plan_and_execute", "execute", "run"):
        if not goal:
            return "Please specify a goal or objective to plan and execute."

        # Generate plan
        plan = planner.generate_plan(goal)
        if not plan.steps:
            return f"Could not generate an executable plan for '{goal}'."

        # Dispatch execution to background worker queue
        ack = planner.execute_plan_async(plan, player=player)
        return ack

    elif action in ("create_plan", "plan"):
        if not goal:
            return "Please provide a goal to create a plan for."
        plan = planner.generate_plan(goal)
        lines = [f"Generated plan '{plan.goal}' ({len(plan.steps)} steps):"]
        for s in plan.steps:
            lines.append(f"{s.step_number}. {s.description} (Tool: {s.tool_name})")
        return "\n".join(lines)

    elif action in ("status", "check_status"):
        if not plan_id:
            return "Please specify a plan_id to check status."
        plan = planner.get_plan(plan_id)
        if not plan:
            return f"Plan with ID '{plan_id}' not found."
        return plan.format_progress()

    else:
        return f"Unknown action '{action}' for task_planner. Valid actions: plan_and_execute, create_plan, status."


# ── Auto-Discovered Tool Declaration ──────────────────────────────────────────
TOOL = {
    "name": "task_planner",
    "description": (
        "Plans and autonomously executes multi-step desktop tasks in the background. "
        "Use this whenever the user gives a chained, complex, or multi-step instruction "
        "(e.g., 'open app X, click Y, and do Z', 'find file in folder, move it to Documents, and open it', "
        "'clean temporary files and organize my desktop')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "plan_and_execute (default) | create_plan | status",
            },
            "goal": {
                "type": "STRING",
                "description": "The high-level goal or multi-step task description to accomplish.",
            },
            "plan_id": {
                "type": "STRING",
                "description": "Optional plan ID to check status of an existing plan.",
            },
        },
        "required": ["goal"],
    },
    "handler": task_planner_action,
}
