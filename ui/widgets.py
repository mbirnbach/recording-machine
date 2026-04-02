"""
Custom widgets for the Recording Machine UI.
"""
import numpy as np
from PyQt6.QtWidgets import QLabel, QWidget, QHBoxLayout, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QImage, QPixmap, QFont, QPainter, QColor, QPen

# ── Palette ─────────────────────────────────────────────────────────────────────
C = dict(
    bg      = '#0f0f0f',
    panel   = '#161616',
    border  = '#2a2a2a',
    text    = '#e8e8e8',
    dim     = '#4a4a4a',
    red     = '#e63946',
    blue    = '#4a9eff',
    green   = '#2ecc71',
    amber   = '#f4a261',
)


class VideoFrame(QLabel):
    """
    A QLabel that displays video frames with correct aspect-ratio letterboxing.
    Accepts numpy BGR frames or a QPixmap directly.
    Shows a 'NO SIGNAL' placeholder when no frame has been set.
    """

    ASPECT = 4 / 3   # Standard-definition analogue video

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f'background: #000;')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._last_pix: QPixmap | None = None
        self._has_signal = False

    def set_frame(self, frame: np.ndarray):
        """Display a BGR numpy array from OpenCV."""
        h, w, ch = frame.shape
        rgb = frame[:, :, ::-1].copy()  # BGR -> RGB, contiguous
        img = QImage(rgb.data, w, h, w * ch, QImage.Format.Format_RGB888)
        self.set_pixmap(QPixmap.fromImage(img))
        self._has_signal = True

    def set_pixmap(self, pix: QPixmap):
        """Display a pre-built pixmap, scaled to fit with letterboxing."""
        self._last_pix = pix
        self._refresh_scaled()

    def freeze(self):
        """Keep showing the current frame but mark as frozen (no new frames)."""
        # Nothing to do visually — caller adds a REC overlay on top
        pass

    def clear_signal(self):
        """Show the NO SIGNAL placeholder."""
        self._has_signal = False
        self._last_pix = None
        self.setPixmap(QPixmap())   # blank
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scaled()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._has_signal:
            self._paint_no_signal()

    def _refresh_scaled(self):
        if self._last_pix is None:
            return
        scaled = self._last_pix.scaled(
            self.width(), self.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        # Use parent's setPixmap (skips our override to avoid recursion)
        QLabel.setPixmap(self, scaled)

    def _paint_no_signal(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Dark grey text
        painter.setPen(QColor(C['dim']))
        font = QFont('monospace', 14)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'NO SIGNAL')
        painter.end()


class RecordingBadge(QWidget):
    """
    A blinking red dot + elapsed time label shown during recording.
    Idle state: dim grey dot, 'STANDBY'.
    Recording state: blinking red dot, 'REC  HH:MM:SS'.
    Stopping state: amber dot, 'STOPPING…'.
    Error state: red dot, error message.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._dot = QLabel('●')
        self._dot.setFont(QFont('monospace', 20))
        self._dot.setFixedWidth(22)

        self._text = QLabel('STANDBY')
        self._text.setFont(QFont('monospace', 14))

        layout.addWidget(self._dot)
        layout.addWidget(self._text)

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_on = True

        self._set_idle()

    # ── Public API ──────────────────────────────────────────────────────────────

    def set_idle(self):
        self._blink_timer.stop()
        self._set_idle()

    def set_recording(self, elapsed: str = '00:00:00'):
        self._blink_timer.start()
        self._blink_on = True
        self._dot.setStyleSheet(f'color: {C["red"]};')
        self._text.setStyleSheet(f'color: {C["text"]};')
        self._text.setText(f'REC  {elapsed}')

    def update_time(self, elapsed: str):
        current = self._text.text()
        if current.startswith('REC'):
            self._text.setText(f'REC  {elapsed}')

    def set_starting(self):
        self._blink_timer.stop()
        self._dot.setStyleSheet(f'color: {C["amber"]};')
        self._text.setStyleSheet(f'color: {C["amber"]};')
        self._text.setText('STARTING…')

    def set_stopping(self):
        self._blink_timer.stop()
        self._dot.setStyleSheet(f'color: {C["amber"]};')
        self._text.setStyleSheet(f'color: {C["amber"]};')
        self._text.setText('STOPPING…')

    def set_error(self, msg: str):
        self._blink_timer.stop()
        self._dot.setStyleSheet(f'color: {C["red"]};')
        self._text.setStyleSheet(f'color: {C["red"]};')
        self._text.setText(msg[:50])

    def set_no_device(self):
        self._blink_timer.stop()
        self._dot.setStyleSheet(f'color: {C["dim"]};')
        self._text.setStyleSheet(f'color: {C["amber"]};')
        self._text.setText('NO DEVICE')

    # ── Internal ───────────────────────────────────────────────────────────────

    def _set_idle(self):
        self._dot.setStyleSheet(f'color: {C["dim"]};')
        self._text.setStyleSheet(f'color: {C["dim"]};')
        self._text.setText('STANDBY')

    def _blink(self):
        self._blink_on = not self._blink_on
        color = C['red'] if self._blink_on else C['dim']
        self._dot.setStyleSheet(f'color: {color};')


class FieldLabel(QLabel):
    """Small monospace uppercase label used above input fields."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont('monospace', 9))
        self.setStyleSheet(f'color: {C["dim"]}; letter-spacing: 2px;')
