"""
core/whatsapp_client.py
Protocol-Level WhatsApp Linked Device Engine for S.P.I.D.Y.

Architecture & Design Decisions:
- Replaces heavy, brittle Playwright headless browser scraping with a high-performance
  protocol-level Linked Device bridge (@whiskeysockets/baileys) running via Node.js.
- ZERO Chromium / Puppeteer dependencies:
  - Connects directly to WhatsApp WebSocket servers.
  - Consumes ~30-50 MB RAM instead of 400-600 MB Chrome.
  - 100% deterministic incoming vs. outgoing detection (fromMe flag directly from protocol).
- Backward Compatibility:
  - Preserves the existing singleton WhatsAppClient interface and get_whatsapp_client()
    so actions/whatsapp_headless.py and ui.py work without breaking changes.
- Self-Healing Background Daemon:
  - Spawns and manages the local Node.js bridge server on port 48888.
  - Automatic reconnection and health polling.
  - Non-blocking background event listener for proactive voice alerts.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import requests

logger = logging.getLogger("SPIDY.WhatsApp")

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BRIDGE_DIR = _base_dir() / "core" / "whatsapp_bridge"
_AUTH_DIR = _base_dir() / "data" / "whatsapp_baileys_auth"
_BRIDGE_PORT = int(os.environ.get("WHATSAPP_BRIDGE_PORT", "48888"))
_BRIDGE_URL = f"http://127.0.0.1:{_BRIDGE_PORT}"


class WhatsAppClient:
    """
    Singleton client managing the Baileys protocol-level WhatsApp bridge.
    """
    _instance: Optional[WhatsAppClient] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> WhatsAppClient:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._is_ready = False
        self._is_logged_in = False
        self._stop_event = threading.Event()
        self._unread_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._last_active_contact: Optional[str] = None
        self._lock_state = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None

        # Start Node Bridge and Background Polling
        self._start_bridge_daemon()
        atexit.register(self.shutdown)

    def _start_bridge_daemon(self) -> None:
        """Launches the Node.js Baileys bridge process and starts event polling."""
        server_js = _BRIDGE_DIR / "server.js"
        if not server_js.exists():
            logger.error(f"WhatsApp bridge script not found at: {server_js}")
            return

        # Check if already running on port
        if self._check_health():
            logger.info(f"[WhatsApp] Existing bridge server detected on port {_BRIDGE_PORT}.")
        else:
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                self._proc = subprocess.Popen(
                    ["node", str(server_js)],
                    cwd=str(_BRIDGE_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
                logger.info(f"[WhatsApp] Launched Node.js bridge daemon (PID: {self._proc.pid})")
            except Exception as e:
                logger.error(f"[WhatsApp] Failed to launch Node.js bridge: {e}")

        # Start background event consumer
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="WhatsAppEventPoll")
        self._poll_thread.start()

    def _check_health(self) -> bool:
        """Pings the bridge server status endpoint."""
        try:
            r = requests.get(f"{_BRIDGE_URL}/status", timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                with self._lock_state:
                    self._is_ready = True
                    self._is_logged_in = bool(data.get("authenticated"))
                return True
        except Exception:
            pass
        return False

    def _poll_loop(self) -> None:
        """Background thread polling the local bridge for events and status."""
        while not self._stop_event.is_set():
            try:
                # 1. Update status
                if self._check_health():
                    # 2. Drain incoming events
                    r = requests.get(f"{_BRIDGE_URL}/events", timeout=2.0)
                    if r.status_code == 200:
                        events = r.json().get("events", [])
                        for ev in events:
                            if ev.get("event") == "new_message":
                                self._handle_incoming_message(ev)
                else:
                    with self._lock_state:
                        self._is_ready = False
                        self._is_logged_in = False

                    # If process died, restart it
                    if self._proc and self._proc.poll() is not None:
                        logger.warning("[WhatsApp] Bridge process stopped. Restarting...")
                        self._start_bridge_daemon()
            except Exception as e:
                pass

            time.sleep(1.0)

    def _handle_incoming_message(self, ev: Dict[str, Any]) -> None:
        """Dispatches an incoming message event to the proactive listener."""
        contact = ev.get("contact", "Unknown")
        text = ev.get("text", "")
        msg_type = ev.get("msg_type", "message")
        msg_time = ev.get("timestamp", 0)

        # Discard historical or stale catch-up messages (older than 60s) from voice alerts
        if msg_time:
            now_ms = time.time() * 1000
            age_sec = (now_ms - msg_time) / 1000.0
            if age_sec > 60:
                logger.info(
                    f"[WhatsApp] Ignored stale catch-up message from {contact} "
                    f"(age: {int(age_sec)}s) - will not alert proactively."
                )
                return

        with self._lock_state:
            last = self._last_active_contact or ""
            is_follow_up = bool(last and last.lower() in contact.lower())

        payload = {
            "contact": contact,
            "unread": "1",
            "msg_type": msg_type,
            "snippet": text,
            "is_follow_up": is_follow_up
        }

        if self._unread_callback:
            try:
                self._unread_callback(payload)
            except Exception as e:
                logger.error(f"[WhatsApp] Callback exception: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def wait_until_ready(self, timeout: float = 12.0) -> bool:
        start = time.time()
        creds_file = _AUTH_DIR / "creds.json"
        while time.time() - start < timeout:
            with self._lock_state:
                if self._is_ready:
                    if not creds_file.exists() or self._is_logged_in:
                        return True
            time.sleep(0.2)
        return False

    def is_logged_in(self) -> bool:
        with self._lock_state:
            return self._is_logged_in

    def get_status(self) -> Dict[str, Any]:
        with self._lock_state:
            return {
                "ready": self._is_ready,
                "logged_in": self._is_logged_in,
                "bridge_url": _BRIDGE_URL,
                "auth_dir": str(_AUTH_DIR)
            }

    def get_unread_messages(self, timeout: float = 10.0, direct_only: bool = False) -> List[Dict[str, Any]]:
        """Returns list of chats with unread messages."""
        try:
            params = {}
            if direct_only:
                params["direct_only"] = "true"
            r = requests.get(f"{_BRIDGE_URL}/unread", params=params, timeout=timeout)
            if r.status_code == 200:
                unreads = r.json().get("unread", [])
                return [
                    {
                        "contact": u.get("contact", "Unknown"),
                        "unread": str(u.get("count", 1)),
                        "jid": u.get("jid", ""),
                        "is_group": bool(u.get("is_group", False)),
                        "last_message": u.get("last_message", ""),
                    }
                    for u in unreads
                ]
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to fetch unread messages: {e}")
        return []

    def search_contacts(self, query: str, limit: int = 10, timeout: float = 10.0) -> List[Dict[str, Any]]:
        """Searches saved WhatsApp contacts using fuzzy name and phone matching."""
        try:
            r = requests.get(
                f"{_BRIDGE_URL}/search_contacts",
                params={"query": query, "limit": limit},
                timeout=timeout
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("contacts", [])
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to search contacts: {e}")
        return []

    def get_contacts(self, limit: int = 50, timeout: float = 10.0) -> List[Dict[str, Any]]:
        """Returns list of all saved WhatsApp contacts."""
        try:
            r = requests.get(
                f"{_BRIDGE_URL}/contacts",
                params={"limit": limit},
                timeout=timeout
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("contacts", [])
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to fetch contacts list: {e}")
        return []

    def read_chat(self, contact: str, max_messages: int = 10, timeout: float = 15.0) -> Dict[str, Any]:
        """Reads recent messages with a contact using the protocol message store."""
        try:
            r = requests.get(
                f"{_BRIDGE_URL}/chat",
                params={"contact": contact, "limit": max_messages},
                timeout=timeout
            )
            data = r.json()
            if r.status_code == 200 and data.get("success"):
                resolved_contact = data.get("contact", contact)
                self.set_last_active_contact(resolved_contact)
                return {
                    "success": True,
                    "contact": resolved_contact,
                    "messages": data.get("messages", [])
                }
            return {
                "success": False,
                "error": data.get("error", "Failed to retrieve conversation history.")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_message(self, contact: str, text: str, timeout: float = 15.0) -> Dict[str, Any]:
        """Sends a text message directly through the WhatsApp protocol bridge."""
        try:
            r = requests.post(
                f"{_BRIDGE_URL}/send",
                json={"contact": contact, "message": text},
                timeout=timeout
            )
            data = r.json()
            if r.status_code == 200 and data.get("success"):
                resolved_contact = data.get("contact", contact)
                self.set_last_active_contact(resolved_contact)
                return {
                    "success": True,
                    "contact": resolved_contact,
                    "message": text
                }
            return {
                "success": False,
                "error": data.get("error", "Failed to send message.")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_last_active_contact(self) -> Optional[str]:
        with self._lock_state:
            return self._last_active_contact

    def set_last_active_contact(self, contact: str) -> None:
        with self._lock_state:
            if contact and str(contact).strip():
                clean = str(contact).strip()
                if clean.lower() not in ("last", "him", "her", "them", "recent", "someone", "unknown"):
                    self._last_active_contact = clean

    def set_unread_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._unread_callback = callback

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


def get_whatsapp_client() -> WhatsAppClient:
    return WhatsAppClient.get_instance()
