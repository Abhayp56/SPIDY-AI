"""
scripts/pair_whatsapp.py
Fast, Browserless WhatsApp Pairing Tool for S.P.I.D.Y. using Protocol Linked Device Bridge.

Usage:
    python scripts/pair_whatsapp.py

Features:
- Instant QR Code scanning (in terminal or auto-opened browser page).
- Optional phone number pairing code (enter 8-digit code directly in WhatsApp on your phone).
- Permanently saves credentials to data/whatsapp_baileys_auth without any Chromium overhead.
"""

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
BRIDGE_DIR = BASE_DIR / "core" / "whatsapp_bridge"
AUTH_DIR = BASE_DIR / "data" / "whatsapp_baileys_auth"
PORT = int(os.environ.get("WHATSAPP_BRIDGE_PORT", "48888"))
URL = f"http://127.0.0.1:{PORT}"


def ensure_bridge_running():
    try:
        r = requests.get(f"{URL}/status", timeout=1.5)
        if r.status_code == 200:
            return None
    except Exception:
        pass

    print("[+] Launching WhatsApp protocol bridge server...")
    server_js = BRIDGE_DIR / "server.js"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        ["node", str(server_js)],
        cwd=str(BRIDGE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags
    )
    time.sleep(2.0)
    return proc


def pair():
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 65)
    print("  S.P.I.D.Y. WhatsApp Protocol Pairing Tool")
    print(f"  Storage Directory: {AUTH_DIR}")
    print("=" * 65)

    proc = ensure_bridge_running()

    # Wait for bridge to be responsive
    for _ in range(15):
        try:
            r = requests.get(f"{URL}/status", timeout=1.5)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.5)

    try:
        r = requests.get(f"{URL}/status", timeout=2.0)
        status_data = r.json()
    except Exception as e:
        print(f"[-] Could not connect to WhatsApp bridge: {e}")
        return

    if status_data.get("authenticated"):
        print("\n[+] SUCCESS: WhatsApp is ALREADY paired and connected!")
        user = status_data.get("user", {})
        if user:
            print(f"    Account ID: {user.get('id', 'Unknown')}")
        print("    S.P.I.D.Y. is ready to read and send messages in the background.")
        print("=" * 65)
        return

    print("\n[*] WhatsApp is not currently paired.")
    print("    Opening QR code pairing screen in your browser...")
    webbrowser.open(f"{URL}/qr")

    print("\n[+] Instructions to pair:")
    print("    1. Open WhatsApp on your phone.")
    print("    2. Tap Settings (iOS) or 3 Dots (Android) > Linked Devices.")
    print("    3. Tap 'Link a Device' and point your camera at the QR code in your browser.")
    print(f"    (If browser didn't open, visit: {URL}/qr)")
    print("\n[*] Waiting for phone authorization (timeout: 120s)...")

    start_time = time.time()
    paired = False

    while time.time() - start_time < 120:
        try:
            res = requests.get(f"{URL}/status", timeout=2.0)
            if res.status_code == 200:
                data = res.json()
                if data.get("authenticated"):
                    paired = True
                    break
        except Exception:
            pass
        time.sleep(1.5)

    if paired:
        print("\n" + "=" * 65)
        print("  🎉 SUCCESS: WhatsApp authenticated successfully!")
        print(f"  Session credentials saved permanently in: {AUTH_DIR}")
        print("  S.P.I.D.Y. can now read chats and send messages with 0 browser load.")
        print("=" * 65)
    else:
        print("\n[-] Pairing timed out. Please run the script again and scan promptly.")


if __name__ == "__main__":
    pair()
