"""Write the Resolve EDL, captions, vertical clips, and thumbnail frames."""
import json
from pathlib import Path

from .media import MediaInfo, frames_to_tc, has_filter, run_ffmpeg, seconds_to_frames, tc_to_frames
from .transcribe import to_srt


def write_edl(clips, media: MediaInfo, out: Path, title="roughcut", record_start="01:00:00:00") -> Path:
    """CMX3600 EDL. In Resolve: File > Import > Timeline > Import AAF, EDL, XML (keep the source clip in the media pool)."""
    fps = media.fps
    src_offset = tc_to_frames(media.start_tc, fps)
    rec = tc_to_frames(record_start, fps)
    name = Path(media.path).name
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for i, c in enumerate(clips, 1):
        s_in = src_offset + seconds_to_frames(c["start"], fps)
        s_out = src_offset + seconds_to_frames(c["end"], fps)
        r_out = rec + (s_out - s_in)
        lines.append(f"{i:03d}  AX       B     C        {frames_to_tc(s_in, fps)} {frames_to_tc(s_out, fps)} {frames_to_tc(rec, fps)} {frames_to_tc(r_out, fps)}")
        lines.append(f"* FROM CLIP NAME: {name}")
        lines.append(f"* COMMENT: {c['title']}")
        lines.append("")
        rec = r_out
    path = out / "roughcut.edl"
    path.write_text("\n".join(lines))
    return path


def write_captions(segs, clips, out: Path) -> None:
    (out / "full_transcript.srt").write_text(to_srt(segs))
    (out / "full_transcript.txt").write_text("\n".join(f"[{s['start']:.1f}] {s['text']}" for s in segs))
    for i, c in enumerate(clips, 1):
        clip_segs = segs[c["start_segment"] : c["end_segment"] + 1]
        (out / "clips" / f"clip_{i:02d}.srt").write_text(to_srt(clip_segs, offset=c["start"]))


def render_vertical(media: MediaInfo, clips, out: Path, burn_captions=True) -> None:
    can_burn = burn_captions and has_filter("subtitles")
    if burn_captions and not can_burn:
        print("  Your ffmpeg build has no 'subtitles' filter; rendering clips without burned-in captions.")
    for i, c in enumerate(clips, 1):
        # Center-crop to 9:16, then scale to 1080x1920 for Reels, Shorts, and TikTok.
        vf = "crop='min(iw,ih*9/16)':ih,scale=1080:1920:flags=lanczos,setsar=1"
        srt = out / "clips" / f"clip_{i:02d}.srt"
        if can_burn:
            style = "FontName=Arial,FontSize=13,Bold=1,Outline=2,Shadow=0,MarginV=70,Alignment=2"
            vf += f",subtitles='{srt.as_posix()}':force_style='{style}'"
        run_ffmpeg([
            "-ss", f"{c['start']:.3f}", "-i", media.path, "-t", f"{c['end'] - c['start']:.3f}",
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-write_tmcd", "0",
            str(out / "clips" / f"clip_{i:02d}_vertical.mp4"),
        ])
        print(f"  rendered clip {i}/{len(clips)}")


def grab_thumbnails(media: MediaInfo, clips, out: Path, per_clip=3) -> None:
    for i, c in enumerate(clips, 1):
        span = c["end"] - c["start"]
        for k in range(per_clip):
            t = c["start"] + span * (k + 1) / (per_clip + 1)
            run_ffmpeg(["-ss", f"{t:.3f}", "-i", media.path, "-frames:v", "1", "-q:v", "2",
                        str(out / "thumbnails" / f"clip_{i:02d}_option_{k + 1}.jpg")])


def write_summary(clips, media: MediaInfo, out: Path) -> None:
    (out / "clips.json").write_text(json.dumps({"source": media.path, "fps": media.fps, "clips": clips}, indent=2))
    md = ["# roughcut picks", "", f"Source: `{Path(media.path).name}`", ""]
    for i, c in enumerate(clips, 1):
        md += [
            f"## {i}. {c['title']}",
            f"- **Time:** {c['start']:.1f}s to {c['end']:.1f}s ({c['duration']}s)",
            f"- **Hook:** {c['hook']}",
            f"- **Thumbnail text:** {c['thumbnail_text']}",
            f"- **Picked by:** {c['picked_by']}" + (f" ({c['why']})" if c["why"] else ""),
            "",
        ]
    (out / "README.md").write_text("\n".join(md))
