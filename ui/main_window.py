"""
MainWindow — state machine, keyboard handling, and top-level layout.

States:
    NO_DEVICE   video device not found / disconnected
    PREVIEW     live feed showing, ready to record
    RECORDING   FFmpeg running, device owned by FFmpeg
    STOPPING    waiting for FFmpeg to finalise the container
    ERROR       unrecoverable error, user must acknowledge
"""
from __future__ import annotations
import datetime
import shutil
from enum import Enum, auto
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QFrame, QSizePolicy, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QFont, QKeyEvent

import config
from core.capture import CaptureThread
from core.recorder import Recorder
from core.device import probe_video_device, probe_audio_device, free_bytes, check_ffmpeg
from ui.widgets import VideoFrame, RecordingBadge, FieldLabel, C


# ── App state ────────────────────────────────────────────────────────────────────
class AppState(Enum):
    NO_DEVICE = auto()
    PREVIEW   = auto()
    STARTING  = auto()   # releasing OpenCV + launching FFmpeg (background)
    RECORDING = auto()
    STOPPING  = auto()
    ERROR     = auto()


# ── Tab interceptor ───────────────────────────────────────────────────────────────
class TabInterceptor(QObject):
    """
    Installed on QApplication to intercept Tab key before Qt focus traversal.
    Routes Tab to the main window's cycle_focus() method.
    """
    def __init__(self, window: 'MainWindow'):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Tab:
                self._window.cycle_focus(1)
                return True
            if event.key() == Qt.Key.Key_Backtab:   # Shift+Tab
                self._window.cycle_focus(-1)
                return True
        return False


# ── Input field ────────────────────────────────────────────────────────────────────
def _make_input(width: int) -> QLineEdit:
    inp = QLineEdit()
    inp.setFixedWidth(width)
    inp.setFont(QFont('monospace', 18))
    inp.setStyleSheet(f'''
        QLineEdit {{
            background: {C["bg"]};
            color: {C["text"]};
            border: 1px solid {C["border"]};
            border-radius: 4px;
            padding: 6px 12px;
        }}
        QLineEdit:focus {{
            border: 1px solid {C["blue"]};
        }}
        QLineEdit:disabled {{
            color: {C["dim"]};
            border-color: {C["border"]};
        }}
    ''')
    return inp


# ── Separator ────────────────────────────────────────────────────────────────────
def _make_vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet(f'background: {C["border"]};')
    return sep


# ── MainWindow ────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._state = AppState.NO_DEVICE
        self._capture: CaptureThread | None = None
        self._recorder = Recorder(self)
        self._recorder.recording_failed.connect(self._on_recording_failed)
        self._recorder.frame_ready.connect(self._on_frame)   # live preview during recording
        self._audio_device: str | None = None
        self._record_start: datetime.datetime | None = None
        self._last_frame: np.ndarray | None = None
        self._preview_enabled = True

        # Timers
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._update_duration)

        self._device_poll = QTimer(self)
        self._device_poll.setInterval(3000)
        self._device_poll.timeout.connect(self._check_device)

        self._setup_ui()
        self._setup_keyboard()

        # Startup checks
        if not check_ffmpeg():
            self._enter_error('FFmpeg not found — install it first:\nsudo apt install ffmpeg')
            return

        self._audio_device = probe_audio_device()
        self._check_device()
        self._device_poll.start()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle('Recording Machine')
        self.setStyleSheet(f'''
            QMainWindow, QWidget {{ background: {C["bg"]}; color: {C["text"]}; }}
            QRadioButton {{
                color: {C["dim"]};
                font-family: monospace;
                font-size: 12px;
                spacing: 7px;
                padding: 2px 8px 2px 2px;
                border-radius: 3px;
            }}
            QRadioButton:focus {{
                color: {C["text"]};
                background: rgba(255, 255, 255, 0.06);
            }}
            QRadioButton::indicator {{
                width: 15px;
                height: 15px;
                border-radius: 8px;
                border: 2px solid #383838;
                background: {C["bg"]};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {C["blue"]};
                background: {C["blue"]};
            }}

            QRadioButton:disabled {{
                color: #282828;
            }}
            QRadioButton::indicator:disabled {{
                border-color: #222222;
                background: {C["bg"]};
            }}
        ''')
        self.showFullScreen()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Video area ─────────────────────────────────────────────────────────
        self._video = VideoFrame()
        root.addWidget(self._video, stretch=1)

        # ── Control panel ──────────────────────────────────────────────────────
        panel = QWidget()
        panel.setFixedHeight(130)
        panel.setStyleSheet(f'background: {C["panel"]}; border-top: 2px solid {C["border"]};')
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # ── Top row: project / reel / status ───────────────────────────────────
        top_row = QWidget()
        top_row.setFixedHeight(80)
        row = QHBoxLayout(top_row)
        row.setContentsMargins(28, 0, 28, 0)
        row.setSpacing(28)

        proj_col = QVBoxLayout()
        proj_col.setSpacing(4)
        proj_col.addWidget(FieldLabel('PROJECT'))
        self._proj_input = _make_input(240)
        self._proj_input.setPlaceholderText('project name')
        proj_col.addWidget(self._proj_input)
        row.addLayout(proj_col)

        row.addWidget(_make_vsep())

        reel_col = QVBoxLayout()
        reel_col.setSpacing(4)
        reel_col.addWidget(FieldLabel('REEL / TAPE'))
        self._reel_input = _make_input(110)
        self._reel_input.setPlaceholderText('001')
        reel_col.addWidget(self._reel_input)
        row.addLayout(reel_col)

        row.addWidget(_make_vsep())

        status_col = QVBoxLayout()
        status_col.setSpacing(4)
        status_col.addWidget(FieldLabel('STATUS'))
        self._badge = RecordingBadge()
        status_col.addWidget(self._badge)
        row.addLayout(status_col)

        row.addStretch()

        hints = QLabel('ENTER  start/stop    F2  new project    F6  toggle preview    TAB  next field    ←→  change option    ESC  quit')
        hints.setFont(QFont('monospace', 10))
        hints.setStyleSheet(f'color: {C["dim"]};')
        row.addWidget(hints)

        panel_layout.addWidget(top_row)

        # ── Divider ────────────────────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f'background: {C["border"]};')
        panel_layout.addWidget(div)

        # ── Bottom row: format settings ────────────────────────────────────────
        bot_row = QWidget()
        bot_row.setFixedHeight(48)
        brow = QHBoxLayout(bot_row)
        brow.setContentsMargins(28, 0, 28, 0)
        brow.setSpacing(28)

        # Format (PAL / NTSC)
        brow.addWidget(FieldLabel('FORMAT'))
        self._fmt_group = QButtonGroup(self)
        self._fmt_buttons: list[QRadioButton] = []
        for i, fmt in enumerate(config.VIDEO_FORMATS):
            rb = QRadioButton(f'{fmt.label}  {fmt.width}×{fmt.height} @ {fmt.fps}fps')
            self._fmt_group.addButton(rb, i)
            brow.addWidget(rb)
            self._fmt_buttons.append(rb)
            if fmt is config.DEFAULT_FORMAT:
                rb.setChecked(True)

        brow.addWidget(_make_vsep())

        # Codec (H.264 / H.265)
        brow.addWidget(FieldLabel('CODEC'))
        self._codec_group = QButtonGroup(self)
        self._codec_buttons: list[QRadioButton] = []
        for i, codec in enumerate(config.CODECS):
            rb = QRadioButton(codec.label)
            self._codec_group.addButton(rb, i)
            brow.addWidget(rb)
            self._codec_buttons.append(rb)
            if codec is config.DEFAULT_CODEC:
                rb.setChecked(True)

        brow.addWidget(_make_vsep())

        # Audio mode (Stereo / Mono R)
        brow.addWidget(FieldLabel('AUDIO'))
        self._audio_group = QButtonGroup(self)
        self._audio_buttons: list[QRadioButton] = []
        for i, mode in enumerate(config.AUDIO_MODES):
            rb = QRadioButton(mode.label)
            self._audio_group.addButton(rb, i)
            brow.addWidget(rb)
            self._audio_buttons.append(rb)
            if mode is config.DEFAULT_AUDIO_MODE:
                rb.setChecked(True)

        brow.addStretch()

        # Disk space warning
        self._disk_warning = QLabel('LOW DISK SPACE')
        self._disk_warning.setFont(QFont('monospace', 10))
        self._disk_warning.setStyleSheet(f'color: {C["amber"]};')
        self._disk_warning.hide()
        brow.addWidget(self._disk_warning)

        panel_layout.addWidget(bot_row)
        root.addWidget(panel)

        # Text inputs (for enable/disable)
        self._inputs = [self._proj_input, self._reel_input]
        # Full Tab cycle: every individual widget in order
        self._focusable = [
            self._proj_input,
            self._reel_input,
            *self._fmt_buttons,
            *self._codec_buttons,
            *self._audio_buttons,
        ]
        self._focus_index = 0
        self._proj_input.setFocus()

    def _setup_keyboard(self):
        """Install our Tab interceptor on the QApplication."""
        from PyQt6.QtWidgets import QApplication
        self._tab_interceptor = TabInterceptor(self)
        QApplication.instance().installEventFilter(self._tab_interceptor)

    # ── Focus cycling ──────────────────────────────────────────────────────────

    def cycle_focus(self, direction: int = 1):
        if self._state in (AppState.RECORDING, AppState.STOPPING):
            return
        self._focus_index = (self._focus_index + direction) % len(self._focusable)
        self._focusable[self._focus_index].setFocus()

    # ── Keyboard events ────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._handle_enter()

        elif key == Qt.Key.Key_F2:
            self._handle_f2()

        elif key == Qt.Key.Key_F6:
            self._toggle_preview()

        elif key == Qt.Key.Key_Escape:
            self._handle_escape()

        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        # Intercept Enter/F2 from inside QLineEdit widgets
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._handle_enter()
                return True
            elif key == Qt.Key.Key_F2:
                self._handle_f2()
                return True
        return super().eventFilter(obj, event)

    # Install filter on inputs so Enter doesn't just confirm the field
    def _install_input_filters(self):
        for inp in self._inputs:
            inp.installEventFilter(self)

    def _selected_format(self):
        return config.VIDEO_FORMATS[self._fmt_group.checkedId()]

    def _selected_codec(self):
        return config.CODECS[self._codec_group.checkedId()]

    def _selected_audio_mode(self):
        return config.AUDIO_MODES[self._audio_group.checkedId()]

    # ── Key handlers ──────────────────────────────────────────────────────────

    def _handle_enter(self):
        if self._state == AppState.PREVIEW:
            self._start_recording()
        elif self._state == AppState.RECORDING:
            self._stop_recording()
        elif self._state == AppState.ERROR:
            self._enter_state(AppState.NO_DEVICE)
            self._check_device()

    def _handle_f2(self):
        if self._state == AppState.RECORDING:
            self._stop_recording()
        self._proj_input.clear()
        self._reel_input.clear()
        self._proj_input.setFocus()
        self._focus_index = 0

    def _handle_escape(self):
        if self._state == AppState.RECORDING:
            self._stop_recording()
        else:
            self.close()

    # ── State transitions ─────────────────────────────────────────────────────

    def _enter_state(self, state: AppState):
        self._state = state

        is_editable = state == AppState.PREVIEW
        for inp in self._inputs:
            inp.setEnabled(is_editable)
        for rb in self._fmt_buttons + self._codec_buttons + self._audio_buttons:
            rb.setEnabled(is_editable)

    def _enter_error(self, msg: str):
        self._enter_state(AppState.ERROR)
        self._badge.set_error(msg)
        self._video.clear_signal()

    # ── Device polling ────────────────────────────────────────────────────────

    def _check_device(self):
        if self._state in (AppState.RECORDING, AppState.STOPPING):
            return
        found = probe_video_device(config.VIDEO_DEVICE)
        if found and self._state == AppState.NO_DEVICE:
            self._start_capture()
        elif not found and self._state == AppState.PREVIEW:
            self._stop_capture()
            self._enter_state(AppState.NO_DEVICE)
            self._badge.set_no_device()
            self._video.clear_signal()
        self._check_disk()

    def _check_disk(self):
        try:
            free = free_bytes(config.OUTPUT_DIR)
            if free < config.DISK_WARN_BYTES:
                self._disk_warning.show()
            else:
                self._disk_warning.hide()
        except OSError:
            pass

    # ── Capture lifecycle ─────────────────────────────────────────────────────

    def _start_capture(self):
        self._stop_capture()
        self._capture = CaptureThread(self)
        self._capture.frame_ready.connect(self._on_frame)
        self._capture.device_lost.connect(self._on_device_lost)
        self._capture.start()
        self._enter_state(AppState.PREVIEW)
        self._badge.set_idle()

    def _stop_capture(self):
        if self._capture is not None:
            self._capture.stop()
            self._capture.wait(3000)
            self._capture = None

    def _toggle_preview(self):
        self._preview_enabled = not self._preview_enabled
        self._video.set_preview_disabled(not self._preview_enabled)

    def _on_frame(self, frame: np.ndarray):
        self._last_frame = frame
        if self._preview_enabled:
            self._video.set_frame(frame)

    def _on_device_lost(self):
        self._enter_state(AppState.NO_DEVICE)
        self._badge.set_no_device()
        self._video.clear_signal()
        self._capture = None   # thread exits itself

    # ── Recording lifecycle ───────────────────────────────────────────────────

    def _start_recording(self):
        project    = self._proj_input.text().strip() or 'untitled'
        reel       = self._reel_input.text().strip() or '001'
        fmt        = self._selected_format()
        codec      = self._selected_codec()
        audio_mode = self._selected_audio_mode()

        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if free_bytes(config.OUTPUT_DIR) < config.DISK_WARN_BYTES:
            self._badge.set_error('Low disk space — recording not started')
            QTimer.singleShot(3000, lambda: self._badge.set_idle() if self._state == AppState.PREVIEW else None)
            return

        # Lock UI immediately — background thread does the blocking work
        self._enter_state(AppState.STARTING)
        self._badge.set_starting()

        thread = QThread(self)
        error  = [None]

        def _do_start():
            # On Linux/Pi V4L2 only allows one reader — stop OpenCV first.
            # On macOS the camera supports multiple opens so OpenCV keeps running.
            if config.IS_LINUX and not config.DEV_MODE:
                cap = self._capture
                self._capture = None
                if cap is not None:
                    cap.stop()
                    cap.wait(3000)
            # Launch FFmpeg
            try:
                self._recorder.start(
                    project, reel, self._audio_device, fmt, codec, audio_mode,
                )
            except Exception as e:
                error[0] = str(e)

        def _on_started():
            if error[0]:
                self._badge.set_error(error[0][:50])
                self._start_capture()
            else:
                self._record_start = datetime.datetime.now()
                self._enter_state(AppState.RECORDING)
                self._badge.set_recording('00:00:00')
                self._duration_timer.start()
            thread.deleteLater()

        thread.run = _do_start
        thread.finished.connect(_on_started)
        thread.start()

    def _stop_recording(self):
        self._duration_timer.stop()
        self._enter_state(AppState.STOPPING)
        self._badge.set_stopping()

        # Stop FFmpeg in a background thread to avoid blocking UI
        thread = QThread(self)
        recorder = self._recorder

        def _do_stop():
            recorder.stop()

        def _on_stopped():
            self._record_start = None
            self._start_capture()
            # Auto-increment reel number
            self._increment_reel()
            thread.deleteLater()

        thread.run = _do_stop
        thread.finished.connect(_on_stopped)
        thread.start()

    def _increment_reel(self):
        """If reel field contains a number, increment it for the next recording."""
        text = self._reel_input.text().strip()
        if text.isdigit():
            self._reel_input.setText(str(int(text) + 1).zfill(len(text)))
        elif text and text[-1].isdigit():
            # e.g. 'A1' -> 'A2', 'side1' -> 'side2'
            i = len(text) - 1
            while i >= 0 and text[i].isdigit():
                i -= 1
            prefix = text[:i + 1]
            num = text[i + 1:]
            self._reel_input.setText(prefix + str(int(num) + 1).zfill(len(num)))

    def _on_recording_failed(self, msg: str):
        self._duration_timer.stop()
        self._record_start = None
        self._enter_error(f'Recording failed: {msg[:40]}')
        self._start_capture()

    # ── Duration timer ────────────────────────────────────────────────────────

    def _update_duration(self):
        if self._record_start is None:
            return
        elapsed = datetime.datetime.now() - self._record_start
        s = int(elapsed.total_seconds())
        hms = f'{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}'
        self._badge.update_time(hms)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._device_poll.stop()
        self._duration_timer.stop()
        if self._recorder.is_recording:
            self._recorder.stop()
        self._stop_capture()
        event.accept()
