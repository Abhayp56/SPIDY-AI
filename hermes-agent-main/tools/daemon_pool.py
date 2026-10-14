"""
tools/daemon_pool.py — DaemonThreadPoolExecutor for background tasks.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import threading

class _DaemonThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True

class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose threads are daemonized so they don't block interpreter shutdown."""
    def _adjust_thread_count(self):
        orig = threading.Thread
        threading.Thread = _DaemonThread
        try:
            super()._adjust_thread_count()
        finally:
            threading.Thread = orig
