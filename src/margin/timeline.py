"""Story notes: the timeline and the bible, built together only when the author asks
(specs 0006 and 0008).

One extraction call per chapter section lists its scenes and the characters and places it
names, with facts. Every quote, time expression and name must verify against the chapter or it
is dropped (ADR 0001). Extractions are cached by chapter text, so a regenerate re-reads only
changed chapters. Then one placement call puts the scenes in story order: a card stands only
when it rests on verified time words, in the card's own scenes or a scene beside them, otherwise
its scenes are shown as not placed. One bible call groups names that are the same character or
place, and code splits any group its names and quotes don't support.
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
from margin.steps import bible as bible_step
from margin.steps import events as events_step
from margin.steps import placement as placement_step
from margin.verify import quote_in_passage

# Bump when the extraction format changes, so cached extractions are re-read.
VERSION = 2
TIME_MIN_WORDS = 2
EVENT_TOKENS = 70  # one scene in the placement prompt
PLACED_TOKENS = 30  # one placed scene in its output
NAME_TOKENS = 80  # one name with its facts in the bible prompt
NAMES_PER_CHAPTER = 15  # for estimating a chapter not read yet
NEIGHBOUR = 2  # a card may borrow time words from a scene at most this far away
BANDS = ("before", "story", "after")
# Words that never tell two names apart.
FILLER = {"the", "of", "a", "an"}
# Titles: "Mr Abernathy" may be "J. Abernathy", but "Mr Venn" is never "Mrs Venn".
TITLES = {
    "mr", "mrs", "miss", "ms", "dr", "doctor", "sir", "lady", "lord", "dame", "master", "mistress",
    "brother", "sister", "father", "mother", "aunt", "uncle", "captain", "commander", "constable",
    "sergeant", "inspector", "major", "colonel", "general", "lieutenant", "reverend", "rev",
    "vicar", "bishop", "abbot", "prior", "judge", "king", "queen", "prince", "princess", "saint",
}  # fmt: skip


def _slug(manuscript: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", manuscript.lower()).strip("-")[:60] or "manuscript"
    return f"{slug}-{hashlib.sha256(manuscript.encode()).hexdigest()[:8]}"


def chapter_hash(chapter: Chapter) -> str:
    text = chapter.title + "\n\n" + "\n\n".join(chapter.paragraphs)
    return hashlib.sha256(text.encode()).hexdigest()


def _extraction_key(s: Settings) -> str:
    """Everything besides the chapter text that shapes an extraction: a change re-reads."""
    parts = [str(VERSION), events_step.SYSTEM, s.events_model, s.events_effort]
    parts += [str(s.event_cap), str(s.scene_words), str(s.section_words), str(TIME_MIN_WORDS)]
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
    """Output room for placing this many scenes, up to the configured ceiling."""
    return min(s.place_max_tokens, events * PLACED_TOKENS * 2 + 2000)


def bible_max_tokens(names: int, s: Settings) -> int:
    return min(s.bible_max_tokens, names * 40 + 1500)


def scene_cap(chapter: Chapter, s: Settings) -> int:
    """About one scene per scene_words words, at least two (a short chapter can still hold two
    scenes), at most event_cap."""
    return max(2, min(s.event_cap, round(chapter.words / s.scene_words)))


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


def _cached(data_dir: Path, chapter: Chapter, s: Settings) -> dict[str, Any] | None:
    path = _cache_path(data_dir, chapter, s)
    if not path.exists():
        return None
    notes: dict[str, Any] = json.loads(path.read_text())
    return notes


def estimate(chapters: list[Chapter], data_dir: Path, s: Settings) -> dict[str, Any]:
    """What a regenerate re-reads and its worst-case cost, before any model call."""
    cached = {c.number: _cached(data_dir, c, s) for c in chapters}
    changed = [c for c in chapters if cached[c.number] is None]
    extract = 0.0
    for c in changed:
        n = len(sections(c.paragraphs, s.section_words)) or 1
        tokens_in = int(min(c.words, s.section_words) * TOKENS_PER_WORD) + 1100
        extract += n * (estimate_cost(s.events_model, tokens_in, s.events_max_tokens) or 0)
    known = [n for n in cached.values() if n is not None]
    events_max = sum(len(n["events"]) for n in known) + sum(scene_cap(c, s) for c in changed)
    names = sum(len(n["entities"]) for n in known) + NAMES_PER_CHAPTER * len(changed)
    place_in = events_max * EVENT_TOKENS + 1500
    place = estimate_cost(s.place_model, place_in, place_max_tokens(events_max, s)) or 0
    bible_in = names * NAME_TOKENS + 800
    bible = estimate_cost(s.bible_model, bible_in, bible_max_tokens(names, s)) or 0
    return {
        "chapters": len(chapters),
        "changed": [
            {"number": c.number, "title": chapter_label(c.number, c.title)} for c in changed
        ],
        "events_max": events_max,
        "worst_case": round(extract + place + bible, 4),
        "placement": round(place, 4),
        "bible": round(bible, 4),
        "models": sorted({s.events_model, s.place_model, s.bible_model}),
    }


# --- Extraction -----------------------------------------------------------------------------


def _name_in(name: str, text: str) -> bool:
    return quote_in_passage(name, text, 1)


def extract_chapter(
    chapter: Chapter, *, client: ModelClient, s: Settings, usage: Usage
) -> tuple[dict[str, Any], dict[str, int]]:
    """Verified scenes in the order the chapter tells them, and the characters and places it
    names with their verified facts; and counts of what failed."""
    events: list[dict[str, Any]] = []
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    seen: set[str] = set()
    failed = {"quotes": 0, "times": 0, "errors": 0, "names": 0, "facts": 0}
    text = "\n\n".join(chapter.paragraphs)
    cap = scene_cap(chapter, s)
    parts = sections(chapter.paragraphs, s.section_words)
    for section in parts:
        section_words = sum(len(p.split()) for p in section)
        share = max(1, round(cap * section_words / max(1, chapter.words)) + 1)
        left = min(share, cap - len(events))
        reply = _call_twice(
            lambda section=section, left=left: events_step.extract(
                client,
                title=chapter.title,
                text="\n\n".join(section),
                cap=max(1, left),
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
        for e in reply.output.events[: max(0, left)]:
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
        for ent in reply.output.entities:
            name = " ".join(html.unescape(ent.name).split())
            if not name or not _name_in(name, text):
                failed["names"] += 1
                continue
            entry = entities.setdefault(
                (ent.kind, name.lower()), {"name": name, "kind": ent.kind, "facts": []}
            )
            for f in ent.facts:
                q = html.unescape(f.quote)
                para = locate(q, chapter.paragraphs)
                if para is None:
                    failed["facts"] += 1
                    continue
                if all(q.lower() != x["quote"].lower() for x in entry["facts"]):
                    entry["facts"].append(
                        {"text": html.unescape(f.text), "quote": q, "paragraph": para}
                    )
    return {"events": events, "entities": list(entities.values())}, failed


# --- Placement ------------------------------------------------------------------------------


def _passage_id(passages: list[Passage], chapter: int, paragraph: int) -> str | None:
    for p in passages:
        if p.chapter == chapter and p.para_start <= paragraph <= p.para_end:
            return p.id
    return None


class PlacementError(RuntimeError):
    pass


def place(
    events: list[dict[str, Any]], *, client: ModelClient, s: Settings, usage: Usage
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Periods in story order (before, story, after) and the scenes not placed. A card stands
    only when every scene in its basis has verified time words and is one of its own scenes,
    or a scene at most NEIGHBOUR places from one of them in the same chapter."""
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

    def near(b: dict[str, Any], own: list[dict[str, Any]]) -> bool:
        return any(
            b["chapter"] == o["chapter"] and abs(b["position"] - o["position"]) <= NEIGHBOUR
            for o in own
        )

    by_band: dict[str, list[dict[str, Any]]] = {band: [] for band in BANDS}
    placed: set[str] = set()
    ungrounded = 0
    for period in reply.output.periods:
        cards = []
        for card in period.cards:
            own = [by_id[i] for i in dict.fromkeys(card.ids) if i in by_id and i not in placed]
            if not own:
                continue
            ids = list(dict.fromkeys(card.basis))
            basis = [by_id[b] for b in ids if b in by_id]
            if (
                not basis
                or len(basis) != len(ids)
                or not all(b["time"] and near(b, own) for b in basis)
            ):
                ungrounded += 1
                continue
            placed.update(o["id"] for o in own)
            cards.append(
                {
                    "tellings": own,
                    "uncertain": card.uncertain,
                    "basis": [
                        {"id": b["id"], "time": b["time"], "chapter_label": b["chapter_label"]}
                        for b in basis
                    ],
                }
            )
        if cards:
            by_band[period.band].append(
                {"label": html.unescape(period.label), "band": period.band, "cards": cards}
            )
    periods = [p for band in BANDS for p in by_band[band]]
    unplaced = [e for e in events if e["id"] not in placed]
    return periods, unplaced, {"ungrounded": ungrounded}


# --- Bible ----------------------------------------------------------------------------------


def _words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", name.lower().replace("’", "'")) if w not in FILLER]


def _within(short: list[str], long: list[str]) -> bool:
    """Every word of the shorter name is in the longer; an initial ("T. Venn") stands for a
    word it begins."""
    rest = list(long)
    for w in short:
        match = next((x for x in rest if x == w or (len(w) == 1 and x.startswith(w))), None)
        if match is None:
            return False
        rest.remove(match)
    return True


def _split(name: str) -> tuple[set[str], list[str]]:
    words = _words(name)
    return {w for w in words if w in TITLES}, [w for w in words if w not in TITLES]


def _same(a: str, b: str) -> bool:
    """The names themselves show one is the other: one's name words are all in the other's,
    and their titles, if both have one, agree ("Odo", "Brother Odo"; "Mr Lusk",
    "Matthew Lusk")."""
    (ta, wa), (tb, wb) = _split(a), _split(b)
    if ta and tb and ta != tb:
        return False
    if not wa or not wb:
        return bool(ta and tb and ta == tb and not wa and not wb)
    return _within(wa, wb) or _within(wb, wa)


def _supported_components(ids: list[str], names: dict[str, dict[str, Any]]) -> list[list[str]]:
    """Split a model's group into the parts its names support. A name joins a part only when it
    is the same as one member ("Odo", "Brother Odo") and contradicts none: two names that
    differ but share a word ("Maren Venn", "Tomas Venn"; "Mr Venn", "Mrs Venn") are never in one
    part. A name that could join two parts (a bare "Venn") stays on its own."""
    # Fullest names first, counting name words before titles, so a "Mrs Garrow" that could be
    # Nell or Kit meets both and stays on its own.
    order = sorted(
        ids, key=lambda i: (-len(_split(names[i]["name"])[1]), -len(_words(names[i]["name"])), i)
    )
    parts: list[list[str]] = []
    for i in order:
        n = names[i]["name"]

        def fits(part: list[str], n: str = n) -> bool:
            others = [names[j]["name"] for j in part]
            clash = any(not _same(n, o) and set(_words(n)) & set(_words(o)) for o in others)
            return not clash and any(_same(n, o) for o in others)

        homes = [part for part in parts if fits(part)]
        if len(homes) == 1:
            homes[0].append(i)
        else:
            parts.append([i])
    return parts


def _titles_clash(a: str, b: str) -> bool:
    ta, tb = _split(a)[0], _split(b)[0]
    return bool(ta and tb and ta != tb)


def appears_in(name: str, text: str) -> bool:
    """The name, as written (case kept, so "Will" isn't "I will"), with word boundaries.
    A leading "the" may be either case."""
    name = re.sub(r"^the\s+", "", " ".join(name.split()), flags=re.IGNORECASE)
    if not name:
        return False
    parts = ["".join("['’]" if ch in "'’" else re.escape(ch) for ch in w) for w in name.split()]
    # A letter or digit next to the name breaks it; "_" doesn't (Markdown italics: _Titubic_).
    return re.search(r"(?<![^\W_])" + r"\s+".join(parts) + r"(?![^\W_])", text) is not None


def build_bible(
    chapters: list[Chapter],
    per_chapter: dict[int, dict[str, Any]],
    passages: list[Passage],
    *,
    client: ModelClient,
    s: Settings,
    usage: Usage,
) -> dict[str, Any]:
    """Entries for characters and places: names, verified facts in reading order, and the
    chapters whose text contains one of the names."""
    names: dict[str, dict[str, Any]] = {}
    index: dict[tuple[str, str], str] = {}
    for c in chapters:
        label = chapter_label(c.number, c.title)
        for ent in per_chapter[c.number]["entities"]:
            key = (ent["kind"], ent["name"].lower())
            if key not in index:
                index[key] = f"N{len(names) + 1}"
                names[index[key]] = {"name": ent["name"], "kind": ent["kind"], "facts": []}
                names[index[key]]["chapter"] = label
            for f in ent["facts"]:
                names[index[key]]["facts"].append(
                    {
                        **f,
                        "chapter": c.number,
                        "chapter_label": label,
                        "passage_id": _passage_id(passages, c.number, f["paragraph"]),
                    }
                )
    if not names:
        return {"characters": [], "places": [], "split": 0}
    reply = _call_twice(
        lambda: bible_step.group(
            client,
            names=[
                {
                    "id": i,
                    "name": n["name"],
                    "kind": n["kind"],
                    "chapter": n["chapter"],
                    "facts": [f["text"] for f in n["facts"]],
                }
                for i, n in names.items()
            ],
            model=s.bible_model,
            effort=s.bible_effort,
            max_tokens=bible_max_tokens(len(names), s),
        ),
        s.bible_model,
        usage,
    )
    groups: list[tuple[list[str], str | None]] = []
    used: set[str] = set()
    split = 0
    for g in reply.output.groups if reply.output else []:
        ids = [i for i in dict.fromkeys(g.ids) if i in names and i not in used]
        by_kind: dict[str, list[str]] = {}
        for i in ids:
            by_kind.setdefault(names[i]["kind"], []).append(i)
        for same_kind in by_kind.values():
            parts = _supported_components(same_kind, names)
            split += len(parts) - 1
            for part in parts:
                used.update(part)
                groups.append((part, html.unescape(g.name)))
    groups += [([i], None) for i in names if i not in used]

    texts = {c.number: "\n\n".join(c.paragraphs) for c in chapters}
    labels = {c.number: chapter_label(c.number, c.title) for c in chapters}
    entries: dict[str, list[dict[str, Any]]] = {"character": [], "place": []}
    for ids, wanted in groups:
        all_names = list(dict.fromkeys(names[i]["name"] for i in ids))
        name = next((n for n in all_names if wanted and n.lower() == wanted.lower()), None)
        name = name or max(all_names, key=len)
        facts = sorted(
            (f for i in ids for f in names[i]["facts"]),
            key=lambda f: (f["chapter"], f["paragraph"]),
        )
        unique = list({f["quote"].lower(): f for f in facts}.values())
        appears = [n for n, t in texts.items() if any(appears_in(x, t) for x in all_names)]
        entries[names[ids[0]]["kind"]].append(
            {
                "name": name,
                "names": all_names,
                "kind": names[ids[0]]["kind"],
                "facts": unique,
                "chapters": [{"number": n, "label": labels[n]} for n in appears],
            }
        )
    for kind in entries:
        entries[kind].sort(key=lambda e: (-len(e["chapters"]), e["name"].lower()))
    return {
        "characters": entries["character"],
        "places": entries["place"],
        "split": split,
        "error": None if reply.output else reply.error,
    }


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
    """Events: chapter_done (one per chapter), placing, bible, done. Saves the story notes."""
    s = settings
    usage = Usage()
    data_dir = s.data_dir
    failed = {"quotes": 0, "times": 0, "errors": 0, "names": 0, "facts": 0}
    per_chapter: dict[int, dict[str, Any]] = {}
    lock = threading.Lock()

    def one(c: Chapter) -> tuple[Chapter, dict[str, Any], bool]:
        cached = _cached(data_dir, c, s)
        if cached is not None:
            return c, cached, True
        notes, f = extract_chapter(c, client=client, s=s, usage=usage)
        with lock:
            for k in failed:
                failed[k] += f[k]
        if not f["errors"]:  # a chapter with a failed call is read again next time
            _write(_cache_path(data_dir, c, s), notes)
        return c, notes, False

    with ThreadPoolExecutor(max_workers=s.check_concurrency) as pool:
        for c, found, cached in pool.map(one, chapters):
            per_chapter[c.number] = found
            yield (
                "chapter_done",
                {
                    "number": c.number,
                    "title": chapter_label(c.number, c.title),
                    "events": len(found["events"]),
                    "cached": cached,
                },
            )

    events: list[dict[str, Any]] = []
    for c in chapters:
        label = chapter_label(c.number, c.title)
        for position, e in enumerate(per_chapter[c.number]["events"]):
            events.append(
                {
                    **e,
                    "id": f"E{len(events) + 1}",
                    "chapter": c.number,
                    "chapter_label": label,
                    "position": position,
                    "passage_id": _passage_id(passages, c.number, e["paragraph"]),
                }
            )
    yield "placing", {"events": len(events)}
    periods, unplaced, placement = (
        place(events, client=client, s=s, usage=usage) if events else ([], [], {"ungrounded": 0})
    )
    yield "bible", {"names": sum(len(n["entities"]) for n in per_chapter.values())}
    bible = build_bible(chapters, per_chapter, passages, client=client, s=s, usage=usage)
    notes = {
        "manuscript": manuscript,
        "made_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "models": sorted({s.events_model, s.place_model, s.bible_model}),
        "hashes": {str(c.number): chapter_hash(c) for c in chapters},
        "periods": periods,
        "unplaced": unplaced,
        "events": len(events),
        "bible": bible,
        "failed": {**failed, **placement, "split": bible["split"]},
        "calls": usage.calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost": round(usage.cost, 4),
    }
    _write(_saved_path(data_dir, manuscript), notes)
    yield "done", notes


def load(data_dir: Path, manuscript: str) -> dict[str, Any] | None:
    """The saved story notes, or None. Notes from before spec 0008 (no bible) count as none."""
    path = _saved_path(data_dir, manuscript)
    if not path.exists():
        return None
    saved: dict[str, Any] = json.loads(path.read_text())
    return saved if "bible" in saved else None


def changed_since(saved: dict[str, Any], chapters: list[Chapter]) -> int:
    """How many chapters were edited or added (their text is new) plus how many were removed,
    by content, so renumbering after an insert doesn't count as a change."""
    now = Counter(chapter_hash(c) for c in chapters)
    then = Counter(saved["hashes"].values())
    return max(sum((now - then).values()), sum((then - now).values()))
