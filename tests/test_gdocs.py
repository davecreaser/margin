"""Google Docs source (spec 0003). Every document here is invented JSON, never a real one."""

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from margin import api, gdocs
from margin import ingest as ing
from margin.config import Settings
from margin.embed_cache import CachedEmbedder
from margin.index import IndexStats
from margin.manuscript import NoChaptersError

LINK = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit?tab=t.0"
DOC = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def para(text: str, style: str = "NORMAL_TEXT") -> dict[str, Any]:
    return {
        "paragraph": {
            "elements": [{"textRun": {"content": text + "\n"}}],
            "paragraphStyle": {"namedStyleType": style},
        }
    }


def tab(tid: str, title: str, paras: list[dict[str, Any]], children: list[Any] | None = None):
    return {
        "tabProperties": {"tabId": tid, "title": title},
        "documentTab": {"body": {"content": paras}},
        "childTabs": children or [],
    }


def words(n: int, word: str) -> str:
    return " ".join([word] * n) + "."


def document(ferry: str = "The ferry left at nine.") -> dict[str, Any]:
    return {
        "title": "The Lantern Road",
        "tabs": [
            tab("t.0", "Notes", [para("Osric: lighthouse keeper, fifty-one.")]),
            tab(
                "t.1",
                "Chapter 1",
                [para("Chapter 1", "HEADING_1"), para(ferry), para(words(200, "gull"))],
                children=[tab("t.1a", "Chapter 2", [para(words(200, "lamp"))])],
            ),
            tab(
                "t.2",
                "Part Two",
                [
                    para("Chapter 3", "HEADING_2"),
                    para(words(200, "rope")),
                    para("Chapter 4", "HEADING_2"),
                    para(words(200, "salt")),
                ],
            ),
            tab("t.3", "Empty", []),
        ],
    }


class FakeDocs:
    def __init__(self, doc: dict[str, Any], revision: str = "r1") -> None:
        self.doc, self.rev, self.fetches = doc, revision, 0

    def revision(self, doc: str) -> tuple[str, str]:
        return self.doc["title"], self.rev

    def fetch(self, doc: str) -> dict[str, Any]:
        self.fetches += 1
        return self.doc


class FakeIndex:
    def __init__(self) -> None:
        self.manuscript: str | None = None
        self.chapters: list[dict[str, Any]] = []
        self.n = 0

    def replace(self, manuscript: str, chapters: Any, passages: list[Any], vectors: Any) -> None:
        self.manuscript, self.chapters, self.n = manuscript, chapters, len(passages)

    def stats(self) -> IndexStats:
        return IndexStats("test", self.manuscript, self.chapters, self.n)


class CountingEmbedder:
    dimensions = 2

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.embedded += texts
        return [[1.0, float(len(t))] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _ingest(docs: FakeDocs, index: FakeIndex, emb: Any, data: Path, exclude: list[str] | None):
    return ing.ingest_google(
        LINK,
        exclude=exclude,
        docs=docs,
        index=index,
        embedder=emb,
        settings=Settings(),
        data_dir=data,
    )


@pytest.mark.parametrize(
    ("link", "ok"),
    [
        (LINK, True),
        ("https://docs.google.com/document/u/1/d/" + DOC + "/view", True),
        (DOC, True),
        ("https://example.com/document/d/abc", False),
        ("chapter-3.md", False),
    ],
)
def test_doc_links(link: str, ok: bool) -> None:
    if ok:
        assert gdocs.doc_id(link) == DOC
    else:
        with pytest.raises(gdocs.NotAGoogleDocError):
            gdocs.doc_id(link)


def test_tabs_in_reading_order_with_children_after_parents() -> None:
    titles = [t.title for t in gdocs.tabs(document())]
    assert titles == ["Notes", "Chapter 1", "Chapter 2", "Part Two", "Empty"]
    assert gdocs.tabs(document())[1].lines[0] == "# Chapter 1"


def test_exclusion_is_a_case_insensitive_glob() -> None:
    assert gdocs.excluded("Notes", ["notes*"]) and gdocs.excluded("Notes: cast", ["Notes*"])
    assert not gdocs.excluded("Chapter 1", ["Notes*"]) and not gdocs.excluded("Notes", [""])


def test_ingest_excludes_tabs_splits_a_multi_chapter_tab_and_remembers(tmp_path: Path) -> None:
    index, emb = FakeIndex(), CountingEmbedder()
    r = _ingest(FakeDocs(document()), index, emb, tmp_path, ["Notes*"])
    assert [c["title"] for c in r.chapters] == ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    assert r.tabs_excluded == ["Notes"] and r.exclude == ["Notes*"]
    assert not any("lighthouse" in t for t in emb.embedded)
    # Re-ingest of a changed document without --exclude: the patterns are remembered.
    r2 = _ingest(FakeDocs(document(), revision="r2"), index, emb, tmp_path, None)
    assert r2.tabs_excluded == ["Notes"]
    # An empty pattern clears them.
    r3 = _ingest(FakeDocs(document(), revision="r3"), index, emb, tmp_path, [""])
    assert r3.chapters[0]["title"] == "Notes" and r3.exclude == []


def test_unchanged_document_stops_after_the_revision_call(tmp_path: Path) -> None:
    index, emb = FakeIndex(), CountingEmbedder()
    _ingest(FakeDocs(document()), index, emb, tmp_path, ["Notes*"])
    docs = FakeDocs(document())
    r = _ingest(docs, index, emb, tmp_path, None)
    assert r.unchanged and docs.fetches == 0 and r.passages_embedded == 0
    # Changing the excluded tabs is a change, even at the same revision.
    r = _ingest(FakeDocs(document()), index, emb, tmp_path, [])
    assert not r.unchanged


def test_only_changed_tabs_are_embedded_again(tmp_path: Path) -> None:
    index, inner = FakeIndex(), CountingEmbedder()
    emb = CachedEmbedder(inner, tmp_path, "test-model")
    first = _ingest(FakeDocs(document()), index, emb, tmp_path, ["Notes*"])
    assert first.passages_embedded == first.passages
    inner.embedded.clear()
    r = _ingest(FakeDocs(document("The ferry left at ten."), "r2"), index, emb, tmp_path, None)
    assert r.tabs_read == ["Chapter 1"] and r.tabs_reused == ["Chapter 2", "Part Two"]
    assert r.passages_embedded == 1 and inner.embedded[0].startswith("The ferry left at ten.")


def test_a_document_with_only_excluded_tabs_has_no_chapters(tmp_path: Path) -> None:
    with pytest.raises(NoChaptersError):
        _ingest(FakeDocs(document()), FakeIndex(), CountingEmbedder(), tmp_path, ["*"])


def test_load_tab_and_tab_list(tmp_path: Path) -> None:
    docs = FakeDocs(document())
    _ingest(docs, FakeIndex(), CountingEmbedder(), tmp_path, ["Notes*"])
    chapter, title, indexed = ing.load_tab("chapter 1", docs=docs, data_dir=tmp_path)
    assert title == "The Lantern Road" and chapter.title == "Chapter 1" and indexed == [1]
    _, _, split = ing.load_tab("Part Two", docs=docs, data_dir=tmp_path)
    assert split == [3, 4]  # a split tab leaves out every chapter it became
    assert chapter.paragraphs[0] == "The ferry left at nine."
    with pytest.raises(gdocs.GoogleError, match="No tab called Chapter 9. Tabs: Notes, Chapter 1"):
        ing.load_tab("Chapter 9", docs=docs, data_dir=tmp_path)
    listing = ing.tab_list(LINK, docs=docs, data_dir=tmp_path)
    assert [(t["title"], t["excluded"]) for t in listing["tabs"]][:2] == [
        ("Notes", True),
        ("Chapter 1", False),
    ]


# --- Sign-in ---------------------------------------------------------------------------


def _auth(tmp_path: Path, handler: Any, configured: bool = True) -> gdocs.GoogleAuth:
    oauth = gdocs.OAuthClient(
        "client-id" if configured else None,
        "client-secret",
        "http://localhost:8000/google/callback",
    )
    return gdocs.GoogleAuth(oauth, tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))


def test_login_url_is_read_only_with_pkce_and_the_token_is_private(tmp_path: Path) -> None:
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(parse_qs(request.content.decode()))
        return httpx.Response(
            200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}
        )

    auth = _auth(tmp_path, handler)
    q = parse_qs(urlparse(auth.login_url()).query)
    assert q["scope"] == [gdocs.SCOPE] and q["code_challenge_method"] == ["S256"]
    auth.finish("the-code", q["state"][0])
    assert seen[0]["code_verifier"] and seen[0]["code"] == ["the-code"]
    assert auth.access_token() == "a1"
    assert (auth.path.stat().st_mode & 0o777) == 0o600
    with pytest.raises(gdocs.GoogleError, match="expired"):
        auth.finish("again", q["state"][0])  # a state is used once


def test_expired_token_refreshes_and_a_revoked_one_asks_to_sign_in(tmp_path: Path) -> None:
    status = {"code": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status["code"], json={"access_token": "a2", "expires_in": 3600})

    auth = _auth(tmp_path, handler)
    auth.path.write_text(
        json.dumps({"access_token": "old", "refresh_token": "r1", "expires_at": time.time() - 5})
    )
    assert auth.access_token() == "a2"
    assert json.loads(auth.path.read_text())["refresh_token"] == "r1"
    auth.path.write_text(
        json.dumps({"access_token": "old", "refresh_token": "r1", "expires_at": 0})
    )
    status["code"] = 400  # invalid_grant: revoked
    with pytest.raises(gdocs.SignInNeededError):
        auth.access_token()
    assert not auth.path.exists()


def test_not_set_up_and_not_signed_in(tmp_path: Path) -> None:
    with pytest.raises(gdocs.NotSetUpError):
        _auth(tmp_path, lambda r: httpx.Response(200), configured=False).login_url()
    with pytest.raises(gdocs.SignInNeededError):
        _auth(tmp_path, lambda r: httpx.Response(200)).access_token()


def test_logout_deletes_and_revokes(tmp_path: Path) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200)

    auth = _auth(tmp_path, handler)
    auth.path.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 0}))
    assert auth.logout() is True
    assert not auth.path.exists() and urls == [gdocs.REVOKE_URL]


def test_logout_says_when_google_did_not_confirm_the_revoke(tmp_path: Path) -> None:
    auth = _auth(tmp_path, lambda r: httpx.Response(503))
    auth.path.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 0}))
    assert auth.logout() is False and not auth.path.exists()


def test_a_wrong_client_secret_is_named_and_keeps_the_token(tmp_path: Path) -> None:
    auth = _auth(tmp_path, lambda r: httpx.Response(401, json={"error": "invalid_client"}))
    auth.path.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 0}))
    with pytest.raises(gdocs.BadClientError, match="GOOGLE_CLIENT_SECRET"):
        auth.access_token()
    assert auth.path.exists()


def test_scene_subheadings_never_split_a_tab_or_drop_its_opening() -> None:
    from margin.manuscript import chapters_from_tab

    lines = [
        "# Chapter 13",
        "",
        "The opening.",
        "",
        "## Morning",
        "",
        "Dawn.",
        "",
        "## Night",
        "",
        "Dark.",
    ]
    chapters = chapters_from_tab("Chapter 13", lines)
    assert len(chapters) == 1 and chapters[0].title == "Chapter 13"
    assert chapters[0].paragraphs == ["The opening.", "Morning", "Dawn.", "Night", "Dark."]


def test_text_before_the_first_chapter_heading_stays_in_the_tab() -> None:
    from margin.manuscript import chapters_from_tab

    lines = ["A prologue line.", "", "Chapter 1", "", "One.", "", "Chapter 2", "", "Two."]
    titles = [(c.title, c.paragraphs) for c in chapters_from_tab("Book", lines)]
    assert titles == [
        ("Book", ["A prologue line."]),
        ("Chapter 1", ["One."]),
        ("Chapter 2", ["Two."]),
    ]


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (401, gdocs.SignInNeededError),
        (403, gdocs.NoAccessError),
        (404, gdocs.NoAccessError),
        (500, gdocs.GoogleUnreachableError),
    ],
)
def test_docs_api_errors(tmp_path: Path, code: int, error: type[Exception]) -> None:
    auth = _auth(tmp_path, lambda r: httpx.Response(code))
    auth.path.write_text(json.dumps({"access_token": "a", "expires_at": time.time() + 999}))
    with pytest.raises(error):
        gdocs.GoogleDocs(auth).revision(DOC)


def test_api_reports_google_errors_as_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth = _auth(tmp_path, lambda r: httpx.Response(200))
    monkeypatch.setattr(api, "google_auth", lambda: auth)
    client = TestClient(api.app)
    r = client.post("/ingest", json={"google_doc": LINK})
    assert (
        r.status_code == 401
        and r.json()["error"] == "Sign in to Google first: ./margin google login"
    )
    r = client.post("/ingest", json={"google_doc": "https://example.com/x"})
    assert r.json()["error"] == "That isn't a Google Doc link"
    assert client.get("/google/status").json()["signed_in"] is False
