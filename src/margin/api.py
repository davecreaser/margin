"""The local HTTP API. The CLI is a client of these endpoints; so could a UI or plugin be."""

import json
from collections.abc import Iterator
from dataclasses import asdict
from functools import cache
from html import escape as html_escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from margin import ask as ask_mod
from margin import check as check_mod
from margin import gdocs
from margin import habits as habits_mod
from margin import ingest as ingest_mod
from margin import progress as progress_mod
from margin import style as style_mod
from margin import timeline as timeline_mod
from margin.config import DEMO_DIR, DEMO_TITLE, Settings
from margin.embed_cache import CachedEmbedder
from margin.embedding import FastEmbedder
from margin.index import ElasticIndex, SearchFailedError, SearchUnavailableError
from margin.llm import AnthropicClient, ModelBusyError, NoApiKeyError, api_key_present
from margin.manuscript import SINGLE_FILE_SUFFIXES, Chapter, NoChaptersError, chapter_from_lines
from margin.retrieval import Mode, Retriever

PRIVACY = (
    "Sent to the model provider for each question: the question and the retrieved passages "
    "(at most {k}), never the whole manuscript. Indexing and embeddings stay on this machine."
)

app = FastAPI(title="Margin", description="Ask your manuscript questions; every quote verified.")

WEB = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", include_in_schema=False)
def page() -> FileResponse:
    """The web page (spec 0004): plain HTML, CSS and JS over this same API."""
    return FileResponse(WEB / "index.html")


@app.get("/manuscripts")
def manuscripts() -> dict[str, Any]:
    """What's in the manuscripts folder, for choosing what to ingest."""
    root = settings().manuscripts_dir
    if not root.is_dir():
        return {"folder": str(root), "items": []}
    items = [
        {"path": str(p), "name": p.name, "kind": "folder" if p.is_dir() else "file"}
        for p in sorted(root.iterdir(), key=lambda p: p.name.lower())
        if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in SINGLE_FILE_SUFFIXES)
    ]
    return {"folder": str(root), "items": items}


class PassageRequest(BaseModel):
    id: str


@app.post("/passage")
def passage(request: PassageRequest) -> Any:
    """One indexed passage, so a client can show the whole passage behind a citation."""
    p = index().get(request.id)
    if p is None:
        return _error(404, "That passage isn't in the index any more: ask again")
    return {"id": p.id, "location": p.location, "chapter_title": p.chapter_title, "text": p.text}


@cache
def settings() -> Settings:
    return Settings()


@cache
def index() -> ElasticIndex:
    return ElasticIndex(settings().es_url, settings().index)


@cache
def embedder() -> FastEmbedder:
    return FastEmbedder(settings().embed_model, settings().embed_cache)


@cache
def cached_embedder() -> CachedEmbedder:
    return CachedEmbedder(embedder, settings().data_dir, settings().embed_model)


@cache
def google_auth() -> gdocs.GoogleAuth:
    s = settings()
    oauth = gdocs.OAuthClient(s.google_client_id, s.google_client_secret, s.google_redirect_uri)
    return gdocs.GoogleAuth(oauth, s.data_dir)


def google_docs() -> gdocs.GoogleDocs:
    return gdocs.GoogleDocs(google_auth())


def retriever() -> Retriever:
    s = settings()
    return Retriever(index(), embedder(), s.top_k, s.candidates_per_method, s.rrf_k)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.exception_handler(SearchUnavailableError)
def _search_down(_request: Any, e: SearchUnavailableError) -> JSONResponse:
    return _error(503, str(e))


@app.exception_handler(SearchFailedError)
def _search_failed(_request: Any, e: SearchFailedError) -> JSONResponse:
    return _error(503, str(e))


@app.exception_handler(NoApiKeyError)
def _no_key(_request: Any, e: NoApiKeyError) -> JSONResponse:
    return _error(401, str(e))


@app.exception_handler(ModelBusyError)
def _busy(_request: Any, e: ModelBusyError) -> JSONResponse:
    return _error(503, str(e))


@app.exception_handler(gdocs.GoogleError)
def _google(_request: Any, e: gdocs.GoogleError) -> JSONResponse:
    return _error(e.status, str(e))


@app.exception_handler(ask_mod.EmptyIndexError)
def _empty(_request: Any, e: ask_mod.EmptyIndexError) -> JSONResponse:
    return _error(409, str(e))


@app.get("/status")
def status() -> dict[str, Any]:
    if not index().ping():
        raise SearchUnavailableError()
    stats = index().stats()
    return {
        "ready": True,
        "index": stats.name,
        "manuscript": stats.manuscript,
        "chapters": len(stats.chapters),
        "chapter_list": stats.chapters,
        "passages": stats.passages,
        "model": settings().answer_model,
        "api_key": api_key_present(),
        "privacy": PRIVACY.format(k=settings().top_k),
    }


class IngestRequest(BaseModel):
    path: str | None = None
    demo: bool = False
    google_doc: str | None = None
    exclude: list[str] | None = None  # glob patterns on tab names; None reuses the last ones


@app.post("/ingest")
def post_ingest(request: IngestRequest) -> Any:
    if request.google_doc:
        try:
            result = ingest_mod.ingest_google(
                request.google_doc,
                exclude=request.exclude,
                docs=google_docs(),
                index=index(),
                embedder=cached_embedder(),
                settings=settings(),
                data_dir=settings().data_dir,
            )
        except NoChaptersError as e:
            return _error(422, str(e))
        _snapshot(result)
        return {**asdict(result), "label": f'"{result.manuscript}" from Google Docs'}
    if request.demo:
        path, label = DEMO_DIR, DEMO_TITLE
    elif request.path:
        path = Path(request.path)
        label = path.name
        if not path.exists():
            return _error(400, f"{request.path} not found")
    else:
        return _error(400, "Give a path, or ingest the demo novel")
    try:
        result = ingest_mod.ingest(
            path, index=index(), embedder=cached_embedder(), settings=settings()
        )
    except NoChaptersError as e:
        return _error(422, str(e))
    _snapshot(result)
    return {**asdict(result), "label": label}


def _snapshot(result: ingest_mod.IngestResult) -> None:
    progress_mod.record(
        settings().data_dir, result.manuscript, result.chapters, changed=not result.unchanged
    )


@app.get("/progress")
def get_progress() -> Any:
    stats = index().stats()
    if not stats.manuscript:
        return _error(409, "Nothing is indexed yet: ingest a manuscript first")
    return progress_mod.summary(
        settings().data_dir, stats.manuscript, stats.chapters, stub_words=settings().stub_words
    )


class TargetRequest(BaseModel):
    target: int | None


@app.post("/progress/target")
def post_target(request: TargetRequest) -> Any:
    stats = index().stats()
    if not stats.manuscript:
        return _error(409, "Nothing is indexed yet: ingest a manuscript first")
    progress_mod.set_target(settings().data_dir, stats.manuscript, request.target)
    return get_progress()


def _manuscript() -> tuple[str, list[Chapter], list[Any]]:
    stats = index().stats()
    if not stats.manuscript:
        raise ask_mod.EmptyIndexError()
    passages = index().all_passages()
    return stats.manuscript, timeline_mod.chapters_from_passages(passages), passages


@app.get("/timeline")
def get_timeline() -> Any:
    """The saved timeline (or null), and how many chapters changed since it was made."""
    manuscript, chapters, _ = _manuscript()
    saved = timeline_mod.load(settings().data_dir, manuscript)
    return {
        "manuscript": manuscript,
        "timeline": saved,
        "changed": timeline_mod.changed_since(saved, chapters) if saved else None,
    }


@app.get("/bible")
def get_bible() -> Any:
    """The saved bible (or null), and how many chapters changed since it was made."""
    manuscript, chapters, _ = _manuscript()
    saved = timeline_mod.load(settings().data_dir, manuscript)
    return {
        "manuscript": manuscript,
        "bible": saved["bible"] if saved else None,
        "made_at": saved["made_at"] if saved else None,
        "models": saved["models"] if saved else None,
        "cost": saved["cost"] if saved else None,
        "changed": timeline_mod.changed_since(saved, chapters) if saved else None,
    }


# --- Habits and house style (spec 0007): deterministic, no model, no key ---------------------


def _habits() -> habits_mod.Analysis:
    manuscript, chapters, passages = _manuscript()
    return habits_mod.cached(manuscript, chapters, passages, settings())


@app.get("/habits")
def get_habits(narration: bool = False, all: bool = False) -> Any:
    """Counts only: kinds, habits, totals, rates and per-chapter counts. No instances."""
    s = settings()
    return habits_mod.report(
        _habits(), narration=narration, all_phrases=all, phrase_top=s.phrase_top
    )


@app.get("/habits/instances")
def get_habit_instances(
    habit: str,
    chapter: int | None = None,
    offset: int = 0,
    limit: int = 50,
    narration: bool = False,
) -> Any:
    """One habit's instances, a page at a time, each with its sentence and match span."""
    a = _habits()
    h = habits_mod.find_habit(a, habit)
    if h is None:
        close = habits_mod.closest(a, habit)
        hint = f": closest are {', '.join(close)}" if close else ""
        return _error(404, f'No habit "{habit}" in this manuscript{hint}')
    limit = max(1, min(limit, 500))
    return habits_mod.instances(
        a, h.id, chapter=chapter, narration=narration, offset=max(0, offset), limit=limit
    )


def _scene_breaks() -> dict[int, list[dict[str, Any]]] | None:
    """Scene-break lines recorded at ingest, or None for an index made before they were."""
    chapters = index().stats().chapters
    if not chapters or any("scene_breaks" not in c for c in chapters):
        return None
    return {int(c["number"]): list(c["scene_breaks"]) for c in chapters}


@app.get("/style")
def get_style() -> Any:
    """The house style rules that are set, and whether scene breaks can be checked."""
    manuscript, _, _ = _manuscript()
    return {
        "manuscript": manuscript,
        "rules": style_mod.load(settings().data_dir, manuscript),
        "breaks_recorded": _scene_breaks() is not None,
        "choices": style_mod.CHOICES,
        "default_exempt": style_mod.DEFAULT_EXEMPT,
    }


class StyleRequest(BaseModel):
    rules: dict[str, Any] | None = None
    toml: str | None = None


@app.put("/style")
def put_style(request: StyleRequest) -> Any:
    """Save the rules (all of them, replacing the old set), or 422 with the allowed values."""
    manuscript, _, _ = _manuscript()
    try:
        rules = (
            style_mod.parse(request.toml)
            if request.toml is not None
            else style_mod.validate(request.rules or {})
        )
    except style_mod.StyleError as e:
        return _error(422, str(e))
    return {
        "manuscript": manuscript,
        "rules": style_mod.save(settings().data_dir, manuscript, rules),
    }


@app.get("/style/detect")
def get_style_detect() -> Any:
    """For each rule, the form the manuscript mostly uses and its share. Saves nothing."""
    manuscript, chapters, _ = _manuscript()
    return {"manuscript": manuscript, "detected": style_mod.detect(chapters, _scene_breaks())}


@app.get("/style/mismatches")
def get_style_mismatches() -> Any:
    """Mismatches with the saved house style, grouped by rule."""
    manuscript, chapters, passages = _manuscript()
    rules = style_mod.load(settings().data_dir, manuscript)
    out = style_mod.report(style_mod.check(rules, chapters, passages, _scene_breaks()))
    out["manuscript"] = manuscript
    out["words"] = sum(c.words for c in chapters)
    out["chapters"] = len(chapters)
    return out


@app.post("/timeline/estimate")
def timeline_estimate() -> Any:
    _, chapters, _ = _manuscript()
    s = settings()
    return {**timeline_mod.estimate(chapters, s.data_dir, s), "confirm_above": s.confirm_above_usd}


@app.post("/timeline/regenerate")
def timeline_regenerate() -> Any:
    manuscript, chapters, passages = _manuscript()
    client = AnthropicClient()  # fails fast when there is no key

    def events() -> Iterator[tuple[str, Any]]:
        try:
            yield from timeline_mod.regenerate(
                manuscript, chapters, passages, client=client, settings=settings()
            )
        except (
            ModelBusyError,
            SearchUnavailableError,
            SearchFailedError,
            NoApiKeyError,
            timeline_mod.PlacementError,
        ) as e:
            yield "error", {"message": str(e)}

    return StreamingResponse(_sse(events()), media_type="text/event-stream")


class AskRequest(BaseModel):
    question: str
    show_passages: bool = False
    debug: bool = False
    retrieval: Mode = "hybrid"


def _sse(events: Iterator[tuple[str, Any]]) -> Iterator[str]:
    for name, data in events:
        yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/ask")
def post_ask(request: AskRequest) -> StreamingResponse:
    client = AnthropicClient()  # fails fast, before retrieval, when there is no key
    result = ask_mod.run(
        request.question,
        retriever=retriever(),
        store=index(),
        client=client,
        settings=settings(),
        mode=request.retrieval,
    )
    stream = ask_mod.events(result, show_passages=request.show_passages, debug=request.debug)
    return StreamingResponse(_sse(stream), media_type="text/event-stream")


class CheckRequest(BaseModel):
    title: str = ""
    paragraphs: list[str] = []
    tab: str | None = None  # a tab of the ingested Google Doc, in place of title and text
    replaces: int | list[int] | None = None
    debug: bool = False


def _tab_chapter(name: str) -> dict[str, Any]:
    chapter, doc_title, indexed = ingest_mod.load_tab(
        name, docs=google_docs(), data_dir=settings().data_dir
    )
    replaces = indexed if index().stats().manuscript == doc_title and indexed else None
    return {
        "title": chapter.title,
        "paragraphs": chapter.paragraphs,
        "words": chapter.words,
        "replaces": replaces,
    }


class EstimateRequest(BaseModel):
    title: str = ""
    text: str = ""
    tab: str | None = None


@app.post("/check/estimate")
def check_estimate(request: EstimateRequest) -> Any:
    """The chapter as it will be checked, what it is checked against, and the worst-case cost,
    before any model call."""
    if request.tab:
        chapter = _tab_chapter(request.tab)
    else:
        c = chapter_from_lines(request.title.strip() or "Untitled", request.text.split("\n"))
        if request.title.strip():
            c.title = request.title.strip()
        chapter = {"title": c.title, "paragraphs": c.paragraphs, "words": c.words, "replaces": None}
    if not chapter["paragraphs"]:
        return _error(422, f"{chapter['title']} has no text to check")
    s = settings()
    return {
        **chapter,
        "worst_case": check_mod.worst_case_cost(chapter["words"], s),
        "confirm_above": s.confirm_above_usd,
        "claim_cap": s.claim_cap,
        "models": sorted({s.claims_model, s.judge_model}),
    }


@app.get("/google/status")
def google_status() -> dict[str, Any]:
    auth = google_auth()
    return {
        "configured": auth.oauth.configured,
        "signed_in": auth.signed_in,
        "signed_in_at": auth.signed_in_at,
        "current": ingest_mod.current_doc(settings().data_dir),
    }


@app.get("/google/login")
def google_login() -> dict[str, str]:
    return {"url": google_auth().login_url()}


@app.get("/google/callback", response_class=HTMLResponse)
def google_callback(code: str = "", state: str = "", error: str = "") -> Any:
    if error or not code:
        return HTMLResponse("<p>Google sign-in was cancelled. You can close this tab.</p>", 400)
    try:
        google_auth().finish(code, state)
    except gdocs.GoogleError as e:
        return HTMLResponse(f"<p>{html_escape(str(e))}</p>", e.status)
    return HTMLResponse("<p>Signed in to Google. You can close this tab.</p>")


@app.post("/google/logout")
def google_logout() -> dict[str, bool]:
    return {"signed_in": False, "revoked": google_auth().logout()}


class TabsRequest(BaseModel):
    doc: str


@app.post("/google/tabs")
def google_tabs(request: TabsRequest) -> dict[str, Any]:
    """A document's tabs, with which are excluded, so a client can choose before ingesting."""
    return ingest_mod.tab_list(request.doc, docs=google_docs(), data_dir=settings().data_dir)


class TabRequest(BaseModel):
    name: str


@app.post("/google/tab")
def google_tab(request: TabRequest) -> dict[str, Any]:
    """One tab of the ingested document as a chapter to check, with the chapters it replaces."""
    return _tab_chapter(request.name)


@app.post("/check")
def post_check(request: CheckRequest) -> Any:
    if request.tab:
        tab = _tab_chapter(request.tab)
        request.title, request.paragraphs = tab["title"], tab["paragraphs"]
        if request.replaces is None:
            request.replaces = tab["replaces"]
    chapter = Chapter(
        number=0, title=request.title, paragraphs=[p for p in request.paragraphs if p.strip()]
    )
    if not chapter.paragraphs:
        return _error(422, f"{request.title} has no text to check")
    client = AnthropicClient()  # fails fast when there is no key
    if index().stats().passages == 0:
        raise ask_mod.EmptyIndexError()

    def events() -> Iterator[tuple[str, Any]]:
        try:
            for name, data in check_mod.run(
                chapter,
                retriever=retriever(),
                store=index(),
                client=client,
                settings=settings(),
                replaces=request.replaces,
            ):
                if name == "debug" and not request.debug:
                    continue
                yield name, data
        except (ModelBusyError, SearchUnavailableError, SearchFailedError, NoApiKeyError) as e:
            yield "error", {"message": str(e)}

    return StreamingResponse(_sse(events()), media_type="text/event-stream")
