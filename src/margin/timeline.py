"""Timeline: the story's events in story order, built only when the author asks (spec 0006).

Each chapter's events are extracted section by section, and each event's quote must verify
against the chapter or the event is dropped. Its time words must verify too, or the event has
none. Extraction results are cached by chapter text, so a regenerate re-reads only changed
chapters. One placement call then groups every event into periods; a placement counts only
when it rests on verified time words, otherwise the event is shown as not placed (ADR 0001).
"""

import hashlib
import html
import json
import os
import re
import threading
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from margin.check import TOKENS_PER_WORD, Usage, _call_twice, locate, sections
from margin.config import Settings, estimate_cost
from margin.llm import ModelClient
from margin.manuscript import Chapter
from margin.passages import Passage, chapter_label
from margin.steps import events as events_step
from margin.steps import placement as placement_step
from margin.verify import quote_in_passage

# Bump when a prompt or the event format changes, so cached extractions are re-read.
VERSION = 1
TIME_MIN_WORDS = 2
EVENT_TOKENS = 70  # one event in the placement prompt
PLACED_TOKENS = 30  # one placed event in its output


def _slug(manuscript: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", manuscript.lower()).strip("-")[:60] or "manuscript"
    return f"{slug}-{hashlib.sha256(manuscript.encode()).hexdigest()[:8]}"


def chapter_hash(chapter: Chapter) -> str:
    text = chapter.title + "\n\n" + "\n\n".join(chapter.paragraphs)
    return hashlib.sha256(text.encode()).hexdigest()


def _extraction_key(s: Settings) -> str:
    """Everything besides the chapter text that shapes an extraction: a change re-reads."""
    parts = [str(VERSION), events_step.SYSTEM, s.events_model, s.events_effort]
    parts += [str(s.event_cap), str(s.section_words), str(TIME_MIN_WORDS)]
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:12]


def _cache_path(data_dir: Path, chapter: Chapter, s: Settings) -> Path:
    name = f"{chapter_hash(chapter)[:40]}-{_extraction_key(s)}.json"
    return data_dir / "timeline" / "events" / name


def _write(path: Path, data: Any) -> None:
    """Write whole or not at all, so a crash or a concurrent read never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(tmp, path)


def place_max_tokens(events: int, s: Settings) -> int:
    """Output room for placing this many events, up to the configured ceiling."""
    return min(s.place_max_tokens, events * PLACED_TOKENS * 2 + 2000)


def _saved_path(data_dir: Path, manuscript: str) -> Path:
    return data_dir / "timeline" / f"{_slug(manuscript)}.json"


def chapters_from_passages(passages: list[Passage]) -> list[Chapter]:
    """The indexed chapters' text, rebuilt from their passages (chapters with no text have none)."""
    by_chapter: dict[int, list[Passage]] = {}
    for p in passages:
        by_chapter.setdefault(p.chapter, []).append(p)
    out = []
    for number in sorted(by_chapter):
        ps = sorted(by_chapter[number], key=lambda p: p.para_start)
        paragraphs = [para for p in ps for para in p.text.split("\n\n")]
        out.append(Chapter(number=number, title=ps[0].chapter_title, paragraphs=paragraphs))
    return out


# --- Cost -----------------------------------------------------------------------------------


def _cached(data_dir: Path, chapter: Chapter, s: Settings) -> list[dict[str, Any]] | None:
    path = _cache_path(data_dir, chapter, s)
    if not path.exists():
        return None
    events: list[dict[str, Any]] = json.loads(path.read_text())
    return events


def estimate(chapters: list[Chapter], data_dir: Path, s: Settings) -> dict[str, Any]:
    """What a regenerate re-reads and its worst-case cost, before any model call."""
    changed = [c for c in chapters if _cached(data_dir, c, s) is None]
    extract = 0.0
    for c in changed:
        n = len(sections(c.paragraphs, s.section_words)) or 1
        tokens_in = int(min(c.words, s.section_words) * TOKENS_PER_WORD) + 900
        extract += n * (estimate_cost(s.events_model, tokens_in, s.events_max_tokens) or 0)
    cached_events = sum(len(_cached(data_dir, c, s) or []) for c in chapters if c not in changed)
    events_max = cached_events + s.event_cap * len(changed)
    place_in = events_max * EVENT_TOKENS + 1200
    place = estimate_cost(s.place_model, place_in, place_max_tokens(events_max, s)) or 0
    return {
        "chapters": len(chapters),
        "changed": [
            {"number": c.number, "title": chapter_label(c.number, c.title)} for c in changed
        ],
        "events_max": events_max,
        "worst_case": round(extract + place, 4),
        "placement": round(place, 4),
        "models": sorted({s.events_model, s.place_model}),
    }


# --- Extraction -----------------------------------------------------------------------------


def extract_chapter(
    chapter: Chapter, *, client: ModelClient, s: Settings, usage: Usage
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Verified events in the order the chapter tells them, and counts of what failed."""
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    failed = {"quotes": 0, "times": 0, "errors": 0}
    text = "\n\n".join(chapter.paragraphs)
    for section in sections(chapter.paragraphs, s.section_words):
        left = s.event_cap - len(events)
        if left <= 0:
            break
        reply = _call_twice(
            lambda section=section, left=left: events_step.extract(
                client,
                title=chapter.title,
                text="\n\n".join(section),
                cap=left,
                model=s.events_model,
                effort=s.events_effort,
                max_tokens=s.events_max_tokens,
            ),
            s.events_model,
            usage,
        )
        if reply.output is None:
            failed["errors"] += 1
            continue
        for e in reply.output.events[:left]:
            quote = html.unescape(e.quote)
            para = locate(quote, chapter.paragraphs)
            if para is None:
                failed["quotes"] += 1
                continue
            if quote.lower() in seen:
                continue
            seen.add(quote.lower())
            time = html.unescape(e.time).strip()
            if time and not quote_in_passage(time, text, TIME_MIN_WORDS):
                failed["times"] += 1
                time = ""
            events.append(
                {"text": html.unescape(e.text), "quote": quote, "paragraph": para, "time": time}
            )
    return events, failed


# --- Placement ------------------------------------------------------------------------------


def _passage_id(passages: list[Passage], chapter: int, paragraph: int) -> str | None:
    for p in passages:
        if p.chapter == chapter and p.para_start <= paragraph <= p.para_end:
            return p.id
    return None


def place(
    events: list[dict[str, Any]], *, client: ModelClient, s: Settings, usage: Usage
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Periods in story order and the events not placed. A placement stands only when every
    event in its basis exists and has verified time words."""
    by_id = {e["id"]: e for e in events}
    reply = _call_twice(
        lambda: placement_step.place(
            client,
            events=[
                {"id": e["id"], "chapter": e["chapter_label"], "text": e["text"], "time": e["time"]}
                for e in events
            ],
            model=s.place_model,
            effort=s.place_effort,
            max_tokens=place_max_tokens(len(events), s),
        ),
        s.place_model,
        usage,
    )
    if reply.output is None:
        raise PlacementError(reply.error or "no placement")
    periods: list[dict[str, Any]] = []
    placed: set[str] = set()
    ungrounded = 0
    for period in reply.output.periods:
        cards = []
        for p in period.events:
            event = by_id.get(p.id)
            if event is None or p.id in placed:
                continue
            basis = [by_id[b] for b in dict.fromkeys(p.basis) if b in by_id]
            if not basis or len(basis) != len(set(p.basis)) or not all(b["time"] for b in basis):
                ungrounded += 1
                continue
            placed.add(p.id)
            cards.append(
                {
                    **event,
                    "uncertain": p.uncertain,
                    "basis": [
                        {"id": b["id"], "time": b["time"], "chapter_label": b["chapter_label"]}
                        for b in basis
                    ],
                }
            )
        if cards:
            periods.append({"label": html.unescape(period.label), "events": cards})
    unplaced = [e for e in events if e["id"] not in placed]
    return periods, unplaced, {"ungrounded": ungrounded}


class PlacementError(RuntimeError):
    pass


# --- Regenerate, save, load -----------------------------------------------------------------


def regenerate(
    manuscript: str,
    chapters: list[Chapter],
    passages: list[Passage],
    *,
    client: ModelClient,
    settings: Settings,
    now: datetime | None = None,
) -> Iterator[tuple[str, Any]]:
    """Events: chapter_done (one per chapter), placing, done. Saves the timeline."""
    s = settings
    usage = Usage()
    data_dir = s.data_dir
    failed = {"quotes": 0, "times": 0, "errors": 0}
    per_chapter: dict[int, list[dict[str, Any]]] = {}
    lock = threading.Lock()

    def one(c: Chapter) -> tuple[Chapter, list[dict[str, Any]], bool]:
        cached = _cached(data_dir, c, s)
        if cached is not None:
            return c, cached, True
        events, f = extract_chapter(c, client=client, s=s, usage=usage)
        with lock:
            for k in failed:
                failed[k] += f[k]
        if not f["errors"]:  # a chapter with a failed call is read again next time
            _write(_cache_path(data_dir, c, s), events)
        return c, events, False

    with ThreadPoolExecutor(max_workers=s.check_concurrency) as pool:
        for c, found, cached in pool.map(one, chapters):
            per_chapter[c.number] = found
            yield (
                "chapter_done",
                {
                    "number": c.number,
                    "title": chapter_label(c.number, c.title),
                    "events": len(found),
                    "cached": cached,
                },
            )

    events: list[dict[str, Any]] = []
    for c in chapters:
        label = chapter_label(c.number, c.title)
        for e in per_chapter[c.number]:
            events.append(
                {
                    **e,
                    "id": f"E{len(events) + 1}",
                    "chapter": c.number,
                    "chapter_label": label,
                    "passage_id": _passage_id(passages, c.number, e["paragraph"]),
                }
            )
    yield "placing", {"events": len(events)}
    periods, unplaced, placement = (
        place(events, client=client, s=s, usage=usage) if events else ([], [], {"ungrounded": 0})
    )
    timeline = {
        "manuscript": manuscript,
        "made_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "models": sorted({s.events_model, s.place_model}),
        "hashes": {str(c.number): chapter_hash(c) for c in chapters},
        "periods": periods,
        "unplaced": unplaced,
        "events": len(events),
        "failed": {**failed, **placement},
        "calls": usage.calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost": round(usage.cost, 4),
    }
    _write(_saved_path(data_dir, manuscript), timeline)
    yield "done", timeline


def load(data_dir: Path, manuscript: str) -> dict[str, Any] | None:
    path = _saved_path(data_dir, manuscript)
    if not path.exists():
        return None
    saved: dict[str, Any] = json.loads(path.read_text())
    return saved


def changed_since(saved: dict[str, Any], chapters: list[Chapter]) -> int:
    """How many chapters were edited, added or removed since the timeline was made."""
    # By content, so renumbering after an inserted chapter doesn't count as a change.
    now = Counter(chapter_hash(c) for c in chapters)
    then = Counter(saved["hashes"].values())
    return max(sum((now - then).values()), sum((then - now).values()))
