"""Progress tracker (spec 0005): word-count snapshots per manuscript, a target, and a summary.

Numbers and chapter titles only, never text. One JSON file per manuscript in the data
directory. No model calls.
"""

import hashlib
import json
import re
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _path(data_dir: Path, manuscript: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", manuscript.lower()).strip("-")[:60] or "manuscript"
    digest = hashlib.sha256(manuscript.encode()).hexdigest()[:8]  # names that slug alike
    return data_dir / "progress" / f"{slug}-{digest}.json"


def load(data_dir: Path, manuscript: str) -> dict[str, Any]:
    p = _path(data_dir, manuscript)
    if p.exists():
        return dict(json.loads(p.read_text()))
    return {"manuscript": manuscript, "target": None, "snapshots": []}


def _save(data_dir: Path, state: dict[str, Any]) -> None:
    p = _path(data_dir, state["manuscript"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state))


def _now() -> datetime:
    return datetime.now(UTC)


def record(
    data_dir: Path,
    manuscript: str,
    chapters: list[dict[str, Any]],
    *,
    changed: bool = True,
    now: datetime | None = None,
) -> bool:
    """Save a snapshot after an ingest that indexed something (or the first one ever).
    Returns whether a snapshot was saved."""
    state = load(data_dir, manuscript)
    if not changed and state["snapshots"]:
        return False
    snapshot = {
        "at": (now or _now()).isoformat(),
        "chapters": [
            {"number": c["number"], "title": c["title"], "words": c["words"]} for c in chapters
        ],
    }
    if state["snapshots"] and state["snapshots"][-1]["chapters"] == snapshot["chapters"]:
        return False  # nothing to add: same counts as last time
    state["snapshots"].append(snapshot)
    _save(data_dir, state)
    return True


def set_target(data_dir: Path, manuscript: str, target: int | None) -> None:
    state = load(data_dir, manuscript)
    state["target"] = target if target and target > 0 else None
    _save(data_dir, state)


def _total(snapshot: dict[str, Any]) -> int:
    return sum(int(c["words"]) for c in snapshot["chapters"])


def summary(
    data_dir: Path,
    manuscript: str,
    current: list[dict[str, Any]],
    *,
    stub_words: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """What the page and the CLI show. `current` is the indexed chapter list, used when no
    snapshot exists yet."""
    now = now or _now()
    state = load(data_dir, manuscript)
    snaps = state["snapshots"]
    chapters = snaps[-1]["chapters"] if snaps else current
    total = sum(int(c["words"]) for c in chapters)
    drafted = [c for c in chapters if c["words"] >= stub_words]
    median = statistics.median([c["words"] for c in drafted]) if drafted else None

    since_last = None
    if len(snaps) >= 2:
        since_last = {"words": total - _total(snaps[-2]), "since": snaps[-2]["at"]}
    week = None
    if snaps:
        cutoff = now - timedelta(days=7)
        before = [s for s in snaps if datetime.fromisoformat(s["at"]) <= cutoff]
        base = before[-1] if before else snaps[0]
        if base is not snaps[-1]:
            week = total - _total(base)

    target = state["target"]
    return {
        "manuscript": manuscript,
        "target": target,
        "total": total,
        "percent": round(100 * total / target, 1) if target else None,
        "chapters": [
            {
                **c,
                "status": "drafted" if c["words"] >= stub_words else "stub",
                "of_median": round(100 * c["words"] / median) if median else None,
            }
            for c in chapters
        ],
        "drafted": len(drafted),
        "stubs": len(chapters) - len(drafted),
        "stub_words": stub_words,
        "median": median,
        "since_last": since_last,
        "last_7_days": week,
        "history": [{"at": s["at"], "total": _total(s)} for s in snaps],
        "updated": snaps[-1]["at"] if snaps else None,
    }
