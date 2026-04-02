"""
CaptureThread — reads frames from a V4L2 (or webcam) device via OpenCV
and emits them as Qt signals for the UI to display.
"""
import time

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

import config


class CaptureThread(QThread):
    frame_ready  = pyqtSignal(np.ndarray)   # emitted for every decoded frame
    device_lost  = pyqtSignal()             # emitted after consecutive read failures

    # How many consecutive failed reads before we declare device lost
    _MAX_FAILURES = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    # ── Public API ──────────────────────────────────────────────────────────────

    def stop(self):
        """Signal the thread to stop. Call wait() afterwards."""
        self._running = False

    # ── Thread body ────────────────────────────────────────────────────────────

    def run(self):
        self._running = True
        failures = 0

        device = config.VIDEO_DEVICE
        # OpenCV expects an integer index for webcams, a string path for V4L2
        device_arg = int(device) if device.isdigit() else device

        cap = cv2.VideoCapture(device_arg, cv2.CAP_V4L2 if config.IS_LINUX else cv2.CAP_ANY)

        if not cap.isOpened():
            self.device_lost.emit()
            return

        # Request the desired resolution; the device may not honour it exactly
        if not config.DEV_MODE:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.DEFAULT_FORMAT.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.DEFAULT_FORMAT.height)
            try:
                fps = float(config.DEFAULT_FORMAT.fps)
                cap.set(cv2.CAP_PROP_FPS, fps)
            except ValueError:
                pass  # fractional fps strings like '30000/1001' handled by ffmpeg only

        target_interval = 1.0 / 25.0   # aim for ~25 fps display regardless of capture fps
        last_emit = 0.0

        while self._running:
            ret, frame = cap.read()

            if not ret:
                failures += 1
                if failures >= self._MAX_FAILURES:
                    cap.release()
                    self.device_lost.emit()
                    return
                time.sleep(0.05)
                continue

            failures = 0

            now = time.monotonic()
            if now - last_emit >= target_interval:
                self.frame_ready.emit(frame)
                last_emit = now

        cap.release()
