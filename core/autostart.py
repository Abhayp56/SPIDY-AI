"""
core/autostart.py — Cross-platform auto-start management.

Isolated single-responsibility module to register or unregister JARVIS to
start automatically when the operating system boots or the user logs in.
Supports:
  - Windows: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  - macOS:   ~/Library/LaunchAgents/com.jarvis.assistant.plist
  - Linux:   ~/.config/autostart/jarvis.desktop
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def _get_main_script() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "main.py"


def is_autostart_enabled() -> bool:
    """Check if JARVIS is currently registered to launch at OS login."""
    try:
        if _OS == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            )
            try:
                winreg.QueryValueEx(key, "JARVIS_AI")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)

        elif _OS == "Darwin":
            plist = Path.home() / "Library" / "LaunchAgents" / "com.jarvis.assistant.plist"
            return plist.exists()

        else:  # Linux
            desk = Path.home() / ".config" / "autostart" / "jarvis.desktop"
            return desk.exists()

    except Exception as e:
        print(f"[Autostart] Query error: {e}")
        return False


def set_autostart_enabled(enabled: bool) -> bool:
    """Enable or disable JARVIS launch at OS login. Returns True on success."""
    try:
        script = str(_get_main_script())

        if _OS == "Windows":
            import winreg
            reg = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_ALL_ACCESS,
            )
            try:
                if enabled:
                    pythonw = Path(sys.executable).parent / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else sys.executable)
                    cmd = f'"{exe}" "{script}"'
                    winreg.SetValueEx(reg, "JARVIS_AI", 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(reg, "JARVIS_AI")
                    except FileNotFoundError:
                        pass
                return True
            finally:
                winreg.CloseKey(reg)

        elif _OS == "Darwin":
            plist_dir = Path.home() / "Library" / "LaunchAgents"
            plist_dir.mkdir(parents=True, exist_ok=True)
            plist = plist_dir / "com.jarvis.assistant.plist"
            if enabled:
                python = sys.executable
                content = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0">\n<dict>\n'
                    '  <key>Label</key><string>com.jarvis.assistant</string>\n'
                    '  <key>ProgramArguments</key>\n  <array>\n'
                    f'    <string>{python}</string>\n'
                    f'    <string>{script}</string>\n'
                    '  </array>\n'
                    '  <key>RunAtLoad</key><true/>\n'
                    '  <key>KeepAlive</key><false/>\n'
                    '</dict>\n</plist>\n'
                )
                plist.write_text(content, encoding="utf-8")
            else:
                plist.unlink(missing_ok=True)
            return True

        else:  # Linux
            desk_dir = Path.home() / ".config" / "autostart"
            desk_dir.mkdir(parents=True, exist_ok=True)
            desk = desk_dir / "jarvis.desktop"
            if enabled:
                python = sys.executable
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=JARVIS\n"
                    f"Exec={python} {script}\n"
                    "Hidden=false\n"
                    "NoDisplay=false\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                desk.write_text(content, encoding="utf-8")
            else:
                desk.unlink(missing_ok=True)
            return True

    except Exception as e:
        print(f"[Autostart] Set error: {e}")
        return False
