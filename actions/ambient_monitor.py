"""
actions/ambient_monitor.py
Action tool for proactive ambient monitoring and system health auditing.

Architecture & Design Decisions:
- Follows SOLID principles:
  - Single Responsibility: Exposes proactive health checks and ambient desktop diagnostics.
  - Dependency Inversion: Uses get_ambient_monitor() singleton.
- Auto-discovered by core/action_loader.py.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from core.ambient_monitor import get_ambient_monitor


def ambient_monitor_action(
    parameters: Optional[Dict[str, Any]] = None,
    player: Any = None,
    speak: Any = None,
    **kwargs
) -> str:
    """
    Handler for ambient_monitor tool.
    Audits desktop health, system resources, battery, disk space, and active error windows.
    """
    params = parameters or {}
    action = params.get("action", "audit").strip().lower()

    monitor = get_ambient_monitor()

    try:
        if action in ("audit", "health_check", "status"):
            alerts = monitor.audit_system()
            if not alerts:
                return "System health audit passed. All resources, disk space, and desktop windows are operating nominally."
            
            lines = [f"System Audit detected {len(alerts)} item(s) requiring attention:"]
            for a in alerts:
                lines.append(f"- {a.format_log()}")
            return "\n".join(lines)

        elif action in ("check_disk", "disk_space", "disk"):
            alerts = monitor.check_disk_space()
            if not alerts:
                import psutil
                usage = psutil.disk_usage("C:" if psutil.WINDOWS else "/")
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                return f"Disk space is healthy. Drive has {free_gb:.1f} GB free out of {total_gb:.1f} GB ({usage.percent}% used)."
            return "\n".join([a.message for a in alerts])

        elif action in ("check_battery", "battery"):
            import psutil
            batt = psutil.sensors_battery()
            if not batt:
                return "No battery detected (desktop PC or AC mains)."
            state = "Plugged in / Charging" if batt.power_plugged else "On battery / Discharging"
            return f"Battery is at {int(batt.percent)}% ({state})."

        elif action in ("check_errors", "errors"):
            alerts = monitor.check_error_windows()
            if not alerts:
                return "No application error or crash dialogs detected on screen."
            return "\n".join([a.message for a in alerts])

        elif action in ("check_resources", "resources"):
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory().percent
            return f"Current CPU utilization is {int(cpu)}%, and RAM utilization is {int(ram)}%."

        else:
            return f"Unknown action '{action}' for ambient_monitor. Valid actions: audit, check_disk, check_battery, check_resources, check_errors."

    except Exception as e:
        print(f"[ambient_monitor] Error: {e}")
        return f"System health audit failed: {e}"


# ── Auto-Discovered Tool Declaration ──────────────────────────────────────────
TOOL = {
    "name": "ambient_monitor",
    "description": (
        "Performs proactive desktop health checks and audits system resources. "
        "Use this whenever the user asks for a system health check, battery status, "
        "disk space diagnostics, or to check for active error/crash windows."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "audit (default) | check_disk | check_battery | check_resources | check_errors",
            },
        },
        "required": [],
    },
    "handler": ambient_monitor_action,
}
