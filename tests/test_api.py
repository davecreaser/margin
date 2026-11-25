from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from margin import api
from margin.index import SearchUnavailableError


class DownIndex:
    def ping(self) -> bool:
        return False

    def stats(self) -> None:
        raise SearchUnavailableError()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api, "index", lambda: DownIndex())
    return TestClient(api.app)


def test_status_when_search_is_down(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 503
    assert r.json() == {"error": "Search index isn't running: start it with docker compose up -d"}


@pytest.mark.parametrize("key", ["", "your-key-here"])
def test_ask_without_a_key(client: TestClient, monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    r = client.post("/ask", json={"question": "Who?"})
    assert r.status_code == 401
    assert r.json() == {
        "error": "No Anthropic API key: add ANTHROPIC_API_KEY to .env (see .env.example)"
    }


def test_ingest_of_a_file_without_chapters(client: TestClient, tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_text("No headings here.\n")
    r = client.post("/ingest", json={"path": str(f)})
    assert r.status_code == 422
    assert "No chapters found in notes.txt" in r.json()["error"]


def test_openapi_docs_are_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/status", "/ingest", "/ask"} <= set(paths)
