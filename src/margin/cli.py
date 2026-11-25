"""The `margin` command: a thin client of the local HTTP API."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console

from margin.config import Settings

app = typer.Typer(add_completion=False, help="Margin reads your manuscript like an editor.")
out = Console(highlight=False)
err = Console(stderr=True, highlight=False)

SERVICE_DOWN = "Margin isn't running: start it with docker compose up -d"


def _url(path: str) -> str:
    return Settings().service_url.rstrip("/") + path


def _fail(message: str) -> None:
    err.print(f"[red]{message}[/red]")
    raise typer.Exit(1)


def _check(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        try:
            message = response.json().get("error") or response.text
        except ValueError:
            message = response.text
        _fail(message)
    return response.json()


def _request(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return _check(httpx.request(method, _url(path), timeout=None, **kwargs))
    except httpx.ConnectError:
        _fail(SERVICE_DOWN)


@app.command()
def status() -> None:
    """Show whether Margin is ready and what is indexed."""
    s = _request("GET", "/status")
    out.print("[green]Ready[/green]")
    out.print(f"Index: {s['index']}" + (f" ({s['manuscript']})" if s["manuscript"] else ""))
    out.print(f"Chapters: {s['chapters']}  Passages: {s['passages']}")
    key = "set" if s["api_key"] else "missing: add ANTHROPIC_API_KEY to .env"
    out.print(f"Model: {s['model']}  API key: {key}")
    out.print(f"[dim]{s['privacy']}[/dim]")


@app.command()
def ingest(
    path: Annotated[
        Path | None, typer.Argument(help="Folder of chapter files, or one file")
    ] = None,
    demo: Annotated[bool, typer.Option(help="Index the bundled demo novel")] = False,
) -> None:
    """Index a manuscript (replaces whatever was indexed before). Source files are only read."""
    if not demo and path is None:
        _fail("Give a path, or --demo")
    body = {"demo": True} if demo else {"path": str(path.resolve())}  # type: ignore[union-attr]
    with err.status("Reading and indexing…"):
        r = _request("POST", "/ingest", json=body)
    out.print(f"Reading {r['label']}")
    width = max(len(c["title"]) for c in r["chapters"]) + 4
    for c in r["chapters"]:
        out.print(f"{c['number']:>3}  {c['title'] + ' ':.<{width}} {c['words']:>7,} words")
    minutes, seconds = divmod(int(r["seconds"]), 60)
    took = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
    out.print(
        f"{len(r['chapters'])} chapters, {r['words']:,} words, {r['passages']} passages. "
        f"Indexed in {took}."
    )


def _events(response: httpx.Response) -> Iterator[tuple[str, Any]]:
    name = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            yield name, json.loads(line[6:])
            name = None


def _rank(rank: int | None, score: float | None) -> str:
    return f"#{rank} ({score:.3f})" if rank is not None and score is not None else "—"


@app.command()
def ask(
    question: str,
    show_passages: Annotated[
        bool, typer.Option("--show-passages", help="Print the retrieved passages and scores")
    ] = False,
    debug: Annotated[
        bool, typer.Option("--debug", help="Show dropped statements and failed quotes")
    ] = False,
    retrieval: Annotated[str, typer.Option(help="hybrid, bm25 or knn")] = "hybrid",
) -> None:
    """Ask the manuscript a question. Every quote shown has been checked against the text."""
    body = {
        "question": question,
        "show_passages": show_passages,
        "debug": debug,
        "retrieval": retrieval,
    }
    try:
        with (
            err.status("Reading the manuscript…"),
            httpx.stream("POST", _url("/ask"), json=body, timeout=None) as response,
        ):
            if response.status_code >= 400:
                response.read()
                _check(response)
            events = list(_events(response))
    except httpx.ConnectError:
        _fail(SERVICE_DOWN)
    answer: list[str] = []
    for name, data in events:
        if name == "passages":
            out.print("[bold]Retrieved passages[/bold] (fused, BM25, kNN)")
            for p in data:
                out.print(
                    f"  {p['location']:<22} {p['score']:.4f}  BM25 {_rank(p['bm25_rank'], p['bm25_score'])}"
                    f"  kNN {_rank(p['knn_rank'], p['knn_score'])}"
                )
                out.print(f"    [dim]{p['snippet']}[/dim]")
            out.print()
        elif name == "answer_delta":
            markers = "".join(f" [{n}]" for n in data["citations"])
            answer.append(data["text"] + markers)
            out.print(data["text"] + markers)
        elif name == "citation":
            if data["n"] == 1:
                out.print()
            out.print(f"[{data['n']}] {data['location']}", markup=False)
            out.print(f'    "{data["quote"]}"', markup=False)
        elif name == "debug":
            if data["kind"] == "failed_citation":
                state = "kept (other citations verified)" if data["kept"] else "DROPPED"
                out.print(f"[yellow][debug] statement {state}:[/yellow] {data['statement']}")
                for f in data["failed"]:
                    out.print(f"[yellow]  failed quote ({f['passage_id']}):[/yellow] {f['quote']}")
            else:
                out.print(f"[yellow][debug] {data['kind']}: {data.get('error')}[/yellow]")
        elif name == "done":
            if data["closest"]:
                out.print("\nClosest passages:")
                for p in data["closest"]:
                    out.print(f'  {p["location"]:<20} "{p["snippet"]}"', markup=False)
            cost = f" · ≈ ${data['cost']:.3f}" if data["cost"] is not None else ""
            out.print(
                f"\n[dim]{data['model']} · {data['input_tokens']:,} in / "
                f"{data['output_tokens']:,} out{cost}[/dim]"
            )
