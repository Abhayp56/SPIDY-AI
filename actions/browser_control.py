"""
actions/browser_control.py — Lightweight, Native Single-Window Browser Controller.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP): Solely responsible for orchestrating
  web browsing, tab navigation, and search queries across native web browsers.
- Native Single-Instance Architecture: Completely eliminates heavy, profile-locking
  Playwright automation daemons and extra automation profiles (.jarvis_profiles).
- Native Chrome Tab Management: When Chrome (or Edge/Brave) is already running,
  passing URLs directly commands the running process to open a new tab in the active window,
  eliminating multiple duplicate browser windows.
- Full Pre-filled Query Support: If the user provides a search query for YouTube, GitHub,
  Google, etc., the URL is automatically formatted and launched with the query already searched.
- Preserves Backward Compatibility: Maintains the `browser_control` function signature
  and `TOOL` schema expected by action_loader and hermes_bridge.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Any, Dict

_OS = platform.system()   # "Windows" | "Darwin" | "Linux"

_SEARCH_ENGINES = {
    "google":     "https://www.google.com/search?q=",
    "bing":       "https://www.bing.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "youtube":    "https://www.youtube.com/results?search_query=",
    "github":     "https://github.com/search?q=",
    "wikipedia":  "https://en.wikipedia.org/wiki/Special:Search?search=",
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
    "brave browser":   "brave",
}


def _normalize_url(url: str, query: str = "") -> str:
    """
    Constructs a fully-qualified URL, supporting pre-filled search queries
    for YouTube, GitHub, Google, or direct domains.
    """
    url = (url or "").strip()
    query = (query or "").strip()

    if not url and not query:
        return "https://www.google.com"

    # Only query provided -> Google search
    if not url and query:
        return _SEARCH_ENGINES["google"] + urllib.parse.quote_plus(query)

    url_lower = url.lower()

    # Pre-filled queries on popular platforms
    if "youtube" in url_lower and query:
        return _SEARCH_ENGINES["youtube"] + urllib.parse.quote_plus(query)
    if "github" in url_lower and query:
        return _SEARCH_ENGINES["github"] + urllib.parse.quote_plus(query)
    if ("google" in url_lower or "search" in url_lower) and query:
        return _SEARCH_ENGINES["google"] + urllib.parse.quote_plus(query)

    # Standard full URLs
    if "://" in url:
        if query and not ("?" in url or "&" in url):
            return f"{url}/search?q={urllib.parse.quote_plus(query)}"
        return url

    # Bare words like "youtube", "github", "reddit"
    if "." not in url:
        url = url + ".com"
    return "https://" + url


def _find_browser_exe(browser_name: str) -> Optional[str]:
    """Locates the native browser binary on the system."""
    name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())

    if _OS == "Windows":
        # 1. Registry App Paths
        try:
            import winreg
            key_paths = [
                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}.exe",
                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}",
                rf"SOFTWARE\Clients\StartMenuInternet\{name}\shell\open\command",
            ]
            if name == "chrome":
                key_paths.append(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
            elif name == "edge":
                key_paths.append(r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe")

            for kp in key_paths:
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        k = winreg.OpenKey(hive, kp)
                        val = winreg.QueryValue(k, None)
                        winreg.CloseKey(k)
                        exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                        if exe and Path(exe).exists():
                            return exe
                    except Exception:
                        pass
        except Exception:
            pass

        # 2. Known Windows standard installation directories
        prog = os.environ.get("PROGRAMFILES", "")
        prog86 = os.environ.get("PROGRAMFILES(X86)", "")
        local = os.environ.get("LOCALAPPDATA", "")

        candidates: dict[str, list[Path]] = {
            "chrome": [
                Path(prog) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(prog86) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ],
            "edge": [
                Path(prog86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(prog) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ],
            "brave": [
                Path(prog) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                Path(local) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
            ],
            "firefox": [
                Path(prog) / "Mozilla Firefox" / "firefox.exe",
                Path(prog86) / "Mozilla Firefox" / "firefox.exe",
            ],
            "opera": [
                Path(local) / "Programs" / "Opera" / "opera.exe",
                Path(local) / "Programs" / "Opera GX" / "opera.exe",
            ],
        }

        for p in candidates.get(name, []):
            if p.exists():
                return str(p)

        return shutil.which(f"{name}.exe") or shutil.which(name)

    elif _OS == "Darwin":
        mac_apps = {
            "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "firefox": "/Applications/Firefox.app/Contents/MacOS/firefox",
            "brave": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        }
        p = mac_apps.get(name)
        if p and Path(p).exists():
            return p
        return shutil.which(name)

    else:  # Linux
        linux_bins = {
            "chrome": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
            "edge": ["microsoft-edge", "microsoft-edge-stable"],
            "firefox": ["firefox"],
            "brave": ["brave-browser", "brave"],
        }
        for b in linux_bins.get(name, [name]):
            found = shutil.which(b)
            if found:
                return found

    return shutil.which(name)


def _open_in_native_browser(url: str, browser_name: str = "chrome") -> str:
    """
    Opens a URL in the native browser.
    If the browser is already running, Chrome's native IPC automatically creates
    a new tab in the currently active window and brings it forward.
    """
    name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip()) if browser_name else "chrome"

    # Bring existing window to focus if already running
    window_focused = False
    try:
        from core.window_tracker import get_window_tracker
        wt = get_window_tracker()
        window_focused = wt.focus_window(name)
    except Exception:
        pass

    exe = _find_browser_exe(name)
    if exe:
        try:
            cmd = [exe, url] if url else [exe]
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            verb = "New tab opened" if window_focused else "Opened"
            return f"{verb} in {name}: {url}" if url else f"Opened {name}."
        except Exception as e:
            print(f"[Browser] Native launch error: {e}")

    # Fallback to system OS opener
    try:
        if _OS == "Windows":
            os.startfile(url)
        elif _OS == "Darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return f"Opened in default browser: {url}"
    except Exception:
        import webbrowser
        if webbrowser.open(url):
            return f"Opened: {url}"
        return f"Could not open browser for: {url}"


def browser_control(
    parameters: Optional[Dict[str, Any]] = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Unified native browser controller for S.P.I.D.Y.
    Executes actions instantaneously using the user's real browser profile without extra windows.
    """
    params = parameters or {}
    action = (params.get("action") or "go_to").lower().strip()
    browser = (params.get("browser") or "chrome").strip()
    raw_url = (params.get("url") or "").strip()
    query = (params.get("query") or "").strip()

    if player and hasattr(player, "write_log"):
        player.write_log(f"[browser] {action} {browser}")

    print(f"[Browser] Action: '{action}' | Browser: '{browser}' | URL: '{raw_url}' | Query: '{query}'")

    # 1. Navigation / Opening URLs or Platforms
    if action in ("go_to", "open", "new_tab", "navigate"):
        target_url = _normalize_url(raw_url, query)
        result = _open_in_native_browser(target_url, browser)
        print(f"[Browser] ✅ {result}")
        return result

    # 2. Search query
    elif action == "search":
        engine = (params.get("engine") or "google").lower()
        base_engine = _SEARCH_ENGINES.get(engine, _SEARCH_ENGINES["google"])
        target_url = base_engine + urllib.parse.quote_plus(query or raw_url)
        result = _open_in_native_browser(target_url, browser)
        print(f"[Browser] ✅ {result}")
        return result

    # 3. Close active tab
    elif action == "close_tab":
        try:
            from core.window_tracker import get_window_tracker
            wt = get_window_tracker()
            wt.focus_window(browser)
            time.sleep(0.1)
            import pyautogui
            pyautogui.hotkey("ctrl", "w")
            return f"Closed active tab in {browser}."
        except Exception as e:
            return f"Could not close tab: {e}"

    # 4. Close browser window
    elif action in ("close", "close_all"):
        try:
            from core.window_tracker import get_window_tracker
            wt = get_window_tracker()
            if wt.close_window(browser):
                return f"Closed {browser}."
            return f"No active window found for {browser}."
        except Exception as e:
            return f"Could not close browser: {e}"

def _switch_to_tab(tab_target: str, browser_name: str = "chrome") -> str:
    """
    Switches to a specific tab in the browser using safe title-inspection and Ctrl+Tab cycling.
    Avoids conflicting global hotkeys (like Ctrl+Shift+A) that trigger screenshot/snipping tools on ASUS and Windows systems.
    """
    from core.window_tracker import get_window_tracker
    wt = get_window_tracker()

    name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip()) if browser_name else "chrome"
    if not wt.focus_window(name):
        return f"{name} is not open."

    time.sleep(0.12)
    clean = tab_target.strip().lower()

    try:
        import pyautogui

        # 1. Numbered tab navigation (e.g. '1', '2', 'first tab', 'second tab')
        num_map = {
            "first": "1", "1st": "1", "one": "1", "1": "1",
            "second": "2", "2nd": "2", "two": "2", "2": "2",
            "third": "3", "3rd": "3", "three": "3", "3": "3",
            "fourth": "4", "4th": "4", "four": "4", "4": "4",
            "fifth": "5", "5th": "5", "five": "5", "5": "5",
            "last": "9",
        }
        num_key = num_map.get(clean.replace("tab", "").strip())
        if num_key:
            pyautogui.hotkey("ctrl", num_key)
            return f"Switched to tab {num_key} in {name}."

        # 2. Next / Previous tab navigation
        if any(w in clean for w in ("next", "forward")):
            pyautogui.hotkey("ctrl", "tab")
            return f"Switched to next tab in {name}."
        if any(w in clean for w in ("previous", "prev", "back")):
            pyautogui.hotkey("ctrl", "shift", "tab")
            return f"Switched to previous tab in {name}."

        # 3. Keyword-based tab switching (e.g. 'github', 'youtube')
        # Strips out filler words like 'tab', 'the', etc.
        keyword = clean.replace("tab", "").replace("the", "").strip()
        if not keyword:
            return f"No target tab name specified for {name}."

        # Check if the currently active tab ALREADY matches
        curr = wt.get_active_window()
        if curr and keyword in curr.title.lower():
            return f"Already on the '{keyword}' tab in {name}."

        start_title = curr.title if curr else ""
        found = False
        visited = set()
        if start_title:
            visited.add(start_title)

        # Safely cycle through open tabs using Ctrl+Tab while inspecting real-time window titles
        for _ in range(16):
            pyautogui.hotkey("ctrl", "tab")
            time.sleep(0.12)
            new_win = wt.get_active_window()
            if not new_win:
                continue

            t_lower = new_win.title.lower()
            if keyword in t_lower:
                found = True
                return f"Switched to '{keyword}' tab in {name}."

            # If we looped back to an already visited tab after seeing other tabs, stop cycling
            if new_win.title in visited and len(visited) > 1:
                break
            visited.add(new_win.title)

        if not found:
            # If the requested tab is not already open, open it cleanly in a new tab!
            target_url = _normalize_url(keyword)
            _open_in_native_browser(target_url, name)
            return f"'{keyword}' was not open, so I opened it in a new tab in {name}."

        return f"Switched to '{keyword}' tab in {name}."

    except Exception as e:
        return f"Could not switch to tab '{tab_target}': {e}"


def browser_control(
    parameters: Optional[Dict[str, Any]] = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Unified native browser controller for S.P.I.D.Y.
    Executes actions instantaneously using the user's real browser profile without extra windows.
    """
    params = parameters or {}
    action = (params.get("action") or "go_to").lower().strip()
    browser = (params.get("browser") or "chrome").strip()
    raw_url = (params.get("url") or "").strip()
    query = (params.get("query") or "").strip()
    tab_target = (params.get("tab") or "").strip()

    if player and hasattr(player, "write_log"):
        player.write_log(f"[browser] {action} {browser}")

    print(f"[Browser] Action: '{action}' | Browser: '{browser}' | URL: '{raw_url}' | Tab: '{tab_target}' | Query: '{query}'")

    # 1. Navigation / Opening URLs or Platforms
    if action in ("go_to", "open", "new_tab", "navigate"):
        target_url = _normalize_url(raw_url, query)
        result = _open_in_native_browser(target_url, browser)
        print(f"[Browser] ✅ {result}")
        return result

    # 2. Search query
    elif action == "search":
        engine = (params.get("engine") or "google").lower()
        base_engine = _SEARCH_ENGINES.get(engine, _SEARCH_ENGINES["google"])
        target_url = base_engine + urllib.parse.quote_plus(query or raw_url)
        result = _open_in_native_browser(target_url, browser)
        print(f"[Browser] ✅ {result}")
        return result

    # 3. Switch to specific Tab or focus Browser
    elif action in ("switch", "switch_tab", "focus"):
        target = tab_target or raw_url or query
        if target and target.lower() not in ("chrome", "browser", "window"):
            result = _switch_to_tab(target, browser)
            print(f"[Browser] ✅ {result}")
            return result
        else:
            try:
                from core.window_tracker import get_window_tracker
                wt = get_window_tracker()
                if wt.focus_window(browser):
                    return f"Switched focus to {browser}."
                return f"{browser} is not currently open."
            except Exception as e:
                return f"Could not focus browser: {e}"

    # 4. Close active tab
    elif action == "close_tab":
        try:
            from core.window_tracker import get_window_tracker
            wt = get_window_tracker()
            wt.focus_window(browser)
            time.sleep(0.1)
            import pyautogui
            pyautogui.hotkey("ctrl", "w")
            return f"Closed active tab in {browser}."
        except Exception as e:
            return f"Could not close tab: {e}"

    # 5. Close browser window
    elif action in ("close", "close_all"):
        try:
            from core.window_tracker import get_window_tracker
            wt = get_window_tracker()
            if wt.close_window(browser):
                return f"Closed {browser}."
            return f"No active window found for {browser}."
        except Exception as e:
            return f"Could not close browser: {e}"

    # 6. Reload page
    elif action == "reload":
        try:
            from core.window_tracker import get_window_tracker
            wt = get_window_tracker()
            wt.focus_window(browser)
            time.sleep(0.1)
            import pyautogui
            pyautogui.press("f5")
            return f"Reloaded page in {browser}."
        except Exception as e:
            return f"Could not reload: {e}"

    else:
        # Default fallback to opening the url
        target_url = _normalize_url(raw_url, query)
        return _open_in_native_browser(target_url, browser)


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "browser_control",
    "description": (
        "Controls web browsers natively in a single window. Use for: opening websites, "
        "opening URLs in a new tab, searching Google, YouTube, GitHub, closing tabs, and "
        "switching between tabs. If Chrome is already open, it automatically creates a NEW TAB "
        "in that same window without shrinking or opening new windows. "
        "To switch to a specific tab, use action='switch_tab' and pass tab='github' or tab='youtube'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "go_to | search | new_tab | switch_tab | close_tab | close | reload"
            },
            "browser": {
                "type": "STRING",
                "description": "Target browser: chrome | edge | firefox | brave | opera (default: chrome)"
            },
            "url": {
                "type": "STRING",
                "description": "URL or website name to open (e.g. 'youtube', 'github', 'https://reddit.com')"
            },
            "tab": {
                "type": "STRING",
                "description": "Tab name or keyword to switch to (e.g. 'github', 'youtube', 'gmail', '1', 'next')"
            },
            "query": {
                "type": "STRING",
                "description": "Search query to automatically pre-fill and search (e.g. 'song name', 'repository name')"
            },
            "engine": {
                "type": "STRING",
                "description": "Search engine: google | youtube | github | bing | duckduckgo (default: google)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": browser_control,
}
