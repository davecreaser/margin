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


BAND_NAMES = {"before": "Before the story", "story": "", "after": "After"}


def _print_timeline(t: dict[str, Any]) -> None:
    cards = [c for p in t["periods"] for c in p["cards"]]
    width = max(
        [len(e["chapter_label"]) for c in cards for e in c["tellings"]]
        + [len(e["chapter_label"]) for e in t["unplaced"]]
        + [8]
    )
    band = None
    for period in t["periods"]:
        if period["band"] != band and BAND_NAMES[period["band"]]:
            out.print(f"\n[bold underline]{BAND_NAMES[period['band']]}[/bold underline]")
        band = period["band"]
        out.print(f"\n[bold]{escape(period['label'])}[/bold]")
        for card in period["cards"]:
            first = card["tellings"][0]
            mark = " [dim](uncertain)[/dim]" if card["uncertain"] else ""
            out.print(f"  {escape(first['chapter_label']):<{width}}  {escape(first['text'])}{mark}")
            for e in card["tellings"]:
                label = "" if e is first else f"also told in {e['chapter_label']}: "
                out.print(f'  {"":<{width}}  [dim]{escape(label)}"{escape(e["quote"])}"[/dim]')
            basis = " · ".join(
                f'"{escape(b["time"])}" ({escape(b["chapter_label"])})' for b in card["basis"]
            )
            out.print(f"  {'':<{width}}  [dim]placed by {basis}[/dim]")
    if t["unplaced"]:
        out.print("\n[bold]Not placed[/bold] [dim](the text gives no time)[/dim]")
        for e in t["unplaced"]:
            out.print(f"  {escape(e['chapter_label']):<{width}}  {escape(e['text'])}")
    out.print(
        f"\n[dim]{len(cards)} moments placed in {len(t['periods'])} periods · "
        f"{len(t['unplaced'])} not placed · made {_day(t['made_at'])} · "
        f"{' + '.join(t['models'])} · ≈ ${t['cost']:.2f}[/dim]"
    )


def _print_bible(notes: dict[str, Any]) -> None:
    b = notes["bible"]
    if b.get("error"):
        out.print(
            "[yellow]Grouping the names failed, so each name is shown on its own. "
            "./margin bible --regenerate tries again (chapters already read are free).[/yellow]"
        )
    for title, entries in (("Characters", b["characters"]), ("Places", b["places"])):
        out.print(f"\n[bold underline]{title}[/bold underline]")
        if not entries:
            out.print("  [dim]None found.[/dim]")
        for e in entries:
            others = [n for n in e["names"] if n != e["name"]]
            also = f" [dim]({escape(', '.join(others))})[/dim]" if others else ""
            where = ", ".join(c["label"] for c in e["chapters"])
            out.print(f"\n  [bold]{escape(e['name'])}[/bold]{also}  [dim]{escape(where)}[/dim]")
            for f in e["facts"]:
                out.print(f"    {escape(f['text'])}")
                out.print(f'      [dim]{escape(f["chapter_label"])}  "{escape(f["quote"])}"[/dim]')
    out.print(
        f"\n[dim]{len(b['characters'])} characters · {len(b['places'])} places · "
        f"made {_day(notes['made_at'])} · {' + '.join(notes['models'])} · "
        f"≈ ${notes['cost']:.2f}[/dim]"
    )


def _story_notes(regenerate: bool, yes: bool, show: Any, what: str) -> None:
    g = _request("GET", "/timeline")
    saved = g["timeline"]
    if not regenerate:
        if saved is None:
            e = _request("POST", "/timeline/estimate")
            out.print(
                f"No {what} for {g['manuscript']} yet. Make the timeline and the bible with "
                f"./margin {what} --regenerate (≈ ${e['worst_case']:.2f} at most).",
                markup=False,
            )
            return
        if g["changed"]:
            n = g["changed"]
            out.print(
                f"[yellow]Made on {_day(saved['made_at'])} · {n} chapter{'s' if n > 1 else ''} "
                f"changed since. ./margin {what} --regenerate updates it.[/yellow]"
            )
        show(saved)
        return

    e = _request("POST", "/timeline/estimate")
    n = len(e["changed"])
    reading = (
        f"{n} of {e['chapters']} chapters changed" if saved else f"Reading {e['chapters']} chapters"
    )
    out.print(
        f"Timeline and bible for {g['manuscript']}: {reading}, then placing up to "
        f"{e['events_max']} scenes and grouping names, with {' + '.join(e['models'])} "
        f"≈ ${e['worst_case']:.2f} at most.",
        markup=False,
    )
    if not yes and not typer.confirm("Continue?"):  # always asked: spec 0006, AC-1
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
                    how = "unchanged" if data["cached"] else f"{data['events']} scenes"
                    status.update(f"Read {data['title']} ({how})…")
                elif name == "placing":
                    status.update(f"Placing {data['events']} scenes in story order…")
                elif name == "bible":
                    status.update(f"Grouping {data['names']} names into the bible…")
                elif name == "error":
                    status.stop()
                    _fail(data["message"])
                elif name == "done":
                    status.stop()
                    show(data)
    except httpx.ConnectError:
        _fail(SERVICE_DOWN)


REGENERATE = "Rebuild the timeline and the bible (re-reads changed chapters)"


@app.command()
def timeline(
    regenerate: Annotated[bool, typer.Option("--regenerate", help=REGENERATE)] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before spending")] = False,
) -> None:
    """The story's scenes in story order, each quoted. Built only when you ask."""
    _story_notes(regenerate, yes, _print_timeline, "timeline")


@app.command()
def bible(
    regenerate: Annotated[bool, typer.Option("--regenerate", help=REGENERATE)] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before spending")] = False,
) -> None:
    """Characters and places, with facts quoted from the text. Built only when you ask."""
    _story_notes(regenerate, yes, _print_bible, "bible")


# --- Habits and house style (spec 0007) -------------------------------------------------------


def _highlight(sentence: str, match: list[int]) -> str:
    a, b = match
    return f"{escape(sentence[:a])}[bold]{escape(sentence[a:b])}[/bold]{escape(sentence[b:])}"


def _top_chapters(h: dict[str, Any], chapters: dict[str, dict[str, Any]], n: int = 3) -> str:
    def rate(item: tuple[str, int]) -> float:
        words = chapters[item[0]]["words"]
        return item[1] / words if words else 0.0

    ranked = sorted(h["chapters"].items(), key=lambda kv: (-rate(kv), int(kv[0])))
    return ", ".join(chapters[k]["label"] for k, _ in ranked[:n])


def _habit_row(h: dict[str, Any], kind: str, chapters: dict[str, dict[str, Any]]) -> str:
    label = f'"{h["label"]}"' if kind == "phrases" else h["label"]
    if kind == "phrases":
        where = f"in {h['in_chapters']} chapters"
        if h["variants"]:
            also = ", ".join(f"{v['form']} ({v['count']})" for v in h["variants"][:3])
            where += f" · also: {also}"
    else:
        where = _top_chapters(h, chapters)
    return f"  {label:<32.32} {h['total']:>5} {h['narration']:>10} {h['rate']:>10.2f}  {where}"


@app.command()
def habits(
    all: Annotated[bool, typer.Option("--all", help="List every habit and phrase")] = False,
    show: Annotated[
        str | None,
        typer.Option("--show", help='One habit\'s chapters and instances: --show "nodded"'),
    ] = None,
    narration: Annotated[
        bool, typer.Option("--narration", help="Count and list narration only, without dialogue")
    ] = False,
) -> None:
    """The constructions you repeat, counted per chapter. Free: no model calls."""
    flag = "true" if narration else "false"
    if show is not None:
        _show_habit(show, flag)
        return
    r = _request("GET", f"/habits?narration={flag}&all={'true' if all else 'false'}")
    chapters = {str(c["number"]): c for c in r["chapters"]}
    scope = " Narration only." if narration else ""
    out.print(
        f"Habits in {r['manuscript']}: {r['words']:,} words, {len(r['chapters'])} chapters. "
        f"Free: no model calls.{scope}",
        markup=False,
    )
    if not r["found"]:
        out.print(
            f"No repeated constructions found in {len(r['chapters'])} chapters "
            f"({r['words']:,} words)."
        )
        return
    out.print()
    out.print(f"[dim]{'':<34} {'total':>5} {'narration':>10} {'per 1,000':>10}  highest in[/dim]")
    for k in r["kinds"]:
        out.print(f"[bold]{escape(k['label'])}[/bold]")
        rows = k["habits"]
        if not rows:
            out.print("  [dim]None found[/dim]")
            continue
        shown = rows if all else rows[:5]
        for h in shown:
            out.print(_habit_row(h, k["kind"], chapters), markup=False, soft_wrap=True)
        more = len(rows) - len(shown) + k["more"]
        if more:
            out.print(f"  [dim]+ {more} more: ./margin habits --all[/dim]")


def _show_habit(name: str, flag: str) -> None:
    from urllib.parse import quote

    first = _request("GET", f"/habits/instances?habit={quote(name)}&limit=500&narration={flag}")
    r = _request("GET", f"/habits?narration={flag}&all=true")
    chapters = {str(c["number"]): c for c in r["chapters"]}
    h = next((x for k in r["kinds"] for x in k["habits"] if x["id"] == first["habit"]), None)
    if h is None:  # found only in dialogue, and Narration only is on
        out.print(f"{first['label']} · 0 in narration in {r['manuscript']}", markup=False)
        return
    out.print(
        f"{h['label']} · {h['total']} in {r['manuscript']} ({h['rate']:.2f} per 1,000 words), "
        f"{h['narration']} in narration",
        markup=False,
    )
    cells = []
    for n, count in h["chapters"].items():
        c = chapters[n]
        rate = count / c["words"] * 1000 if c["words"] else 0
        cells.append(f"{c['label']:<12} {count:>3} · {rate:.1f} per 1,000")
    for i in range(0, len(cells), 3):
        out.print("  " + "    ".join(cells[i : i + 3]), markup=False)
    out.print()
    items = first["instances"]
    offset = len(items)
    while offset < first["total"]:
        page = _request(
            "GET",
            f"/habits/instances?habit={quote(name)}&limit=500&offset={offset}&narration={flag}",
        )
        items += page["instances"]
        offset += len(page["instances"]) or first["total"]
    for i in items:
        tag = "dialogue " if i["dialogue"] else "narration"
        out.print(
            f"  {escape(i['label']):<12} ¶ {i['paragraph']:<4} [dim]{tag}[/dim]  "
            + _highlight(i["sentence"], i["match"])
        )


style_app = typer.Typer(
    invoke_without_command=True,
    help="Your house style: the rules you keep, and where the text differs. Free: no model calls.",
)
app.add_typer(style_app, name="style")
watch_app = typer.Typer(help="Words and phrases to list every use of.")
style_app.add_typer(watch_app, name="watch")


def _print_mismatches(r: dict[str, Any]) -> None:
    rules = {k: v for k, v in r["rules"].items() if k != "heading_exempt"}
    if not rules:
        out.print("No house style set: see what you mostly use with ./margin style --detect")
        return
    out.print(f"House style for {r['manuscript']}: {len(rules)} rules set.", markup=False)
    for rule in r["by_rule"]:
        head = f"[bold]{rule['rule']}[/bold]: {escape(str(rule['value']))}"
        if rule.get("unchecked"):
            out.print(f"{head} · {rule['unchecked']}")
            continue
        if not rule["total"]:
            out.print(f"{head} · matches")
            continue
        unit = "mismatch" if rule["total"] == 1 else "mismatches"
        out.print(f"{head} · {rule['total']} {unit}")
        if len(rule["chapters"]) > 1:
            labels = {str(row["chapter"]): row["label"] for row in rule["rows"]}
            per = " · ".join(f"{labels.get(n, n)} {k}" for n, k in rule["chapters"].items())
            out.print(f"  [dim]by chapter: {escape(per)}[/dim]")
        for row in rule["rows"]:
            where = (
                ("at the start" if row["paragraph"] == 0 else f"after ¶ {row['paragraph']}")
                if row["after"]
                else ("heading" if row["paragraph"] == 0 else f"¶ {row['paragraph']}")
            )
            line = f"  {escape(row['label']):<12} {where:<12} "
            if row["after"] or row["paragraph"] == 0:
                out.print(line + escape(row["text"]))
            else:
                out.print(
                    line
                    + _highlight(row["sentence"], row["match"])
                    + f"  [dim]{escape(row['what'])}[/dim]"
                )
    for w in r["watch"]:
        if w["total"]:
            n = len(w["chapters"])
            out.print(
                f'[bold]watch[/bold]: "{escape(w["word"])}" · {w["total"]} uses in {n} '
                f"chapter{'s' if n != 1 else ''}"
            )
            for row in w["rows"]:
                out.print(
                    f"  {escape(row['label']):<12} ¶ {row['paragraph']:<9} "
                    + _highlight(row["sentence"], row["match"])
                )
        else:
            out.print(f'[bold]watch[/bold]: "{escape(w["word"])}" · not in the manuscript')
    if not r["mismatches"]:
        out.print(f"Matches your house style: {r['checked']} rules checked.")


@style_app.callback()
def style(
    ctx: typer.Context,
    from_file: Annotated[
        Path | None, typer.Option("--from", help="Use the rules in this local TOML file")
    ] = None,
    detect: Annotated[
        bool, typer.Option("--detect", help="Show what the manuscript mostly uses (saves nothing)")
    ] = False,
    save: Annotated[
        bool, typer.Option("--save", help="With --detect: save what was found")
    ] = False,
) -> None:
    """Prints the rules that are set, then every mismatch grouped by rule."""
    if ctx.invoked_subcommand is not None:
        return
    if from_file is not None:
        try:
            text = from_file.read_text()
        except OSError:
            _fail(f"Can't read {from_file}")
        r = _request("PUT", "/style", json={"toml": text})
        out.print(f"Saved {len(r['rules'])} rules from {from_file.name}.", markup=False)
        return
    if detect:
        d = _request("GET", "/style/detect")
        found = d["detected"]
        if not found:
            out.print("Nothing to detect yet in this manuscript.")
            return
        if save:
            current = _request("GET", "/style")["rules"]
            r = _request(
                "PUT",
                "/style",
                json={"rules": {**current, **{k: v["value"] for k, v in found.items()}}},
            )
            out.print(
                f"Saved: {', '.join(f'{k} = {v}' for k, v in r['rules'].items())}.", markup=False
            )
            return
        out.print(f"What {d['manuscript']} mostly uses (nothing saved):", markup=False)
        for k, v in found.items():
            out.print(f"  {k:<12} {v['value']:<16} {v['share']}% of {v['of']}", markup=False)
        out.print("Use these: ./margin style --detect --save")
        return
    _print_mismatches(_request("GET", "/style/mismatches"))


@style_app.command("set")
def style_set(
    rule: Annotated[str, typer.Argument(help="spelling, quotes, scene_break, chapter_heading, …")],
    value: Annotated[str, typer.Argument(help='The value, e.g. british or "* * *"; "" clears it')],
) -> None:
    """Set one house-style rule."""
    current = _request("GET", "/style")["rules"]
    new = dict(current)
    if value == "":
        new.pop(rule, None)
    elif rule in ("watch", "heading_exempt"):
        new[rule] = [x.strip() for x in value.split(",")]
    else:
        new[rule] = value
    _request("PUT", "/style", json={"rules": new})
    out.print(f"Saved: {rule} = {value}." if value else f"Cleared: {rule}.", markup=False)


@watch_app.command("add")
def watch_add(phrase: str) -> None:
    """Watch a word or phrase."""
    current = _request("GET", "/style")["rules"]
    words = [*current.get("watch", []), phrase]
    _request("PUT", "/style", json={"rules": {**current, "watch": words}})
    out.print(f'Watching "{phrase}".', markup=False)


@watch_app.command("remove")
def watch_remove(phrase: str) -> None:
    """Stop watching a word or phrase."""
    current = _request("GET", "/style")["rules"]
    watched = current.get("watch", [])
    words = [w for w in watched if w.lower() != phrase.lower()]
    if len(words) == len(watched):
        out.print(f'"{phrase}" isn\'t watched.', markup=False)
        return
    _request("PUT", "/style", json={"rules": {**current, "watch": words}})
    out.print(f'Stopped watching "{phrase}".', markup=False)
