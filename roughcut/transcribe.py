"""Speech to text with faster-whisper, plus SRT helpers."""
import json
from pathlib import Path


SAMPLE_RATE = 16000


def load_audio(path: str):
    """Decode any video's audio to 16 kHz mono float32 with ffmpeg.

    We do this ourselves instead of letting faster-whisper use PyAV, because
    newer PyAV releases break faster-whisper's decoder, and ffmpeg reads every
    camera format (ProRes .mov, XAVC .mp4, MXF) reliably.
    """
    import subprocess

    import numpy as np

    from .media import require

    require("ffmpeg")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg couldn't read the audio in {path}:\n{proc.stderr.decode(errors='ignore').strip()}")
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if audio.size == 0:
        raise SystemExit(f"No audio track found in {path}")
    return audio


def transcribe(path: str, model_size: str = "small", language: str | None = None, device: str = "auto") -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SystemExit("faster-whisper is not installed. Run: pip install -e .") from e
    audio = load_audio(path)
    print(f"  loaded {audio.size / SAMPLE_RATE / 60:.1f} minutes of audio")
    model = WhisperModel(model_size, device=device, compute_type="auto")
    segments, _info = model.transcribe(audio, language=language, vad_filter=True)
    out = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            out.append({"id": len(out), "start": round(seg.start, 3), "end": round(seg.end, 3), "text": text})
        print(f"\r  transcribed {seg.end:7.1f}s", end="", flush=True)
    print()
    return out


def load_transcript(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    segs = data["segments"] if isinstance(data, dict) else data
    return [{"id": i, "start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()} for i, s in enumerate(segs)]


def srt_time(sec: float) -> str:
    ms = int(round(max(sec, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[dict], offset: float = 0.0) -> str:
    lines = []
    for n, seg in enumerate(segments, 1):
        lines += [str(n), f"{srt_time(seg['start'] - offset)} --> {srt_time(seg['end'] - offset)}", seg["text"], ""]
    return "\n".join(lines)