"""
ui_island.py — Futuristic Holographic HUD Dynamic Island Bar for S.P.I.D.Y. AI.

Faithfully implements the user's reference HUD design with intelligent Auto-Hide:
  • Sleek Auto-Hide: When user is not speaking, collapses into a minimal, non-intrusive
    top bezel micro-notch capsule (Width ~76px, Height ~7px) with glowing cyan halo.
  • Voice-Reactive Expansion: As soon as the user speaks into the microphone, wake word
    is detected, or S.P.I.D.Y. responds, smoothly slides down and expands into the full HUD pill!
  • State-Adaptive Sizing:
      - LISTENING: Full expanded HUD bar (Avatar + S.P.I.D.Y. + LISTENING + Soundwave + Mic button + •••)
      - THINKING:  Compact HUD capsule (Avatar + S.P.I.D.Y. + Rotating Spinner + THINKING... + •••)
      - SPEAKING:  Medium HUD capsule (Avatar + S.P.I.D.Y. + Red Dot + SPEAKING + Compact Soundwave + •••)
      - COLLAPSED: Minimal top bezel micro-notch with cyan halo aura when silent.
  • Dynamic dual-tone soundwave visualizer (vibrant scarlet/red center bars, electric cyan flank bars,
    trailing dots) reactive to live microphone & assistant speech.
  • Stylized Spider Avatar HUD dial with crimson-red accent arc and glowing angular cyan eyes.
  • Draggable anywhere on desktop with position memory; always-on-top, translucent frameless widget.
  • Interactive circular glass microphone button (click to mute/unmute) & three-dots HUD menu.
  • Global Hotkey: Press Ctrl+Space or Ctrl+A anywhere in Windows to trigger/wake instantly.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect,
    QRectF, Qt, QTimer, pyqtProperty, pyqtSignal, QObject,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMenu,
    QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget, QLineEdit,
)

from memory.config_manager import (
    get_gemini_key, save_api_keys, get_assistant_name,
    get_voice, get_push_to_talk_enabled, save_ui_mode,
)
from core.autostart import is_autostart_enabled, set_autostart_enabled


# ── Color Palette: Cyber Neon Cyan & Scarlet HUD ─────────────────────────────
class HudColors:
    BG_OBSIDIAN_1  = QColor(7, 16, 26, 240)
    BG_OBSIDIAN_2  = QColor(4, 9, 16, 248)
    BG_OBSIDIAN_3  = QColor(6, 12, 22, 252)
    NEON_CYAN      = QColor(0, 242, 255)
    NEON_CYAN_GLOW = QColor(0, 235, 255)
    NEON_CYAN_CORE = QColor(220, 255, 255)
    HUD_RED        = QColor(255, 30, 68)
    HUD_RED_MID    = QColor(255, 55, 90)
    TEXT_WHITE     = QColor(255, 255, 255)
    TEXT_CYAN      = QColor(0, 242, 255)
    TEXT_MUTED     = QColor(130, 180, 215)


# ── Dynamic S.P.I.D.Y. HUD Island Bar Widget ─────────────────────────────────
class IslandWidget(QWidget):
    """
    Floating frameless, translucent, always-on-top HUD pill widget.
    Smoothly transitions between:
      - COLLAPSED: Minimal top bezel micro-notch (Width ~76, Height ~7) when user doesn't speak.
      - LISTENING: Full bar (~620px) with live dual-tone audio waveform & mic button.
      - THINKING:  Compact capsule (~290px) with rotating HUD spinner.
      - SPEAKING:  Medium capsule (~410px) with red speaking indicator & speech waveform.
    """

    COLLAPSED_W = 54
    COLLAPSED_H = 4

    EXPANDED_H  = 44
    W_LISTENING = 380
    W_THINKING  = 195
    W_SPEAKING  = 270

    def __init__(self, ui_controller: "JarvisIslandUI"):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.ui_ctrl = ui_controller
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._state = "SLEEPING"
        self._auto_hide = True
        self._is_expanded = False
        self._progress = 0.0  # 0.0 = collapsed notch, 1.0 = fully expanded HUD

        self._audio_level = 0.0
        self._phase = 0.0
        self._spinner_angle = 0.0
        self._brand_text = (get_assistant_name() or "S.P.I.D.Y.").upper()
        self._center_text = "LISTENING"

        # Mouse Dragging State
        self._drag_pos: Optional[QPoint] = None

        # Position Setup (Centered horizontally at screen top)
        scr = QApplication.primaryScreen()
        if scr:
            geom = scr.geometry()
            self._screen_x = geom.x()
            self._screen_y = geom.y()
            self._screen_w = geom.width()
        else:
            self._screen_x = 0
            self._screen_y = 0
            self._screen_w = 1920

        self._current_w = float(self.COLLAPSED_W)
        self._current_h = float(self.COLLAPSED_H)
        self._current_y = float(self._screen_y)

        self._update_geometry_pos()

        # Smooth Slide & Expansion Animation (240ms OutCubic)
        self._anim = QPropertyAnimation(self, b"anim_progress")
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 60 FPS Animation Timer (Waveform oscillation, eye breathing, spinner)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_frame)
        self._timer.start()

        # Collapse Timer (slides back up into notch when user/JARVIS finishes speaking)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

    # ── Animated Progress Property ────────────────────────────────────────────
    def get_anim_progress(self) -> float:
        return self._progress

    def set_anim_progress(self, val: float):
        self._progress = max(0.0, min(1.0, val))

        target_expanded_w = self._get_target_width_for_state()
        self._current_w = self.COLLAPSED_W + (target_expanded_w - self.COLLAPSED_W) * self._progress
        self._current_h = self.COLLAPSED_H + (self.EXPANDED_H - self.COLLAPSED_H) * self._progress
        # Sits flush at screen_y when collapsed; slides down 18px below bezel when expanded
        self._current_y = self._screen_y + (18.0 * self._progress)

        self._update_geometry_pos()
        self.update()

    anim_progress = pyqtProperty(float, get_anim_progress, set_anim_progress)

    def _get_target_width_for_state(self) -> float:
        if self._state == "THINKING":
            return float(self.W_THINKING)
        elif self._state == "SPEAKING":
            return float(self.W_SPEAKING)
        else:
            return float(self.W_LISTENING)

    def _update_geometry_pos(self):
        cx = self._screen_x + (self._screen_w - int(self._current_w)) // 2
        self.setGeometry(cx, int(self._current_y), int(self._current_w), int(self._current_h))

    # ── Expansion & Collapse Controls ─────────────────────────────────────────
    def expand(self, keep_alive: bool = False):
        """Expands the bar downwards from the top edge."""
        self._collapse_timer.stop()
        if not self._is_expanded or self._progress < 0.95:
            self._is_expanded = True
            self._anim.stop()
            self._anim.setStartValue(self._progress)
            self._anim.setEndValue(1.0)
            self._anim.start()

        if self._auto_hide and not keep_alive and self._state != "SPEAKING":
            self._collapse_timer.start(2800)

    def collapse(self):
        """Smoothly slides the bar back UP into the hidden top dock."""
        if not self._auto_hide or self._state == "SPEAKING":
            return
        self._is_expanded = False
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def schedule_collapse(self, delay_ms: int = 2500):
        """Schedules the bar to slide up after silence."""
        self._collapse_timer.stop()
        if self._auto_hide:
            self._collapse_timer.start(delay_ms)

    def _on_collapse_timeout(self):
        if self._state == "SPEAKING":
            return
        self.collapse()

    # ── State Updates ─────────────────────────────────────────────────────────
    def set_state(self, state: str):
        prev = self._state
        self._state = state
        self._brand_text = (self.ui_ctrl.assistant_name or "S.P.I.D.Y.").upper()

        if state == "SPEAKING":
            self._center_text = "SPEAKING"
            # Keep expanded while speaking
            self.expand(keep_alive=True)
        elif state == "THINKING":
            self._center_text = "THINKING..."
            self.expand(keep_alive=True)
        elif state == "LISTENING":
            self._center_text = "LISTENING"
            if prev == "SPEAKING":
                # As soon as speaking finishes, schedule smooth tuck away after silence
                self.schedule_collapse(2500)
            elif not self._is_expanded:
                # Standby idle: stays hidden in notch until speech
                pass
        elif state == "SLEEPING":
            self._center_text = "STANDBY"
            self.schedule_collapse(400)
        elif state == "MUTED":
            self._center_text = "MUTED"
            self.expand()
            self.schedule_collapse(1800)

        # Trigger width update if already expanded
        if self._is_expanded and self._progress > 0.8:
            self._anim.stop()
            self._anim.setStartValue(self._progress)
            self._anim.setEndValue(1.0)
            self._anim.start()

        self.update()

    def set_audio_level(self, lvl: float):
        self._audio_level = max(0.0, min(1.0, lvl))
        # When user speaks into the microphone while idle or listening:
        # immediately slide down and expand into the full HUD!
        if lvl > 0.06 and not self.ui_ctrl.muted and self._state != "SPEAKING":
            if not self._is_expanded or self._progress < 0.8:
                self.expand()
            else:
                # Refresh silence timer while user continues speaking
                self._collapse_timer.stop()
                if self._auto_hide:
                    self._collapse_timer.start(2800)

    def set_display_text(self, text: str):
        """Updates display text and expands if needed."""
        self._center_text = text.strip()
        self.expand(keep_alive=(self._state in ("SPEAKING", "THINKING")))
        self.update()

    def _on_frame(self):
        self._phase += 0.08
        if self._phase > 628.3:
            self._phase = 0.0

        if self._state == "THINKING":
            self._spinner_angle = (self._spinner_angle + 7.5) % 360.0

        self.update()

    # ── Paint Pipeline ────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0

        # ── 1. If Collapsed (Hidden Top Notch) ────────────────────────────────
        if self._progress < 0.15:
            self._draw_collapsed_notch(p, cx, w, h)
            return

        # ── 2. Expanded HUD Pill ──────────────────────────────────────────────
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        self._draw_hud_pill(p, rect)

        # Content opacity smoothly fades in with progress
        content_alpha = int(255 * max(0.0, (self._progress - 0.20) / 0.80))
        if content_alpha <= 0:
            return

        # ── Left: Spider Avatar HUD Dial ──────────────────────────────────────
        avatar_r = 15.0
        avatar_cx = 14.0 + avatar_r
        avatar_cy = h / 2.0
        self._draw_spider_avatar(p, QPointF(avatar_cx, avatar_cy), avatar_r, content_alpha)

        # ── Brand Title & Status Indicator ────────────────────────────────────
        text_x = avatar_cx + avatar_r + 10.0
        self._draw_brand_and_status(p, text_x, h, content_alpha)

        # ── State-Specific Middle Visualizers ─────────────────────────────────
        if self._state == "LISTENING" and w >= 280:
            wave_cx = w * 0.58
            wave_cy = h / 2.0
            self._draw_waveform(p, QPointF(wave_cx, wave_cy), 110.0, 26.0, is_large=True, alpha=content_alpha)

            mic_btn_r = 12.5
            mic_btn_cx = w - 42.0
            mic_btn_cy = h / 2.0
            self._draw_microphone_button(p, QPointF(mic_btn_cx, mic_btn_cy), mic_btn_r, content_alpha)

        elif self._state == "SPEAKING" and w >= 220:
            wave_cx = w - 62.0
            wave_cy = h / 2.0
            self._draw_waveform(p, QPointF(wave_cx, wave_cy), 65.0, 22.0, is_large=False, alpha=content_alpha)

        # ── Far Right Menu Dots (•••) ─────────────────────────────────────────
        dots_x = w - 16.0
        dots_cy = h / 2.0
        p.setBrush(QBrush(QColor(0, 242, 255, int(content_alpha * 0.85))))
        p.setPen(Qt.PenStyle.NoPen)
        for j in (-3, 0, 3):
            p.drawEllipse(QPointF(dots_x + j, dots_cy), 1.2, 1.2)

    def _draw_collapsed_notch(self, p: QPainter, cx: float, w: float, h: float):
        """Draws the minimal glowing top bezel micro-notch when user doesn't speak."""
        # Top glowing halo aura
        aura_grad = QRadialGradient(cx, 0, w * 0.7)
        pulse = 0.75 + 0.25 * math.sin(self._phase * 1.5)
        c_aura = QColor(0, 240, 255, int(110 * pulse))
        aura_grad.setColorAt(0.0, c_aura)
        aura_grad.setColorAt(0.6, QColor(0, 240, 255, int(30 * pulse)))
        aura_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(aura_grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - w, -6, w * 2, 20))

        # Sleek dark micro-capsule body
        notch_rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setBrush(QBrush(QColor(5, 11, 18, 250)))
        p.setPen(QPen(QColor(0, 242, 255, 230), 1.2))
        p.drawRoundedRect(notch_rect, h / 2.0, h / 2.0)

        # Luminous neon cyan arc line on bottom edge
        arc_pen = QPen(QColor(220, 255, 255, 255), 1.5)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc_pen)
        p.drawLine(QPointF(cx - 15, h - 0.8), QPointF(cx + 15, h - 0.8))

    def _draw_hud_pill(self, p: QPainter, rect: QRectF):
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        radius = h / 2.0

        # Multi-tier outer cyan neon glow bloom
        for i in (5, 3, 1):
            alpha = int((28 / (i * 0.75)) * self._progress)
            p.setPen(QPen(QColor(0, 235, 255, alpha), 1.2 + i * 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-i * 0.8, -i * 0.8, i * 0.8, i * 0.8), radius + i, radius + i)

        # Glassmorphic Body Fill (deep cyber dark obsidian)
        bg_grad = QLinearGradient(x, y, x, y + h)
        bg_grad.setColorAt(0.0, HudColors.BG_OBSIDIAN_1)
        bg_grad.setColorAt(0.35, HudColors.BG_OBSIDIAN_2)
        bg_grad.setColorAt(1.0, HudColors.BG_OBSIDIAN_3)
        p.setBrush(QBrush(bg_grad))

        # Vivid Electric Cyan Rim
        border_pen = QPen(HudColors.NEON_CYAN, 1.4)
        p.setPen(border_pen)
        p.drawRoundedRect(rect, radius, radius)

        # Top subtle specular glass reflection highlight
        spec_path = QPainterPath()
        spec_path.addRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -h * 0.52), radius - 1, radius - 1)
        spec_grad = QLinearGradient(x, y, x, y + h * 0.45)
        spec_grad.setColorAt(0.0, QColor(0, 240, 255, 35))
        spec_grad.setColorAt(0.7, QColor(0, 240, 255, 10))
        spec_grad.setColorAt(1.0, QColor(0, 240, 255, 0))
        p.setBrush(QBrush(spec_grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(spec_path)

        # Top and bottom sci-fi HUD frame brackets / notches
        notch_w = min(90.0, w * 0.32)
        cx = x + w / 2.0
        bracket_pen = QPen(QColor(0, 255, 255, 160), 1.0)
        p.setPen(bracket_pen)
        p.drawLine(QPointF(cx - notch_w / 2.0, y + 1.0), QPointF(cx + notch_w / 2.0, y + 1.0))
        p.drawLine(QPointF(cx - notch_w / 2.0, y + h - 1.0), QPointF(cx + notch_w / 2.0, y + h - 1.0))

    def _draw_spider_avatar(self, p: QPainter, center: QPointF, radius: float, alpha: int = 255):
        cx, cy = center.x(), center.y()

        # Outer dark dial
        p.setBrush(QBrush(QColor(5, 11, 18, alpha)))
        p.setPen(QPen(QColor(0, 180, 220, int(alpha * 0.32)), 1.2))
        p.drawEllipse(center, radius, radius)

        # Inner dark disc
        p.setBrush(QBrush(QColor(2, 6, 11, alpha)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, radius - 2.0, radius - 2.0)

        arc_rect = QRectF(cx - radius + 1.2, cy - radius + 1.2, (radius - 1.2) * 2, (radius - 1.2) * 2)

        # Tactical HUD Arcs
        # Red accent arc on top-left (approx 75 deg to 155 deg)
        red_pen = QPen(QColor(HudColors.HUD_RED.red(), HudColors.HUD_RED.green(), HudColors.HUD_RED.blue(), alpha), 2.0)
        red_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(red_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, int(75 * 16), int(80 * 16))

        # Cyan accent arc on bottom
        cyan_pen = QPen(QColor(HudColors.NEON_CYAN.red(), HudColors.NEON_CYAN.green(), HudColors.NEON_CYAN.blue(), alpha), 1.5)
        cyan_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(cyan_pen)
        p.drawArc(arc_rect, int(225 * 16), int(75 * 16))

        s = radius / 28.0

        # ── Spider Mask Head Silhouette ───────────────────────────────────────
        mask_outline = QPainterPath()
        mask_outline.moveTo(cx, cy - 16.5 * s)
        mask_outline.cubicTo(cx + 12.0 * s, cy - 15.5 * s, cx + 13.5 * s, cy + 1.0 * s, cx + 9.0 * s, cy + 9.5 * s)
        mask_outline.cubicTo(cx + 5.5 * s, cy + 14.5 * s, cx + 1.8 * s, cy + 17.0 * s, cx, cy + 17.2 * s)
        mask_outline.cubicTo(cx - 1.8 * s, cy + 17.0 * s, cx - 5.5 * s, cy + 14.5 * s, cx - 9.0 * s, cy + 9.5 * s)
        mask_outline.cubicTo(cx - 13.5 * s, cy + 1.0 * s, cx - 12.0 * s, cy - 15.5 * s, cx, cy - 16.5 * s)

        p.setBrush(QBrush(QColor(6, 13, 21, alpha)))
        p.setPen(QPen(QColor(0, 220, 250, int(alpha * 0.76)), 1.0 * s))
        p.drawPath(mask_outline)

        p.setPen(QPen(QColor(0, 200, 240, int(alpha * 0.62)), 0.9 * s))
        p.drawLine(QPointF(cx - 4.5 * s, cy + 15.5 * s), QPointF(cx - 7.5 * s, cy + 20.5 * s))
        p.drawLine(QPointF(cx + 4.5 * s, cy + 15.5 * s), QPointF(cx + 7.5 * s, cy + 20.5 * s))

        # ── Stylized Aggressive Glowing Spider Eyes ──────────────────────────
        left_eye = QPainterPath()
        left_eye.moveTo(cx - 2.5 * s, cy - 4.5 * s)
        left_eye.cubicTo(cx - 5.5 * s, cy - 6.5 * s, cx - 9.5 * s, cy - 8.5 * s, cx - 12.5 * s, cy - 7.0 * s)
        left_eye.cubicTo(cx - 13.5 * s, cy - 1.0 * s, cx - 11.5 * s, cy + 4.5 * s, cx - 9.0 * s, cy + 7.5 * s)
        left_eye.cubicTo(cx - 6.5 * s, cy + 7.0 * s, cx - 4.0 * s, cy + 3.0 * s, cx - 2.5 * s, cy - 4.5 * s)

        right_eye = QPainterPath()
        right_eye.moveTo(cx + 2.5 * s, cy - 4.5 * s)
        right_eye.cubicTo(cx + 5.5 * s, cy - 6.5 * s, cx + 9.5 * s, cy - 8.5 * s, cx + 12.5 * s, cy - 7.0 * s)
        right_eye.cubicTo(cx + 13.5 * s, cy - 1.0 * s, cx + 11.5 * s, cy + 4.5 * s, cx + 9.0 * s, cy + 7.5 * s)
        right_eye.cubicTo(cx + 6.5 * s, cy + 7.0 * s, cx + 4.0 * s, cy + 3.0 * s, cx + 2.5 * s, cy - 4.5 * s)

        eye_pulse = 0.85 + 0.15 * math.sin(self._phase * 2.0)
        eye_grad = QLinearGradient(cx, cy - 7 * s, cx, cy + 8 * s)
        eye_grad.setColorAt(0.0, QColor(245, 255, 255, int(alpha * eye_pulse)))
        eye_grad.setColorAt(0.35, QColor(0, 245, 255, int(alpha * eye_pulse)))
        eye_grad.setColorAt(1.0, QColor(0, 180, 230, int(alpha * 0.9 * eye_pulse)))

        p.setBrush(QBrush(eye_grad))
        p.setPen(QPen(QColor(0, 255, 255, alpha), 0.8 * s))
        p.drawPath(left_eye)
        p.drawPath(right_eye)

    def _draw_brand_and_status(self, p: QPainter, text_x: float, h: float, alpha: int = 255):
        # 1. Title: S.P.I.D.Y.
        font_title = QFont("Segoe UI", 9, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        p.setFont(font_title)
        p.setPen(QColor(255, 255, 255, alpha))
        p.drawText(QRectF(text_x, 7, 85, 16), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._brand_text)

        # 2. Subtitle Status Indicator
        dot_cy = 28.5

        if self.ui_ctrl.muted:
            p.setBrush(QBrush(QColor(HudColors.HUD_RED.red(), HudColors.HUD_RED.green(), HudColors.HUD_RED.blue(), alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(text_x + 2.0, dot_cy), 2.2, 2.2)

            font_sub = QFont("Segoe UI", 7, QFont.Weight.Bold)
            font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(font_sub)
            p.setPen(QColor(HudColors.HUD_RED.red(), HudColors.HUD_RED.green(), HudColors.HUD_RED.blue(), alpha))
            p.drawText(QRectF(text_x + 9.0, dot_cy - 7, 75, 14), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "MUTED")

        elif self._state == "THINKING":
            spin_pen = QPen(QColor(HudColors.NEON_CYAN.red(), HudColors.NEON_CYAN.green(), HudColors.NEON_CYAN.blue(), alpha), 1.5)
            spin_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(spin_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc_r = QRectF(text_x, dot_cy - 4.0, 7.5, 7.5)
            start_angle = int(self._spinner_angle * 16)
            p.drawArc(arc_r, start_angle, int(260 * 16))

            font_sub = QFont("Segoe UI", 7, QFont.Weight.Bold)
            font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(font_sub)
            p.setPen(QColor(HudColors.TEXT_CYAN.red(), HudColors.TEXT_CYAN.green(), HudColors.TEXT_CYAN.blue(), alpha))
            p.drawText(QRectF(text_x + 11.0, dot_cy - 7, 75, 14), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "THINKING...")

        elif self._state == "SPEAKING":
            p.setBrush(QBrush(QColor(HudColors.HUD_RED.red(), HudColors.HUD_RED.green(), HudColors.HUD_RED.blue(), alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(text_x + 2.0, dot_cy), 2.2, 2.2)

            font_sub = QFont("Segoe UI", 7, QFont.Weight.Bold)
            font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(font_sub)
            p.setPen(QColor(HudColors.TEXT_CYAN.red(), HudColors.TEXT_CYAN.green(), HudColors.TEXT_CYAN.blue(), alpha))
            p.drawText(QRectF(text_x + 9.0, dot_cy - 7, 75, 14), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "SPEAKING")

        elif self._state == "SLEEPING":
            pulse_a = int((140 + 100 * math.sin(self._phase * 1.5)) * (alpha / 255.0))
            p.setBrush(QBrush(QColor(0, 242, 255, pulse_a)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(text_x + 2.0, dot_cy), 2.2, 2.2)

            font_sub = QFont("Segoe UI", 7, QFont.Weight.Bold)
            font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(font_sub)
            p.setPen(QColor(0, 242, 255, pulse_a))
            p.drawText(QRectF(text_x + 9.0, dot_cy - 7, 75, 14), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "STANDBY")

        else:  # LISTENING
            p.setBrush(QBrush(QColor(HudColors.NEON_CYAN.red(), HudColors.NEON_CYAN.green(), HudColors.NEON_CYAN.blue(), alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(text_x + 2.0, dot_cy), 2.2, 2.2)

            font_sub = QFont("Segoe UI", 7, QFont.Weight.Bold)
            font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            p.setFont(font_sub)
            p.setPen(QColor(HudColors.TEXT_CYAN.red(), HudColors.TEXT_CYAN.green(), HudColors.TEXT_CYAN.blue(), alpha))
            p.drawText(QRectF(text_x + 9.0, dot_cy - 7, 75, 14), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), "LISTENING")

    def _draw_waveform(self, p: QPainter, center: QPointF, width: float, height: float, is_large: bool = True, alpha: int = 255):
        cx, cy = center.x(), center.y()

        num_bars = 19 if is_large else 11
        bar_w = 2.4 if is_large else 2.2
        spacing = 2.8 if is_large else 2.6
        total_w = num_bars * bar_w + (num_bars - 1) * spacing
        start_x = cx - total_w / 2.0
        center_idx = num_bars // 2

        audio_factor = self._audio_level if self._state == "LISTENING" else 0.8
        active = (self._state in ("LISTENING", "SPEAKING")) and not self.ui_ctrl.muted

        for i in range(num_bars):
            bx = start_x + i * (bar_w + spacing)
            dist_from_center = abs(i - center_idx)
            envelope = math.exp(- (dist_from_center ** 2) / (16.0 if is_large else 8.0))

            if active:
                wave = math.sin(self._phase * 3.4 + i * 0.52) * 0.38 + 0.62
                h = 4.0 + (height * 0.92 * envelope * (audio_factor * 0.75 + 0.25) * wave)
            else:
                h = 3.5 + (envelope * 3.0 * (math.sin(self._phase + i) * 0.5 + 0.5))

            if dist_from_center <= 1:
                color = QColor(HudColors.HUD_RED.red(), HudColors.HUD_RED.green(), HudColors.HUD_RED.blue(), alpha)
            elif dist_from_center == 2:
                color = QColor(HudColors.HUD_RED_MID.red(), HudColors.HUD_RED_MID.green(), HudColors.HUD_RED_MID.blue(), alpha)
            elif dist_from_center <= (5 if is_large else 3):
                color = QColor(HudColors.NEON_CYAN.red(), HudColors.NEON_CYAN.green(), HudColors.NEON_CYAN.blue(), alpha)
            else:
                tail_a = int(max(70, 255 - (dist_from_center - 5) * 45) * (alpha / 255.0))
                color = QColor(0, 215, 245, tail_a)

            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)

            if is_large and dist_from_center >= 7:
                dot_r = 1.1
                p.drawEllipse(QPointF(bx + bar_w / 2.0, cy), dot_r, dot_r)
            else:
                p.drawRoundedRect(QRectF(bx, cy - h / 2.0, bar_w, h), bar_w / 2.0, bar_w / 2.0)

    def _draw_microphone_button(self, p: QPainter, center: QPointF, radius: float, alpha: int = 255):
        cx, cy = center.x(), center.y()
        is_muted = self.ui_ctrl.muted
        rim_col = HudColors.HUD_RED if is_muted else HudColors.NEON_CYAN

        p.setBrush(QBrush(QColor(6, 14, 24, int(alpha * 0.86))))
        p.setPen(QPen(QColor(rim_col.red(), rim_col.green(), rim_col.blue(), int(alpha * 0.55)), 1.2))
        p.drawEllipse(center, radius, radius)

        mic_pen = QPen(QColor(rim_col.red(), rim_col.green(), rim_col.blue(), alpha), 1.5)
        mic_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(mic_pen)
        p.setBrush(QBrush(QColor(rim_col.red(), rim_col.green(), rim_col.blue(), int(alpha * 0.18))))

        p.drawRoundedRect(QRectF(cx - 2.5, cy - 5.5, 5.0, 7.5), 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx - 4.2, cy - 3.5, 8.4, 7.5), int(190 * 16), int(160 * 16))
        p.drawLine(QPointF(cx, cy + 4.0), QPointF(cx, cy + 6.5))
        p.drawLine(QPointF(cx - 2.8, cy + 6.5), QPointF(cx + 2.8, cy + 6.5))

        if is_muted:
            strike_pen = QPen(QColor(HudColors.HUD_RED.red(), HudColors.HUD_RED.green(), HudColors.HUD_RED.blue(), alpha), 1.5)
            strike_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(strike_pen)
            p.drawLine(QPointF(cx - 5.0, cy - 5.0), QPointF(cx + 5.0, cy + 5.0))

    # ── Hover & Mouse Interactions ───────────────────────────────────────────
    def enterEvent(self, e):
        """Hovering mouse over the top notch expands it smoothly."""
        if self._auto_hide and not self._is_expanded:
            self.expand()
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pt = e.position().toPoint()
            w = self.width()
            h = self.height()

            # If clicked while collapsed: expand immediately!
            if not self._is_expanded or self._progress < 0.5:
                self.expand()
                if self.ui_ctrl.on_wake_manual:
                    self.ui_ctrl.on_wake_manual()
                e.accept()
                return

            # 1. Hit test: Microphone button
            if self._state == "LISTENING" and w >= 280:
                mic_cx = w - 42.0
                mic_cy = h / 2.0
                dist_mic = math.hypot(pt.x() - mic_cx, pt.y() - mic_cy)
                if dist_mic <= 15.0:
                    self.ui_ctrl.muted = not self.ui_ctrl.muted
                    self.update()
                    e.accept()
                    return

            # 2. Hit test: Three dots menu button
            dots_cx = w - 16.0
            dots_cy = h / 2.0
            dist_dots = math.hypot(pt.x() - dots_cx, pt.y() - dots_cy)
            if dist_dots <= 13.0:
                self._show_context_menu(e.globalPosition().toPoint())
                e.accept()
                return

            # 3. Hit test: Avatar (Wake/Toggle)
            avatar_cx = 29.0
            avatar_cy = h / 2.0
            if math.hypot(pt.x() - avatar_cx, pt.y() - avatar_cy) <= 18.0:
                if self.ui_ctrl.on_wake_manual:
                    self.ui_ctrl.on_wake_manual()
                self.expand()
                e.accept()
                return

            # 4. Drag widget anywhere
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

        elif e.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(e.globalPosition().toPoint())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.MouseButton.LeftButton:
            new_pos = e.globalPosition().toPoint() - self._drag_pos
            self._screen_x = new_pos.x() - (self._screen_w - int(self._current_w)) // 2
            self._current_y = new_pos.y()
            self.move(new_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def _show_context_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #08101A;
                color: #F0F9FF;
                border: 1.5px solid #00F2FF;
                border-radius: 12px;
                padding: 8px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QMenu::item {
                padding: 7px 22px 7px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #0E2238;
                color: #00F2FF;
            }
            QMenu::separator {
                height: 1px;
                background: #18344E;
                margin: 5px 8px;
            }
        """)

        state_str = "MUTED" if self.ui_ctrl.muted else self._state
        header = menu.addAction(f"🕷  {self._brand_text} • {state_str}")
        header.setEnabled(False)
        menu.addSeparator()

        if self._state == "SLEEPING":
            wake_act = menu.addAction("⚡  Wake Up")
            wake_act.triggered.connect(lambda: self.ui_ctrl.on_wake_manual() if self.ui_ctrl.on_wake_manual else None)
        else:
            sleep_act = menu.addAction("🌙  Put to Sleep")
            sleep_act.triggered.connect(lambda: self.ui_ctrl.on_wake_manual() if self.ui_ctrl.on_wake_manual else None)

        mute_act = menu.addAction("🔊  Unmute Microphone" if self.ui_ctrl.muted else "🔇  Mute Microphone")
        mute_act.triggered.connect(lambda: setattr(self.ui_ctrl, "muted", not self.ui_ctrl.muted))

        menu.addSeparator()
        # Auto-Hide toggle
        auto_hide_act = menu.addAction("✓  Auto-Hide when Silent" if self._auto_hide else "○  Auto-Hide when Silent")
        auto_hide_act.triggered.connect(self._toggle_auto_hide)

        hotkey_lbl = menu.addAction("⌨  Global Hotkey: Ctrl+Space / Ctrl+A")
        hotkey_lbl.setEnabled(False)

        autostart_on = is_autostart_enabled()
        auto_act = menu.addAction("✓  Auto-Start on Boot" if autostart_on else "○  Auto-Start on Boot")
        auto_act.triggered.connect(lambda: set_autostart_enabled(not autostart_on))

        menu.addSeparator()
        switch_orb = menu.addAction("🔮  Switch to Desktop Orb Mode")
        switch_orb.triggered.connect(self._switch_to_orb)

        menu.addSeparator()
        quit_act = menu.addAction("✕  Quit Assistant")
        quit_act.triggered.connect(QApplication.instance().quit)

        menu.exec(global_pos)

    def _toggle_auto_hide(self):
        self._auto_hide = not self._auto_hide
        if not self._auto_hide:
            self.expand(keep_alive=True)
        else:
            self.schedule_collapse(1000)

    def _switch_to_orb(self):
        save_ui_mode("orb")
        QApplication.instance().quit()


# ── The Root Shim for mainloop() ──────────────────────────────────────────────
class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


# ── Global Keyboard Shortcut Listener ─────────────────────────────────────────
class GlobalIslandHotkey(threading.Thread):
    """
    Background daemon thread polling Windows GetAsyncKeyState at 30Hz
    to wake/toggle the island bar via Ctrl+Space or Ctrl+A anywhere on PC.
    """
    def __init__(self, callback: Callable[[], None]):
        super().__init__(daemon=True, name="IslandGlobalHotkey")
        self._callback = callback
        self._stop = threading.Event()
        self._last_trigger = 0.0

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
        except Exception:
            return

        vk_ctrl = 0x11
        vk_space = 0x20
        vk_a = 0x41  # 'A'

        while not self._stop.is_set():
            time.sleep(0.033)
            ctrl_down = bool(user32.GetAsyncKeyState(vk_ctrl) & 0x8000)
            if not ctrl_down:
                continue

            space_down = bool(user32.GetAsyncKeyState(vk_space) & 0x8000)
            a_down = bool(user32.GetAsyncKeyState(vk_a) & 0x8000)

            if space_down or a_down:
                now = time.monotonic()
                if now - self._last_trigger > 0.4:
                    self._last_trigger = now
                    try:
                        self._callback()
                    except Exception:
                        pass


# ── Duck-Typed JarvisIslandUI Controller ──────────────────────────────────────
class JarvisIslandUI(QObject):
    """
    Main UI controller exposing the exact duck-typed contract expected by
    JarvisLive in main.py, driving the S.P.I.D.Y. HUD Island Bar interface.
    """

    _state_sig = pyqtSignal(str)
    _log_sig = pyqtSignal(str)
    _alert_sig = pyqtSignal(str)
    _text_sig = pyqtSignal(str)
    _audio_sig = pyqtSignal(float)
    _expand_sig = pyqtSignal(bool)
    _collapse_sig = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")

        self._muted = False
        self._ready = bool(get_gemini_key() and len(get_gemini_key()) > 15)

        # Callbacks expected by JarvisLive
        self.on_text_command: Optional[Callable] = None
        self.on_remote_clicked: Optional[Callable] = None
        self.on_interrupt: Optional[Callable] = None
        self.on_voice_change: Optional[Callable] = None
        self.on_audio_device_change: Optional[Callable] = None
        self.on_push_to_talk: Optional[Callable] = None
        self.ptt_hold: Optional[Callable] = None
        self.on_wake_toggle: Optional[Callable] = None
        self.on_wake_manual: Optional[Callable] = None
        self.on_wake_install: Optional[Callable] = None
        self.wake_get_state: Optional[Callable] = None
        self.wake_is_ready: Optional[Callable] = None
        self.get_plugins: Optional[Callable] = None
        self.get_plugin_settings: Optional[Callable] = None
        self.request_say: Optional[Callable] = None

        self._assistant_name = get_assistant_name() or "S.P.I.D.Y."

        # Instantiate Island Widget
        self._island = IslandWidget(self)
        self.root = _RootShim(self._app)

        # Wire Qt signals across thread boundaries
        self._state_sig.connect(self._island.set_state)
        self._text_sig.connect(self._island.set_display_text)
        self._log_sig.connect(self._on_log)
        self._audio_sig.connect(self._island.set_audio_level)
        self._expand_sig.connect(self._island.expand)
        self._collapse_sig.connect(self._island.schedule_collapse)

        # Global Hotkey Listener
        self._hotkey = GlobalIslandHotkey(self._on_hotkey_triggered)
        self._hotkey.start()

        self._island.show()
        self._island.raise_()

    def _on_hotkey_triggered(self):
        """Called when Ctrl+Space or Ctrl+A is pressed anywhere in Windows."""
        if self.on_wake_manual:
            self.on_wake_manual()
        self._expand_sig.emit(False)

    # ── Mute Property ─────────────────────────────────────────────────────────
    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, v: bool):
        self._muted = bool(v)
        self._island.update()

    @property
    def current_file(self) -> str | None:
        return None

    @property
    def assistant_name(self) -> str:
        return self._assistant_name

    # ── Public API matching JarvisUI Contract ─────────────────────────────────
    def set_state(self, state: str):
        self._state_sig.emit(state)

    def set_audio_level(self, level: float) -> None:
        self._audio_sig.emit(float(level))

    def write_log(self, text: str):
        self._log_sig.emit(text)

    def _on_log(self, text: str):
        clean = text.strip()
        if clean.startswith("You:"):
            speech = clean[4:].strip()
            if speech:
                self._text_sig.emit(f"You: {speech}")
                self._expand_sig.emit(False)
                self._collapse_sig.emit(3500)
        elif clean.startswith(f"{self._assistant_name}:"):
            speech = clean[len(self._assistant_name) + 1:].strip()
            if speech:
                self._text_sig.emit(speech)
                self._expand_sig.emit(True)
        elif clean.startswith("SYS: Awake"):
            self._text_sig.emit("LISTENING")
            self._expand_sig.emit(False)
        elif clean.startswith("SYS: Sleeping"):
            self._text_sig.emit("STANDBY")
            self._collapse_sig.emit(500)

    def wait_for_api_key(self):
        if not self._ready:
            key = get_gemini_key()
            if not key or len(key) <= 15:
                print("\n" + "=" * 65)
                print("🕷️  S.P.I.D.Y. AI — Setup")
                print("Get your free Gemini API key from: https://aistudio.google.com/app/apikey")
                print("=" * 65)
                try:
                    user_key = input("Enter your Gemini API key: ").strip()
                    if user_key and len(user_key) > 10:
                        save_api_keys(user_key)
                        self._ready = True
                except Exception:
                    pass
        while not self._ready:
            time.sleep(0.4)
            self._ready = bool(get_gemini_key() and len(get_gemini_key()) > 15)

    def prompt_reconfig(self):
        pass

    def show_confirm(self, title: str, detail: str) -> None:
        self._text_sig.emit(f"Confirm: {title}")
        self._expand_sig.emit(True)

    def hide_confirm(self) -> None:
        self._collapse_sig.emit(800)

    def trigger_alert(self, msg: str) -> None:
        self._text_sig.emit(f"Alert: {msg[:30]}")
        self._expand_sig.emit(False)
        self._collapse_sig.emit(2500)

    def highlight_target(self, x: int, y: int, label: str = "") -> None:
        pass

    def show_content(self, title: str, text: str):
        pass

    def show_quiz(self, topic: str, questions, grade=None):
        pass

    def hide_quiz(self):
        pass

    def show_review(self, title: str, summary: str, findings, unclear=None):
        pass

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        pass

    def push_visemes(self, frames, hop: float, at: float) -> None:
        pass

    def notify_phone_connected(self) -> None:
        self._text_sig.emit("Phone Dashboard Connected")
        self._expand_sig.emit(False)
        self._collapse_sig.emit(2000)

    def start_speaking(self):
        self.set_state("SPEAKING")
        self._expand_sig.emit(True)

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
        # When assistant finishes speaking, schedule smooth collapse after brief grace period (2.5s)
        self._collapse_sig.emit(2500)

    def show_video(self, source: str, title: str = "", muted: bool = True, audio_source: str = ""):
        pass

    def stop_video(self):
        pass

    def set_video_muted(self, muted: bool):
        pass

    def video_is_playing(self) -> bool:
        return False

    def start_camera_stream(self):
        self.write_log("CAM: Camera active - capturing frame...")

    def stop_camera_stream(self):
        self.write_log("CAM: Camera closed.")

    def show_camera_frame(self, img_bytes: bytes):
        pass
