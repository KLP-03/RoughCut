"""Pick the strongest moments: an LLM when an API key is set, a transparent heuristic otherwise."""
import json
import os
import re

DEFAULT_MODEL = os.environ.get("ROUGHCUT_MODEL", "claude-sonnet-5-5")

PROMPT = """You are an expert social video editor. Below is a transcript

Pick the {n} strongest standalone moments for short-form social clips. Each clip must:
- run between {min_s} and {max_s} seconds (end of last segment minus start of first segment)
- open with a hook that makes sense without context, and end on a complete thought
- if the moment answers a question, start the clip at the question so viewers have context
- not overlap any other clip

For each clip give: start_segment and end_segment (segment numbers), a title of at most 8 words, the hook (the opening line, quoted from the transcript), thumbnail_text (2 to 5 punchy words), and why (one sentence).

Transcript:
{transcript}"""


def _duration(segs, a, b):
    return segs[b]["end"] - segs[a]["start"]


def _valid(segs, picks, min_s, max_s):
    out, used = [], []
    for p in picks:
        try:
            a, b = int(p["start_segment"]), int(p["end_segment"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= a <= b < len(segs)):
            continue
        d = _duration(segs, a, b)
        if d < min_s * 0.8 or d > max_s * 1.2:
            continue
        if any(not (b < ua or a > ub) for ua, ub in used):
            continue
        used.append((a, b))
        out.append(_clip(segs, a, b, p.get("title"), p.get("hook"), p.get("thumbnail_text"), p.get("why"), "llm"))
    return out


def _clip(segs, a, b, title=None, hook=None, thumb=None, why=None, source="heuristic"):
    first = segs[a]["text"]
    return {
        "start_segment": a,
        "end_segment": b,
        "start": segs[a]["start"],
        "end": segs[b]["end"],
        "duration": round(_duration(segs, a, b), 2),
        "title": (title or _short(first, 10)).strip(),
        "hook": (hook or first).strip(),
        "thumbnail_text": (thumb or " ".join(re.sub(r"[^\w\s']", "", first).split()[:4])).strip(),
        "why": why or "",
        "picked_by": source,
        "text": " ".join(s["text"] for s in segs[a : b + 1]),
    }


def _short(text, max_words):
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words]) + "..."


CLIPS_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_segment": {"type": "integer"},
                    "end_segment": {"type": "integer"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "thumbnail_text": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["start_segment", "end_segment", "title", "hook", "thumbnail_text", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def pick_with_llm(segs, n, min_s, max_s, model=DEFAULT_MODEL):
    import anthropic  # imported lazily so the heuristic path has no dependency

    transcript = "\n".join(f"[{s['id']}] {s['start']:.1f}-{s['end']:.1f}: {s['text']}" for s in segs)
    msg = anthropic.Anthropic().messages.create(
        model=model,
        max_tokens=16000,
        # Structured outputs: Claude's reply is guaranteed to be JSON matching CLIPS_SCHEMA.
        output_config={"format": {"type": "json_schema", "schema": CLIPS_SCHEMA}},
        messages=[{"role": "user", "content": PROMPT.format(n=n, min_s=min_s, max_s=max_s, transcript=transcript)}],
    )
    raw = "".join(getattr(block, "text", "") for block in msg.content if getattr(block, "type", "") == "text")
    stop = getattr(msg, "stop_reason", None)
    if stop not in (None, "end_turn"):
        raise ValueError(f"Claude stopped early (stop_reason: {stop}); its reply began: {raw[:200]!r}")
    try:
        return json.loads(raw)["clips"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return parse_llm_json(raw)


def parse_llm_json(raw: str):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("model did not return a JSON array")
    return json.loads(raw[start : end + 1])


HOOK_WORDS = re.compile(r"\b(why|how|secret|mistake|never|always|actually|biggest|first|best|worst|truth|problem|fast|faster)\b", re.I)


def _score(segs, a, b):
    text = " ".join(s["text"] for s in segs[a : b + 1])
    words = len(text.split())
    d = _duration(segs, a, b)
    pace = words / d if d else 0  # dense, energetic speech
    first = segs[a]["text"]
    score = min(pace, 3.5)
    score += 1.0 if "?" in first else 0
    score += 0.5 * len(HOOK_WORDS.findall(first))
    score += 0.3 * len(re.findall(r"\d", text[:200])) ** 0.5  # numbers and specifics
    score += 0.5 if segs[b]["text"].rstrip().endswith((".", "!", "?")) else -0.5
    return score


def pick_heuristic(segs, n, min_s, max_s):
    candidates = []
    for a in range(len(segs)):
        for b in range(a, len(segs)):
            d = _duration(segs, a, b)
            if d > max_s:
                break
            if d >= min_s:
                candidates.append((_score(segs, a, b), a, b))
    candidates.sort(reverse=True)
    picks, used = [], []
    for _score_val, a, b in candidates:
        if any(not (b < ua or a > ub) for ua, ub in used):
            continue
        used.append((a, b))
        picks.append(_clip(segs, a, b))
        if len(picks) == n:
            break
    return picks


def pick_moments(segs, n=5, min_s=15, max_s=60, use_llm=True, model=DEFAULT_MODEL):
    if use_llm:
        try:
            picks = _valid(segs, pick_with_llm(segs, n, min_s, max_s, model), min_s, max_s)
            if picks:
                return sorted(picks, key=lambda c: c["start"])
            print("  LLM picks did not pass validation; falling back to the heuristic.")
        except Exception as e:  # missing credentials, network, or parsing problems should never stop the edit
            if "authentication" in str(e).lower():
                print("  No Claude credentials found (run `ant auth login`, or set ANTHROPIC_API_KEY); using the built-in heuristic.")
            else:
                print(f"  LLM selection failed ({e}); falling back to the heuristic.")
    return sorted(pick_heuristic(segs, n, min_s, max_s), key=lambda c: c["start"])
