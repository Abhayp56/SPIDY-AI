"""Todoist task integration using the official REST API."""
from __future__ import annotations

import requests
from memory.config_manager import load_api_keys

_API = "https://api.todoist.com/api/v1"


def todoist_control(parameters: dict, **_kwargs) -> str:
    cfg = load_api_keys().get("plugin_config", {}).get("todoist", {})
    token = str(cfg.get("api_token") or "").strip()
    if not token:
        return "Todoist is not connected. Add plugin_config.todoist.api_token in config/api_keys.json."
    action = str(parameters.get("action", "list")).lower().strip()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        if action == "list":
            resp = requests.get(f"{_API}/tasks", headers=headers, params={"limit": 30}, timeout=12)
        elif action == "create":
            content = str(parameters.get("content", "")).strip()
            if not content:
                return "Task content is required."
            body = {"content": content}
            for key in ("description", "due_string", "priority"):
                if parameters.get(key) not in (None, ""):
                    body[key] = parameters[key]
            resp = requests.post(f"{_API}/tasks", headers=headers, json=body, timeout=12)
        elif action == "complete":
            task_id = str(parameters.get("task_id", "")).strip()
            if not task_id:
                return "Task ID is required to complete a Todoist task."
            resp = requests.post(f"{_API}/tasks/{task_id}/close", headers=headers, timeout=12)
            if resp.status_code in (200, 204):
                return "Marked the Todoist task complete."
        else:
            return "Todoist action must be list, create, or complete."
        if not resp.ok:
            return f"Todoist returned HTTP {resp.status_code}: {resp.text[:300]}"
        if action == "create":
            task = resp.json()
            return f"Created Todoist task '{task.get('content', 'task')}' (ID {task.get('id')})."
        tasks = resp.json()
        items = tasks.get("results", tasks) if isinstance(tasks, dict) else tasks
        if not items:
            return "You have no open Todoist tasks."
        return "Open Todoist tasks: " + "; ".join(f"{t.get('content', 'Untitled')} (ID {t.get('id')})" for t in items[:20])
    except requests.RequestException as exc:
        return f"Todoist request failed: {exc}"


TOOL = {"name": "todoist_control", "description": "List open Todoist tasks, create a task, or mark a task complete. Never deletes tasks.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["list", "create", "complete"]},
        "content": {"type": "STRING"}, "task_id": {"type": "STRING"},
        "description": {"type": "STRING"}, "due_string": {"type": "STRING"},
        "priority": {"type": "INTEGER"}}, "required": ["action"]}, "handler": todoist_control}
