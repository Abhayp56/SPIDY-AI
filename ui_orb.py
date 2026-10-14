"""
ui_orb.py — Lightweight Ambient Desktop Orb for JARVIS.

A frameless, translucent, always-on-top interactive Desktop Orb widget that
serves as a drop-in replacement for the full 3D HUD.

Key Features:
  • Ambient Background Presence: Runs quietly on your desktop without window chrome.
  • One-Click Mute: Click the orb to immediately toggle mute/unmute.
  • Visual State Feedback:
      - SLEEPING: Gentle ambient breathing pulse (waiting for "Hey Jarvis").
      - LISTENING: Bright cyan/azure aura that dynamically pulses with your voice.
      - SPEAKING: Luminous resonance with JARVIS's voice output.
      - THINKING / WORKING: Dual rotating orbital energy rings for background tasks.
      - MUTED: Striking crimson-red aura.
  • Freely Draggable: Move anywhere on any monitor; position persists across reboots.
  • Confirmation Pill: Floating non-blocking gate for irreversible actions (shutdown/wifi).
  • Context Menu & System Tray: Quick controls for wake, autostart, settings, exit.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal, QObject,
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
    get_orb_position, save_orb_position, get_voice,
    get_push_to_talk_enabled, save_push_to_talk_enabled,
    save_ui_mode,
)
from core.autostart import is_autostart_enabled, set_autostart_enabled
from core import confirm as confirm_gate


# ── Color Palette ─────────────────────────────────────────────────────────────
class OrbColors:
    SLEEP_CYAN   = QColor(0, 180, 216)
    SLEEP_DEEP   = QColor(10, 40, 70)
    LISTEN_CYAN  = QColor(0, 240, 255)
    LISTEN_CORE  = QColor(180, 255, 255)
    SPEAK_BLUE   = QColor(72, 149, 239)
    THINK_GOLD   = QColor(255, 183, 3)
    THINK_AMBER  = QColor(251, 133, 0)
    MUTE_RED     = QColor(230, 57, 70)
    MUTE_CORE    = QColor(255, 100, 110)
    BG_DARK      = QColor(15, 20, 30, 220)


# ── Confirmation Pill Dialog ──────────────────────────────────────────────────
class ConfirmPill(QWidget):
    """Floating confirmation pill that appears adjacent to the Orb for safety gates."""

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(280)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.title_lbl = QLabel("CONFIRM ACTION")
        self.title_lbl.setStyleSheet("color: #FFB703; font-weight: bold; font-size: 11px; font-family: 'Segoe UI', sans-serif;")
        lay.addWidget(self.title_lbl)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setWordWrap(True)
        self.detail_lbl.setStyleSheet("color: #E0E0E0; font-size: 11px; font-family: 'Segoe UI', sans-serif;")
        lay.addWidget(self.detail_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.confirm_btn = QPushButton("CONFIRM")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background: #E63946; color: white; border: none; border-radius: 4px;
                padding: 6px 12px; font-weight: bold; font-size: 10px;
            }
            QPushButton:hover { background: #FF4D5A; }
        """)
        self.confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self.confirm_btn)

        self.cancel_btn = QPushButton("CANCEL")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #2B2D42; color: #8D99AE; border: 1px solid #4A4E69;
                border-radius: 4px; padding: 6px 12px; font-size: 10px;
            }
            QPushButton:hover { background: #3A3D5A; color: white; }
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)

        lay.addLayout(btn_row)

    def set_content(self, title: str, detail: str) -> None:
        self.title_lbl.setText(title.upper())
        self.detail_lbl.setText(detail)
        self.adjustSize()

    def _on_confirm(self) -> None:
        confirm_gate.resolve()
        self.hide()

    def _on_cancel(self) -> None:
        confirm_gate.cancel()
        self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QBrush(QColor(15, 23, 42, 245)))
        p.setPen(QPen(QColor(230, 57, 70, 180), 1.5))
        p.drawRoundedRect(rect, 8, 8)


# ── Ghost Target Overlay Widget ───────────────────────────────────────────────
class GhostTargetOverlay(QWidget):
    """
    Transparent, click-through desktop overlay that displays a sci-fi targeting
    reticle and expanding ripple over elements when JARVIS locates or clicks them.
    """

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._active = False
        self._target_x = 0
        self._target_y = 0
        self._label = ""
        self._progress = 0.0

        # Full desktop coverage
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60 FPS
        self._anim_timer.timeout.connect(self._step_anim)

    def trigger_target(self, x: int, y: int, label: str = "") -> None:
        self._target_x = int(x)
        self._target_y = int(y)
        self._label = str(label or "")
        self._progress = 0.0
        self._active = True
        self.show()
        self._anim_timer.start()

    def _step_anim(self) -> None:
        self._progress += 0.05
        if self._progress >= 1.0:
            self._anim_timer.stop()
            self._active = False
            self.hide()
        self.update()

    def paintEvent(self, _):
        if not self._active:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        alpha = max(0, int((1.0 - self._progress) * 230))
        cx = float(self._target_x)
        cy = float(self._target_y)

        # Expanding ripple ring
        r = 10.0 + (self._progress * 26.0)
        ring_col = QColor(0, 240, 255, alpha)
        pen = QPen(ring_col, 2.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Outer crosshairs
        ch_len = 8.0 + (self._progress * 6.0)
        p.drawLine(QPointF(cx - r - ch_len, cy), QPointF(cx - r + 2, cy))
        p.drawLine(QPointF(cx + r - 2, cy), QPointF(cx + r + ch_len, cy))
        p.drawLine(QPointF(cx, cy - r - ch_len), QPointF(cx, cy - r + 2))
        p.drawLine(QPointF(cx, cy + r - 2), QPointF(cx, cy + r + ch_len))

        # Center dot
        p.setBrush(QBrush(QColor(0, 240, 255, alpha)))
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)

        # Label tag if available
        if self._label and self._progress < 0.8:
            lbl_alpha = max(0, int((0.8 - self._progress) * 255))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.setPen(QPen(QColor(240, 248, 255, lbl_alpha)))
            p.drawText(int(cx + r + 6), int(cy + 4), self._label[:30])


# ── The Interactive Desktop Orb Widget ────────────────────────────────────────
class OrbWidget(QWidget):
    """The circular, draggable, reactive desktop orb."""

    def __init__(self, ui_controller: JarvisOrbUI):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.ui_ctrl = ui_controller

        self.orb_size = 80
        self.setFixedSize(self.orb_size, self.orb_size)

        # Dragging state
        self._dragging = False
        self._drag_start = QPoint()

        # Animation states
        self._state = "SLEEPING"   # SLEEPING | LISTENING | SPEAKING | THINKING | WORKING
        self._audio_level = 0.0    # 0.0 - 1.0 smoothed mic level
        self._target_level = 0.0
        self._phase = 0.0
        self._orbit_angle = 0.0
        self._click_flash = 0.0    # Click ripple flash 0.0 -> 1.0

        # Confirmation pill window
        self._confirm_pill = ConfirmPill()

        # Position restore
        saved_pos = get_orb_position()
        if saved_pos:
            self.move(saved_pos[0], saved_pos[1])
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.x() + screen.width() - 120, screen.y() + screen.height() - 140)

        # 40 FPS render loop
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(25)

        self.setToolTip("JARVIS Desktop Assistant\n• Click: Mute / Unmute\n• Double-click: Wake / Sleep\n• Drag: Move anywhere")

    def set_state(self, state: str) -> None:
        self._state = str(state).strip().upper()
        self.update()

    def set_audio_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, float(level)))

    def _tick(self) -> None:
        # Smooth audio level
        self._audio_level += (self._target_level - self._audio_level) * 0.35

        # Progress animation phases
        if self._state == "SLEEPING":
            self._phase += 0.04
        elif self._state == "LISTENING":
            self._phase += 0.10
        elif self._state in ("THINKING", "WORKING"):
            self._phase += 0.08
            self._orbit_angle = (self._orbit_angle + 4.5) % 360.0
        elif self._state == "SPEAKING":
            self._phase += 0.12
        elif self._state == "ALERT":
            self._phase += 0.14

        if self._click_flash > 0.01:
            self._click_flash *= 0.82
        else:
            self._click_flash = 0.0

        self.update()

    def trigger_alert_pulse(self, message: str, duration_seconds: float = 6.0) -> None:
        """Pulses in Amber alert state for duration_seconds then smoothly reverts."""
        prev = self._state
        self.set_state("ALERT")
        self.setToolTip(f"JARVIS ALERT:\n{message}")

        def _revert():
            if self._state == "ALERT":
                self.set_state(prev)
                self.setToolTip("JARVIS Desktop Assistant\n• Click: Mute / Unmute\n• Double-click: Wake / Sleep\n• Drag: Move anywhere")

        QTimer.singleShot(int(duration_seconds * 1000), _revert)

    # ── Mouse Interaction ─────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(e.globalPosition().toPoint())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging and e.buttons() & Qt.MouseButton.LeftButton:
            new_pos = e.globalPosition().toPoint() - self._drag_start
            self.move(new_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            # Persist orb position
            pos = self.pos()
            save_orb_position(pos.x(), pos.y())

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Toggle wake/sleep manually
            if self.ui_ctrl.on_wake_manual:
                self.ui_ctrl.on_wake_manual()
            e.accept()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self._click_time = time.monotonic()
            self._press_pos = e.globalPosition().toPoint()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            # If release was within 5 pixels and 300ms, treat as click
            if hasattr(self, "_press_pos"):
                dist = (e.globalPosition().toPoint() - self._press_pos).manhattanLength()
                if dist < 6 and (time.monotonic() - getattr(self, "_click_time", 0)) < 0.35:
                    self._on_single_click()

    def _on_single_click(self) -> None:
        """Single click toggles mute/unmute instantly."""
        self._click_flash = 1.0
        self.ui_ctrl.muted = not self.ui_ctrl.muted
        status = "Muted" if self.ui_ctrl.muted else "Unmuted"
        self.setToolTip(f"JARVIS: {status}\n• Click: Mute / Unmute\n• Drag: Move")
        self.update()

    # ── Context Menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid #1E293B;
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1E293B;
                color: #38BDF8;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        # Status Header
        is_muted = self.ui_ctrl.muted
        state_str = "MUTED" if is_muted else self._state
        header = menu.addAction(f"JARVIS • {state_str}")
        header.setEnabled(False)
        menu.addSeparator()

        # Mute Toggle
        mute_act = menu.addAction("🔊  Unmute Microphone" if is_muted else "🔇  Mute Microphone")
        mute_act.triggered.connect(self._on_single_click)

        # Wake / Sleep Toggle
        if self._state == "SLEEPING":
            wake_act = menu.addAction("⚡  Wake Up Now")
            wake_act.triggered.connect(lambda: self.ui_ctrl.on_wake_manual() if self.ui_ctrl.on_wake_manual else None)
        else:
            sleep_act = menu.addAction("🌙  Put to Sleep")
            sleep_act.triggered.connect(lambda: self.ui_ctrl.on_wake_manual() if self.ui_ctrl.on_wake_manual else None)

        menu.addSeparator()

        # Auto-start on boot
        autostart_on = is_autostart_enabled()
        auto_act = menu.addAction("✓  Auto-Start on Boot" if autostart_on else "○  Auto-Start on Boot")
        auto_act.triggered.connect(lambda: set_autostart_enabled(not autostart_on))

        # Push to talk toggle
        ptt_on = get_push_to_talk_enabled()
        ptt_act = menu.addAction("✓  Push-to-Talk (Ctrl+Space)" if ptt_on else "○  Push-to-Talk")
        ptt_act.triggered.connect(lambda: self.ui_ctrl.on_push_to_talk(not ptt_on) if self.ui_ctrl.on_push_to_talk else None)

        menu.addSeparator()

        # API Key Reconfig
        reconfig_act = menu.addAction("⚙  API Key Configuration")
        reconfig_act.triggered.connect(self.ui_ctrl.prompt_reconfig)

        # Reset Orb Position
        reset_act = menu.addAction("⌖  Reset Orb Position")
        reset_act.triggered.connect(self._reset_position)

        # Switch UI mode
        island_act = menu.addAction("⚡  Switch to Top Island Bar")
        island_act.triggered.connect(self._switch_to_island)

        hud_act = menu.addAction("🖥  Switch to Holographic HUD")
        hud_act.triggered.connect(self._switch_to_hud)

        menu.addSeparator()

        # Quit
        quit_act = menu.addAction("✕  Quit Assistant")
        quit_act.triggered.connect(QApplication.instance().quit)

        menu.exec(global_pos)

    def _reset_position(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        x, y = screen.width() - 120, screen.height() - 150
        self.move(x, y)
        save_orb_position(x, y)

    def _switch_to_island(self) -> None:
        save_ui_mode("island")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Mode Changed",
            "UI Mode switched to Dynamic Top Island Bar. Please restart JARVIS to launch the new bar.",
        )

    def _switch_to_hud(self) -> None:
        save_ui_mode("hud")
        # Inform user to restart for mode change
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Mode Changed",
            "UI Mode switched to Full HUD. Please restart JARVIS to launch the 3D window.",
        )

    # ── Paint Event (Aesthetics) ──────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W = float(self.width())
        H = float(self.height())
        cx = W / 2.0
        cy = H / 2.0
        base_r = (W / 2.0) - 10.0

        is_muted = self.ui_ctrl.muted

        # Select color theme based on state
        if is_muted:
            primary_col = OrbColors.MUTE_RED
            core_col = OrbColors.MUTE_CORE
            pulse = math.sin(self._phase * 0.8) * 0.15
        elif self._state == "LISTENING":
            primary_col = OrbColors.LISTEN_CYAN
            core_col = OrbColors.LISTEN_CORE
            # Expand with audio level
            pulse = (self._audio_level * 0.45) + (math.sin(self._phase) * 0.05)
        elif self._state == "SPEAKING":
            primary_col = OrbColors.SPEAK_BLUE
            core_col = OrbColors.LISTEN_CORE
            pulse = math.sin(self._phase * 1.5) * 0.18
        elif self._state in ("THINKING", "WORKING"):
            primary_col = OrbColors.THINK_GOLD
            core_col = OrbColors.THINK_AMBER
            pulse = math.sin(self._phase) * 0.12
        elif self._state == "ALERT":
            primary_col = QColor(255, 120, 0)
            core_col = QColor(255, 200, 100)
            pulse = math.sin(self._phase * 2.0) * 0.20
        else:  # SLEEPING
            primary_col = OrbColors.SLEEP_CYAN
            core_col = OrbColors.SLEEP_DEEP
            pulse = math.sin(self._phase) * 0.08

        # Add click ripple flash
        if self._click_flash > 0.01:
            pulse += self._click_flash * 0.25

        current_r = base_r * (1.0 + pulse)

        # 1. Outer Ambient Aura
        aura = QRadialGradient(cx, cy, current_r * 1.35)
        c_aura = QColor(primary_col)
        c_aura.setAlpha(int(65 + (pulse * 40)))
        aura.setColorAt(0.0, c_aura)
        aura.setColorAt(0.7, QColor(primary_col.red(), primary_col.green(), primary_col.blue(), 25))
        aura.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(aura))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), current_r * 1.35, current_r * 1.35)

        # 2. Outer Rotating Orbital Rings (THINKING / WORKING mode)
        if self._state in ("THINKING", "WORKING"):
            p.save()
            p.translate(cx, cy)
            p.rotate(self._orbit_angle)
            orbit_pen = QPen(primary_col, 2.0, Qt.PenStyle.DashLine)
            p.setPen(orbit_pen)
            p.drawEllipse(QPointF(0, 0), current_r * 1.12, current_r * 1.12)

            p.rotate(-self._orbit_angle * 1.6)
            orbit_pen2 = QPen(core_col, 1.5, Qt.PenStyle.DotLine)
            p.setPen(orbit_pen2)
            p.drawEllipse(QPointF(0, 0), current_r * 1.22, current_r * 1.22)
            p.restore()

        # 3. Glassmorphic Sphere Body
        grad = QRadialGradient(cx - (current_r * 0.28), cy - (current_r * 0.28), current_r)
        c_center = QColor(core_col)
        c_center.setAlpha(240 if not is_muted else 210)
        c_edge = QColor(primary_col)
        c_edge.setAlpha(180)
        c_dark = QColor(10, 15, 25, 230)

        grad.setColorAt(0.0, c_center)
        grad.setColorAt(0.55, c_edge)
        grad.setColorAt(1.0, c_dark)

        p.setBrush(QBrush(grad))
        glow_pen = QPen(QColor(primary_col.red(), primary_col.green(), primary_col.blue(), 220), 1.8)
        p.setPen(glow_pen)
        p.drawEllipse(QPointF(cx, cy), current_r, current_r)

        # 4. Specular Highlight (Glass Shine)
        spec = QRadialGradient(cx - (current_r * 0.32), cy - (current_r * 0.35), current_r * 0.55)
        spec.setColorAt(0.0, QColor(255, 255, 255, 160))
        spec.setColorAt(0.6, QColor(255, 255, 255, 30))
        spec.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(spec))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - (current_r * 0.2), cy - (current_r * 0.22)), current_r * 0.45, current_r * 0.35)

        # 5. Mute Indicator Icon if muted
        if is_muted:
            p.setPen(QPen(QColor(255, 255, 255, 230), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx - 10, cy - 10), QPointF(cx + 10, cy + 10))
            p.setPen(QPen(QColor(230, 57, 70, 220), 1.8))
            p.drawEllipse(QPointF(cx, cy), 12, 12)

    def show_confirm_banner(self, title: str, detail: str) -> None:
        """Position confirmation pill near the Orb."""
        orb_geom = self.frameGeometry()
        pill_x = max(10, orb_geom.left() - 290)
        pill_y = max(10, orb_geom.top() - 20)
        self._confirm_pill.set_content(title, detail)
        self._confirm_pill.move(pill_x, pill_y)
        self._confirm_pill.show()

    def hide_confirm_banner(self) -> None:
        self._confirm_pill.hide()


# ── API Key Setup Dialog for Orb Mode ─────────────────────────────────────────
class KeyConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("JARVIS — API Key Setup")
        self.setFixedSize(380, 160)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.x() + (screen.width() - 380) // 2,
                  screen.y() + (screen.height() - 160) // 2)
        self.setStyleSheet("""
            QDialog { background-color: #0F172A; color: white; font-family: 'Segoe UI', sans-serif; }
            QLabel { color: #E2E8F0; font-size: 12px; }
            QLineEdit {
                background: #1E293B; color: white; border: 1px solid #334155;
                border-radius: 6px; padding: 8px; font-size: 12px;
            }
            QPushButton {
                background: #0284C7; color: white; border: none; border-radius: 6px;
                padding: 8px 16px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #0369A1; }
        """)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        lbl = QLabel("Enter your Google Gemini API Key to activate JARVIS:")
        lay.addWidget(lbl)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("AIzaSy...")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        existing = get_gemini_key()
        if existing:
            self.key_edit.setText(existing)
        lay.addWidget(self.key_edit)

        save_btn = QPushButton("Save & Connect")
        save_btn.clicked.connect(self._save)
        lay.addWidget(save_btn)

    def _save(self):
        k = self.key_edit.text().strip()
        if len(k) > 10:
            save_api_keys(k)
            self.accept()


# ── The Root Shim for mainloop() ──────────────────────────────────────────────
class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


# ── Duck-Typed JarvisOrbUI (Drop-in replacement for JarvisUI) ─────────────────
class JarvisOrbUI(QObject):
    """
    Main UI controller exposing the exact duck-typed contract expected by
    JarvisLive in main.py, driving the Desktop Orb instead of the full HUD.
    """

    _state_sig = pyqtSignal(str)
    _log_sig = pyqtSignal(str)
    _alert_sig = pyqtSignal(str)
    _target_highlight_sig = pyqtSignal(int, int, str)
    _confirm_sig = pyqtSignal(str, str)
    _confirm_hide_sig = pyqtSignal()
    _reconfig_sig = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")

        global _ACTIVE_ORB_UI
        _ACTIVE_ORB_UI = self

        self._muted = False
        self._ready = bool(get_gemini_key() and len(get_gemini_key()) > 15)

        # Callbacks (assigned by JarvisLive)
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

        self._assistant_name = get_assistant_name()

        # Instantiate Orb Widget & Ghost Target Overlay
        self._orb = OrbWidget(self)
        self._ghost_overlay = GhostTargetOverlay()
        self.root = _RootShim(self._app)

        # Wire Qt signals for thread-safe cross-thread calls
        self._state_sig.connect(self._orb.set_state)
        self._alert_sig.connect(self._orb.trigger_alert_pulse)
        self._target_highlight_sig.connect(self._ghost_overlay.trigger_target)
        self._confirm_sig.connect(self._orb.show_confirm_banner)
        self._confirm_hide_sig.connect(self._orb.hide_confirm_banner)
        self._log_sig.connect(self._on_log)
        self._reconfig_sig.connect(self._do_prompt_reconfig)

        # Tray Icon
        self._tray = None
        self._setup_tray()

        self._orb.show()
        self._orb.raise_()
        self._orb.activateWindow()

        # If API key is not configured, prompt user on the Qt main thread
        if not self._ready:
            QTimer.singleShot(250, self._do_prompt_reconfig)

    def _setup_tray(self) -> None:
        try:
            self._tray = QSystemTrayIcon(self._orb)
            # Create a simple colored icon for the tray
            pix = QPixmap(24, 24)
            pix.fill(Qt.GlobalColor.transparent)
            tp = QPainter(pix)
            tp.setRenderHint(QPainter.RenderHint.Antialiasing)
            tp.setBrush(QBrush(OrbColors.SLEEP_CYAN))
            tp.setPen(Qt.PenStyle.NoPen)
            tp.drawEllipse(3, 3, 18, 18)
            tp.end()
            self._tray.setIcon(QIcon(pix))
            self._tray.setToolTip(f"{self._assistant_name} Desktop Assistant")

            tray_menu = QMenu()
            m_wake = tray_menu.addAction("⚡ Wake / Sleep")
            m_wake.triggered.connect(lambda: self.on_wake_manual() if self.on_wake_manual else None)
            m_mute = tray_menu.addAction("🔇 Toggle Mute")
            m_mute.triggered.connect(lambda: setattr(self, "muted", not self.muted))
            tray_menu.addSeparator()
            m_quit = tray_menu.addAction("✕ Quit")
            m_quit.triggered.connect(self._app.quit)
            self._tray.setContextMenu(tray_menu)
            self._tray.show()
        except Exception as e:
            print(f"[OrbTray] Could not initialize system tray: {e}")

    # ── Mute Property ─────────────────────────────────────────────────────────

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, v: bool):
        self._muted = bool(v)
        self._orb.update()

    @property
    def current_file(self) -> str | None:
        return None

    @property
    def assistant_name(self) -> str:
        return self._assistant_name

    # ── Public API matching JarvisUI ──────────────────────────────────────────

    def set_state(self, state: str):
        self._state_sig.emit(state)

    def set_audio_level(self, level: float) -> None:
        self._orb.set_audio_level(level)

    def write_log(self, text: str):
        self._log_sig.emit(text)

    def _on_log(self, text: str):
        print(f"[ORB LOG] {text}")

    def wait_for_api_key(self):
        while not self._ready:
            time.sleep(0.2)

    def prompt_reconfig(self):
        self._reconfig_sig.emit()

    def _do_prompt_reconfig(self):
        dlg = KeyConfigDialog(self._orb)
        dlg.exec()
        self._ready = bool(get_gemini_key() and len(get_gemini_key()) > 15)

    def show_confirm(self, title: str, detail: str) -> None:
        self._confirm_sig.emit(str(title)[:120], str(detail)[:300])

    def hide_confirm(self) -> None:
        self._confirm_hide_sig.emit()

    def trigger_alert(self, msg: str) -> None:
        self._alert_sig.emit(str(msg))

    def highlight_target(self, x: int, y: int, label: str = "") -> None:
        self._target_highlight_sig.emit(int(x), int(y), str(label))

    def show_content(self, title: str, text: str):
        print(f"[Content] {title}: {text[:140]}...")

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
        if self._tray:
            self._tray.showMessage("JARVIS", "Remote phone dashboard connected.", QSystemTrayIcon.MessageIcon.Information, 2500)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def show_video(self, source: str, title: str = "", muted: bool = True, audio_source: str = ""):
        pass

    def stop_video(self):
        pass

    def set_video_muted(self, muted: bool):
        pass

    def video_is_playing(self) -> bool:
        return False

    def start_camera_stream(self):
        pass

    def stop_camera_stream(self):
        pass

    def show_camera_frame(self, img_bytes: bytes):
        pass


_ACTIVE_ORB_UI: Optional[JarvisOrbUI] = None

def get_active_orb_ui() -> Optional[JarvisOrbUI]:
    """Returns the globally active JarvisOrbUI instance if running in Orb mode."""
    global _ACTIVE_ORB_UI
    return _ACTIVE_ORB_UI
