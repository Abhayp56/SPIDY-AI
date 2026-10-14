"""
S.P.I.D.Y. AI — Setup Script.

Installs the Python dependencies for THIS operating system: the OS-specific
packages in requirements.txt carry `sys_platform` markers, so a macOS or Linux
user never pulls Windows-only libraries (and vice-versa). Then it fetches the
Playwright browsers needed for web automation (current-OS builds only).
"""
import platform
import subprocess
import sys
from pathlib import Path

OS = platform.system()  # "Windows" | "Darwin" | "Linux"
HERE = Path(__file__).resolve().parent

MIN_PY = (3, 10)        # Supports Python 3.10+
MAX_PY = (3, 13)


def _run(label: str, args: list[str]) -> None:
    print(f"\n▶ {label}")
    subprocess.run(args, check=True)


def _check_python() -> None:
    """Fail immediately and clearly rather than deep inside a pip resolver."""
    v = sys.version_info[:2]
    if v > MAX_PY:
        print(f"\n⚠️  Python {v[0]}.{v[1]} is newer than the "
              f"{MAX_PY[0]}.{MAX_PY[1]} tested. Continuing...")
        return
    if v < MIN_PY:
        print(f"\n❌ Python {v[0]}.{v[1]} detected — S.P.I.D.Y. AI needs at "
              f"least Python {MIN_PY[0]}.{MIN_PY[1]}.")
        print("   Install a supported version and run setup with it, e.g.:")
        print(f"     py -{MIN_PY[0]}.{MIN_PY[1]} setup.py        (Windows)")
        print(f"     python{MIN_PY[0]}.{MIN_PY[1]} setup.py      (macOS / Linux)")
        sys.exit(1)


def _check_assets() -> None:
    pass


def main() -> None:
    print(f"⚙  S.P.I.D.Y. AI setup — detected OS: {OS or 'unknown'}, "
          f"Python {sys.version_info[0]}.{sys.version_info[1]}")
    _check_python()

    # requirements.txt filters OS-specific extras by itself via pip markers.
    _run("Installing Python dependencies (OS-specific extras auto-filtered)…",
         [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    # Chromium covers Chrome/Edge/Opera/Brave/Vivaldi; Firefox for Firefox.
    # (Safari automation additionally needs: python -m playwright install webkit)
    # Not fatal: these are a few hundred megabytes from a CDN that a corporate
    # network or a flaky connection can refuse, and everything except browser
    # automation works without them. Failing the whole install there would send
    # a user away from a working app.
    try:
        _run("Installing Playwright browsers (chromium + firefox)…",
             [sys.executable, "-m", "playwright", "install", "chromium", "firefox"])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"\n⚠️  Playwright browsers were not installed ({e}).")
        print("    Everything except browser automation works. Retry later with:")
        print(f'    {sys.executable} -m playwright install chromium firefox')

    _check_assets()

    # ── OS-specific post-install notes ────────────────────────────────────────
    if OS == "Windows":
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            postinstall = Path(sys.executable).parent / "Scripts" / "pywin32_postinstall.py"
            print(
                "\n⚠️  pywin32 did not register correctly — desktop-shortcut "
                "creation will use a slower fallback. To fix it, run:\n"
                f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
                f'    "{sys.executable}" "{postinstall}" -install'
            )
    elif OS == "Linux":
        print(
            "\nℹ️  Linux note — a few voice-controlled OS actions shell out to "
            "native tools. Install the ones you'll use via your package manager:\n"
            "    • volume      → pulseaudio-utils   (pactl)\n"
            "    • brightness  → brightnessctl\n"
            "    • reminders   → systemd (systemd-run) or 'at'\n"
            "    • open URLs   → xdg-utils          (xdg-open)"
        )
    elif OS == "Darwin":
        print(
            "\nℹ️  macOS note — volume, brightness and reminders use the built-in "
            "'osascript' / LaunchAgents, so no extra tools are required.\n"
            "    For Safari automation only: python -m playwright install webkit"
        )

    print("\n✅ Setup complete!")
    print("   1) Launch S.P.I.D.Y.:  python main.py")
    print("   2) Configure your free Gemini API key in config/api_keys.json or via setup prompt.")
    print("   3) Global hotkey: Press Ctrl+Space anywhere in Windows to wake instantly.")


if __name__ == "__main__":
    main()
