"""
core/window_tracker.py
Single-responsibility module for ambient desktop awareness and window management.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP): Solely responsible for tracking foreground
  and visible windows across the operating system.
- Cross-platform support with deep native Windows integration (via ctypes + dwmapi + psutil)
  and graceful fallbacks for macOS and Linux.
- Thread-safe tracking and caching: Maintains focus duration, window bounding boxes,
  and active window history so the assistant understands temporal context ("what was I working on before?").
- Loose coupling: Exposes clean dataclasses and high-level query methods for actions and main runtime.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import platform
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

_SYSTEM = platform.system()


@dataclass
class WindowState:
    """Represents a snapshot of a desktop window."""
    hwnd: int = 0
    title: str = ""
    app_name: str = ""
    process_name: str = ""
    process_path: str = ""
    pid: int = 0
    bounds: Dict[str, int] = field(default_factory=lambda: {"left": 0, "top": 0, "width": 0, "height": 0})
    is_active: bool = False
    focus_start: float = 0.0
    focus_duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "app_name": self.app_name,
            "process_name": self.process_name,
            "process_path": self.process_path,
            "pid": self.pid,
            "bounds": self.bounds,
            "is_active": self.is_active,
            "focus_duration_seconds": round(self.focus_duration, 1),
        }

    def format_summary(self) -> str:
        name = self.app_name or self.process_name or "Application"
        t = f" - '{self.title}'" if self.title else ""
        dur = f" (focused {int(self.focus_duration)}s)" if self.focus_duration > 0 else ""
        return f"[{name}]{t}{dur}"


class WindowTracker:
    """
    Tracks foreground/active window state, maintains focus history,
    and enumerates open desktop application windows.
    """

    def __init__(self, history_limit: int = 15):
        self._history_limit = history_limit
        self._lock = threading.RLock()
        self._current_window: Optional[WindowState] = None
        self._history: List[WindowState] = []
        self._last_poll_time = 0.0

        # Windows-specific function signatures
        self._user32 = None
        self._dwmapi = None
        if _SYSTEM == "Windows":
            try:
                self._user32 = ctypes.windll.user32
                self._dwmapi = ctypes.windll.dwmapi
            except Exception as e:
                print(f"[WindowTracker] ⚠ Windows native API init warning: {e}")

    # ── Friendly app name resolution ──────────────────────────────────────────
    @staticmethod
    def _clean_app_name(proc_name: str, title: str) -> str:
        """Translates binary names like 'Code.exe' or 'chrome.exe' to clean readable names."""
        raw = proc_name.lower().replace(".exe", "")
        lookup = {
            "code": "Visual Studio Code",
            "chrome": "Google Chrome",
            "msedge": "Microsoft Edge",
            "firefox": "Mozilla Firefox",
            "brave": "Brave Browser",
            "spotify": "Spotify",
            "discord": "Discord",
            "slack": "Slack",
            "telegram": "Telegram",
            "whatsapp": "WhatsApp",
            "explorer": "File Explorer",
            "notepad": "Notepad",
            "windowsterminal": "Windows Terminal",
            "cmd": "Command Prompt",
            "powershell": "PowerShell",
            "taskmgr": "Task Manager",
            "vlc": "VLC Media Player",
            "steam": "Steam",
            "obs64": "OBS Studio",
            "devenv": "Visual Studio",
            "pycharm64": "PyCharm",
            "idea64": "IntelliJ IDEA",
            "notion": "Notion",
            "obsidian": "Obsidian",
            "postman": "Postman",
            "zoom": "Zoom",
            "teams": "Microsoft Teams",
            "msteams": "Microsoft Teams",
            "epicgameslauncher": "Epic Games",
            "calculatorapp": "Calculator",
            "calc": "Calculator",
            "mspaint": "Paint",
        }
        if raw in lookup:
            return lookup[raw]
        if raw:
            return raw.capitalize()
        # Fallback from title
        if title:
            parts = [p.strip() for p in title.split(" - ") if p.strip()]
            if len(parts) > 1:
                return parts[-1]
        return "Application"

    # ── Windows Native Detection ──────────────────────────────────────────────
    def _is_cloaked_window(self, hwnd: int) -> bool:
        """Determines if a window is hidden/cloaked (e.g. UWP suspended background tile)."""
        if not self._dwmapi:
            return False
        try:
            DWMWA_CLOAKED = 14
            cloaked = ctypes.c_int(0)
            res = self._dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_CLOAKED,
                ctypes.byref(cloaked),
                ctypes.sizeof(cloaked)
            )
            return res == 0 and cloaked.value != 0
        except Exception:
            return False

    def _get_window_bounds_win(self, hwnd: int) -> Dict[str, int]:
        bounds = {"left": 0, "top": 0, "width": 0, "height": 0}
        if not self._user32:
            return bounds
        try:
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long)
                ]
            rect = RECT()
            if self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                bounds = {
                    "left": int(rect.left),
                    "top": int(rect.top),
                    "width": int(rect.right - rect.left),
                    "height": int(rect.bottom - rect.top)
                }
        except Exception:
            pass
        return bounds

    def _get_proc_info(self, pid: int) -> tuple[str, str]:
        """Returns (process_name, process_path). Safe against process exits."""
        if not _HAS_PSUTIL or pid <= 0:
            return "", ""
        try:
            p = psutil.Process(pid)
            name = p.name()
            try:
                exe = p.exe()
            except Exception:
                exe = ""
            return name, exe
        except Exception:
            return "", ""

    def _get_active_window_win(self) -> Optional[WindowState]:
        if not self._user32:
            return None
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Title
        length = self._user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

        # PID
        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        p_val = int(pid.value)
        proc_name, proc_path = self._get_proc_info(p_val)

        bounds = self._get_window_bounds_win(hwnd)
        app_name = self._clean_app_name(proc_name, title)

        now = time.monotonic()
        return WindowState(
            hwnd=int(hwnd),
            title=title,
            app_name=app_name,
            process_name=proc_name,
            process_path=proc_path,
            pid=p_val,
            bounds=bounds,
            is_active=True,
            focus_start=now,
            focus_duration=0.0
        )

    # ── Cross-Platform Fallbacks ──────────────────────────────────────────────
    def _get_active_window_fallback(self) -> Optional[WindowState]:
        # macOS / Linux fallback
        if _SYSTEM == "Darwin":
            try:
                import subprocess
                cmd = (
                    'tell application "System Events" to get '
                    '{name, (name of window 1)} of (first application process whose frontmost is true)'
                )
                res = subprocess.run(["osascript", "-e", cmd], capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    parts = [p.strip() for p in res.stdout.split(",") if p.strip()]
                    app = parts[0] if len(parts) > 0 else ""
                    title = parts[1] if len(parts) > 1 else app
                    return WindowState(
                        title=title,
                        app_name=app,
                        process_name=app,
                        is_active=True,
                        focus_start=time.monotonic()
                    )
            except Exception:
                pass

        elif _SYSTEM == "Linux":
            try:
                import subprocess
                res = subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                                     capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    title = res.stdout.strip()
                    return WindowState(
                        title=title,
                        app_name="Active Window",
                        is_active=True,
                        focus_start=time.monotonic()
                    )
            except Exception:
                pass
        return None

    # ── Public Tracking API ───────────────────────────────────────────────────
    def get_active_window(self) -> WindowState:
        """
        Retrieves the currently focused window. Updates focus durations
        and recent history.
        """
        with self._lock:
            now = time.monotonic()
            new_win = None
            if _SYSTEM == "Windows":
                new_win = self._get_active_window_win()
            if not new_win:
                new_win = self._get_active_window_fallback()

            # If no foreground window detected (e.g. temporary transition or lock screen)
            if not new_win:
                if self._current_window:
                    self._current_window.focus_duration = now - self._current_window.focus_start
                    return self._current_window
                return WindowState(title="Desktop", app_name="Desktop")

            # Check if user switched to another window
            if self._current_window and (
                self._current_window.hwnd == new_win.hwnd
                and self._current_window.title == new_win.title
            ):
                self._current_window.focus_duration = now - self._current_window.focus_start
                return self._current_window

            # Window has changed: archive previous to history
            if self._current_window:
                self._current_window.focus_duration = now - self._current_window.focus_start
                self._history.insert(0, self._current_window)
                if len(self._history) > self._history_limit:
                    self._history.pop()

            self._current_window = new_win
            self._current_window.focus_duration = 0.0
            return self._current_window

    def get_history(self) -> List[WindowState]:
        """Returns recently focused windows (most recent first)."""
        with self._lock:
            return list(self._history)

    def list_visible_windows(self) -> List[WindowState]:
        """
        Enumerates all open, visible, non-minimized desktop windows.
        Filters out internal tooltips and cloaked background processes.
        """
        windows: List[WindowState] = []
        if _SYSTEM == "Windows" and self._user32:
            try:
                active_hwnd = self._user32.GetForegroundWindow()

                def _enum_proc(hwnd, lparam):
                    if not self._user32.IsWindowVisible(hwnd):
                        return True
                    if self._is_cloaked_window(hwnd):
                        return True

                    length = self._user32.GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True

                    buf = ctypes.create_unicode_buffer(length + 1)
                    self._user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if not title or title in ("Default IME", "MSCTFIME UI", "Program Manager"):
                        return True

                    bounds = self._get_window_bounds_win(hwnd)
                    if bounds["width"] <= 10 or bounds["height"] <= 10:
                        return True

                    pid = ctypes.c_ulong(0)
                    self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    p_val = int(pid.value)
                    proc_name, proc_path = self._get_proc_info(p_val)
                    app_name = self._clean_app_name(proc_name, title)

                    win = WindowState(
                        hwnd=int(hwnd),
                        title=title,
                        app_name=app_name,
                        process_name=proc_name,
                        process_path=proc_path,
                        pid=p_val,
                        bounds=bounds,
                        is_active=(hwnd == active_hwnd)
                    )
                    windows.append(win)
                    return True

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                self._user32.EnumWindows(WNDENUMPROC(_enum_proc), 0)
            except Exception as e:
                print(f"[WindowTracker] EnumWindows error: {e}")

        elif _SYSTEM == "Darwin":
            # Basic fallback for macOS
            curr = self.get_active_window()
            if curr.title:
                windows.append(curr)

        elif _SYSTEM == "Linux":
            try:
                import subprocess
                res = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    for line in res.stdout.strip().splitlines():
                        parts = line.split(None, 3)
                        if len(parts) >= 4:
                            title = parts[3].strip()
                            windows.append(WindowState(title=title, app_name="Window"))
            except Exception:
                pass

        return windows

    # ── On-Demand Process & Window Resolution ──────────────────────────────────
    def _bring_to_foreground(self, hwnd: int) -> bool:
        """
        Reliably brings a window handle to the foreground on Windows.
        Handles:
        - Minimized windows (restores via SW_RESTORE).
        - Maximized windows (preserves maximization via SW_SHOW/SW_MAXIMIZE).
        - Normal visible windows (preserves geometry).
        - Bypasses Windows OS foreground-lock restrictions via ThreadAttach & Alt-key simulation.
        """
        if not self._user32 or not hwnd:
            return False
        try:
            # 1. Window State Restoration
            if self._user32.IsIconic(hwnd):
                self._user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            elif hasattr(self._user32, "IsZoomed") and self._user32.IsZoomed(hwnd):
                self._user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            else:
                self._user32.ShowWindow(hwnd, 5)  # SW_SHOW

            # 2. Attach thread input to bypass Windows foreground lock
            fore_hwnd = self._user32.GetForegroundWindow()
            fore_thread = self._user32.GetWindowThreadProcessId(fore_hwnd, None) if fore_hwnd else 0
            target_thread = self._user32.GetWindowThreadProcessId(hwnd, None)
            curr_thread = ctypes.windll.kernel32.GetCurrentThreadId() if hasattr(ctypes, "windll") else 0

            threads_attached = False
            if fore_thread and target_thread and fore_thread != target_thread and curr_thread:
                try:
                    self._user32.AttachThreadInput(curr_thread, target_thread, True)
                    self._user32.AttachThreadInput(fore_thread, target_thread, True)
                    threads_attached = True
                except Exception:
                    pass

            # 3. Simulate Alt key release to unlock foreground switch
            try:
                VK_MENU = 0x12
                KEYEVENTF_KEYUP = 0x0002
                self._user32.keybd_event(VK_MENU, 0, 0, 0)
                self._user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass

            self._user32.BringWindowToTop(hwnd)
            self._user32.SetForegroundWindow(hwnd)

            if threads_attached:
                try:
                    self._user32.AttachThreadInput(curr_thread, target_thread, False)
                    self._user32.AttachThreadInput(fore_thread, target_thread, False)
                except Exception:
                    pass

            time.sleep(0.12)
            self.get_active_window()
            return True
        except Exception as e:
            print(f"[WindowTracker] _bring_to_foreground error: {e}")
            return False

    def find_all_desktop_windows(self, include_minimized: bool = True) -> List[WindowState]:
        """
        Enumerates all desktop application windows on demand.
        Unlike list_visible_windows(), this includes minimized, taskbar, and off-screen windows.
        """
        windows: List[WindowState] = []
        if _SYSTEM == "Windows" and self._user32:
            try:
                active_hwnd = self._user32.GetForegroundWindow()

                def _enum_proc(hwnd, lparam):
                    length = self._user32.GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True

                    buf = ctypes.create_unicode_buffer(length + 1)
                    self._user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()

                    # Filter out system low-level clutter
                    if not title or title in ("Default IME", "MSCTFIME UI", "Program Manager", "Windows Shell Experience Host"):
                        return True

                    is_iconic = bool(self._user32.IsIconic(hwnd))
                    is_visible = bool(self._user32.IsWindowVisible(hwnd))

                    if not is_visible and not is_iconic:
                        return True

                    bounds = self._get_window_bounds_win(hwnd)
                    # Minimized windows have width 0 or bounds offscreen (-32000), which we allow when iconic
                    if not is_iconic and (bounds["width"] <= 10 or bounds["height"] <= 10):
                        return True

                    pid = ctypes.c_ulong(0)
                    self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    p_val = int(pid.value)
                    proc_name, proc_path = self._get_proc_info(p_val)
                    app_name = self._clean_app_name(proc_name, title)

                    win = WindowState(
                        hwnd=int(hwnd),
                        title=title,
                        app_name=app_name,
                        process_name=proc_name,
                        process_path=proc_path,
                        pid=p_val,
                        bounds=bounds,
                        is_active=(hwnd == active_hwnd)
                    )
                    windows.append(win)
                    return True

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                self._user32.EnumWindows(WNDENUMPROC(_enum_proc), 0)
            except Exception as e:
                print(f"[WindowTracker] find_all_desktop_windows error: {e}")
        return windows

    def find_process_by_query(self, query: str) -> Optional[dict]:
        """
        Rapid on-demand (zero background polling) lookup of running processes via psutil.
        Matches process names, executable names, and friendly aliases in milliseconds.
        """
        if not _HAS_PSUTIL:
            return None

        q = query.lower().strip().replace(".exe", "")
        # Common query aliases
        alias_map = {
            "chrome": ["chrome"],
            "google chrome": ["chrome"],
            "edge": ["msedge"],
            "firefox": ["firefox"],
            "brave": ["brave"],
            "code": ["code"],
            "vscode": ["code"],
            "visual studio code": ["code"],
            "spotify": ["spotify"],
            "discord": ["discord"],
            "slack": ["slack"],
            "telegram": ["telegram"],
            "whatsapp": ["whatsapp"],
            "steam": ["steam"],
            "notepad": ["notepad"],
            "cmd": ["cmd"],
            "terminal": ["windowsterminal", "wt"],
            "powershell": ["powershell", "pwsh"],
            "vlc": ["vlc"],
            "obs": ["obs64", "obs32"],
            "postman": ["postman"],
            "notion": ["notion"],
            "obsidian": ["obsidian"],
            "zoom": ["zoom"],
            "teams": ["teams", "msteams"],
        }
        cand_names = alias_map.get(q, [q])

        try:
            for p in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    pname = (p.info.get("name") or "").lower().replace(".exe", "")
                    pexe = (p.info.get("exe") or "").lower()
                    for cand in cand_names:
                        if cand == pname or cand in pname or cand in pexe:
                            return {
                                "pid": p.info["pid"],
                                "name": p.info.get("name") or "",
                                "exe": p.info.get("exe") or "",
                            }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f"[WindowTracker] psutil lookup error: {e}")

        return None

    def find_hwnds_for_pid(self, pid: int) -> List[int]:
        """Finds all window handles belonging to a process ID on demand."""
        hwnds: List[int] = []
        if _SYSTEM == "Windows" and self._user32 and pid > 0:
            def _enum_proc(hwnd, lparam):
                target_pid = ctypes.c_ulong(0)
                self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
                if target_pid.value == pid:
                    length = self._user32.GetWindowTextLengthW(hwnd)
                    if length > 0 or self._user32.IsWindowVisible(hwnd) or self._user32.IsIconic(hwnd):
                        hwnds.append(int(hwnd))
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            self._user32.EnumWindows(WNDENUMPROC(_enum_proc), 0)
        return hwnds

    # ── Control Operations ────────────────────────────────────────────────────
    def focus_window(self, query: str | int) -> bool:
        """
        Brings an application window into the foreground on demand.
        3-Tier On-Demand Resolution:
        Tier 1: Check active / visible desktop windows.
        Tier 2: Check minimized, taskbar, or off-screen windows (restores via SW_RESTORE).
        Tier 3: Check running background processes via psutil and restore their window or signal tray.
        Tier 4: Windows PowerShell AppActivate fallback.
        """
        if isinstance(query, int):
            return self._bring_to_foreground(query)

        q_lower = str(query).lower().strip()
        if not q_lower:
            return False

        # ── Tier 1: Visible Desktop Windows ───────────────────────────────────
        visible = self.list_visible_windows()
        for w in visible:
            if q_lower in w.app_name.lower() or q_lower in w.process_name.lower() or q_lower in w.title.lower():
                if self._bring_to_foreground(w.hwnd):
                    return True

        # ── Tier 2: Minimized / Off-screen Desktop Windows ────────────────────
        all_windows = self.find_all_desktop_windows(include_minimized=True)
        for w in all_windows:
            if q_lower in w.app_name.lower() or q_lower in w.process_name.lower() or q_lower in w.title.lower():
                if self._bring_to_foreground(w.hwnd):
                    return True

        # ── Tier 3: Live Background Process / Tray App Resolution ─────────────
        proc = self.find_process_by_query(q_lower)
        if proc:
            pid = proc["pid"]
            hwnds = self.find_hwnds_for_pid(pid)
            for h in hwnds:
                if self._bring_to_foreground(h):
                    return True

            # If process has no standard window or is minimized to tray:
            # Re-invoking the executable tells the existing running process to reveal its UI!
            exe_path = proc.get("exe")
            if exe_path and os.path.exists(exe_path):
                try:
                    import subprocess
                    subprocess.Popen([exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(0.3)
                    new_hwnds = self.find_hwnds_for_pid(pid)
                    for h in new_hwnds:
                        if self._bring_to_foreground(h):
                            return True
                except Exception:
                    pass

        # ── Tier 4: PowerShell WScript.Shell AppActivate Fallback ─────────────
        if _SYSTEM == "Windows":
            try:
                import subprocess
                for name_to_try in [q_lower, str(query)]:
                    script = f'(New-Object -ComObject WScript.Shell).AppActivate("{name_to_try}")'
                    res = subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                        capture_output=True, text=True, timeout=2,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                    if "True" in res.stdout:
                        time.sleep(0.15)
                        self.get_active_window()
                        return True
            except Exception:
                pass

        return False

    def close_window(self, query: Optional[str | int] = None) -> bool:
        """
        Sends WM_CLOSE cleanly to target window or currently active window.
        """
        if _SYSTEM == "Windows" and self._user32:
            target_hwnd = 0
            if query is None or query == "current" or query == "active":
                target_hwnd = self._user32.GetForegroundWindow()
            elif isinstance(query, int):
                target_hwnd = query
            else:
                q = str(query).lower()
                for w in self.find_all_desktop_windows(include_minimized=True):
                    if q in w.title.lower() or q in w.app_name.lower() or q in w.process_name.lower():
                        target_hwnd = w.hwnd
                        break

            if target_hwnd:
                WM_CLOSE = 0x0010
                self._user32.PostMessageW(target_hwnd, WM_CLOSE, 0, 0)
                time.sleep(0.2)
                return True
        return False

    def minimize_window(self, query: Optional[str | int] = None) -> bool:
        if _SYSTEM == "Windows" and self._user32:
            target_hwnd = self._user32.GetForegroundWindow() if not query else None
            if not target_hwnd and isinstance(query, int):
                target_hwnd = query
            if target_hwnd:
                SW_MINIMIZE = 6
                self._user32.ShowWindow(target_hwnd, SW_MINIMIZE)
                return True
        return False

    def maximize_window(self, query: Optional[str | int] = None) -> bool:
        if _SYSTEM == "Windows" and self._user32:
            target_hwnd = self._user32.GetForegroundWindow() if not query else None
            if not target_hwnd and isinstance(query, int):
                target_hwnd = query
            if target_hwnd:
                SW_MAXIMIZE = 3
                self._user32.ShowWindow(target_hwnd, SW_MAXIMIZE)
                return True
        return False

    # ── Ambient Context Generation ────────────────────────────────────────────
    def get_ambient_context_summary(self) -> str:
        """
        Generates a concise, highly readable summary of the active window and open applications
        suitable for feeding directly into system turns or LLM prompts.
        """
        active = self.get_active_window()
        visible = self.list_visible_windows()

        lines = ["[DESKTOP & ACTIVE WINDOW CONTEXT]"]
        lines.append(f"Current Focused Window: {active.format_summary()}")

        other_wins = [w for w in visible if w.hwnd != active.hwnd and w.title]
        if other_wins:
            app_list = [f"- {w.format_summary()}" for w in other_wins[:8]]
            lines.append("Other Open Applications:")
            lines.extend(app_list)

        return "\n".join(lines)


# ── Global Singleton Accessor ─────────────────────────────────────────────────
_INSTANCE: Optional[WindowTracker] = None
_INSTANCE_LOCK = threading.Lock()

def get_window_tracker() -> WindowTracker:
    """Dependency injection / singleton accessor for WindowTracker."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = WindowTracker()
    return _INSTANCE
