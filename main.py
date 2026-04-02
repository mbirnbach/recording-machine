#!/usr/bin/env python3
"""
Recording Machine
─────────────────
Fullscreen video archiving application for Raspberry Pi + USB video grabber.

Controls:
  ENTER   start / stop recording
  F2      new project (clears fields, stops recording)
  TAB     switch between Project and Reel/Tape input fields
  ESC     quit (or cancel recording first)

Environment variables (all optional):
  VIDEO_DEVICE   V4L2 device path  (default: /dev/video0)
  AUDIO_DEVICE   ALSA device       (default: auto-detect USB audio)
  OUTPUT_DIR     output directory  (default: ~/Recordings)
  VIDEO_WIDTH    capture width     (default: 720)
  VIDEO_HEIGHT   capture height    (default: 576)
  VIDEO_FPS      capture framerate (default: 25)
  DEV_MODE       set to 1 to force development mode on Linux
"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Recording Machine')

    # Hide cursor for the appliance feel — operator navigates by keyboard only
    app.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))

    # Import after QApplication is created (Qt requires this on some platforms)
    from ui.main_window import MainWindow
    window = MainWindow()

    # Install input filters so Enter/F2 work from inside text fields
    window._install_input_filters()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
