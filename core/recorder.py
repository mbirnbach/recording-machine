"""
Recorder — manages the FFmpeg subprocess that captures and encodes to disk.

FFmpeg owns the V4L2 device during recording and produces two simultaneous outputs:
  1. Raw BGR24 frames piped to stdout  →  preview thread  →  frame_ready signal
  2. Encoded H.264/H.265 + AAC        →  output .mp4 file

This keeps the live preview running while recording, with correct A/V sync.
"""
from __future__ import annotations
import re
import subprocess
import threading
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

import config


def _sanitize(s: str) -> str:
    """Replace characters unsafe for filenames with underscores."""
    return re.sub(r'[^\w\-]', '_', s).strip('_') or 'untitled'


class Recorder(QObject):
    recording_failed = pyqtSignal(str)      # FFmpeg exited unexpectedly
    frame_ready      = pyqtSignal(np.ndarray)  # preview frames while recording

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._monitor: threading.Thread | None = None
        self._preview: threading.Thread | None = None
        self._output_path: Path | None = None
        self._fmt = None

    # ── Public API ──────────────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def output_path(self) -> Path | None:
        return self._output_path

    def start(self, project: str, reel: str, audio_device: str | None,
              fmt=None, codec=None, audio_mode=None) -> Path:
        if self.is_recording:
            raise RuntimeError('Already recording')

        self._fmt  = fmt        or config.DEFAULT_FORMAT
        codec      = codec      or config.DEFAULT_CODEC
        audio_mode = audio_mode or config.DEFAULT_AUDIO_MODE

        import datetime
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{_sanitize(project)}_{_sanitize(reel)}_{ts}.mp4'
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._output_path = config.OUTPUT_DIR / filename

        cmd = self._build_command(audio_device, self._fmt, codec, audio_mode, self._output_path)

        # On Linux/Pi: pipe raw frames to stdout for live preview during recording.
        # On macOS: camera supports multiple readers, so OpenCV keeps providing
        # preview — no pipe needed, and macOS pipe buffers are too small anyway.
        use_pipe = config.IS_LINUX and not config.DEV_MODE

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if use_pipe else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        if use_pipe:
            self._preview = threading.Thread(target=self._read_preview_frames, daemon=True)
            self._preview.start()

        # Drain stderr so the pipe never fills and blocks FFmpeg
        self._stderr_buf: list[str] = []
        self._stderr_lock = threading.Lock()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        self._monitor = threading.Thread(target=self._monitor_proc, daemon=True)
        self._monitor.start()

        return self._output_path

    def stop(self) -> Path | None:
        """Gracefully stop — sends 'q' to FFmpeg and waits for file finalisation."""
        proc = self._proc
        if proc is None:
            return None

        path = self._output_path
        self._proc = None   # signals monitor/preview threads to exit quietly

        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(b'q\n')
                proc.stdin.flush()
                proc.stdin.close()
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except OSError:
            pass

        return path

    # ── Internal ───────────────────────────────────────────────────────────────

    def _build_command(self, audio_device: str | None, fmt, codec, audio_mode, output: Path) -> list[str]:
        cmd = ['ffmpeg', '-y']
        has_audio = bool(audio_device and not config.DEV_MODE)

        # ── Video input ────────────────────────────────────────────────────────
        if config.IS_LINUX and not config.DEV_MODE:
            cmd += [
                '-f', 'v4l2',
                '-input_format', 'yuyv422',
                '-video_size', f'{fmt.width}x{fmt.height}',
                '-framerate', fmt.fps,
                '-thread_queue_size', '512',
                '-i', config.VIDEO_DEVICE,
            ]
        else:
            device = config.VIDEO_DEVICE
            if not config.IS_LINUX:
                cmd += ['-f', 'avfoundation', '-framerate', '30', '-video_size', '1920x1080', '-i', f'{device}:']
            else:
                cmd += ['-i', device]

        # ── Audio input ────────────────────────────────────────────────────────
        if has_audio:
            cmd += [
                '-f', 'alsa',
                '-thread_queue_size', '512',
                '-i', audio_device,
            ]

        # ── Output 1: raw preview frames → stdout (Linux/Pi only) ─────────────
        if config.IS_LINUX and not config.DEV_MODE:
            cmd += [
                '-map', '0:v',
                '-s', f'{fmt.width}x{fmt.height}',
                '-f', 'rawvideo',
                '-pix_fmt', 'bgr24',
                'pipe:1',
            ]

        # ── Output 2: encoded file ─────────────────────────────────────────────
        cmd += ['-map', '0:v']
        if has_audio:
            cmd += ['-map', '1:a']

        cmd += [
            '-c:v', codec.ffmpeg_name,
            '-crf', str(codec.crf),
            '-preset', 'faster',
            '-pix_fmt', 'yuv420p',
        ]

        if has_audio:
            cmd += ['-c:a', 'aac', '-b:a', '192k', '-ac', str(audio_mode.channels)]
            if audio_mode.af:
                cmd += ['-af', audio_mode.af]

        cmd += ['-movflags', '+faststart', str(output)]
        return cmd

    def _read_preview_frames(self):
        """Read raw BGR24 frames from FFmpeg stdout and emit for display."""
        proc = self._proc
        if not proc or not proc.stdout:
            return

        w, h = self._fmt.width, self._fmt.height
        frame_bytes = w * h * 3

        while True:
            # Read exactly one frame's worth of bytes
            data = b''
            while len(data) < frame_bytes:
                chunk = proc.stdout.read(frame_bytes - len(data))
                if not chunk:
                    return   # FFmpeg closed stdout — recording ended
                data += chunk

            frame = np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3)).copy()
            self.frame_ready.emit(frame)

    def _drain_stderr(self):
        """Read stderr continuously so the pipe never fills and blocks FFmpeg."""
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for raw_line in proc.stderr:
            line = raw_line.decode('utf-8', errors='replace').rstrip()
            with self._stderr_lock:
                self._stderr_buf.append(line)
                if len(self._stderr_buf) > 50:   # keep last 50 lines
                    self._stderr_buf.pop(0)

    def _monitor_proc(self):
        """Watch FFmpeg; emit signal if it exits unexpectedly."""
        proc = self._proc
        if proc is None:
            return
        proc.wait()
        if self._proc is None:
            return   # cleared by stop() — expected exit
        with self._stderr_lock:
            lines = list(self._stderr_buf)
        self._proc = None
        self.recording_failed.emit(lines[-1] if lines else 'unknown error')
