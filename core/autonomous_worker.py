"""
core/autonomous_worker.py — Background Autonomous Worker Engine for Desktop Tasks.

Provides an asynchronous execution pipeline for long-running or multi-step
desktop automation jobs (e.g., file reorganization, web scraping, multi-step
coding, system auditing).

Decouples heavy background work from the real-time Gemini Live WebSocket
audio loop:
  1. A command triggers an autonomous job.
  2. Jarvis immediately acknowledges verbally ("Working on that, sir").
  3. The task runs in a background worker thread.
  4. The Desktop Orb reflects the "WORKING" state (spinning orbital aura).
  5. On completion, Jarvis announces the results and the Orb transitions
     back to "SLEEPING".
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class WorkerTask:
    task_id: str
    description: str
    func: Callable[[], str]
    created_at: float = field(default_factory=time.monotonic)
    status: str = "queued"  # queued | running | completed | failed
    result: Optional[str] = None
    error: Optional[str] = None


class AutonomousWorkerManager:
    """Singleton manager for background autonomous desktop tasks."""

    _instance: Optional[AutonomousWorkerManager] = None
    _lock = threading.Lock()

    def __init__(self, max_workers: int = 3):
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="JarvisWorker"
        )
        self._tasks: dict[str, WorkerTask] = {}
        self._active_count: int = 0
        self._state_callbacks: list[Callable[[str, WorkerTask], None]] = []
        self._completion_notifier: Optional[Callable[[str], None]] = None

    @classmethod
    def get_instance(cls) -> AutonomousWorkerManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register_state_listener(self, callback: Callable[[str, WorkerTask], None]) -> None:
        """Register a callback(event_name: 'started' | 'completed' | 'failed', task: WorkerTask)."""
        self._state_callbacks.append(callback)

    def set_completion_notifier(self, notifier: Callable[[str], None]) -> None:
        """Register a voice/log notifier for when tasks complete."""
        self._completion_notifier = notifier

    def is_busy(self) -> bool:
        """True if any background worker task is currently executing."""
        with self._lock:
            return self._active_count > 0

    def submit_task(self, task_id: str, description: str, func: Callable[[], str]) -> WorkerTask:
        """Queue and run an autonomous task in the background executor."""
        task = WorkerTask(task_id=task_id, description=description, func=func)
        with self._lock:
            self._tasks[task_id] = task

        self._executor.submit(self._run_task, task)
        return task

    def _run_task(self, task: WorkerTask) -> None:
        with self._lock:
            self._active_count += 1
            task.status = "running"

        self._emit_event("started", task)

        try:
            res = task.func()
            task.result = str(res) if res is not None else "Completed."
            task.status = "completed"
            self._emit_event("completed", task)
            if self._completion_notifier:
                try:
                    self._completion_notifier(
                        f"Task '{task.description}' finished: {task.result[:180]}"
                    )
                except Exception:
                    pass
        except Exception as e:
            task.error = str(e)
            task.status = "failed"
            self._emit_event("failed", task)
            if self._completion_notifier:
                try:
                    self._completion_notifier(
                        f"Task '{task.description}' encountered an error: {e}"
                    )
                except Exception:
                    pass
        finally:
            with self._lock:
                self._active_count = max(0, self._active_count - 1)

    def _emit_event(self, event: str, task: WorkerTask) -> None:
        for cb in list(self._state_callbacks):
            try:
                cb(event, task)
            except Exception as e:
                print(f"[Worker] Callback error: {e}")

    def get_status_summary(self) -> str:
        """Return a brief status summary of active background work."""
        with self._lock:
            if self._active_count == 0:
                return "All background tasks completed."
            running = [t.description for t in self._tasks.values() if t.status == "running"]
            return f"{self._active_count} task(s) active: " + ", ".join(running[:3])


# Global singleton accessors
def get_worker() -> AutonomousWorkerManager:
    return AutonomousWorkerManager.get_instance()
