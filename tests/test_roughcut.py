import json
import os
import unittest
from pathlib import Path
from unittest import mock

from roughcut import select
from roughcut.media import frames_to_tc, seconds_to_frames, tc_to_frames
from roughcut.transcribe import load_transcript, to_srt

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_transcript.json"


class TimecodeTests(unittest.TestCase):
    def test_round_trip(self):
        for fps in (23.976, 24, 25, 29.97, 30, 59.94):
            self.assertEqual(frames_to_tc(tc_to_frames("10:00:05:12", fps), fps), "10:00:05:12")

    def test_true_frame_count(self):
        # 100 real seconds at 23.976 fps is 2398 frames, not 2400
        self.assertEqual(seconds_to_frames(100, 24000 / 1001), 2398)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.segs = load_transcript(SAMPLE)

    def test_heuristic_respects_bounds_and_overlap(self):
        clips = select.pick_heuristic(self.segs, 4, 15, 60)
        self.assertEqual(len(clips), 4)
        spans = [(c["start_segment"], c["end_segment"]) for c in clips]
        for c in clips:
            self.assertTrue(15 <= c["duration"] <= 60)
        for i, (a, b) in enumerate(spans):
            for c, d in spans[i + 1 :]:
                self.assertTrue(b < c or d < a, "clips overlap")

    def test_parse_llm_json_with_fences_and_prose(self):
        raw = 'Here you go:\n```json\n[{"start_segment": 8, "end_segment": 14, "title": "t"}]\n```'
        self.assertEqual(select.parse_llm_json(raw)[0]["end_segment"], 14)

    def test_llm_picks_are_validated(self):
        fake = [
            {"start_segment": 8, "end_segment": 14, "title": "The index mistake", "hook": "Here's the biggest mistake", "thumbnail_text": "Too Many Indexes", "why": "story"},
            {"start_segment": 10, "end_segment": 12, "title": "overlaps the first"},
            {"start_segment": 0, "end_segment": 0, "title": "too short"},
            {"start_segment": 99, "end_segment": 120, "title": "out of range"},
        ]
        with mock.patch.object(select, "pick_with_llm", return_value=fake):
            clips = select.pick_moments(self.segs, 4, 15, 60)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["title"], "The index mistake")
        self.assertEqual(clips[0]["picked_by"], "llm")

    def test_no_credentials_falls_back(self):
        err = TypeError("Could not resolve authentication method. Expected one of api_key, auth_token, or credentials")
        with mock.patch.object(select, "pick_with_llm", side_effect=err):
            clips = select.pick_moments(self.segs, 3, 15, 60)
        self.assertEqual(len(clips), 3)

    def test_llm_failure_falls_back(self):
        with mock.patch.object(select, "pick_with_llm", side_effect=RuntimeError("offline")):
            clips = select.pick_moments(self.segs, 3, 15, 60)
        self.assertEqual(len(clips), 3)
        self.assertTrue(all(c["picked_by"] == "heuristic" for c in clips))


class AudioTests(unittest.TestCase):
    def test_transcribe_passes_ffmpeg_audio_to_whisper(self):
        import subprocess
        import tempfile

        import numpy as np

        from roughcut import transcribe as tr

        with tempfile.TemporaryDirectory() as d:
            clip = f"{d}/tone.mov"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                            "-t", "3", "-c:a", "aac", clip], check=True)
            audio = tr.load_audio(clip)
            self.assertEqual(audio.dtype, np.float32)
            self.assertAlmostEqual(audio.size / tr.SAMPLE_RATE, 3.0, delta=0.1)

            seen = {}

            class FakeSeg:
                start, end, text = 0.0, 1.0, " hello "

            class FakeModel:
                def __init__(self, *a, **k):
                    seen["device"] = k.get("device")

                def transcribe(self, audio_in, **k):
                    seen["audio"] = audio_in
                    return iter([FakeSeg()]), None

            with mock.patch("faster_whisper.WhisperModel", FakeModel):
                segs = tr.transcribe(clip, "tiny", device="cpu")
        self.assertIsInstance(seen["audio"], np.ndarray)
        self.assertEqual(seen["device"], "cpu")
        self.assertEqual(segs[0]["text"], "hello")


class StartTimeTests(unittest.TestCase):
    def test_parse_time(self):
        from roughcut.cli import parse_time
        self.assertEqual(parse_time("90"), 90)
        self.assertEqual(parse_time("12:30"), 750)
        self.assertEqual(parse_time("1:02:03"), 3723)

    def test_start_skips_earlier_moments_and_maps_back(self):
        import json
        import tempfile

        from roughcut import cli

        with tempfile.TemporaryDirectory() as d, mock.patch.object(cli, "probe") as probe, \
                mock.patch.object(cli, "render_vertical"), mock.patch.object(cli, "grab_thumbnails"):
            probe.return_value = mock.Mock(path="x.mov", duration=130, fps=24.0, width=1920, height=1080, start_tc="00:00:00:00")
            video = f"{d}/x.mov"
            Path(video).write_bytes(b"")
            cli.main([video, "--transcript", str(SAMPLE), "-o", d + "/out", "-n", "2", "--start", "1:00", "--no-llm"])
            clips = json.loads(Path(d, "out", "clips.json").read_text())["clips"]
        segs = load_transcript(SAMPLE)
        for c in clips:
            self.assertGreaterEqual(c["start"], 60)
            self.assertEqual(c["start"], segs[c["start_segment"]]["start"])
            self.assertEqual(c["end"], segs[c["end_segment"]]["end"])


class StructuredOutputTests(unittest.TestCase):
    def test_reads_picks_from_structured_json(self):
        import sys
        import types

        segs = load_transcript(SAMPLE)
        picks = [{"start_segment": 8, "end_segment": 14, "title": "t", "hook": "h", "thumbnail_text": "x", "why": "w"}]
        captured = {}

        class Msgs:
            def create(self, **k):
                captured.update(k)
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps({"clips": picks}))])

        fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(messages=Msgs()))
        with mock.patch.dict(sys.modules, {"anthropic": fake}):
            out = select.pick_with_llm(segs, 3, 15, 60)
        self.assertEqual(out, picks)
        self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("tool_choice", captured)


class FramingTests(unittest.TestCase):
    @staticmethod
    def face(cx, h, cy=0.3):
        return {"cx": cx, "cy": cy, "h": h, "kind": "front", "box": (0, 0, 1, 1)}

    def test_two_faces_apart_means_stack(self):
        from roughcut.framing import STACK, decide
        self.assertEqual(decide([self.face(0.7, 0.08), self.face(0.25, 0.06)]), (STACK, 0.5, True))

    def test_one_big_face_means_face_crop(self):
        from roughcut.framing import FACE, decide
        self.assertEqual(decide([self.face(0.52, 0.3)]), (FACE, 0.52, True))

    def test_one_small_face_is_still_a_wide_shot(self):
        from roughcut.framing import STACK, decide
        self.assertEqual(decide([self.face(0.7, 0.14)]), (STACK, 0.5, False))  # not confident: camera check decides

    def test_no_faces_means_unsure(self):
        from roughcut.framing import CENTER, decide
        self.assertEqual(decide([]), (CENTER, 0.5, False))

    def test_one_off_false_hit_is_ignored(self):
        from roughcut.framing import stable_faces
        real = [self.face(0.52 + d, 0.3) for d in (0, 0.01, -0.01, 0.0, 0.02)]
        frames = [[f] for f in real]
        frames[2].append(self.face(0.85, 0.35))  # a leaf that looked like a face once
        stable = stable_faces(frames)
        self.assertEqual(len(stable), 1)
        self.assertAlmostEqual(stable[0]["cx"], 0.52, places=2)

    def test_unclear_shot_matches_same_camera(self):
        import numpy as np
        from roughcut import framing
        framing._MEMORY.clear()
        close_up = np.full((36, 64), 100, "float32")
        wide = np.full((36, 64), 160, "float32")
        framing._MEMORY += [(close_up, framing.FACE, 0.48), (wide, framing.STACK, 0.5)]
        self.assertEqual(framing.match_camera(close_up + 8), (framing.FACE, 0.48))   # same camera, slightly different
        self.assertEqual(framing.match_camera(wide - 8), (framing.STACK, 0.5))
        self.assertIsNone(framing.match_camera(np.full((36, 64), 230, "float32")))  # a camera never seen
        framing._MEMORY.clear()

    def test_face_crop_stays_inside_the_frame(self):
        from roughcut.framing import FACE, segment_filter
        f = segment_filter(0, 0, 4, FACE, 0.98, 1920, 1080)
        self.assertIn("crop=608:1080:1312:0", f)  # pushed left so the crop never runs off the right edge

class StopReasonTests(unittest.TestCase):
    def test_cut_off_reply_explains_itself(self):
        import sys
        import types

        segs = load_transcript(SAMPLE)

        class Msgs:
            def create(self, **k):
                return types.SimpleNamespace(stop_reason="max_tokens", content=[types.SimpleNamespace(type="text", text='{"clips": [{"start_')])

        fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(messages=Msgs()))
        with mock.patch.dict(sys.modules, {"anthropic": fake}), self.assertRaisesRegex(ValueError, "max_tokens"):
            select.pick_with_llm(segs, 3, 15, 60)


class ResolveExportTests(unittest.TestCase):
    def test_face_shot_fills_height_and_centers_face(self):
        from roughcut.resolve_export import transforms
        [layer] = transforms("face", 0.5, 1920, 1080)
        self.assertAlmostEqual(layer["zoom"], 1920 / 1080)
        self.assertAlmostEqual(layer["pan"], 0)

    def test_face_near_edge_never_shows_past_frame(self):
        from roughcut.resolve_export import transforms
        [layer] = transforms("face", 0.99, 1920, 1080)
        from roughcut.resolve_export import X_UNITS
        visible_right = 1920 / 2 - layer["pan"] / X_UNITS / layer["zoom"] + (1080 / layer["zoom"]) / 2
        self.assertAlmostEqual(visible_right, 1920)

    def test_stack_halves_meet_in_the_middle(self):
        from roughcut.resolve_export import transforms
        top, bottom = transforms("stack", 0.5, 1920, 1080)
        self.assertAlmostEqual(top["zoom"] * 1080, 960)
        self.assertAlmostEqual(top["tilt"], 480 * 1920 / 1080)
        self.assertAlmostEqual(bottom["tilt"], -480 * 1920 / 1080)
        self.assertAlmostEqual(top["pan"], 313.3333 * 1080 / 1920, places=2)
        self.assertAlmostEqual(top["pan"], -bottom["pan"])


class ResolveCalibrationTests(unittest.TestCase):
    """Measured in Resolve Studio 21 with a 1920x1080 grid on a 1080x1920 center-crop timeline:
    Position X 200 moved the image 355 px, Position Y 300 moved it about 167 px, and both
    distances were the same at Zoom 1 and Zoom 2."""

    PX_PER_PAN, PX_PER_TILT = 1920 / 1080, 1080 / 1920

    def test_face_value_lands_face_at_center(self):
        from roughcut.resolve_export import transforms
        [layer] = transforms("face", 0.6, 1920, 1080)
        shift_px = layer["pan"] * self.PX_PER_PAN
        face_x_after_zoom = (0.6 * 1920 - 960) * layer["zoom"]
        self.assertAlmostEqual(face_x_after_zoom + shift_px, 0, places=6)

    def test_stack_halves_fill_their_panels(self):
        from roughcut.resolve_export import transforms
        top, bottom = transforms("stack", 0.5, 1920, 1080)
        self.assertAlmostEqual(top["tilt"] * self.PX_PER_TILT, 480)
        left_edge = -1920 * top["zoom"] / 2 + top["pan"] * self.PX_PER_PAN
        self.assertAlmostEqual(left_edge, -540)


class CaptionTests(unittest.TestCase):
    def test_srt_offset(self):
        srt = to_srt([{"start": 61.5, "end": 63.25, "text": "hi"}], offset=60)
        self.assertIn("00:00:01,500 --> 00:00:03,250", srt)


if __name__ == "__main__":
    unittest.main()