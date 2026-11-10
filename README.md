# roughcut

**Turn an hour of raw footage into a rough cut in minutes.**

roughcut transcribes a video, picks its strongest moments, and hands you everything you need to finish the edit in DaVinci Resolve: a rough-cut timeline, captions, vertical clips ready for Reels, Shorts, and TikTok, and thumbnail options.

I built it because the slowest part of editing interviews, podcasts, and conference talks isn't the creative work. It's scrubbing through footage to find the 30 seconds worth sharing. roughcut does that first pass so I can spend my time on pacing, story, and polish.

## What you get

Run it on one video and you get a folder with:

| File | What it's for |
| --- | --- |
| `roughcut.edl` | A rough-cut timeline of the picked moments. Import it into Resolve and start editing. |
| `README.md` | Each pick with its timestamp, hook line, title, and suggested thumbnail text |
| `clips/clip_01_vertical.mp4` | 1080x1920 vertical cuts with burned-in captions, ready to review or post |
| `clips/clip_01.srt` | Captions for each clip, timed to the clip |
| `full_transcript.srt` / `.txt` | Captions and a searchable transcript for the full video |
| `thumbnails/` | Three frame options per clip for thumbnail design |
| `clips.json` | Everything above as data, for scripting the next step |

## How it works

1. **Transcribe.** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) runs Whisper locally, so footage never leaves your machine for this step.
2. **Pick moments.** If `ANTHROPIC_API_KEY` is set, Claude reads the transcript and picks standalone moments with a strong hook and a complete ending. Every pick is checked for length, range, and overlap before it's used. Without a key, or if the API call fails, a built-in heuristic scores moments on pacing, questions, hook words, specifics, and whether they end on a complete thought.
3. **Build the timeline.** roughcut writes a CMX3600 EDL. It reads the camera's embedded timecode, so the edit lines up with your original media in Resolve.
4. **Render.** ffmpeg center-crops each moment to 9:16, burns in captions, and grabs thumbnail frames.

## Setup

You need Python 3.10+ and ffmpeg.

```bash
# macOS
brew install ffmpeg

git clone https://github.com/KLP-03/roughcut.git
cd roughcut
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Optional, for AI-picked moments:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

## Usage

```bash
roughcut interview.mp4
```

Common options:

```bash
roughcut talk.mp4 -n 8 --min 20 --max 45   # 8 clips, 20 to 45 seconds each
roughcut talk.mp4 --model medium           # more accurate transcription (slower)
roughcut talk.mp4 --no-llm                 # heuristic only, fully offline
roughcut talk.mp4 --no-render              # timeline and captions only, skip rendering
roughcut talk.mp4 --transcript talk_roughcut/transcript.json   # reuse a transcript and re-pick
```

Run `roughcut --help` for everything.

### Importing into DaVinci Resolve

1. Add the source video to your Media Pool.
2. Go to **File > Import > Timeline > Import AAF, EDL, XML** and choose `roughcut.edl`.
3. Resolve builds a timeline with each picked moment in order, with titles in the clip comments.

## Try it without footage

The repo includes a sample transcript from a database talk. Point it at any video at least two and a half minutes long to see the full pipeline:

```bash
roughcut any_video.mp4 --transcript examples/sample_transcript.json -n 4
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover timecode math at common frame rates, clip selection rules, validation of AI picks, and the fallback when the API is unavailable.

## Roadmap

- Speaker-aware vertical framing that follows the active speaker instead of a center crop
- Animated captions and title cards rendered with [Remotion](https://www.remotion.dev/)
- FCPXML export with markers for every pick, not just the selected clips
- Batch mode for a folder of conference talks

## About

Built by James Hortman, a video editor and former software engineer (BlackRock, FIS) who runs [Kingdom Lens Productions](https://kingdomlensproductions.com) in Atlanta.
