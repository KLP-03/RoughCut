"""Shot-aware vertical framing: stack wide two-shots, follow the face in close-ups.

Face detection can be fooled (a leaf, a jacket fold), so a face only counts when it shows up in
the same spot across most of a shot's sample frames. When a shot is unclear, it matches the
framing of the most similar earlier shot (usually the same camera) instead of guessing.
"""
import re
import subprocess
from pathlib import Path

STACK, FACE, CENTER = "stack", "face", "center"
OUT_W, OUT_H = 1080, 1920
ANALYSIS_W = 960      # analyze downscaled frames; faster and plenty for finding faces
SAMPLES = (0.1, 0.3, 0.5, 0.7, 0.9)
MIN_HITS = 3          # a face must appear in at least this many of the sample frames
SAME_SPOT = 0.08      # detections within this fraction of the frame width count as the same face
SAME_CAMERA = 35.0    # average difference of tiny grayscale stills; same camera measured <=30, different >=40
CLOSE_UP_FACE = 0.22  # a face at least this tall (fraction of frame height) means a close-up
MAX_FACE_Y = 0.65     # a face's center sits in the upper part of the frame, not at waist level
MIN_SKIN = 0.25       # at least this share of a face box must be skin-toned (rules out leaves, wood, fabric)
DEBUG_DIR = None      # set to a folder to save a marked-up still for every shot


def find_cuts(path: str, start: float, duration: float, threshold: float = 0.3) -> list[float]:
    """Return camera-cut times (seconds from clip start) using ffmpeg's scene-change score."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", path, "-an",
         "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def shots(path: str, start: float, duration: float, min_len: float = 0.6) -> list[tuple[float, float]]:
    """Split a clip into (start, end) shots, merging flashes shorter than min_len into the previous shot."""
    bounds = [0.0]
    for t in find_cuts(path, start, duration):
        if t - bounds[-1] >= min_len and duration - t >= min_len:
            bounds.append(t)
    bounds.append(duration)
    return list(zip(bounds[:-1], bounds[1:]))


def grab_frame(path: str, t: float):
    """One frame at time t, downscaled, as a color image (or None)."""
    import cv2
    import numpy as np

    png = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
         "-vf", f"scale={ANALYSIS_W}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True,
    ).stdout
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR) if png else None


_CASCADES = {}


def _cascade(name):
    import cv2

    if name not in _CASCADES:
        _CASCADES[name] = cv2.CascadeClassifier(cv2.data.haarcascades + name)
    return _CASCADES[name]


def skin_share(frame, box) -> float:
    """Share of a box's center that is skin-toned, using a YCrCb range that covers light to dark skin."""
    import cv2

    x, y, bw, bh = box
    core = frame[y + bh // 4: y + bh * 3 // 4, x + bw // 4: x + bw * 3 // 4]  # the middle of the face
    if core.size == 0:
        return 0.0
    ycrcb = cv2.cvtColor(core, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
    return float((mask > 0).mean())


def detect_faces(frame) -> list[dict]:
    """Faces as dicts with center x/y and height (fractions of the frame) and the detector that found them."""
    import cv2

    gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    h, w = gray.shape
    size = (int(h * 0.04),) * 2
    found = []
    for x, y, bw, bh in _cascade("haarcascade_frontalface_default.xml").detectMultiScale(gray, 1.1, 6, minSize=size):
        found.append((x, y, bw, bh, "front"))
    # The side-profile model makes more false hits, so it has to be more confident (more neighbors).
    profile = _cascade("haarcascade_profileface.xml")
    for x, y, bw, bh in profile.detectMultiScale(gray, 1.1, 9, minSize=size):
        found.append((x, y, bw, bh, "side"))
    for x, y, bw, bh in profile.detectMultiScale(cv2.flip(gray, 1), 1.1, 9, minSize=size):
        found.append((w - x - bw, y, bw, bh, "side"))
    faces = []
    for x, y, bw, bh, kind in sorted(found, key=lambda f: (f[4] != "front", -f[2] * f[3])):
        cx, cy, fh = (x + bw / 2) / w, (y + bh / 2) / h, bh / h
        if cy > MAX_FACE_Y or skin_share(frame, (x, y, bw, bh)) < MIN_SKIN:
            continue  # waist-level or not skin-toned: a pocket, a leaf, a pattern
        if all(abs(cx - f["cx"]) > SAME_SPOT or abs(cy - f["cy"]) > fh * 0.6 for f in faces):  # drop duplicate boxes
            faces.append({"cx": cx, "cy": cy, "h": fh, "kind": kind, "box": (x, y, bw, bh)})
    return faces


def stable_faces(frames_faces: list[list[dict]], min_hits: int = MIN_HITS) -> list[dict]:
    """Keep only faces seen in about the same spot in at least min_hits sample frames."""
    groups = []  # each group: list of detections believed to be the same face
    for faces in frames_faces:
        for f in faces:
            for g in groups:
                if abs(g[0]["cx"] - f["cx"]) <= SAME_SPOT and abs(g[0]["cy"] - f["cy"]) <= 0.15:
                    g.append(f)
                    break
            else:
                groups.append([f])
    out = []
    for g in groups:
        frames_hit = len({id(ff) for ff in frames_faces for f in g if f in ff})
        if frames_hit >= min_hits:
            xs, hs = sorted(f["cx"] for f in g), sorted(f["h"] for f in g)
            out.append({"cx": xs[len(xs) // 2], "h": hs[len(hs) // 2], "hits": frames_hit})
    return sorted(out, key=lambda f: -f["h"])


def decide(faces) -> tuple[str, float, bool]:
    """Framing from a shot's steady faces. Returns (mode, face_center_x, confident)."""
    if len(faces) >= 2 and max(f["cx"] for f in faces) - min(f["cx"] for f in faces) > 0.25:
        return STACK, 0.5, True                 # two people far apart: a wide shot
    if faces and faces[0]["h"] >= CLOSE_UP_FACE:
        return FACE, faces[0]["cx"], True       # one large face: a close-up
    if faces:
        return STACK, 0.5, False                # one small face: probably wide, but a side view can look small
    return CENTER, 0.5, False                   # nothing reliable


def thumbnail(frame):
    """A tiny grayscale version of a frame, for telling cameras apart."""
    import cv2

    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype("float32")


def classify_shot(path: str, abs_start: float, abs_end: float):
    """Sample frames across a shot. Returns (mode, cx, confident, thumbnail, frames, per-frame faces, stable faces)."""
    frames, per_frame = [], []
    for frac in SAMPLES:
        frame = grab_frame(path, abs_start + (abs_end - abs_start) * frac)
        if frame is not None:
            frames.append(frame)
            per_frame.append(detect_faces(frame))
    if not frames:
        return CENTER, 0.5, False, None, [], [], []
    stable = stable_faces(per_frame, min(MIN_HITS, len(frames)))
    mode, cx, confident = decide(stable)
    return mode, cx, confident, thumbnail(frames[len(frames) // 2]), frames, per_frame, stable


def _save_debug(clip_no, shot_no, frames, per_frame, stable, mode, cx, note):
    import cv2

    if DEBUG_DIR is None or not frames:
        return
    folder = Path(DEBUG_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    img = frames[len(frames) // 2].copy()
    h, w = img.shape[:2]
    for faces in per_frame:  # every raw detection: green for front, orange for side
        for f in faces:
            x, y, bw, bh = f["box"]
            cv2.rectangle(img, (x, y), (x + bw, y + bh), (0, 200, 0) if f["kind"] == "front" else (0, 140, 255), 1)
    for f in stable:  # faces that held steady: thick white line
        cv2.line(img, (int(f["cx"] * w), 0), (int(f["cx"] * w), h), (255, 255, 255), 3)
    if mode == FACE:  # the vertical crop that will be used
        cw = h * 9 / 16
        left = int(min(max(cx * w - cw / 2, 0), w - cw))
        cv2.rectangle(img, (left, 0), (int(left + cw), h - 1), (255, 0, 255), 3)
    label = f"clip {clip_no} shot {shot_no}: {mode} {note}".strip()
    cv2.putText(img, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
    cv2.putText(img, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.imwrite(str(folder / f"clip{clip_no:02d}_shot{shot_no:02d}_{mode}.jpg"), img)


def segment_filter(i: int, s: float, e: float, mode: str, cx: float, src_w: int, src_h: int) -> str:
    head = f"[in{i}]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS"
    if mode == STACK:
        pw = min(src_w, round(src_h * 9 / 8) // 2 * 2)  # each panel is 1080x960, so crop at 9:8
        return (f"{head},split=2[l{i}][r{i}];"
                f"[l{i}]crop={pw}:{src_h}:0:0,scale={OUT_W}:{OUT_H // 2}:flags=lanczos,setsar=1[t{i}];"
                f"[r{i}]crop={pw}:{src_h}:{src_w - pw}:0,scale={OUT_W}:{OUT_H // 2}:flags=lanczos,setsar=1[b{i}];"
                f"[t{i}][b{i}]vstack=inputs=2[v{i}]")
    cw = min(src_w, round(src_h * 9 / 16) // 2 * 2)
    x = int(min(max(cx * src_w - cw / 2, 0), src_w - cw))
    return f"{head},crop={cw}:{src_h}:{x}:0,scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[v{i}]"


_CLIP_COUNT = [0]
_MEMORY = []  # (thumbnail, mode, cx) for confident shots, shared across clips so later clips can borrow


def match_camera(thumb):
    """(mode, cx) of the most similar confident shot so far, if it looks like the same camera."""
    import numpy as np

    best = None
    for t, mode, cx in _MEMORY:
        diff = float(np.abs(t - thumb).mean())
        if diff < SAME_CAMERA and (best is None or diff < best[0]):
            best = (diff, mode, cx)
    return (best[1], best[2]) if best else None


def auto_graph(media, clip, clip_no: int = 0) -> tuple[str, list[tuple[float, float, str, float]]]:
    """Build an ffmpeg filter graph that frames every shot in the clip on its own."""
    _CLIP_COUNT[0] += 1
    clip_no = clip_no or _CLIP_COUNT[0]
    plan = []
    for shot_no, (s, e) in enumerate(shots(media.path, clip["start"], clip["end"] - clip["start"]), 1):
        mode, cx, confident, thumb, frames, per_frame, stable = classify_shot(
            media.path, clip["start"] + s, clip["start"] + e)
        note = ""
        if confident:
            if thumb is not None:
                _MEMORY.append((thumb, mode, cx))
        else:
            match = match_camera(thumb) if thumb is not None else None
            if match and match[0] == FACE:
                # Same camera as a known close-up: crop on the face we found here, or where that camera's face was.
                mode, cx = FACE, (stable[0]["cx"] if stable else match[1])
                note = "(close-up camera matched)"
            elif match:
                mode, cx = match
                note = "(wide camera matched)"
            else:
                note = "(unsure: no matching camera yet)"
        _save_debug(clip_no, shot_no, frames, per_frame, stable, mode, cx, note)
        if plan and plan[-1][2] == mode and abs(plan[-1][3] - cx) < 0.05:
            plan[-1] = (plan[-1][0], e, mode, plan[-1][3])  # same framing as the previous shot: merge
        else:
            plan.append((s, e, mode, cx))
    n = len(plan)
    parts = [f"[0:v]split={n}" + "".join(f"[in{i}]" for i in range(n))]
    parts += [segment_filter(i, s, e, m, cx, media.width, media.height) for i, (s, e, m, cx) in enumerate(plan)]
    parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]")
    return ";".join(parts), plan