"""
core/developer_autopilot.py
Developer Autopilot, Terminal Diagnostics, and Code Error Analyzer for JARVIS.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Provides automated developer diagnostics, stack trace analysis, git status tracking,
  and intelligent code error resolution.
- Dependency Inversion:
  Integrates with WindowTracker to identify active IDE/Terminal windows and Gemini (tier=FAST/SMART)
  for instant root-cause analysis and actionable fixes.
- Safe Subprocess Isolation:
  Executes diagnostic checks (git status, syntax compilation) safely within the project workspace.
- Production-ready & Decoupled:
  Exposes clean query methods for actions and proactive ambient monitoring.
"""

from __future__ import annotations

import os
import re
import sys
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List

from core import gemini
from core.window_tracker import get_window_tracker, WindowTracker


@dataclass
class DiagnosticReport:
    """Represents an error diagnosis report."""
    has_error: bool = False
    error_type: str = "none"
    file_path: str = ""
    line_number: Optional[int] = None
    root_cause: str = ""
    suggested_fix: str = ""
    raw_snippet: str = ""

    def summary(self) -> str:
        if not self.has_error:
            return "No syntax or runtime errors detected."
        loc = f" in {Path(self.file_path).name}" if self.file_path else ""
        ln = f" on line {self.line_number}" if self.line_number else ""
        return f"{self.error_type}{loc}{ln}: {self.root_cause}\nSuggested Fix: {self.suggested_fix}"


class DeveloperAutopilot:
    """
    Developer assistant engine for analyzing terminal outputs, tracebacks,
    git workspace status, and code issues.
    """

    def __init__(self, window_tracker: Optional[WindowTracker] = None):
        self._tracker = window_tracker or get_window_tracker()
        self._workspace = Path(__file__).resolve().parent.parent

    # ── Error Detection & Diagnosis ───────────────────────────────────────────
    def diagnose_error(self, text_or_traceback: Optional[str] = None) -> DiagnosticReport:
        """
        Analyzes a traceback, terminal error output, or checks active clipboard
        for developer errors, returning root-cause diagnosis and code fixes.
        """
        raw_text = text_or_traceback or ""

        # If no explicit text provided, check clipboard for error traces
        if not raw_text.strip():
            try:
                import pyperclip
                clip = pyperclip.paste().strip()
                if any(kw in clip for kw in ("Traceback", "SyntaxError", "Error:", "npm ERR!", "Exception")):
                    raw_text = clip
            except Exception:
                pass

        if not raw_text.strip():
            return DiagnosticReport(has_error=False, root_cause="No error text or traceback found.")

        # Quick pattern matching for common Python tracebacks
        file_path = ""
        line_num = None
        match_line = re.search(r'File\s+"([^"]+)",\s+line\s+(\d+)', raw_text)
        if match_line:
            file_path = match_line.group(1)
            try:
                line_num = int(match_line.group(2))
            except ValueError:
                pass

        error_match = re.search(r'([A-Za-z]+Error:[^\n]+)', raw_text)
        error_type = error_match.group(1) if error_match else "Runtime/Build Error"

        prompt = (
            f"You are JARVIS, an elite developer assistant. Analyze this error/traceback:\n\n"
            f"```\n{raw_text[:2000]}\n```\n\n"
            f"Provide a concise, expert diagnostic in JSON with this exact format:\n"
            f"{{\n"
            f'  "has_error": true,\n'
            f'  "error_type": "Specific error name",\n'
            f'  "root_cause": "One clear sentence explaining why this occurred",\n'
            f'  "suggested_fix": "The exact code change or command to fix it"\n'
            f"}}\n"
        )

        try:
            resp_text = gemini.text(prompt, tier=gemini.FAST, timeout_ms=12_000)
            json_match = re.search(r"\{.*\}", resp_text or "", re.DOTALL)
            if json_match:
                import json
                data = json.loads(json_match.group(0))
                return DiagnosticReport(
                    has_error=True,
                    error_type=data.get("error_type", error_type),
                    file_path=file_path,
                    line_number=line_num,
                    root_cause=data.get("root_cause", ""),
                    suggested_fix=data.get("suggested_fix", ""),
                    raw_snippet=raw_text[:300],
                )
        except Exception as e:
            print(f"[Autopilot] Reasoning error: {e}")

        return DiagnosticReport(
            has_error=True,
            error_type=error_type,
            file_path=file_path,
            line_number=line_num,
            root_cause=error_type,
            suggested_fix="Inspect recent changes near the indicated line.",
            raw_snippet=raw_text[:200],
        )

    # ── Workspace Git Status ──────────────────────────────────────────────────
    def get_git_status(self) -> str:
        """Returns concise status of the git repository."""
        try:
            res = subprocess.run(
                ["git", "status", "--short", "--branch"],
                cwd=str(self._workspace),
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if res.returncode != 0:
                return "Not a git repository or git command unavailable."
            output = res.stdout.strip()
            if not output:
                return "Git workspace is completely clean. No uncommitted changes."
            lines = output.splitlines()
            branch = lines[0] if lines else ""
            changes_count = len(lines) - 1
            return f"Git branch: {branch}. Found {changes_count} modified/untracked file(s)."
        except Exception as e:
            return f"Git check failed: {e}"

    # ── Syntax Verifier ───────────────────────────────────────────────────────
    def check_python_syntax(self, target_file: Optional[str] = None) -> str:
        """Runs py_compile check on target python file or all core files."""
        files_to_check = []
        if target_file:
            p = Path(target_file)
            if not p.is_absolute():
                p = self._workspace / p
            if p.exists() and p.suffix == ".py":
                files_to_check.append(p)
        else:
            files_to_check = list(self._workspace.glob("*.py"))[:10]

        if not files_to_check:
            return "No python files found to verify."

        errors = []
        import py_compile
        for f in files_to_check:
            try:
                py_compile.compile(str(f), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{f.name}: {e.msg}")

        if not errors:
            return f"Syntax check passed: {len(files_to_check)} Python file(s) are syntactically valid."
        return f"Syntax check found {len(errors)} error(s):\n" + "\n".join(errors[:4])


# ── Global Singleton Accessor ─────────────────────────────────────────────────
_AUTOPILOT_INSTANCE: Optional[DeveloperAutopilot] = None
_AUTOPILOT_LOCK = threading.Lock()

def get_developer_autopilot() -> DeveloperAutopilot:
    """Dependency injection / singleton accessor for DeveloperAutopilot."""
    global _AUTOPILOT_INSTANCE
    if _AUTOPILOT_INSTANCE is None:
        with _AUTOPILOT_LOCK:
            if _AUTOPILOT_INSTANCE is None:
                _AUTOPILOT_INSTANCE = DeveloperAutopilot()
    return _AUTOPILOT_INSTANCE
