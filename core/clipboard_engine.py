"""
core/clipboard_engine.py
Semantic Clipboard Engine and Smart History for JARVIS.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Manages semantic clipboard capture, automatic history indexing, content classification,
  and AI-assisted formatting and code fixing.
- Low-Overhead Background Daemon:
  Monitors OS clipboard changes unobtrusively in a dedicated thread without locking UI.
- Intelligent Classification:
  Automatically categorizes clipboard content as 'code', 'stack_trace', 'json', 'url',
  'file_path', 'command', or 'text'.
- Integration with Gemini:
  Provides instant semantic explanation and code/error auto-repair via Gemini FAST tier.
- Production-ready & Thread-Safe:
  Protected with threading locks and bounded collections (ring buffer).
"""

from __future__ import annotations

import collections
import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

try:
    import pyperclip
    _HAS_PYPERCLIP = True
except ImportError:
    _HAS_PYPERCLIP = False

from core import gemini


@dataclass
class ClipboardItem:
    """Represents an entry in the smart clipboard history."""
    content: str
    category: str  # code, stack_trace, json, url, file_path, command, text
    timestamp: float = field(default_factory=time.time)
    char_count: int = 0
    lines_count: int = 0
    preview: str = ""

    def __post_init__(self):
        self.char_count = len(self.content)
        self.lines_count = len(self.content.splitlines())
        first_line = self.content.strip().splitlines()[0] if self.content.strip() else ""
        self.preview = (first_line[:60] + "...") if len(first_line) > 60 else first_line

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "preview": self.preview,
            "char_count": self.char_count,
            "lines_count": self.lines_count,
            "timestamp": datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S"),
            "content": self.content[:300] + ("..." if len(self.content) > 300 else ""),
        }


class ClipboardEngine:
    """
    Semantic clipboard manager tracking recent items and providing
    formatting, analysis, and AI fixes.
    """

    def __init__(self, max_history: int = 30):
        self._history: collections.deque[ClipboardItem] = collections.deque(maxlen=max_history)
        self._lock = threading.Lock()
        self._last_raw: str = ""
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None

        # Seed initial content if available
        self._poll_clipboard()
        self.start_monitoring()

    # ── Content Classifier ────────────────────────────────────────────────────
    @staticmethod
    def classify_content(text: str) -> str:
        """Determines the semantic nature of clipboard text."""
        raw = text.strip()
        if not raw:
            return "empty"

        # Check for URLs
        if re.match(r"^https?://[^\s]+$", raw):
            return "url"

        # Check for Tracebacks & Error Logs
        if (
            "Traceback (most recent call last)" in raw
            or re.search(r"\b(Error|Exception|ERR!):\s", raw)
            or ("File \"" in raw and ", line " in raw)
        ):
            return "stack_trace"

        # Check for JSON
        if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith("[") and raw.endswith("]")):
            try:
                json.loads(raw)
                return "json"
            except Exception:
                pass

        # Check for File Paths
        if re.match(r"^([a-zA-Z]:\\|\/)[^\n\r*?\"<>|]+$", raw) and ("\\" in raw or "/" in raw):
            return "file_path"

        # Check for Shell / Terminal Commands
        if re.match(r"^(git|npm|pip|python|docker|curl|pnpm|cargo|go|dotnet)\s+", raw):
            return "command"

        # Check for Code
        code_indicators = [
            r"\bdef\s+[a-zA-Z0-9_]+\s*\(",
            r"\bclass\s+[a-zA-Z0-9_]+",
            r"\bimport\s+[a-zA-Z0-9_]+",
            r"\bfrom\s+[a-zA-Z0-9_]+\s+import",
            r"\bfunction\s+[a-zA-Z0-9_]*\s*\(",
            r"\bconst\s+[a-zA-Z0-9_]+\s*=",
            r"\blet\s+[a-zA-Z0-9_]+\s*=",
            r"\bconsole\.log\(",
            r"\bprint\(",
            r"[{};]\s*$",
        ]
        if any(re.search(pat, raw, re.MULTILINE) for pat in code_indicators):
            return "code"

        return "text"

    # ── Clipboard Polling & History Tracking ──────────────────────────────────
    def _poll_clipboard(self) -> Optional[ClipboardItem]:
        """Polls the OS clipboard and logs newly copied items."""
        if not _HAS_PYPERCLIP:
            return None
        try:
            current = pyperclip.paste()
            if not current or current == self._last_raw:
                return None

            self._last_raw = current
            cat = self.classify_content(current)
            item = ClipboardItem(content=current, category=cat)

            with self._lock:
                # Avoid adjacent duplicate items in history
                if not self._history or self._history[0].content != current:
                    self._history.appendleft(item)
            return item
        except Exception:
            return None

    def start_monitoring(self) -> None:
        """Starts background daemon thread monitoring OS clipboard."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="JARVIS-ClipboardMonitor"
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Lightweight loop running every 1.5 seconds."""
        while not self._stop_event.is_set():
            try:
                self._poll_clipboard()
            except Exception:
                pass
            time.sleep(1.5)

    def stop_monitoring(self) -> None:
        """Stops background monitor."""
        self._stop_event.set()

    # ── Clipboard Query & Operations ──────────────────────────────────────────
    def get_current(self) -> Optional[ClipboardItem]:
        """Returns the most recent clipboard item, checking OS clipboard directly if needed."""
        self._poll_clipboard()
        with self._lock:
            if self._history:
                return self._history[0]
        # Direct fallback to OS clipboard
        if _HAS_PYPERCLIP:
            for _ in range(3):
                try:
                    raw = pyperclip.paste()
                    if raw:
                        cat = self.classify_content(raw)
                        item = ClipboardItem(content=raw, category=cat)
                        with self._lock:
                            self._history.appendleft(item)
                        return item
                    break
                except Exception:
                    time.sleep(0.05)
        return None

    def get_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Returns recent clipboard history metadata."""
        self._poll_clipboard()
        with self._lock:
            items = list(self._history)[:limit]
        return [it.to_dict() for it in items]

    def set_content(self, text: str) -> bool:
        """Writes text into OS clipboard with retries and records in history."""
        if not _HAS_PYPERCLIP:
            return False
        for attempt in range(4):
            try:
                pyperclip.copy(text)
                # Verify copy succeeded
                readback = pyperclip.paste()
                if readback == text:
                    self._last_raw = text
                    cat = self.classify_content(text)
                    item = ClipboardItem(content=text, category=cat)
                    with self._lock:
                        self._history.appendleft(item)
                    return True
            except Exception as e:
                time.sleep(0.08)
        print("[Clipboard] Warning: Failed to set clipboard after retries.")
        return False

    # ── AI Formatting & Semantic Operations ───────────────────────────────────
    def format_json(self) -> Tuple[bool, str]:
        """Prettifies copied JSON text and copies it back to the clipboard."""
        current = self.get_current()
        if not current or not current.content.strip():
            return False, "Clipboard is empty."

        try:
            parsed = json.loads(current.content.strip())
            formatted = json.dumps(parsed, indent=2)
            self.set_content(formatted)
            return True, f"Prettified JSON ({len(formatted)} characters) copied to clipboard."
        except Exception as e:
            return False, f"Copied content is not valid JSON: {e}"

    def explain_content(self) -> str:
        """Uses Gemini to explain what is currently in the clipboard."""
        current = self.get_current()
        if not current or not current.content.strip():
            return "The clipboard is currently empty."

        prompt = (
            f"You are JARVIS. Explain concisely what is in the user's clipboard.\n"
            f"Content Category: {current.category}\n"
            f"Length: {current.char_count} chars, {current.lines_count} lines\n\n"
            f"```\n{current.content[:2500]}\n```\n\n"
            f"Provide a clear, 2-sentence explanation of what this is and what it does."
        )

        try:
            resp = gemini.text(prompt, tier=gemini.FAST, timeout_ms=10_000)
            return resp.strip() if resp else f"Clipboard contains {current.category}: {current.preview}"
        except Exception as e:
            return f"Clipboard contains {current.category} ({current.lines_count} lines): {current.preview}"

    def fix_code_or_error(self) -> Tuple[bool, str]:
        """
        Analyzes copied error or code, produces a fix, and writes the fixed
        code/command directly to the clipboard.
        """
        current = self.get_current()
        if not current or not current.content.strip():
            return False, "Clipboard is empty. Please copy the code or error first."

        prompt = (
            f"You are JARVIS, an expert senior software engineer. The user copied this code or error traceback:\n\n"
            f"```\n{current.content[:4000]}\n```\n\n"
            f"Tasks:\n"
            f"1. Identify the bug, syntax issue, or root cause.\n"
            f"2. Provide the complete, working, fixed code snippet (or fix command).\n\n"
            f"Format your response as:\n"
            f"DIAGNOSIS: <1-2 concise sentences explaining what was wrong>\n"
            f"FIX:\n"
            f"```\n<complete fixed code here>\n```"
        )

        try:
            resp = gemini.text(prompt, tier=gemini.FAST, timeout_ms=16_000)
            if not resp:
                return False, "Unable to generate fix for clipboard content."

            # Robust code block extraction across CRLF and LF line endings
            fixed_code = ""
            matches = re.findall(r"```(?:[a-zA-Z0-9_\-\+]+)?[\r\n]+(.*?)[\r\n]*```", resp, re.DOTALL)
            if matches:
                fixed_code = max(matches, key=len).strip()
            else:
                # Fallback: if no backtick block, extract stripped response
                lines = [l for l in resp.strip().splitlines() if not l.strip().startswith("```")]
                fixed_code = "\n".join(lines).strip()

            if fixed_code:
                copied = self.set_content(fixed_code)
                if not copied:
                    return False, "Failed to write fixed code into Windows clipboard."

                # Extract diagnosis explanation if present
                diag = ""
                diag_match = re.search(r"DIAGNOSIS:\s*([^\r\n]+)", resp, re.IGNORECASE)
                if diag_match:
                    diag = diag_match.group(1).strip()
                elif "```" in resp:
                    diag = resp.split("```")[0].strip()

                msg = f"Fixed code copied to clipboard! {diag}".strip()
                return True, msg

            return False, "Could not extract fixed code from AI response."
        except Exception as e:
            return False, f"Failed to analyze clipboard content: {e}"


# ── Global Singleton Accessor ─────────────────────────────────────────────────
_CLIPBOARD_INSTANCE: Optional[ClipboardEngine] = None
_CLIPBOARD_LOCK = threading.Lock()

def get_clipboard_engine() -> ClipboardEngine:
    """Dependency injection / singleton accessor for ClipboardEngine."""
    global _CLIPBOARD_INSTANCE
    if _CLIPBOARD_INSTANCE is None:
        with _CLIPBOARD_LOCK:
            if _CLIPBOARD_INSTANCE is None:
                _CLIPBOARD_INSTANCE = ClipboardEngine()
    return _CLIPBOARD_INSTANCE
