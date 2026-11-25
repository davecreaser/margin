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
    source: Annotated[
        str | None,
        typer.Argument(help="Folder of chapter files, one file, or a Google Doc link"),
    ] = None,
    demo: Annotated[bool, typer.Option(help="Index the bundled demo novel")] = False,
    exclude: Annotated[
        list[str] | None,
        typer.Option(help='Google Docs: leave out tabs matching this (e.g. "Notes*"); repeatable'),
    ] = None,
) -> None:
    """Index a manuscript (replaces whatever was indexed before). Sources are only read."""
    from margin.gdocs import looks_like_google_doc

    if not demo and source is None:
        _fail("Give a path or a Google Doc link, or --demo")
    body: dict[str, Any]
    if demo:
        body = {"demo": True}
    elif looks_like_google_doc(source or ""):
        body = {"google_doc": source, "exclude": exclude}
    else:
        body = {"path": str(Path(source or "").resolve())}
    with err.status("Reading and indexing…"):
        r = _request("POST", "/ingest", json=body)
    if r.get("source") == "google":
        _google_ingest_summary(r)
        return
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
    path: Annotated[Path | None, typer.Argument(help="One chapter: .md, .txt or .docx")] = None,
    tab: Annotated[
        str | None, typer.Option(help="A tab of the ingested Google Doc, in place of a file")
    ] = None,
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
    from margin.manuscript import Chapter, load_chapter

    if (path is None) == (tab is None):
        _fail("Give a chapter file, or --tab with a tab of the ingested Google Doc")
    s = _request("GET", "/status")
    if s["passages"] == 0:
        _fail("Nothing is indexed yet: run ./margin ingest --demo, or ./margin ingest <path>")
    leave_out: int | list[int] | None = replaces
    if tab is not None:
        t = _request("POST", "/google/tab", json={"name": tab})
        chapter = Chapter(0, t["title"], t["paragraphs"])
        if replaces is None and t["replaces"]:
            leave_out = t["replaces"]
    else:
        assert path is not None
        if not path.is_file():
            _fail(f"{path} not found")
        chapter = load_chapter(path)
    if not chapter.paragraphs:
        _fail(f"{chapter.title} has no text to check")
    shown = ", ".join(map(str, leave_out)) if isinstance(leave_out, list) else leave_out
    plural = "s" if isinstance(leave_out, list) and len(leave_out) > 1 else ""
    against = (
        f"the rest of {s['manuscript']} (it replaces chapter{plural} {shown})"
        if leave_out is not None
        else f"{s['manuscript']}: {s['chapters']} chapters, {s['passages']} passages"
    )
    out.print(
        f'Checking "{chapter.title}" ({chapter.words:,} words) against {against}.', markup=False
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
        "replaces": leave_out,
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


def _google_ingest_summary(r: dict[str, Any]) -> None:
    excluded = r["tabs_excluded"]
    left_out = f" Excluded: {', '.join(excluded)}." if excluded else ""
    if r["unchanged"]:
        out.print(
            f'"{r["manuscript"]}": no changes since the last ingest. '
            f"{len(r['chapters'])} chapters, {r['passages']} passages.{left_out}",
            markup=False,
        )
        return
    read, reused = r["tabs_read"], r["tabs_reused"]
    changed = f" ({', '.join(read)})" if read and reused and len(read) <= 5 else ""
    out.print(
        f"{r['label']}: {len(read)} tabs read{changed}, {len(reused)} unchanged.{left_out}",
        markup=False,
    )
    width = max(len(c["title"]) for c in r["chapters"]) + 4
    for c in r["chapters"]:
        out.print(
            f"{c['number']:>3}  {c['title'] + ' ':.<{width}} {c['words']:>7,} words", markup=False
        )
    embedded = r.get("passages_embedded")
    new = f" ({embedded} newly embedded)" if embedded is not None else ""
    out.print(
        f"{len(r['chapters'])} chapters, {r['words']:,} words, {r['passages']} passages{new}. "
        f"Indexed in {r['seconds']:.0f}s."
    )
    if r["exclude"]:
        out.print(f"[dim]Excluding tabs matching: {escape(', '.join(r['exclude']))} "
                  "(remembered; --exclude \"\" clears)[/dim]")  # fmt: skip


google = typer.Typer(help="Read your manuscript from Google Docs (read-only).")
app.add_typer(google, name="google")


@google.command()
def login() -> None:
    """Give Margin read-only access to your Google Docs."""
    import time

    before = _request("GET", "/google/status")["signed_in_at"]
    url = _request("GET", "/google/login")["url"]
    out.print("Open this link to give Margin read-only access to your Google Docs:")
    out.print(url, markup=False, soft_wrap=True)
    with err.status("Waiting for Google…"):
        for _ in range(300):
            if _request("GET", "/google/status")["signed_in_at"] not in (None, before):
                out.print("[green]Signed in.[/green]")
                return
            time.sleep(1)
    _fail("Timed out waiting for Google: run ./margin google login again")


@google.command()
def logout() -> None:
    """Forget the Google token and revoke it with Google."""
    if _request("POST", "/google/logout")["revoked"]:
        out.print("Signed out; Margin's access to your Google Docs is revoked.")
    else:
        out.print(
            "Token deleted here, but Google didn't confirm the revoke: remove Margin's access "
            "at https://myaccount.google.com/permissions"
        )


@google.command("status")
def google_status() -> None:
    """Show whether Google Docs is set up and signed in."""
    s = _request("GET", "/google/status")
    if not s["configured"]:
        out.print(
            "Not set up: add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env (README, Google Docs)"
        )
    else:
        out.print("Signed in." if s["signed_in"] else "Not signed in: ./margin google login")
    if s["current"]:
        out.print(f'Ingested: "{s["current"]["title"]}"', markup=False)


@app.command()
def progress(
    target: Annotated[
        int | None, typer.Option(help="Set the word target for the indexed manuscript (0 clears)")
    ] = None,
) -> None:
    """Words against your target, drafted and stub chapters, and growth since last time."""
    from datetime import datetime

    if target is not None:
        p = _request("POST", "/progress/target", json={"target": target or None})
    else:
        p = _request("GET", "/progress")
    total = f"{p['total']:,}"
    if p["target"]:
        total += f" of {p['target']:,} words ({p['percent']:.0f}%)"
    else:
        total += " words (set a target with --target 80000)"
    out.print(f"{p['manuscript']}: {total}", markup=False)
    n = len(p["chapters"])
    out.print(
        f"Drafted {p['drafted']} of {n} chapters · {p['stubs']} stubs (under {p['stub_words']} words)"
    )

    def day(at: str) -> str:
        return datetime.fromisoformat(at).strftime("%-d %b")

    growth = []
    if p["since_last"]:
        growth.append(f"{p['since_last']['words']:+,} words since {day(p['since_last']['since'])}")
    if p["last_7_days"] is not None:
        growth.append(f"{p['last_7_days']:+,} in the last 7 days")
    out.print(
        " · ".join(growth)
        if growth
        else "[dim]Growth appears once you've ingested on two different days.[/dim]"
    )
    out.print()
    width = max(len(c["title"]) for c in p["chapters"]) + 4
    for c in p["chapters"]:
        out.print(
            f"{c['number']:>3}  {c['title'] + ' ':.<{width}} {c['words']:>7,}  {c['status']}",
            markup=False,
        )


def _day(at: str) -> str:
    from datetime import datetime

    return datetime.fromisoformat(at).strftime("%-d %b")


def _print_timeline(t: dict[str, Any]) -> None:
    width = max(
        [len(e["chapter_label"]) for p in t["periods"] for e in p["events"]]
        + [len(e["chapter_label"]) for e in t["unplaced"]]
        + [8]
    )
    for period in t["periods"]:
        out.print(f"\n[bold]{escape(period['label'])}[/bold]")
        for e in period["events"]:
            mark = " [dim](uncertain)[/dim]" if e["uncertain"] else ""
            out.print(f"  {escape(e['chapter_label']):<{width}}  {escape(e['text'])}{mark}")
            out.print(f'  {"":<{width}}  [dim]"{escape(e["quote"])}"[/dim]')
            basis = " · ".join(
                f'"{escape(b["time"])}" ({escape(b["chapter_label"])})' for b in e["basis"]
            )
            out.print(f"  {'':<{width}}  [dim]placed by {basis}[/dim]")
    if t["unplaced"]:
        out.print("\n[bold]Not placed[/bold] [dim](the text gives no time)[/dim]")
        for e in t["unplaced"]:
            out.print(f"  {escape(e['chapter_label']):<{width}}  {escape(e['text'])}")
    placed = sum(len(p["events"]) for p in t["periods"])
    out.print(
        f"\n[dim]{placed} events placed in {len(t['periods'])} periods · "
        f"{len(t['unplaced'])} not placed · made {_day(t['made_at'])} · "
        f"{' + '.join(t['models'])} · ≈ ${t['cost']:.2f}[/dim]"
    )


@app.command()
def timeline(
    regenerate: Annotated[
        bool, typer.Option("--regenerate", help="Rebuild it (re-reads changed chapters)")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before spending")] = False,
) -> None:
    """The story's events in story order, each quoted. Built only when you ask."""
    g = _request("GET", "/timeline")
    saved = g["timeline"]
    if not regenerate:
        if saved is None:
            e = _request("POST", "/timeline/estimate")
            out.print(
                f"No timeline for {g['manuscript']} yet. Make one with "
                f"./margin timeline --regenerate (≈ ${e['worst_case']:.2f} at most).",
                markup=False,
            )
            return
        if g["changed"]:
            n = g["changed"]
            out.print(
                f"[yellow]Made on {_day(saved['made_at'])} · {n} chapter{'s' if n > 1 else ''} "
                "changed since. ./margin timeline --regenerate updates it.[/yellow]"
            )
        _print_timeline(saved)
        return

    e = _request("POST", "/timeline/estimate")
    n = len(e["changed"])
    what = (
        f"{n} of {e['chapters']} chapters changed" if saved else f"Reading {e['chapters']} chapters"
    )
    out.print(
        f"Timeline for {g['manuscript']}: {what}, then placing up to {e['events_max']} events "
        f"with {' + '.join(e['models'])} ≈ ${e['worst_case']:.2f} at most.",
        markup=False,
    )
    if e["worst_case"] > e["confirm_above"] and not yes and not typer.confirm("Continue?"):
        raise typer.Exit(0)
    try:
        with httpx.stream("POST", _url("/timeline/regenerate"), timeout=None) as response:
            if response.status_code >= 400:
                response.read()
                _check(response)
            status = err.status("Reading chapters…")
            status.start()
            for name, data in _events(response):
                if name == "chapter_done":
                    how = "unchanged" if data["cached"] else f"{data['events']} events"
                    status.update(f"Read {data['title']} ({how})…")
                elif name == "placing":
                    status.update(f"Placing {data['events']} events in story order…")
                elif name == "error":
                    status.stop()
                    _fail(data["message"])
                elif name == "done":
                    status.stop()
                    _print_timeline(data)
    except httpx.ConnectError:
        _fail(SERVICE_DOWN)
