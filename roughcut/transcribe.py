"""Speech to text with faster-whisper, plus SRT helpers."""
import json
from pathlib import Path


def transcribe(path: str, model_size: str = "small", language: str | None = None) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SystemExit("faster-whisper is not installed. Run: pip install -r requirements.txt") from e
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _info = model.transcribe(path, language=language, vad_filter=True)
    out = []
    for i, seg in enumerate(segments):
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
