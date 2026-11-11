# roughcut

https://github.com/user-attachments/assets/436764e0-653f-4183-b1f8-1f5838e51687

**Turn a long podcast, interview, or talk into framed, captioned vertical clips, plus editable timelines in DaVinci Resolve, with one command.**

roughcut transcribes your footage, has Claude pick the strongest moments, frames every shot for 9:16 (stacking two-person wide shots, following the face in close-ups), burns in captions, and builds a vertical timeline in Resolve for each clip where every framing decision is a normal Zoom and Position value you can adjust.

I built it because the slowest part of editing a podcast isn't the creative work. It's scrubbing an hour of footage for the 30 seconds worth sharing, then reframing every shot by hand. On my own client work, roughcut gets a clip about 75% of the way there, so my time goes to pacing, story, and polish.

## What you get

Run it on one video and you get a folder with:

| Output | What it's for |
| --- | --- |
| `clips/clip_01_vertical.mp4` | 1080x1920 clips, framed shot by shot, with burned-in captions, ready to review or post |
| `resolve_vertical_timeline.py` | Builds one framed vertical timeline per clip in DaVinci Resolve, with every shot's zoom and position editable |
| `roughcut.edl` | A 16:9 rough-cut timeline of the picks, for traditional editing |
| `README.md` | Each pick with its timestamp, hook, title, thumbnail text, and Claude's reason for choosing it |
| `clips/clip_01.srt`, `full_transcript.srt` | Captions per clip and for the whole video |
| `thumbnails/` | Three frame options per clip |
| `framing_debug/` | With `--debug-framing`: a marked-up still of every shot showing what was detected and why it was framed that way |

## How it works

1. **Transcribe locally.** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) runs Whisper on your machine, so footage never leaves it. ffmpeg decodes the audio, so any camera format works.
2. **Pick moments with Claude.** Claude reads the transcript and picks standalone moments with a strong hook and a complete ending. Its answer comes back through **structured outputs**, a JSON schema the response is guaranteed to match, and every pick is still checked for length, range, and overlap. If Claude is unavailable, a built-in heuristic scores moments on pacing, questions, hook words, specifics, and clean endings.
3. **Frame every shot.** ffmpeg finds each camera cut. OpenCV detects faces in five frames per shot, and a face only counts if it holds steady, sits in the upper frame, and is skin-toned, which filters out false hits on leaves, pockets, and patterns. Two faces far apart means a wide shot (stacked top and bottom). One large face means a close-up (cropped on the face). Unclear shots, like a face in profile, are matched to the most similar confident shot by comparing tiny grayscale stills, which reliably tells the cameras apart.
4. **Render and export.** ffmpeg renders each clip shot by shot with captions. roughcut also writes a Resolve script that rebuilds each clip as an editable timeline, converting the framing into Resolve's Inspector units.

### Getting Resolve's numbers right

In a vertical timeline, Resolve measures Position in landscape terms: one unit of Position X moves the image about 1.78 pixels, and one unit of Position Y moves it about 0.56. I measured this with a calibration grid at several zoom and position settings, confirmed the conversion doesn't change with zoom, and locked those measurements into the test suite. Clips are placed by asking Resolve where the previous shot actually ended, so timelines never have gaps.

## Setup

You need Python 3.10+ and ffmpeg. On a Mac:

```bash
brew install python@3.12 ffmpeg-full   # ffmpeg-full includes the library for burning in captions

git clone https://github.com/KLP-03/roughcut.git
cd roughcut
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
```

roughcut automatically uses Homebrew's `ffmpeg-full` when it's installed. With the standard `ffmpeg`, everything works except burned-in captions.

### Sign in to Claude (optional)

For Claude-picked moments, sign in once with Anthropic's `ant` CLI. There's no API key to store:

```bash
brew install anthropics/tap/ant
ant auth login
```

roughcut picks up that sign-in automatically. An `ANTHROPIC_API_KEY` environment variable also works. With neither, roughcut uses its built-in heuristic and runs fully offline.

## Usage

```bash
roughcut podcast.mov --layout auto
```

Common options:

```bash
roughcut podcast.mov -n 8 --min 20 --max 45         # 8 clips, 20 to 45 seconds each
roughcut podcast.mov --start 1:15                    # skip the intro: only pick moments after 1:15
roughcut podcast.mov --layout auto --debug-framing   # save a marked-up still of every shot
roughcut podcast.mov --no-captions                   # render clips without burned-in captions
roughcut podcast.mov --model medium                  # more accurate transcription (slower)
roughcut podcast.mov --no-llm                        # heuristic only, fully offline
roughcut podcast.mov --transcript podcast_roughcut/transcript.json   # reuse a transcript and re-pick in seconds
```

Layouts: `center` (one speaker), `stack` (two people, top and bottom), and `auto` (decides shot by shot). Run `roughcut --help` for everything.

### Building the timelines in DaVinci Resolve

1. Open your project in Resolve.
2. Go to **Workspace > Console** and choose **Py3**.
3. Paste the `exec(...)` line roughcut prints at the end of its run.

Resolve creates a bin with one 1080x1920 timeline per clip, named with its number and title. Single-person shots sit on V1. Stacked shots use V1 (bottom person, with audio) and V2 (top person). Every clip points to your original footage, so you can drag edges to add context, like the question before an answer.

## Tests

```bash
python -m unittest discover -s tests
```

25 tests cover timecode math at common frame rates, clip selection rules, validation of Claude's picks and the fallbacks when Claude is unavailable, face filtering and camera matching, the Resolve unit conversion (from the calibration measurements), and an end-to-end run.

## Roadmap

- Show only the active speaker in wide shots, instead of stacking both
- A clean mode that removes filler words and retakes from long-form footage
- Animated captions and title cards rendered with [Remotion](https://www.remotion.dev/)
- Batch mode for a folder of episodes or conference talks

## About

Built by James Hortman, a video producer and editor and former software engineer (BlackRock, FIS) who runs [Kingdom Lens Productions](https://kingdomlensproductions.com) in Atlanta.
