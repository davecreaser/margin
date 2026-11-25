"""The `margin` CLI against canned HTTP responses (no service, no model)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from margin import cli

runner = CliRunner()

DONE = {
    "outcome": "answer",
    "closest": [],
    "model": "claude-opus-5-5",
    "input_tokens": 4210,
    "output_tokens": 380,
    "cost": 0.0244,
    "retrieval_ms": 20,
    "model_ms": 1500,
}


def _sse(events: list[tuple[str, Any]]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events
    ).encode()


def _serve(monkeypatch: pytest.MonkeyPatch, status: int, body: bytes) -> None:
    @contextmanager
    def stream(method: str, url: str, **kwargs: Any) -> Iterator[httpx.Response]:
        yield httpx.Response(status, content=body, request=httpx.Request(method, url))

    monkeypatch.setattr(cli.httpx, "stream", stream)


def _ask(monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]], *args: str) -> Any:
    _serve(monkeypatch, 200, _sse(events))
    return runner.invoke(cli.app, ["ask", "A question?", *args])


def test_answer_citations_and_cost_line(monkeypatch: pytest.MonkeyPatch) -> None:
    r = _ask(
        monkeypatch,
        [
            ("answer_delta", {"text": "The lantern cost nine shillings.", "citations": [1]}),
            (
                "citation",
                {
                    "n": 1,
                    "passage_id": "1:2-2",
                    "location": "Chapter 1, ¶ 2",
                    "quote": "sold the brass lanterns for nine shillings",
                },
            ),
            ("done", DONE),
        ],
    )
    assert r.exit_code == 0
    assert "The lantern cost nine shillings. [1]" in r.output
    assert "[1] Chapter 1, ¶ 2" in r.output
    assert '"sold the brass lanterns for nine shillings"' in r.output
    assert "claude-opus-5-5 · 4,210 in / 380 out · ≈ $0.024" in r.output


def test_not_in_the_manuscript_lists_three_closest_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closest = [
        {"location": f"Chapter {i}, ¶ 1", "snippet": f"Snippet number {i}"} for i in (1, 2, 3)
    ]
    r = _ask(
        monkeypatch,
        [
            ("answer_delta", {"text": "Not in the manuscript.", "citations": []}),
            ("done", {**DONE, "outcome": "not_in_manuscript", "closest": closest}),
        ],
    )
    assert r.exit_code == 0
    assert "Not in the manuscript." in r.output
    assert "Closest passages:" in r.output
    assert all(f"Snippet number {i}" in r.output for i in (1, 2, 3))


def test_service_error_exits_non_zero_with_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    message = "No Anthropic API key: add ANTHROPIC_API_KEY to .env (see .env.example)"
    _serve(monkeypatch, 401, json.dumps({"error": message}).encode())
    r = runner.invoke(cli.app, ["ask", "Who?"])
    assert r.exit_code == 1
    assert "No Anthropic API key" in r.output


# Manuscript text and model statements can contain square brackets ("[sic]", an editor's
# "[est. 1852]", a draft note "[/]"). The CLI prints them through Rich with markup enabled,
# so bracketed text is silently removed from a verified statement, or crashes the CLI.
def test_bracketed_text_in_a_statement_is_printed_as_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = 'The sign read "Tolliver & Daughter [est. 1852]".'
    r = _ask(
        monkeypatch,
        [("answer_delta", {"text": text, "citations": [1]}), ("done", DONE)],
    )
    assert f"{text} [1]" in r.output


def test_bracketed_text_in_a_passage_snippet_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passage = {
        "passage_id": "1:1-1",
        "location": "Chapter 1, ¶ 1",
        "chapter_title": "One",
        "score": 0.03,
        "bm25_rank": 1,
        "bm25_score": 9.0,
        "knn_rank": 1,
        "knn_score": 0.8,
        "snippet": "The keeper would arrive on the Thursday boat [/] with his wife",
    }
    r = _ask(
        monkeypatch,
        [
            ("passages", [passage]),
            ("answer_delta", {"text": "Not in the manuscript.", "citations": []}),
            ("done", {**DONE, "outcome": "not_in_manuscript"}),
        ],
        "--show-passages",
    )
    assert r.exit_code == 0, r.output
    assert "Thursday boat [/] with his wife" in r.output
