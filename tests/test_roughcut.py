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


class CaptionTests(unittest.TestCase):
    def test_srt_offset(self):
        srt = to_srt([{"start": 61.5, "end": 63.25, "text": "hi"}], offset=60)
        self.assertIn("00:00:01,500 --> 00:00:03,250", srt)


if __name__ == "__main__":
    unittest.main()
