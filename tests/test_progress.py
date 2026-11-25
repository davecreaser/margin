"""Progress tracker (spec 0005): snapshots, stubs, growth, target. Numbers only."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from margin import api, progress
from margin.config import Settings
from margin.index import IndexStats

T0 = datetime(2026, 11, 1, 9, tzinfo=UTC)


def chapters(*words: int) -> list[dict[str, Any]]:
    return [{"number": i, "title": f"Chapter {i}", "words": w} for i, w in enumerate(words, 1)]


def test_snapshots_only_when_something_changed(tmp_path: Path) -> None:
    assert progress.record(tmp_path, "Book", chapters(1000, 5), changed=False, now=T0)  # first ever
    assert not progress.record(tmp_path, "Book", chapters(1000, 5), changed=False, now=T0)
    assert not progress.record(
        tmp_path, "Book", chapters(1000, 5), changed=True, now=T0
    )  # same counts
    assert progress.record(tmp_path, "Book", chapters(1200, 5), changed=True, now=T0)
    assert len(progress.load(tmp_path, "Book")["snapshots"]) == 2
    assert progress.load(tmp_path, "Other")["snapshots"] == []  # per manuscript


def test_summary_counts_stubs_growth_and_the_median(tmp_path: Path) -> None:
    progress.record(tmp_path, "Book", chapters(1000, 5), now=T0)
    progress.record(tmp_path, "Book", chapters(1500, 5), now=T0 + timedelta(days=5))
    progress.record(tmp_path, "Book", chapters(1500, 5, 3000), now=T0 + timedelta(days=9))
    progress.set_target(tmp_path, "Book", 9000)
    s = progress.summary(tmp_path, "Book", [], stub_words=200, now=T0 + timedelta(days=9))
    assert (s["total"], s["percent"], s["drafted"], s["stubs"]) == (4505, 50.1, 2, 1)
    assert s["since_last"]["words"] == 3000
    assert s["last_7_days"] == 4505 - 1005  # from the last snapshot at least 7 days old
    assert s["median"] == 2250 and s["chapters"][0]["of_median"] == 67
    assert [c["status"] for c in s["chapters"]] == ["drafted", "stub", "drafted"]
    assert [h["total"] for h in s["history"]] == [1005, 1505, 4505]


def test_summary_before_any_snapshot_uses_the_index(tmp_path: Path) -> None:
    s = progress.summary(tmp_path, "Book", chapters(300, 10), stub_words=200)
    assert s["total"] == 310 and s["history"] == [] and s["since_last"] is None
    assert s["last_7_days"] is None and s["target"] is None and s["percent"] is None


def test_target_can_be_cleared(tmp_path: Path) -> None:
    progress.set_target(tmp_path, "Book", 80000)
    progress.set_target(tmp_path, "Book", 0)
    assert progress.load(tmp_path, "Book")["target"] is None


class Index:
    def stats(self) -> IndexStats:
        return IndexStats("t", "The Lantern Road", chapters(2400, 30), 9)


def test_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(api, "index", lambda: Index())
    monkeypatch.setattr(api, "settings", lambda: Settings(data_dir=tmp_path))
    client = TestClient(api.app)
    assert client.get("/progress").json()["total"] == 2430
    r = client.post("/progress/target", json={"target": 80000}).json()
    assert r["target"] == 80000 and r["percent"] == 3.0
