"""Write a script that builds an editable, already-framed vertical timeline inside DaVinci Resolve.

Each shot becomes a normal timeline clip with Zoom and Position (Pan/Tilt) set in the Inspector,
so every framing decision can be adjusted by hand. Stacked shots use two layers (V1 and V2).
"""
import json
from pathlib import Path

TL_W, TL_H = 1080, 1920
# In a vertical timeline, Resolve measures Position in landscape terms: X units are 1.778x smaller
# than pixels and Y units are 1.778x larger. These convert our pixel offsets into Inspector values.
X_UNITS = TL_W / TL_H
Y_UNITS = TL_H / TL_W


def transforms(mode: str, cx: float, src_w: int, src_h: int) -> list[dict]:
    """Inspector values for one shot, assuming the timeline places media at 1:1 pixels, centered."""
    if mode == "stack":
        zoom = (TL_H / 2) / src_h            # each person fills a 1080x960 half
        panel_w = TL_W / zoom                 # source pixels visible across one panel
        left_center, right_center = panel_w / 2, src_w - panel_w / 2
        return [
            {"layer": "top", "zoom": zoom, "pan": -(left_center - src_w / 2) * zoom * X_UNITS, "tilt": TL_H / 4 * Y_UNITS},
            {"layer": "bottom", "zoom": zoom, "pan": -(right_center - src_w / 2) * zoom * X_UNITS, "tilt": -TL_H / 4 * Y_UNITS},
        ]
    zoom = TL_H / src_h                       # fill the full height
    crop_w = TL_W / zoom
    left = min(max(cx * src_w - crop_w / 2, 0), src_w - crop_w)  # never show past the frame edge
    return [{"layer": "full", "zoom": zoom, "pan": -(left + crop_w / 2 - src_w / 2) * zoom * X_UNITS, "tilt": 0.0}]


def build_plan(clips, media, name: str) -> dict:
    fps = media.fps
    shots, rec = [], 0
    for n, c in enumerate(clips, 1):
        for s, e, mode, cx in c.get("framing") or [(0.0, c["end"] - c["start"], "center", 0.5)]:
            src_in = round((c["start"] + s) * fps)
            src_out = round((c["start"] + e) * fps)
            shots.append({"clip": n, "mode": mode, "src_in": src_in, "src_out": src_out, "rec": rec,
                          "layers": transforms(mode, float(cx), media.width, media.height)})
            rec += src_out - src_in
    titles = {n: c.get("title", "") for n, c in enumerate(clips, 1)}
    return {"name": name, "source": str(Path(media.path).resolve()), "fps": fps, "shots": shots, "titles": titles}


SCRIPT = r'''# roughcut: build a framed vertical timeline in DaVinci Resolve.
# Open your project in Resolve, then go to Workspace > Console, choose Py3, and run:
#   exec(open("__PATH__").read())
import json

PLAN = json.loads(r"""__PLAN__""")
TILT_SIGN = 1  # if stacked shots come out with top and bottom swapped, change this to -1 and run again


def get_resolve():
    for getter in (lambda: resolve, lambda: app.GetResolve()):
        try:
            return getter()
        except NameError:
            pass
    import DaVinciResolveScript as bmd
    return bmd.scriptapp("Resolve")


project = get_resolve().GetProjectManager().GetCurrentProject()
pool = project.GetMediaPool()

# Reuse the source clip if it is already in the Media Pool, otherwise import it.
item = None
folders = [pool.GetRootFolder()]
while folders and item is None:
    folder = folders.pop()
    folders += folder.GetSubFolderList()
    for clip in folder.GetClipList():
        if clip.GetClipProperty("File Path") == PLAN["source"]:
            item = clip
            break
if item is None:
    item = pool.ImportMedia([PLAN["source"]])[0]

# Keep this run's timelines together in their own Media Pool bin.
bin_name = PLAN["name"]
existing = [f.GetName() for f in pool.GetRootFolder().GetSubFolderList()]
n = 2
while bin_name in existing:
    bin_name = f"{PLAN['name']} ({n})"
    n += 1
folder = pool.AddSubFolder(pool.GetRootFolder(), bin_name)
if folder:
    pool.SetCurrentFolder(folder)

end_offset = None  # 0 if Resolve's endFrame includes the last frame, 1 if it doesn't (checked on the first shot)
clip_numbers = sorted({shot["clip"] for shot in PLAN["shots"]})

for number in clip_numbers:
    title = PLAN["titles"].get(str(number), "")
    name = f"roughcut {number:02d}" + (f" - {title[:40]}" if title else "")
    timeline, base, k = pool.CreateEmptyTimeline(name), name, 2
    while timeline is None and k < 50:  # Resolve needs unique timeline names; add (2), (3)... on reruns
        name = f"{base} ({k})"
        timeline, k = pool.CreateEmptyTimeline(name), k + 1
    if timeline is None:
        print("Could not create timeline", base)
        continue
    timeline.SetSetting("useCustomSettings", "1")
    timeline.SetSetting("timelineResolutionWidth", "1080")
    timeline.SetSetting("timelineResolutionHeight", "1920")
    timeline.SetSetting("timelineInputResMismatchBehavior", "centerCrop")  # 1:1 pixels, so our numbers line up
    timeline.AddTrack("video")
    project.SetCurrentTimeline(timeline)  # AppendToTimeline places clips on the current timeline
    cursor = timeline.GetStartFrame()  # where the next shot starts; always the real end of the last one

    for shot in [s for s in PLAN["shots"] if s["clip"] == number]:
        length = shot["src_out"] - shot["src_in"]
        placed_end = None
        for layer in sorted(shot["layers"], key=lambda l: l["layer"] == "top"):  # V1 first, so we know where it ends
            info = {"mediaPoolItem": item, "startFrame": shot["src_in"],
                    "endFrame": shot["src_in"] + length - 1 + (end_offset or 0),
                    "trackIndex": 2 if layer["layer"] == "top" else 1, "recordFrame": cursor}
            if layer["layer"] == "top":
                info["mediaType"] = 1  # video only; the bottom layer on V1 carries the audio
            placed = pool.AppendToTimeline([info])
            if not placed:
                print("Could not place a shot in", name)
                continue
            clip_item = placed[0]
            if end_offset is None:
                end_offset = length - clip_item.GetDuration()  # 1 if Resolve came up a frame short
                if end_offset:
                    print("roughcut: Resolve's endFrame excludes the last frame; adjusting the remaining shots")
            clip_item.SetProperty("ZoomX", layer["zoom"])
            clip_item.SetProperty("ZoomY", layer["zoom"])
            clip_item.SetProperty("Pan", layer["pan"])
            clip_item.SetProperty("Tilt", layer["tilt"] * TILT_SIGN)
            if layer["layer"] != "top":
                placed_end = clip_item.GetEnd()
        if placed_end is not None:
            cursor = placed_end
    print("roughcut: built", name)

print(f"roughcut: done. {len(clip_numbers)} timelines in the '{bin_name}' bin.")
'''


def write_resolve_script(clips, media, out: Path, name: str = "roughcut vertical") -> Path:
    path = (out / "resolve_vertical_timeline.py").resolve()
    plan = build_plan(clips, media, name)
    path.write_text(SCRIPT.replace("__PLAN__", json.dumps(plan, indent=1)).replace("__PATH__", str(path)))
    return path