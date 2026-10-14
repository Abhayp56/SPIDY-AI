"""
core/ambient_monitor.py
Ambient Desktop Monitoring, System Health Auditing, and Proactive Alerting.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Monitors desktop anomalies (error dialogs, crash alerts, unresponsiveness),
  system resources (low disk space, critical battery, high memory/CPU), and continuous work fatigue.
- Non-intrusive & Cooldown-controlled:
  Each alert category maintains independent cooldowns to prevent spamming the user.
- Multi-Channel Notification:
  Alerts trigger the Desktop Orb's visual alert pulse (Amber), write to the activity stream,
  and optionally dispatch a gentle spoken notification when appropriate.
- Thread-safe and lightweight:
  Audits run periodically on a daemon timer consuming negligible CPU (<0.01%).
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable

import psutil

from core.window_tracker import get_window_tracker, WindowTracker


@dataclass
class AmbientAlert:
    """Represents a proactive alert or notification."""
    alert_type: str  # "error_dialog" | "disk_space" | "battery" | "resource_spike" | "fatigue"
    severity: str    # "info" | "warning" | "critical"
    title: str
    message: str
    timestamp: float = field(default_factory=time.monotonic)

    def format_log(self) -> str:
        return f"[{self.severity.upper()}] {self.title}: {self.message}"


class AmbientMonitor:
    """
    Background engine for proactive health auditing and anomaly detection.
    """

    def __init__(
        self,
        window_tracker: Optional[WindowTracker] = None,
        disk_threshold_gb: float = 10.0,
        battery_threshold_pct: float = 20.0,
        cpu_threshold_pct: float = 92.0,
        ram_threshold_pct: float = 92.0,
        fatigue_threshold_mins: float = 90.0,
    ):
        self._tracker = window_tracker or get_window_tracker()
        self._disk_thresh = disk_threshold_gb
        self._battery_thresh = battery_threshold_pct
        self._cpu_thresh = cpu_threshold_pct
        self._ram_thresh = ram_threshold_pct
        self._fatigue_thresh = fatigue_threshold_mins

        # Cooldown tracking (type -> last_triggered_monotonic)
        self._cooldowns: Dict[str, float] = {}
        self._cooldown_durations: Dict[str, float] = {
            "error_dialog": 180.0,      # 3 minutes
            "disk_space": 7200.0,       # 2 hours
            "battery": 1800.0,          # 30 minutes
            "resource_spike": 600.0,    # 10 minutes
            "fatigue": 5400.0,          # 90 minutes
        }

        self._alert_listeners: List[Callable[[AmbientAlert], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def register_alert_listener(self, callback: Callable[[AmbientAlert], None]) -> None:
        """Register a callback to receive ambient alerts."""
        with self._lock:
            self._alert_listeners.append(callback)

    def _is_on_cooldown(self, alert_key: str) -> bool:
        now = time.monotonic()
        last = self._cooldowns.get(alert_key, 0.0)
        dur = self._cooldown_durations.get(alert_key.split(":")[0], 300.0)
        return (now - last) < dur

    def _mark_triggered(self, alert_key: str) -> None:
        self._cooldowns[alert_key] = time.monotonic()

    # ── Health & Anomaly Check Methods ────────────────────────────────────────
    def check_error_windows(self) -> List[AmbientAlert]:
        """Detects error dialogs, crashes, or unresponsiveness on screen."""
        alerts = []
        try:
            visible = self._tracker.list_visible_windows()
            error_keywords = ("error", "crash", "not responding", "exception", "failed", "access denied", "fatal")

            for w in visible:
                t_lower = w.title.lower()
                matched_kw = next((kw for kw in error_keywords if kw in t_lower), None)
                if matched_kw:
                    alert_key = f"error_dialog:{w.hwnd}:{matched_kw}"
                    if not self._is_on_cooldown(alert_key):
                        self._mark_triggered(alert_key)
                        alerts.append(AmbientAlert(
                            alert_type="error_dialog",
                            severity="warning",
                            title=f"Application Error ({w.app_name})",
                            message=f"An error or dialog was detected: '{w.title}'",
                        ))
        except Exception:
            pass
        return alerts

    def check_disk_space(self) -> List[AmbientAlert]:
        """Alerts if primary system drive is running critically low on space."""
        alerts = []
        try:
            drive = "C:" if os.name == "nt" else "/"
            usage = psutil.disk_usage(drive)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < self._disk_thresh:
                alert_key = "disk_space:low"
                if not self._is_on_cooldown(alert_key):
                    self._mark_triggered(alert_key)
                    alerts.append(AmbientAlert(
                        alert_type="disk_space",
                        severity="warning",
                        title="Low Disk Space",
                        message=f"Drive {drive} has only {free_gb:.1f} GB remaining.",
                    ))
        except Exception:
            pass
        return alerts

    def check_battery(self) -> List[AmbientAlert]:
        """Alerts if running on battery and charge drops below threshold."""
        alerts = []
        try:
            batt = psutil.sensors_battery()
            if batt and not batt.power_plugged and batt.percent <= self._battery_thresh:
                alert_key = "battery:low"
                if not self._is_on_cooldown(alert_key):
                    self._mark_triggered(alert_key)
                    alerts.append(AmbientAlert(
                        alert_type="battery",
                        severity="warning",
                        title="Low Battery",
                        message=f"Battery is at {int(batt.percent)}% and discharging.",
                    ))
        except Exception:
            pass
        return alerts

    def check_resource_spikes(self) -> List[AmbientAlert]:
        """Alerts if CPU or RAM is saturated."""
        alerts = []
        try:
            ram = psutil.virtual_memory()
            if ram.percent >= self._ram_thresh:
                alert_key = "resource_spike:ram"
                if not self._is_on_cooldown(alert_key):
                    self._mark_triggered(alert_key)
                    alerts.append(AmbientAlert(
                        alert_type="resource_spike",
                        severity="warning",
                        title="High Memory Usage",
                        message=f"System RAM utilization has reached {int(ram.percent)}%.",
                    ))

            cpu = psutil.cpu_percent(interval=0.1)
            if cpu >= self._cpu_thresh:
                alert_key = "resource_spike:cpu"
                if not self._is_on_cooldown(alert_key):
                    self._mark_triggered(alert_key)
                    alerts.append(AmbientAlert(
                        alert_type="resource_spike",
                        severity="warning",
                        title="High CPU Usage",
                        message=f"CPU load is currently at {int(cpu)}%.",
                    ))
        except Exception:
            pass
        return alerts

    def check_fatigue(self) -> List[AmbientAlert]:
        """Gently reminds user if they have been continuously working in one app for > 90 mins."""
        alerts = []
        try:
            active = self._tracker.get_active_window()
            if active and active.focus_duration > (self._fatigue_thresh * 60.0):
                alert_key = "fatigue:break"
                if not self._is_on_cooldown(alert_key):
                    self._mark_triggered(alert_key)
                    hours = active.focus_duration / 3600.0
                    alerts.append(AmbientAlert(
                        alert_type="fatigue",
                        severity="info",
                        title="Continuous Focus Reminder",
                        message=f"You've been focused in {active.app_name} for over {hours:.1f} hours. Consider a brief break.",
                    ))
        except Exception:
            pass
        return alerts

    # ── Full Audit & Background Thread ────────────────────────────────────────
    def audit_system(self) -> List[AmbientAlert]:
        """Runs a complete proactive audit and returns any triggered alerts."""
        all_alerts: List[AmbientAlert] = []
        all_alerts.extend(self.check_error_windows())
        all_alerts.extend(self.check_disk_space())
        all_alerts.extend(self.check_battery())
        all_alerts.extend(self.check_resource_spikes())
        all_alerts.extend(self.check_fatigue())
        return all_alerts

    def start_monitoring(self, interval_seconds: float = 40.0) -> None:
        """Starts the ambient monitoring loop in a background daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True

        def _loop():
            while self._running:
                try:
                    time.sleep(interval_seconds)
                    alerts = self.audit_system()
                    for alert in alerts:
                        self._notify_listeners(alert)
                except Exception as e:
                    print(f"[AmbientMonitor] ⚠ Audit error: {e}")

        self._thread = threading.Thread(target=_loop, daemon=True, name="AmbientMonitorThread")
        self._thread.start()
        print("[AmbientMonitor] 🛡 Ambient desktop monitoring active.")

    def stop_monitoring(self) -> None:
        with self._lock:
            self._running = False

    def _notify_listeners(self, alert: AmbientAlert) -> None:
        for cb in list(self._alert_listeners):
            try:
                cb(alert)
            except Exception as e:
                print(f"[AmbientMonitor] Listener error: {e}")


# ── Global Singleton Accessor ─────────────────────────────────────────────────
_MONITOR_INSTANCE: Optional[AmbientMonitor] = None
_MONITOR_LOCK = threading.Lock()

def get_ambient_monitor() -> AmbientMonitor:
    """Dependency injection / singleton accessor for AmbientMonitor."""
    global _MONITOR_INSTANCE
    if _MONITOR_INSTANCE is None:
        with _MONITOR_LOCK:
            if _MONITOR_INSTANCE is None:
                _MONITOR_INSTANCE = AmbientMonitor()
    return _MONITOR_INSTANCE
