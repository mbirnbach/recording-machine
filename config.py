"""
Recording Machine — Configuration
All tunables. Override via environment variables.
"""
from __future__ import annotations
import os
import platform
from dataclasses import dataclass
from pathlib import Path

# ── Platform detection ──────────────────────────────────────────────────────────
IS_LINUX = platform.system() == 'Linux'

# Dev mode: on macOS or when DEV_MODE=1 is set — uses built-in webcam, skips audio
DEV_MODE = (platform.system() == 'Darwin') or (os.environ.get('DEV_MODE') == '1')

# ── Capture device ──────────────────────────────────────────────────────────────
# On Linux: V4L2 device path. On Mac: camera index as string.
VIDEO_DEVICE = os.environ.get('VIDEO_DEVICE', '/dev/video0' if IS_LINUX else '0')

# ALSA capture device for audio. None = auto-detect at startup.
AUDIO_DEVICE = os.environ.get('AUDIO_DEVICE', None)

# ── Format presets (resolution + framerate) ─────────────────────────────────────
@dataclass(frozen=True)
class VideoFormat:
    label: str
    width: int
    height: int
    fps: str      # string passed directly to ffmpeg -framerate

PAL  = VideoFormat('PAL',  720, 576, '25')
NTSC = VideoFormat('NTSC', 720, 480, '30000/1001')

VIDEO_FORMATS = [PAL, NTSC]
DEFAULT_FORMAT = PAL

# ── Codec presets ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Codec:
    label: str
    ffmpeg_name: str
    crf: int

H264 = Codec('H.264', 'libx264', 20)
H265 = Codec('H.265', 'libx265', 26)

CODECS = [H264, H265]
DEFAULT_CODEC = H264

# ── Audio mode presets ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AudioMode:
    label: str
    channels: int
    af: str | None   # ffmpeg -af filter string, None = no filter

STEREO = AudioMode('Stereo',      2, None)
MONO_R = AudioMode('Mono (R ch)', 1, 'pan=mono|c0=c1')  # right channel → mono (16mm film)

AUDIO_MODES = [STEREO, MONO_R]
DEFAULT_AUDIO_MODE = STEREO

# ── Recording ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(os.environ.get('OUTPUT_DIR', Path.home() / 'Recordings'))

# Minimum free disk space before warning (bytes)
DISK_WARN_BYTES = int(os.environ.get('DISK_WARN_GB', 5)) * 1024 ** 3
