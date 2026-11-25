"""The `margin` command: a thin client of the local HTTP API."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.markup import escape

from margin.config import Settings

app = typer.Typer(add_completion=False, help="Margin reads your manuscript like an editor.")
out = Console(highlight=False)
err = Console(stderr=True, highlight=False)

SERVICE_DOWN = "Margin isn't running: start it with docker compose up -d"


def _url(path: str) -> str:
    return Settings().service_url.rstrip("/") + path


def _fail(message: str) -> None:
    err.print(f"[red]{escape(message)}[/red]")
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
    out.print(
        f"Index: {s['index']}" + (f" ({s['manuscript']})" if s["manuscript"] else ""), markup=False
    )
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
    out.print(f"Reading {r['label']}", markup=False)
    width = max(len(c["title"]) for c in r["chapters"]) + 4
    for c in r["chapters"]:
        out.print(
            f"{c['number']:>3}  {c['title'] + ' ':.<{width}} {c['words']:>7,} words", markup=False
        )
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
                out.print(f"    [dim]{escape(p['snippet'])}[/dim]")
            out.print()
        elif name == "answer_delta":
            markers = "".join(f" [{n}]" for n in data["citations"])
            answer.append(data["text"] + markers)
            out.print(data["text"] + markers, markup=False)
        elif name == "citation":
            if data["n"] == 1:
                out.print()
            out.print(f"[{data['n']}] {data['location']}", markup=False)
            out.print(f'    "{data["quote"]}"', markup=False)
        elif name == "debug":
            if data["kind"] == "failed_citation":
                state = "kept (other citations verified)" if data["kept"] else "DROPPED"
                out.print(
                    f"[yellow]\\[debug] statement {state}:[/yellow] {escape(data['statement'])}"
                )
                for f in data["failed"]:
                    out.print(
                        f"[yellow]  failed quote ({f['passage_id']}):[/yellow] {escape(f['quote'])}"
                    )
            else:
                detail = escape(f"{data['kind']}: {data.get('error')}")
                out.print(f"[yellow]\\[debug] {detail}[/yellow]")
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


def _finding(f: dict[str, Any]) -> None:
    out.print(f"{f['n']}. {f['explanation'] or f['claim']}", markup=False)
    out.print(f'   This chapter, ¶ {f["paragraph"]:<6} "{f["quote"]}"', markup=False)
    for c in f["citations"]:
        out.print(f'   {c["location"]:<19} "{c["quote"]}"', markup=False)


@app.command()
def check(
    path: Annotated[Path, typer.Argument(help="One chapter: .md, .txt or .docx")],
    replaces: Annotated[
        int | None, typer.Option(help="Leave out this indexed chapter (when revising it)")
    ] = None,
    all_: Annotated[
        bool, typer.Option("--all", help="Also list consistent and new claims")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before spending")] = False,
    debug: Annotated[
        bool, typer.Option("--debug", help="Show dropped claims and failed quotes")
    ] = False,
) -> None:
    """Check a new or revised chapter against the indexed manuscript. Never rewrites it."""
    from margin.check import worst_case_cost
    from margin.manuscript import load_chapter

    if not path.is_file():
        _fail(f"{path} not found")
    chapter = load_chapter(path)
    if not chapter.paragraphs:
        _fail(f"{path.name} has no text to check")
    s = _request("GET", "/status")
    if s["passages"] == 0:
        _fail("Nothing is indexed yet: run ./margin ingest --demo, or ./margin ingest <path>")
    out.print(
        f'Checking "{chapter.title}" ({chapter.words:,} words) against {s["manuscript"]}: '
        f"{s['chapters']} chapters, {s['passages']} passages.",
        markup=False,
    )
    settings = Settings()
    worst = worst_case_cost(chapter.words, settings)
    models = " + ".join(sorted({settings.claims_model, settings.judge_model}))
    out.print(
        f"Worst case: claims + up to {settings.claim_cap} judging calls with {models} ≈ ${worst:.2f}.",
        markup=False,
    )
    if worst > settings.confirm_above_usd and not yes and not typer.confirm("Continue?"):
        raise typer.Exit(0)

    body = {
        "title": chapter.title,
        "paragraphs": chapter.paragraphs,
        "replaces": replaces,
        "debug": debug,
    }
    listed: dict[str, list[dict[str, Any]]] = {"consistent": [], "new": [], "not_checked": []}
    contradictions = 0
    try:
        with httpx.stream("POST", _url("/check"), json=body, timeout=None) as response:
            if response.status_code >= 400:
                response.read()
                _check(response)
            status = err.status("Finding claims…")
            status.start()
            for name, data in _events(response):
                if name == "claim_count":
                    status.update(f"Checking {data['claims']} claims…")
                    note = f" (the cap of {data['cap']})" if data["capped"] else ""
                    status.stop()
                    out.print(f"Found {data['claims']} claims{note}.\n")
                    status.start()
                elif name == "finding":
                    if data["verdict"] == "contradicts":
                        status.stop()
                        if contradictions == 0:
                            out.print("[bold red]CONTRADICTS[/bold red]")
                        contradictions += 1
                        _finding(data)
                        out.print()
                        status.start()
                    else:
                        listed[data["verdict"]].append(data)
                    if debug and data["failed"]:
                        status.stop()
                        for f in data["failed"]:
                            out.print(
                                f"[yellow]\\[debug] failed quote ({escape(f['passage_id'])}):[/yellow] {escape(f['quote'])}"
                            )
                        status.start()
                elif name == "debug":
                    status.stop()
                    out.print(f"[yellow]\\[debug] {escape(str(data))}[/yellow]")
                    status.start()
                elif name == "error":
                    status.stop()
                    _fail(data["message"])
                elif name == "done":
                    status.stop()
                    _check_summary(data, contradictions, listed, all_)
    except httpx.ConnectError:
        _fail(SERVICE_DOWN)


def _check_summary(
    done: dict[str, Any], contradictions: int, listed: dict[str, list[dict[str, Any]]], all_: bool
) -> None:
    if contradictions == 0:
        out.print("No contradictions found.")
    if all_:
        for verdict, heading in (("consistent", "CONSISTENT"), ("new", "NEW")):
            if listed[verdict]:
                out.print(f"\n[bold]{heading}[/bold]")
                for f in sorted(listed[verdict], key=lambda f: f["n"]):
                    _finding(f)
    c = done["counts"]
    more = "" if all_ else "  (--all to list them)"
    out.print(
        f"\n{c['contradicts']} contradictions · {c['consistent']} consistent · {c['new']} new{more}"
    )
    if listed["not_checked"]:
        out.print("Not checked (the model's reply failed twice):")
        for f in listed["not_checked"]:
            out.print(f'  ¶ {f["paragraph"]} "{f["quote"]}"', markup=False)
    out.print(
        f"\n[dim]{', '.join(done['models'])} · {done['calls']} calls · {done['input_tokens']:,} in / "
        f"{done['output_tokens']:,} out · ≈ ${done['cost']:.3f}[/dim]"
    )
