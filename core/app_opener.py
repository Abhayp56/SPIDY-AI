"""
core/app_opener.py
Universal Application Launcher for Files & Folders in JARVIS / S.P.I.D.Y.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Responsible solely for discovering installed applications and launching them
  with a target file or folder argument.
- Extensible Application Registry (Open/Closed Principle):
  Maps common developer and productivity applications (Antigravity IDE, VS Code,
  PyCharm, Sublime, Notepad, Office, Browsers) with smart dynamic fallbacks via
  Windows Registry, Start Menu, LocalAppData, and system PATH.
- Preserves Backward Compatibility:
  Provides a clean, decoupled interface (AppOpener.open_target_in_app) that can be
  used by actions/explorer_copilot.py, actions/file_controller.py, and actions/open_app.py
  without altering default File Explorer behaviors when no app is specified.
- Cross-Platform Support:
  Tailored for Windows with standard POSIX fallbacks for macOS/Linux.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _normalize_name(name: str) -> str:
    """Normalizes application or folder names by lowercasing and stripping punctuation."""
    if not name:
        return ""
    return re.sub(r"[\s_\-]+", " ", str(name).lower()).strip()


class AppOpener:
    """
    Service for locating user-preferred applications and launching files or folders in them.
    """

    # Common aliases mapping user spoken phrases to preferred binary names
    _KNOWN_ALIASES: Dict[str, List[str]] = {
        "antigravity": [
            "antigravity-ide.cmd",
            "Antigravity IDE.exe",
            "Antigravity IDE",
            "antigravity",
            "antigravity-ide",
            "agy",
        ],
        "anti gravity": [
            "antigravity-ide.cmd",
            "Antigravity IDE.exe",
            "Antigravity IDE",
            "antigravity",
            "antigravity-ide",
            "agy",
        ],
        "antigravity ide": [
            "antigravity-ide.cmd",
            "Antigravity IDE.exe",
            "Antigravity IDE",
            "antigravity",
        ],
        "anti gravity ide": [
            "antigravity-ide.cmd",
            "Antigravity IDE.exe",
            "Antigravity IDE",
            "antigravity",
        ],
        "vscode": [
            "code.cmd",
            "Code.exe",
            "code",
        ],
        "vs code": [
            "code.cmd",
            "Code.exe",
            "code",
        ],
        "visual studio code": [
            "code.cmd",
            "Code.exe",
            "code",
        ],
        "code": [
            "code.cmd",
            "Code.exe",
            "code",
        ],
        "notepad": [
            "notepad.exe",
        ],
        "notepad++": [
            "notepad++.exe",
        ],
        "pycharm": [
            "pycharm64.exe",
            "pycharm.exe",
        ],
        "sublime": [
            "sublime_text.exe",
            "subl.exe",
        ],
        "sublime text": [
            "sublime_text.exe",
            "subl.exe",
        ],
        "android studio": [
            "studio64.exe",
            "studio.exe",
        ],
        "chrome": [
            "chrome.exe",
        ],
        "google chrome": [
            "chrome.exe",
        ],
        "edge": [
            "msedge.exe",
        ],
        "microsoft edge": [
            "msedge.exe",
        ],
        "firefox": [
            "firefox.exe",
        ],
        "brave": [
            "brave.exe",
        ],
        "word": [
            "winword.exe",
        ],
        "excel": [
            "excel.exe",
        ],
        "powerpoint": [
            "powerpnt.exe",
        ],
        "vlc": [
            "vlc.exe",
        ],
        "explorer": [
            "explorer.exe",
        ],
        "file explorer": [
            "explorer.exe",
        ],
    }

    @classmethod
    def resolve_target_path(cls, target: str) -> Optional[Path]:
        """
        Resolves a user-provided target string (folder or file path or shortcut)
        to an existing Path on disk.
        """
        if not target or not str(target).strip():
            return None

        clean = str(target).strip().strip('"').strip("'")
        clean_lower = clean.lower()

        # 1. Check known folder shortcuts
        home = Path.home()
        known_shortcuts: Dict[str, Path] = {
            "desktop": home / "Desktop",
            "downloads": home / "Downloads",
            "documents": home / "Documents",
            "pictures": home / "Pictures",
            "music": home / "Music",
            "videos": home / "Videos",
            "home": home,
            "workspace": Path.cwd(),
            "project": Path.cwd(),
            "my project": Path.cwd(),
            "this project": Path.cwd(),
            "the project": Path.cwd(),
            "folder": Path.cwd(),
            "my folder": Path.cwd(),
            "this folder": Path.cwd(),
            "the folder": Path.cwd(),
            "current folder": Path.cwd(),
            "current directory": Path.cwd(),
            "here": Path.cwd(),
            "directory": Path.cwd(),
            "my directory": Path.cwd(),
            "this directory": Path.cwd(),
        }

        # Handle generic folder / project references
        if clean_lower in known_shortcuts:
            p = known_shortcuts[clean_lower]
            if p.exists():
                return p

        # Strip phrases like "my folder", "the folder", "folder"
        stripped_target = re.sub(
            r"^(my|the|this)\s+", "", clean, flags=re.IGNORECASE
        ).strip()
        stripped_target = re.sub(
            r"\s*(folder|directory|project)$", "", stripped_target, flags=re.IGNORECASE
        ).strip()

        # If user just said "my folder" or "the project", resolve to current workspace
        if not stripped_target or stripped_target.lower() in ("folder", "project", "directory"):
            return Path.cwd()

        if stripped_target.lower() in known_shortcuts:
            p = known_shortcuts[stripped_target.lower()]
            if p.exists():
                return p

        # 2. Check if clean path is absolute or directly resolvable
        try:
            direct_p = Path(clean).expanduser()
            if direct_p.exists():
                return direct_p.resolve()
        except Exception:
            pass

        # 3. Check stripped path
        try:
            stripped_p = Path(stripped_target).expanduser()
            if stripped_p.exists():
                return stripped_p.resolve()
        except Exception:
            pass

        # 4. Search in common roots: Current workspace, Desktop, Downloads, Documents, Home
        candidate_roots = [
            Path.cwd(),
            home / "Desktop",
            home / "Downloads",
            home / "Documents",
            home,
        ]

        # Check exact child match
        for root in candidate_roots:
            if not root.exists():
                continue
            child = root / clean
            if child.exists():
                return child.resolve()
            if stripped_target:
                stripped_child = root / stripped_target
                if stripped_child.exists():
                    return stripped_child.resolve()

        # 5. Fuzzy match against subdirectories / files in common roots
        norm_clean = _normalize_name(clean)
        norm_stripped = _normalize_name(stripped_target)

        for root in candidate_roots:
            if not root.exists():
                continue
            try:
                for entry in root.iterdir():
                    norm_entry = _normalize_name(entry.name)
                    norm_stem = _normalize_name(entry.stem)
                    if (
                        norm_entry == norm_clean
                        or norm_stem == norm_clean
                        or (norm_stripped and (norm_entry == norm_stripped or norm_stem == norm_stripped))
                    ):
                        return entry.resolve()
            except Exception:
                continue

        # 6. Fallback: return direct path even if not strictly validated yet
        try:
            return Path(clean).expanduser().resolve()
        except Exception:
            return None

    @classmethod
    def find_application_executable(cls, app_name: str) -> Optional[Tuple[str, str]]:
        """
        Locates the executable path or command for an application name.
        Returns a tuple of (executable_path_or_command, friendly_display_name) or None.
        """
        if not app_name or not str(app_name).strip():
            return None

        clean_app = str(app_name).strip()
        norm_app = _normalize_name(clean_app)

        # Collect candidate names to search for
        candidates: List[str] = []
        if norm_app in cls._KNOWN_ALIASES:
            candidates.extend(cls._KNOWN_ALIASES[norm_app])

        # Substring alias match
        for alias_key, alias_list in cls._KNOWN_ALIASES.items():
            if alias_key in norm_app or norm_app in alias_key:
                for item in alias_list:
                    if item not in candidates:
                        candidates.append(item)

        # Add the raw requested name
        if clean_app not in candidates:
            candidates.append(clean_app)
        if clean_app.replace(" ", "") not in candidates:
            candidates.append(clean_app.replace(" ", ""))

        # ── Strategy 1: Check System PATH via shutil.which ────────────────────
        for cand in candidates:
            found = (
                shutil.which(cand)
                or shutil.which(f"{cand}.exe")
                or shutil.which(f"{cand}.cmd")
                or shutil.which(f"{cand}.bat")
            )
            if found:
                return (found, clean_app.title())

        # ── Strategy 2: Windows Specific Discovery ────────────────────────────
        if sys.platform == "win32":
            local_appdata = Path(os.environ.get("LOCALAPPDATA", ""))
            prog_files = Path(os.environ.get("PROGRAMFILES", "C:\\Program Files"))
            prog_files_x86 = Path(
                os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
            )

            # 2a. Check LocalAppData Programs directory (e.g. Antigravity IDE, VS Code user install)
            programs_dirs = [
                local_appdata / "Programs",
                prog_files,
                prog_files_x86,
            ]

            for base_dir in programs_dirs:
                if not base_dir.exists():
                    continue
                try:
                    for app_dir in base_dir.iterdir():
                        if not app_dir.is_dir():
                            continue
                        norm_dir = _normalize_name(app_dir.name)
                        # Check match against requested app name
                        matches = any(
                            _normalize_name(c) in norm_dir or norm_dir in _normalize_name(c)
                            for c in candidates
                        )
                        if matches:
                            # 1. Look for direct .exe matching folder or app name
                            for exe in app_dir.glob("*.exe"):
                                if "unins" in exe.name.lower():
                                    continue
                                return (str(exe), app_dir.name)

                            # 2. Look in bin subdirectory (e.g. antigravity-ide.cmd, code.cmd)
                            bin_dir = app_dir / "bin"
                            if bin_dir.exists():
                                for cmd in bin_dir.glob("*.cmd"):
                                    return (str(cmd), app_dir.name)
                                for exe in bin_dir.glob("*.exe"):
                                    return (str(exe), app_dir.name)
                except Exception:
                    pass

            # 2b. Check Windows Registry App Paths
            try:
                import winreg

                for cand in candidates:
                    for ext_cand in (cand if cand.endswith(".exe") else f"{cand}.exe", cand):
                        for subkey in (
                            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{ext_cand}",
                            rf"SOFTWARE\Clients\StartMenuInternet\{ext_cand}\shell\open\command",
                        ):
                            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                                try:
                                    k = winreg.OpenKey(hive, subkey)
                                    val = winreg.QueryValue(k, None)
                                    winreg.CloseKey(k)
                                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                                    if exe and Path(exe).exists():
                                        return (exe, clean_app.title())
                                except Exception:
                                    pass
            except Exception:
                pass

            # 2c. Check Windows Start Menu Shortcuts (.lnk files)
            start_menu_dirs = [
                Path(os.environ.get("APPDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs",
                Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs",
            ]
            for sm_dir in start_menu_dirs:
                if not sm_dir.exists():
                    continue
                try:
                    for lnk in sm_dir.rglob("*.lnk"):
                        norm_lnk = _normalize_name(lnk.stem)
                        if any(_normalize_name(c) in norm_lnk for c in candidates):
                            return (str(lnk), lnk.stem)
                except Exception:
                    pass

        # ── Strategy 3: macOS Discovery ───────────────────────────────────────
        elif sys.platform == "darwin":
            for cand in candidates:
                # Direct app bundle
                app_path = Path(f"/Applications/{cand}.app")
                if app_path.exists():
                    return (str(app_path), cand)
                user_app = Path.home() / f"Applications/{cand}.app"
                if user_app.exists():
                    return (str(user_app), cand)

        # ── Strategy 4: Fallback to raw candidate if none found ───────────────
        return (candidates[0] if candidates else clean_app, clean_app.title())

    @classmethod
    def _resolve_shortcut_target(cls, lnk_path: str) -> Optional[str]:
        """Resolves the destination executable of a Windows .lnk shortcut."""
        if sys.platform != "win32" or not str(lnk_path).lower().endswith(".lnk"):
            return None
        try:
            ps_script = (
                f"$sh = New-Object -ComObject WScript.Shell; "
                f"$sc = $sh.CreateShortcut('{lnk_path}'); "
                f"$sc.TargetPath"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                text=True,
                timeout=4.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).strip()
            if out and Path(out).exists():
                return out
        except Exception:
            pass
        return None

    @classmethod
    def open_target_in_app(
        cls,
        target: Optional[str] = None,
        app_name: Optional[str] = None,
    ) -> str:
        """
        Opens the specified file or folder in the user's preferred application.

        Args:
            target: The file or folder path/name (e.g. "Mark-LV-main", "notes.txt").
            app_name: The application name (e.g. "anti gravity", "vscode", "notepad").

        Returns:
            Human-friendly result message.
        """
        if not target and not app_name:
            return "Please specify the file or folder and the application to open."

        # If no app specified, fall back to default OS open
        if not app_name or not str(app_name).strip():
            target_path = cls.resolve_target_path(target or "")
            if not target_path or not target_path.exists():
                return f"Path not found: {target}"
            try:
                if sys.platform == "win32":
                    if target_path.is_dir():
                        subprocess.Popen(["explorer.exe", str(target_path)])
                        return f"Opened folder '{target_path.name}' in File Explorer."
                    else:
                        os.startfile(str(target_path))
                        return f"Opened '{target_path.name}' on screen in its default application."
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target_path)])
                    return f"Opened '{target_path.name}' on screen."
                else:
                    subprocess.Popen(["xdg-open", str(target_path)])
                    return f"Opened '{target_path.name}' on screen."
            except Exception as e:
                return f"Failed to open '{target_path.name}': {e}"

        # Resolve target path
        target_path = cls.resolve_target_path(target or "")
        if not target_path or not target_path.exists():
            return f"Path does not exist: '{target}'."

        # Resolve application
        resolved = cls.find_application_executable(app_name)
        if not resolved:
            return f"Could not find application '{app_name}' installed on this computer."

        app_cmd, app_display = resolved

        # On Windows, if a .cmd/.bat script in bin was resolved (e.g. antigravity-ide.cmd, code.cmd),
        # prefer launching the native GUI .exe directly to avoid console flashing and subprocess wrapping.
        if sys.platform == "win32" and app_cmd.lower().endswith((".cmd", ".bat")):
            cmd_p = Path(app_cmd)
            for parent_dir in (cmd_p.parent.parent, cmd_p.parent):
                if parent_dir.exists():
                    for exe in parent_dir.glob("*.exe"):
                        if "unins" not in exe.name.lower():
                            app_cmd = str(exe)
                            break
                    if not app_cmd.lower().endswith((".cmd", ".bat")):
                        break

        print(f"[AppOpener] Opening '{target_path}' in '{app_display}' ({app_cmd})")

        try:
            if sys.platform == "win32":
                # If target is a .lnk shortcut, resolve the actual executable binary
                if app_cmd.lower().endswith(".lnk"):
                    resolved_target = cls._resolve_shortcut_target(app_cmd)
                    if resolved_target:
                        app_cmd = resolved_target

                creationflags = 0
                if app_cmd.lower().endswith((".cmd", ".bat")):
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    subprocess.Popen(
                        [app_cmd, str(target_path)],
                        shell=True,
                        creationflags=creationflags,
                    )
                elif app_cmd.lower().endswith(".lnk"):
                    # Safe Windows startfile fallback for shortcut with arguments
                    try:
                        os.startfile(app_cmd, "open", f'"{target_path}"')
                    except Exception:
                        subprocess.Popen(
                            ["powershell", "-NoProfile", "-Command", f'Start-Process -FilePath "{app_cmd}" -ArgumentList "\"{target_path}\""'],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                else:
                    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
                    subprocess.Popen(
                        [app_cmd, str(target_path)],
                        creationflags=creationflags,
                    )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", app_cmd, str(target_path)])
            else:
                subprocess.Popen([app_cmd, str(target_path)])

            item_type = "folder" if target_path.is_dir() else "file"
            return f"Opened {item_type} '{target_path.name}' in {app_display}."

        except Exception as e:
            return f"Failed to open '{target_path.name}' in {app_display}: {e}"
