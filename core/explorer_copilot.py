"""
core/explorer_copilot.py
Windows File Explorer Copilot, Semantic File Search, and Autonomous Butler for JARVIS.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Integrates Windows File Explorer (explorer.exe) window awareness, active selected item inspection,
  natural-language content-aware file searching, intelligent folder auto-organization, and AI batch renaming.
- Windows COM Automation via Shell.Application:
  Inspects running Explorer instances, active paths, and user-selected items with clean JSON serialization.
- Fully Reversible with core.undo:
  Folder auto-organization and batch renames push reversal closures onto the JARVIS undo stack,
  allowing the user to say "Jarvis, undo" to instantly restore files to their previous locations.
- Production-ready, loosely coupled, and thread-safe.
"""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from core import gemini
from core.undo import push_undo


# ── Known User Directory Shortcuts ────────────────────────────────────────────
def _get_known_folders() -> Dict[str, Path]:
    home = Path.home()
    workspace = Path(__file__).resolve().parent.parent
    return {
        "desktop": home / "Desktop",
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "pictures": home / "Pictures",
        "photos": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
        "home": home,
        "user": home,
        "workspace": workspace,
        "project": workspace,
        "mark-lv": workspace,
    }


def resolve_folder_path(path_or_alias: Optional[str]) -> Path:
    """Resolves an alias or relative/absolute path to a valid Path object."""
    if not path_or_alias or not str(path_or_alias).strip():
        return Path.home() / "Downloads"

    clean = str(path_or_alias).strip().lower()
    shortcuts = _get_known_folders()
    if clean in shortcuts:
        return shortcuts[clean]

    p = Path(path_or_alias).expanduser()
    if not p.is_absolute():
        p = (Path.home() / p).resolve()
    return p


# ── File Category Classifications for Auto-Organization ───────────────────────
FILE_CATEGORIES = {
    "Documents": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".rtf", ".odt", ".csv", ".tsv"},
    "Images": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp", ".ico", ".tiff", ".raw", ".psd"},
    "Installers": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso"},
    "Code_and_Scripts": {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".sql", ".sh", ".ps1", ".bat", ".cpp", ".c", ".rs", ".go"},
    "Media": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"},
}


class ExplorerCopilot:
    """
    Core engine for Windows File Explorer navigation, active selection inspection,
    semantic search, and autonomous folder organization.
    """

    def __init__(self):
        self._lock = threading.Lock()

    # ── Explorer Window Inspection & Selection (Windows COM) ──────────────────
    def get_open_explorer_windows(self) -> List[str]:
        """Returns directory paths of currently open File Explorer windows."""
        if sys.platform != "win32":
            return []

        ps_script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$paths = @(); "
            "foreach ($w in $shell.Windows()) { "
            "  try { "
            "    if ($w.Document.Folder.Self.Path) { "
            "      $paths += $w.Document.Folder.Self.Path "
            "    } "
            "  } catch {} "
            "}; "
            "ConvertTo-Json -Compress $paths"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            out = res.stdout.strip()
            if not out:
                return []
            data = json.loads(out)
            return [data] if isinstance(data, str) else list(data)
        except Exception as e:
            print(f"[ExplorerCopilot] Error getting windows: {e}")
            return []

    def get_selected_files(self) -> List[str]:
        """Returns paths of items currently selected/highlighted in any open File Explorer window."""
        if sys.platform != "win32":
            return []

        ps_script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$selected = @(); "
            "foreach ($w in $shell.Windows()) { "
            "  try { "
            "    foreach ($item in $w.Document.SelectedItems()) { "
            "      $selected += $item.Path "
            "    } "
            "  } catch {} "
            "}; "
            "ConvertTo-Json -Compress $selected"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            out = res.stdout.strip()
            if not out:
                return []
            data = json.loads(out)
            return [data] if isinstance(data, str) else list(data)
        except Exception as e:
            print(f"[ExplorerCopilot] Error getting selection: {e}")
            return []

    def open_item(self, target: Optional[str] = None, app: Optional[str] = None) -> str:
        """
        Opens a file in its default application on screen (e.g. Notepad, Word, browser)
        or opens a folder in Windows File Explorer.
        If 'app' is specified (e.g. 'anti gravity', 'vscode', 'notepad'), opens the file
        or folder in that user-preferred application.
        """
        if not target or not str(target).strip():
            return "No file or folder specified to open."

        if app and str(app).strip():
            from core.app_opener import AppOpener
            return AppOpener.open_target_in_app(target=target, app_name=str(app).strip())

        clean = str(target).strip()
        shortcuts = _get_known_folders()
        if clean.lower() in shortcuts:
            p = shortcuts[clean.lower()]
        else:
            p = Path(clean).expanduser()
            if not p.is_absolute():
                # Check current directory, Desktop, Downloads, Documents
                for parent in (Path.cwd(), Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents"):
                    if (parent / clean).exists():
                        p = parent / clean
                        break
                if not p.is_absolute():
                    p = (Path.home() / p).resolve()

        if not p.exists():
            # If path does not exist (e.g. LLM hallucinated username like C:\Users\xyz\Desktop\file),
            # check the actual current user's Desktop, Downloads, Documents, and working directory
            filename = p.name
            for common_dir in (Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents", Path.cwd()):
                candidate = common_dir / filename
                if candidate.exists():
                    p = candidate
                    break

        if not p.exists():
            return f"Path does not exist: {target}"

        try:
            if p.is_file():
                if sys.platform == "win32":
                    os.startfile(str(p))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(p)])
                else:
                    subprocess.Popen(["xdg-open", str(p)])
                return f"Opened file '{p.name}' on screen in its default application."
            else:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer.exe", str(p)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(p)])
                else:
                    subprocess.Popen(["xdg-open", str(p)])
                return f"Opened File Explorer at folder: {p.name} ({p})"
        except Exception as e:
            return f"Failed to open '{p.name}': {e}"

    def reveal_in_explorer(self, target: Optional[str] = None) -> str:
        """Opens File Explorer with the specific file or folder highlighted."""
        if not target or not str(target).strip():
            return "No file specified to reveal in File Explorer."
        p = Path(target).expanduser()
        if not p.exists():
            filename = p.name
            for common_dir in (Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents", Path.cwd()):
                candidate = common_dir / filename
                if candidate.exists():
                    p = candidate
                    break

        if not p.exists():
            return f"Path does not exist: {target}"
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", f"/select,{str(p)}"])
                return f"Revealed and selected '{p.name}' in File Explorer."
            else:
                return self.open_item(str(p.parent))
        except Exception as e:
            return f"Failed to reveal '{p.name}': {e}"

    def open_folder(self, target: Optional[str] = None) -> str:
        """Opens or navigates Windows File Explorer to the target folder or shortcut."""
        return self.open_item(target)

    # ── Semantic & Content-Aware File Search ──────────────────────────────────
    def semantic_search(
        self,
        query: str,
        search_root: Optional[str] = None,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Searches files by meaning and content rather than strict filename matches.
        Scans filenames, text files, code, and document extracts.
        """
        if not query or not query.strip():
            return []

        if search_root and str(search_root).strip():
            root_p = resolve_folder_path(search_root)
            roots = [root_p] if root_p.exists() else [Path.home()]
        else:
            roots = [Path.home() / "Desktop", Path.home() / "Downloads", Path.home() / "Documents"]

        ignored_dirs = {
            "node_modules", "venv", ".venv", "env", "__pycache__", ".git", ".idea", ".vscode",
            "appdata", "local settings", "application data", "my games", ".gradle", ".android"
        }

        candidates: List[Dict[str, Any]] = []
        scan_extensions = {".txt", ".py", ".md", ".json", ".csv", ".html", ".js", ".ts", ".log", ".pdf", ".docx"}

        count = 0
        try:
            for root in roots:
                if not root.exists():
                    continue
                root_depth = len(root.parts)
                for dirpath, dirnames, filenames in os.walk(str(root)):
                    # Prune ignored directories to avoid slow recursion
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".") and d.lower() not in ignored_dirs
                    ]
                    # Limit scan depth to 3 levels
                    curr_depth = len(Path(dirpath).parts) - root_depth
                    if curr_depth > 3:
                        dirnames.clear()
                        continue

                    for fname in filenames:
                        if count >= 300:
                            break
                        if fname.startswith("."):
                            continue

                        item = Path(dirpath) / fname
                        count += 1
                        snippet = ""
                        if item.suffix.lower() in scan_extensions:
                            try:
                                snippet = item.read_text(encoding="utf-8", errors="ignore")[:600].strip()
                            except Exception:
                                pass

                        try:
                            fsize = item.stat().st_size
                        except Exception:
                            fsize = 0

                        candidates.append({
                            "name": item.name,
                            "path": str(item),
                            "size": fsize,
                            "snippet": snippet[:200]
                        })

                    if count >= 300:
                        break
        except Exception as e:
            print(f"[ExplorerCopilot] Scan warning: {e}")

        if not candidates:
            return []

        # Local fast heuristic matching first (normalizes space/underscore/hyphen)
        def _norm_s(s: str) -> str:
            return re.sub(r"[\s_\-]+", " ", s.lower()).strip()

        words = [w for w in _norm_s(query).split() if len(w) > 2 and w not in ("file", "files", "folder", "about", "there", "show", "find")]
        ranked_candidates = []
        for c in candidates:
            norm_name = _norm_s(c["name"])
            norm_snip = _norm_s(c["snippet"])
            score = 0
            for w in words:
                if w in norm_name:
                    score += 4
                elif w in norm_snip:
                    score += 2
            if score > 0:
                ranked_candidates.append((score, c))

        ranked_candidates.sort(key=lambda x: x[0], reverse=True)
        top_scored = [item for _, item in ranked_candidates[:max_results]]

        if top_scored:
            return [{"path": item["path"], "reason": f"Matches search keywords ({item['name']})"} for item in top_scored]

        # Use Gemini FAST tier with short timeout if no direct keyword match
        prompt = (
            f"You are JARVIS file assistant. The user wants to find files matching this request:\n"
            f"Query: \"{query}\"\n\n"
            f"Here are candidate files found on the machine:\n"
            + "\n".join(f"- {c['name']} (Path: {c['path']}) | Content excerpt: {c['snippet']}" for c in candidates[:40])
            + f"\n\nReturn the top {max_results} best matches as JSON array of objects with keys: 'path', 'reason'. "
            f"Return ONLY valid JSON."
        )

        try:
            resp = gemini.text(prompt, tier=gemini.FAST, timeout_ms=5_000)
            if resp:
                json_match = re.search(r"\[.*\]", resp, re.DOTALL)
                if json_match:
                    matches = json.loads(json_match.group(0))
                    return matches[:max_results]
        except Exception as e:
            print(f"[ExplorerCopilot] Semantic rank error: {e}")

        return [{"path": c["path"], "reason": "Candidate file"} for c in candidates[:max_results]]

    # ── Autonomous Folder Butler & Auto-Organizer ─────────────────────────────
    def auto_organize_folder(self, target_folder: Optional[str] = None) -> Dict[str, Any]:
        """
        Organizes cluttered folders (Downloads, Desktop, etc.) into clean semantic categories.
        Registers an undo callback on core.undo so the entire operation can be reversed.
        """
        folder = resolve_folder_path(target_folder)
        if not folder.exists() or not folder.is_dir():
            return {"success": False, "message": f"Folder not found: {folder}"}

        files_to_move: List[Tuple[Path, Path]] = []
        for item in folder.iterdir():
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            dest_cat = "Others"
            for cat_name, extensions in FILE_CATEGORIES.items():
                if ext in extensions:
                    dest_cat = cat_name
                    break

            # Destination directory
            cat_dir = folder / dest_cat
            target_path = cat_dir / item.name

            # Avoid overwrite collision
            if target_path.exists():
                stem = item.stem
                target_path = cat_dir / f"{stem}_{int(time.time())}{ext}"

            files_to_move.append((item, target_path))

        if not files_to_move:
            return {"success": True, "message": f"No loose files to organize in {folder.name}.", "moved_count": 0}

        # Perform the move
        moved_records: List[Tuple[Path, Path]] = []
        for src, dst in files_to_move:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved_records.append((src, dst))
            except Exception as e:
                print(f"[ExplorerCopilot] Error moving {src.name}: {e}")

        # Register reverse action on JARVIS undo stack
        def _undo_organize() -> str:
            restored = 0
            for orig_src, moved_dst in moved_records:
                try:
                    if moved_dst.exists():
                        shutil.move(str(moved_dst), str(orig_src))
                        restored += 1
                except Exception:
                    pass
            return f"Restored {restored} files back to {folder.name}/."

        push_undo(f"Organize {folder.name} ({len(moved_records)} files)", _undo_organize)

        summary_msg = f"Organized {len(moved_records)} files in {folder.name} into category folders. (Say 'Jarvis, undo' to revert)."
        return {
            "success": True,
            "message": summary_msg,
            "moved_count": len(moved_records),
            "folder": str(folder),
        }

    # ── AI Batch Renamer ──────────────────────────────────────────────────────
    def smart_rename_files(self, target_folder: Optional[str], instruction: str) -> Dict[str, Any]:
        """
        Renames files in a folder using AI instructions (e.g. 'Format by date', 'Convert to kebab-case').
        Registers an undo callback on core.undo.
        """
        folder = resolve_folder_path(target_folder)
        if not folder.exists() or not folder.is_dir():
            return {"success": False, "message": f"Folder not found: {folder}"}

        items = [f for f in folder.iterdir() if f.is_file()][:30]
        if not items:
            return {"success": False, "message": "No files found to rename."}

        prompt = (
            f"You are an expert file organizer. Given these filenames and user instructions, "
            f"generate clean, standardized new filenames.\n"
            f"Instruction: \"{instruction}\"\n"
            f"Files:\n"
            + "\n".join(f"- {f.name}" for f in items)
            + f"\n\nReturn JSON object mapping old_name to new_name. Keep exact same extensions. Format: {{\"old\": \"new\"}}."
        )

        try:
            resp = gemini.text(prompt, tier=gemini.FAST, timeout_ms=12_000)
            json_match = re.search(r"\{.*\}", resp or "", re.DOTALL)
            if not json_match:
                return {"success": False, "message": "Unable to generate rename pattern."}

            mapping = json.loads(json_match.group(0))
            renamed: List[Tuple[Path, Path]] = []
            for old_name, new_name in mapping.items():
                old_path = folder / old_name
                new_path = folder / new_name
                if old_path.exists() and old_name != new_name and not new_path.exists():
                    old_path.rename(new_path)
                    renamed.append((old_path, new_path))

            # Push undo
            def _undo_rename() -> str:
                cnt = 0
                for orig_p, new_p in renamed:
                    try:
                        if new_p.exists():
                            new_p.rename(orig_p)
                            cnt += 1
                    except Exception:
                        pass
                return f"Reverted {cnt} file names in {folder.name}."

            push_undo(f"Rename {len(renamed)} files in {folder.name}", _undo_rename)
            return {"success": True, "renamed_count": len(renamed), "message": f"Renamed {len(renamed)} file(s) in {folder.name}."}
        except Exception as e:
            return {"success": False, "message": f"Rename error: {e}"}

    # ── Instant File Summarizer ───────────────────────────────────────────────
    def summarize_file(self, file_path: Optional[str] = None) -> str:
        """
        Summarizes a file's contents without needing external apps.
        If file_path is omitted, uses the currently selected item in File Explorer.
        """
        target = file_path
        if not target:
            selected = self.get_selected_files()
            if selected:
                target = selected[0]

        if not target or not Path(target).exists():
            return "No file selected or specified to summarize."

        p = Path(target)
        if not p.is_file():
            return f"'{p.name}' is a directory, not a document."

        # Read snippet
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")[:4000]
        except Exception:
            return f"Cannot read content of '{p.name}' directly."

        prompt = (
            f"You are JARVIS. Summarize this file concisely in 2-3 clear bullet points:\n"
            f"Filename: {p.name}\n"
            f"Size: {p.stat().st_size} bytes\n\n"
            f"```\n{content}\n```"
        )
        try:
            resp = gemini.text(prompt, tier=gemini.FAST, timeout_ms=10_000)
            return resp.strip() if resp else f"File '{p.name}' contains {len(content)} characters of data."
        except Exception as e:
            return f"Failed to summarize file: {e}"


# ── Global Singleton Accessor ─────────────────────────────────────────────────
_EXPLORER_COPILOT_INSTANCE: Optional[ExplorerCopilot] = None
_EXPLORER_LOCK = threading.Lock()

def get_explorer_copilot() -> ExplorerCopilot:
    """Dependency injection / singleton accessor for ExplorerCopilot."""
    global _EXPLORER_COPILOT_INSTANCE
    if _EXPLORER_COPILOT_INSTANCE is None:
        with _EXPLORER_LOCK:
            if _EXPLORER_COPILOT_INSTANCE is None:
                _EXPLORER_COPILOT_INSTANCE = ExplorerCopilot()
    return _EXPLORER_COPILOT_INSTANCE
