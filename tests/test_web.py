"""The web page (spec 0004): served by the service, self-contained, and text-only rendering."""

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from margin import api
from margin.config import Settings
from margin.passages import Passage

WEB = Path(api.__file__).parent / "web"


class Index:
    def __init__(self) -> None:
        self.p = Passage(14, "Interlude II", 3, 4, 'She wrote <script>alert("x")</script> & left.')

    def get(self, pid: str) -> Passage | None:
        return self.p if pid == self.p.id else None

    def ping(self) -> bool:
        return True

    def stats(self) -> Any:
        from margin.index import IndexStats

        return IndexStats("t", "The Lantern Road", [{"number": 1, "title": "One", "words": 10}], 5)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(api, "index", lambda: Index())
    monkeypatch.setattr(
        api, "settings", lambda: Settings(manuscripts_dir=tmp_path, data_dir=tmp_path / "d")
    )
    return TestClient(api.app)


def test_page_and_static_files_are_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200 and "<title>Margin</title>" in r.text
    for name in ("app.js", "app.css"):
        assert client.get(f"/static/{name}").status_code == 200


def test_page_makes_no_external_requests() -> None:
    for f in WEB.iterdir():
        text = f.read_text()
        # Links the author follows by hand are fine; nothing is loaded from elsewhere.
        loads = re.findall(
            r'(?:src|href)=["\']https?://|url\(\s*["\']?https?://|@import|fetch\(\s*["\']https?://',
            text,
        )
        assert not loads, (f.name, loads)


def test_page_code_never_inserts_data_as_html() -> None:
    js = (WEB / "app.js").read_text()
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
    assert "document.write" not in js and "eval(" not in js


def test_passage_text_comes_back_as_written(client: TestClient) -> None:
    r = client.post("/passage", json={"id": "14:3-4"})
    assert r.json()["text"] == 'She wrote <script>alert("x")</script> & left.'
    assert r.json()["location"].endswith("¶ 3–4")
    assert client.post("/passage", json={"id": "9:9-9"}).status_code == 404


def test_manuscripts_lists_folders_and_supported_files(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "my-novel").mkdir()
    (tmp_path / "draft.docx").write_bytes(b"")
    (tmp_path / "cover.png").write_bytes(b"")
    (tmp_path / ".hidden").mkdir()
    items = client.get("/manuscripts").json()["items"]
    assert [(i["name"], i["kind"]) for i in items] == [
        ("draft.docx", "file"),
        ("my-novel", "folder"),
    ]


def test_estimate_for_pasted_text_before_any_model_call(client: TestClient) -> None:
    text = "# The Return\n\nThe mule was aged twelve.\n\nIt stood at the gate."
    r = client.post("/check/estimate", json={"title": "", "text": text}).json()
    assert r["title"] == "The Return" and r["paragraphs"] == [
        "The mule was aged twelve.",
        "It stood at the gate.",
    ]
    assert r["worst_case"] > 0 and r["replaces"] is None and r["confirm_above"] == 0.25
    empty = client.post("/check/estimate", json={"title": "Blank", "text": "  "})
    assert empty.status_code == 422 and empty.json()["error"] == "Blank has no text to check"


def test_status_includes_the_chapter_list(client: TestClient) -> None:
    assert client.get("/status").json()["chapter_list"][0]["title"] == "One"
