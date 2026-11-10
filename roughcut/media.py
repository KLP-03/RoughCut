"""ffprobe/ffmpeg helpers and timecode math."""
import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction


@dataclass
class MediaInfo:
    path: str
    duration: float
    fps: float
    width: int
    height: int
    start_tc: str  # embedded camera timecode, or 00:00:00:00


def require(binary: str) -> None:
    if shutil.which(binary) is None:
        raise SystemExit(f"'{binary}' was not found on your PATH. Install ffmpeg first (see README).")


def probe(path: str) -> MediaInfo:
    require("ffprobe")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise SystemExit(f"No video stream found in {path}")
    fps = float(Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"))
    if fps <= 0:
        fps = 30.0
    tc = (video.get("tags", {}) or {}).get("timecode") or (data["format"].get("tags", {}) or {}).get("timecode")
    return MediaInfo(
        path=path,
        duration=float(data["format"]["duration"]),
        fps=fps,
        width=int(video["width"]),
        height=int(video["height"]),
        start_tc=(tc or "00:00:00:00").replace(";", ":"),
    )


def nominal_fps(fps: float) -> int:
    return int(round(fps))


def tc_to_frames(tc: str, fps: float) -> int:
    h, m, s, f = (int(x) for x in tc.split(":"))
    n = nominal_fps(fps)
    return ((h * 60 + m) * 60 + s) * n + f


def frames_to_tc(frames: int, fps: float) -> str:
    n = nominal_fps(fps)
    f = frames % n
    total = frames // n
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def seconds_to_frames(sec: float, fps: float) -> int:
    # Real frame count at the true rate (e.g. 23.976); frames_to_tc then labels it non-drop frame like Resolve does.
    return int(round(sec * fps))


def run_ffmpeg(args: list[str]) -> None:
    require("ffmpeg")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def has_filter(name: str) -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines() if len(line.split()) > 1)
