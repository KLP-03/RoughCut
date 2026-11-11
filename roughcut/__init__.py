"""roughcut: turn raw footage into a DaVinci Resolve rough cut, captions, vertical clips, and thumbnail options."""
import os

__version__ = "0.1.0"

# Homebrew's standard ffmpeg can't burn in captions; ffmpeg-full can. Use it automatically if installed.
for _full in ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"):
    if os.path.exists(os.path.join(_full, "ffmpeg")):
        os.environ["PATH"] = _full + os.pathsep + os.environ.get("PATH", "")
        break