"""Command line entry point: roughcut interview.mp4"""
import argparse
import json
from pathlib import Path

from .export import grab_thumbnails, render_vertical, write_captions, write_edl, write_summary
from .media import probe
from .select import DEFAULT_MODEL, pick_moments
from .transcribe import load_transcript, transcribe


def main(argv=None):
    p = argparse.ArgumentParser(prog="roughcut", description="Turn raw footage into a Resolve rough cut, captions, vertical clips, and thumbnail options.")
    p.add_argument("video", help="source video file")
    p.add_argument("-o", "--out", help="output folder (default: <video name>_roughcut)")
    p.add_argument("-n", "--clips", type=int, default=5, help="number of moments to pick (default 5)")
    p.add_argument("--min", type=float, default=15, help="shortest clip in seconds (default 15)")
    p.add_argument("--max", type=float, default=60, help="longest clip in seconds (default 60)")
    p.add_argument("--model", default="small", help="Whisper model: tiny, base, small, medium, large-v3 (default small)")
    p.add_argument("--language", help="force a language code, e.g. en")
    p.add_argument("--transcript", help="reuse an existing transcript JSON instead of transcribing")
    p.add_argument("--llm-model", default=DEFAULT_MODEL, help=f"Claude model for picking moments (default {DEFAULT_MODEL})")
    p.add_argument("--no-llm", action="store_true", help="use only the built-in heuristic")
    p.add_argument("--no-render", action="store_true", help="skip rendering vertical clips")
    p.add_argument("--no-captions", action="store_true", help="do not burn captions into vertical clips")
    p.add_argument("--no-thumbs", action="store_true", help="skip thumbnail frame grabs")
    a = p.parse_args(argv)

    media = probe(a.video)
    out = Path(a.out or f"{Path(a.video).stem}_roughcut")
    for sub in ("", "clips", "thumbnails"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    print(f"Source: {media.path} ({media.duration:.0f}s, {media.fps:.3f} fps, {media.width}x{media.height})")

    print("1/4 Transcribing")
    if a.transcript:
        segs = load_transcript(a.transcript)
    else:
        segs = transcribe(a.video, a.model, a.language)
        (out / "transcript.json").write_text(json.dumps({"segments": segs}, indent=2))
    if not segs:
        raise SystemExit("No speech found, so there is nothing to cut.")

    print("2/4 Picking moments")
    clips = pick_moments(segs, a.clips, a.min, a.max, use_llm=not a.no_llm, model=a.llm_model)
    if not clips:
        raise SystemExit("No moments fit the --min/--max range. Try a wider range.")

    print("3/4 Writing timeline and captions")
    edl = write_edl(clips, media, out)
    write_captions(segs, clips, out)
    write_summary(clips, media, out)

    print("4/4 Rendering")
    if not a.no_render:
        render_vertical(media, clips, out, burn_captions=not a.no_captions)
    if not a.no_thumbs:
        grab_thumbnails(media, clips, out)

    print(f"\nDone. {len(clips)} moments in {out}/")
    print(f"  Resolve timeline: {edl}")
    print(f"  Picks and thumbnail text: {out / 'README.md'}")


if __name__ == "__main__":
    main()
