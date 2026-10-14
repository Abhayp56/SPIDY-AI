"""
core/gui_grounding.py
High-precision Vision-Guided GUI element detection, coordinate grounding, and automation.

Architecture & Design Decisions:
- Follows Single Responsibility Principle (SRP):
  Handles visual screenshot capture, multimodal coordinate grounding (0-1000 normalized bounding boxes),
  and human-like mouse/keyboard actuation.
- Multi-monitor and DPI-aware: Translates normalized multimodal bounding boxes ([ymin, xmin, ymax, xmax])
  to physical and logical OS desktop coordinates accurately.
- Window-targeted cropping: Can focus visual inspection specifically on an active or named window
  using WindowTracker to maximize visual detail and eliminate background distractions.
- Human-like interaction: Smooth cursor interpolation (pyautogui.moveTo with duration) so the user
  visually sees the assistant interact with elements on screen.
- Fallback resilience: Uses core.gemini ladder (tier=SMART) with structured JSON schema.
"""

from __future__ import annotations

import io
import re
import time
import json
import platform
import threading
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, List

try:
    import mss
    import mss.tools
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False

try:
    import PIL.Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _HAS_PYAUTOGUI = True
except ImportError:
    _HAS_PYAUTOGUI = False

try:
    import pyperclip
    _HAS_PYPERCLIP = True
except ImportError:
    _HAS_PYPERCLIP = False

from core import gemini
from core.window_tracker import get_window_tracker, WindowTracker

_SYSTEM = platform.system()


@dataclass
class GroundingResult:
    """Represents the outcome of a visual element search or click operation."""
    found: bool = False
    x: int = 0
    y: int = 0
    box_2d: List[int] = field(default_factory=list)  # [ymin, xmin, ymax, xmax] (0-1000)
    label: str = ""
    confidence: str = "none"  # "high", "medium", "low", "none"
    element_type: str = "element"  # "button", "input", "icon", "menu", "link", etc.
    action_performed: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "x": self.x,
            "y": self.y,
            "box_2d": self.box_2d,
            "label": self.label,
            "confidence": self.confidence,
            "element_type": self.element_type,
            "action_performed": self.action_performed,
            "error": self.error,
        }

    def summary(self) -> str:
        if not self.found:
            return f"Element not found on screen: '{self.label}'{f' ({self.error})' if self.error else ''}"
        act = f" [{self.action_performed}]" if self.action_performed else ""
        return f"Found '{self.label}' ({self.element_type}) at ({self.x}, {self.y}) with {self.confidence} confidence.{act}"


def _trigger_ghost_highlight(x: int, y: int, label: str = "") -> None:
    """Visual feedback: briefly triggers the glowing ghost cursor reticle overlay."""
    try:
        from ui_orb import get_active_orb_ui
        orb_ui = get_active_orb_ui()
        if orb_ui and hasattr(orb_ui, "highlight_target"):
            orb_ui.highlight_target(x, y, label)
    except Exception:
        pass


class GuiGroundingEngine:
    """
    Engine for multimodal vision grounding and desktop UI interaction.
    """

    def __init__(self, window_tracker: Optional[WindowTracker] = None):
        self._tracker = window_tracker or get_window_tracker()
        self._lock = threading.Lock()

    # ── Screen Capture & Region Calculation ───────────────────────────────────
    def capture_screen_region(
        self,
        window_query: Optional[str] = None
    ) -> Tuple[Optional[bytes], Dict[str, int], str]:
        """
        Captures the screen or targeted window region.
        Returns: (image_bytes, region_dict, error_message)
        region_dict contains: {"left": int, "top": int, "width": int, "height": int}
        """
        if not _HAS_MSS:
            return None, {}, "mss library is not available"
        if not _HAS_PIL:
            return None, {}, "PIL library is not available"

        try:
            # 1. Target specific window if requested
            target_region = None
            if window_query:
                visible = self._tracker.list_visible_windows()
                q = window_query.lower().strip()
                for w in visible:
                    if q in w.title.lower() or q in w.app_name.lower():
                        if w.bounds["width"] > 50 and w.bounds["height"] > 50:
                            target_region = {
                                "left": w.bounds["left"],
                                "top": w.bounds["top"],
                                "width": w.bounds["width"],
                                "height": w.bounds["height"],
                            }
                            # Ensure target window is in focus
                            self._tracker.focus_window(w.hwnd)
                            time.sleep(0.15)
                            break

            with mss.mss() as sct:
                if target_region:
                    # Clip region to desktop bounds
                    sct_shot = sct.grab({
                        "left": target_region["left"],
                        "top": target_region["top"],
                        "width": target_region["width"],
                        "height": target_region["height"],
                    })
                    region = target_region
                else:
                    # Capture primary monitor
                    monitors = sct.monitors
                    monitor = monitors[1] if len(monitors) > 1 else monitors[0]
                    sct_shot = sct.grab(monitor)
                    region = {
                        "left": monitor["left"],
                        "top": monitor["top"],
                        "width": monitor["width"],
                        "height": monitor["height"],
                    }

                # Convert to PNG bytes
                raw_png = mss.tools.to_png(sct_shot.rgb, sct_shot.size)

                # Resize if excessively large for fast vision inference
                img = PIL.Image.open(io.BytesIO(raw_png)).convert("RGB")
                max_dim = 1600
                if img.width > max_dim or img.height > max_dim:
                    img.thumbnail((max_dim, max_dim), PIL.Image.Resampling.LANCZOS)
                
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=88)
                return buf.getvalue(), region, ""

        except Exception as e:
            return None, {}, f"Screen capture failed: {e}"

    # ── Multimodal Grounding Inference ────────────────────────────────────────
    def find_element(
        self,
        description: str,
        window_query: Optional[str] = None
    ) -> GroundingResult:
        """
        Locates a UI element described in natural language (e.g. 'Run button',
        'Search bar', 'Close tab icon', 'Settings gear').
        """
        if not description or not description.strip():
            return GroundingResult(found=False, error="Empty description provided")

        desc_clean = description.strip()

        with self._lock:
            img_bytes, region, err = self.capture_screen_region(window_query)
            if not img_bytes:
                return GroundingResult(found=False, label=desc_clean, error=err)

            prompt = (
                f"You are a high-precision computer UI visual grounding agent.\n"
                f"Identify the following UI element on the screen: '{desc_clean}'\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Detect the exact clickable UI element (button, icon, input field, menu item, tab, or link).\n"
                f"2. Return normalized coordinates [ymin, xmin, ymax, xmax] on a 0 to 1000 scale.\n"
                f"   - (0, 0) is top-left, (1000, 1000) is bottom-right of the image.\n"
                f"3. Output ONLY a valid JSON object matching this schema:\n"
                f"{{\n"
                f'  "found": true,\n'
                f'  "element_type": "button | input | icon | menu | tab | link | text",\n'
                f'  "box_2d": [ymin, xmin, ymax, xmax],\n'
                f'  "confidence": "high | medium | low",\n'
                f'  "label": "Brief description of what you found"\n'
                f"}}\n"
                f"If the element is NOT visible on screen, output:\n"
                f'{{"found": false, "label": "Not visible"}}\n'
            )

            try:
                from google.genai import types as gtypes
                parts = [
                    gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    prompt,
                ]

                # Request vision inference via SMART tier (Gemini 2.5/Flash)
                raw_text = gemini.text(parts, tier=gemini.SMART, timeout_ms=18_000)
                if not raw_text:
                    return GroundingResult(found=False, label=desc_clean, error="Vision model did not return a response")

                # Parse JSON
                parsed = None
                json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))
                    except Exception:
                        pass

                if not parsed or not parsed.get("found"):
                    return GroundingResult(found=False, label=desc_clean, error="Element not visible on screen")

                box = parsed.get("box_2d", [])
                if not isinstance(box, list) or len(box) != 4:
                    return GroundingResult(found=False, label=desc_clean, error="Invalid bounding box returned")

                ymin, xmin, ymax, xmax = [float(v) for v in box]

                # Compute center point in normalized 0-1000 space
                norm_cx = (xmin + xmax) / 2.0
                norm_cy = (ymin + ymax) / 2.0

                # Map normalized coordinate back to absolute desktop coordinates
                reg_left = region.get("left", 0)
                reg_top = region.get("top", 0)
                reg_w = region.get("width", 1920)
                reg_h = region.get("height", 1080)

                screen_x = int(reg_left + (norm_cx / 1000.0) * reg_w)
                screen_y = int(reg_top + (norm_cy / 1000.0) * reg_h)

                return GroundingResult(
                    found=True,
                    x=screen_x,
                    y=screen_y,
                    box_2d=[int(ymin), int(xmin), int(ymax), int(xmax)],
                    label=parsed.get("label", desc_clean),
                    confidence=parsed.get("confidence", "high"),
                    element_type=parsed.get("element_type", "element"),
                )

            except Exception as e:
                return GroundingResult(found=False, label=desc_clean, error=f"Grounding inference failed: {e}")

    # ── Actuation Operations (Click, Type, Hover) ─────────────────────────────
    def click_element(
        self,
        description: str,
        click_type: str = "single",
        window_query: Optional[str] = None
    ) -> GroundingResult:
        """
        Visually locates the target element and performs mouse click.
        click_type: 'single' | 'double' | 'right' | 'middle'
        """
        res = self.find_element(description, window_query=window_query)
        if not res.found:
            return res

        if not _HAS_PYAUTOGUI:
            res.error = "pyautogui is not available for clicking"
            return res

        try:
            # Trigger glowing visual target reticle
            _trigger_ghost_highlight(res.x, res.y, res.label)

            # Human-like smooth mouse glide
            pyautogui.moveTo(res.x, res.y, duration=0.25)
            time.sleep(0.05)

            ct = click_type.lower().strip()
            if ct in ("double", "double_click"):
                pyautogui.doubleClick(res.x, res.y)
                res.action_performed = f"double-clicked at ({res.x}, {res.y})"
            elif ct in ("right", "right_click"):
                pyautogui.rightClick(res.x, res.y)
                res.action_performed = f"right-clicked at ({res.x}, {res.y})"
            elif ct in ("middle", "middle_click"):
                pyautogui.middleClick(res.x, res.y)
                res.action_performed = f"middle-clicked at ({res.x}, {res.y})"
            else:
                pyautogui.click(res.x, res.y)
                res.action_performed = f"clicked at ({res.x}, {res.y})"

            time.sleep(0.1)
            return res

        except Exception as e:
            res.error = f"Click execution failed: {e}"
            return res

    def type_in_element(
        self,
        description: str,
        text: str,
        clear_first: bool = True,
        submit: bool = False,
        window_query: Optional[str] = None
    ) -> GroundingResult:
        """
        Clicks on an input field/box, clears existing text if requested, types new text,
        and optionally presses Enter.
        """
        res = self.click_element(description, click_type="single", window_query=window_query)
        if not res.found:
            return res

        if not _HAS_PYAUTOGUI:
            res.error = "pyautogui is not available for typing"
            return res

        try:
            time.sleep(0.1)

            if clear_first:
                # Select all and delete
                mod_key = "command" if _SYSTEM == "Darwin" else "ctrl"
                pyautogui.hotkey(mod_key, "a")
                time.sleep(0.05)
                pyautogui.press("backspace")
                time.sleep(0.05)

            # Paste text using clipboard for fast, accurate Unicode transmission
            if _HAS_PYPERCLIP:
                pyperclip.copy(text)
                mod_key = "command" if _SYSTEM == "Darwin" else "ctrl"
                pyautogui.hotkey(mod_key, "v")
            else:
                pyautogui.write(text, interval=0.02)

            time.sleep(0.1)
            if submit:
                pyautogui.press("enter")
                res.action_performed += f" and typed '{text}' with Enter"
            else:
                res.action_performed += f" and typed '{text}'"

            return res

        except Exception as e:
            res.error = f"Typing execution failed: {e}"
            return res

    def hover_element(
        self,
        description: str,
        window_query: Optional[str] = None
    ) -> GroundingResult:
        """
        Moves the cursor to hover over an element (e.g. to reveal a tooltip or submenu).
        """
        res = self.find_element(description, window_query=window_query)
        if not res.found:
            return res

        if not _HAS_PYAUTOGUI:
            res.error = "pyautogui is not available for mouse movement"
            return res

        try:
            pyautogui.moveTo(res.x, res.y, duration=0.3)
            res.action_performed = f"hovered at ({res.x}, {res.y})"
            return res
        except Exception as e:
            res.error = f"Hover failed: {e}"
            return res


# ── Global Singleton Accessor ─────────────────────────────────────────────────
_GROUNDING_INSTANCE: Optional[GuiGroundingEngine] = None
_GROUNDING_LOCK = threading.Lock()

def get_gui_grounding() -> GuiGroundingEngine:
    """Dependency injection / singleton accessor for GuiGroundingEngine."""
    global _GROUNDING_INSTANCE
    if _GROUNDING_INSTANCE is None:
        with _GROUNDING_LOCK:
            if _GROUNDING_INSTANCE is None:
                _GROUNDING_INSTANCE = GuiGroundingEngine()
    return _GROUNDING_INSTANCE
