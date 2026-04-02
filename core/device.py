"""
Device probing utilities — detect video/audio devices and check dependencies.
"""
from __future__ import annotations
import re
import subprocess
import shutil
from pathlib import Path

import config


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available in PATH."""
    return shutil.which('ffmpeg') is not None


def probe_video_device(path: str) -> bool:
    """Return True if the video device exists and is accessible."""
    if config.DEV_MODE:
        return True
    return Path(path).exists()


def probe_audio_device() -> str | None:
    """
    Auto-detect the USB audio capture device via 'arecord -l'.
    Returns ALSA device string like 'hw:2,0', or None if not found.
    Skipped entirely in DEV_MODE.
    """
    if config.DEV_MODE:
        return None

    if config.AUDIO_DEVICE:
        return config.AUDIO_DEVICE

    try:
        result = subprocess.run(
            ['arecord', '-l'],
            capture_output=True, text=True, timeout=5,
        )
        # Lines like: card 2: Device [USB Audio], device 0: USB Audio [USB Audio]
        for line in result.stdout.splitlines():
            if any(k in line.lower() for k in ('usb audio', 'usb capture', 'grabber')):
                m = re.search(r'card (\d+):.*device (\d+):', line)
                if m:
                    return f'hw:{m.group(1)},{m.group(2)}'
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return None


def free_bytes(path: Path) -> int:
    """Return free disk space in bytes at the given path."""
    import shutil as _shutil
    return _shutil.disk_usage(path).free
