#!/usr/bin/env bash
# install-pi.sh — Set up Recording Machine on Raspberry Pi OS (Bookworm)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/recording-machine.desktop"

echo "==> Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pyqt6 \
    python3-opencv \
    python3-numpy \
    ffmpeg \
    v4l-utils \
    alsa-utils

echo "==> Adding $USER to video and audio groups..."
sudo usermod -aG video,audio "$USER"

echo "==> Creating output directory..."
mkdir -p "$HOME/Recordings"

echo "==> Installing autostart entry..."
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Recording Machine
Exec=python3 $SCRIPT_DIR/main.py
X-GNOME-Autostart-enabled=true
EOF

echo ""
echo "Done! Reboot (or log out and back in) for group changes to take effect."
echo "The application will start automatically on next login."
echo ""
echo "To test right now:"
echo "  python3 $SCRIPT_DIR/main.py"
echo ""
echo "To test with a different device:"
echo "  VIDEO_DEVICE=/dev/video1 python3 $SCRIPT_DIR/main.py"
echo ""
echo "To check available video devices:"
echo "  v4l2-ctl --list-devices"
echo ""
echo "To check available audio devices:"
echo "  arecord -l"
