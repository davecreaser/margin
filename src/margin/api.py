"""The local HTTP API. The CLI is a client of these endpoints; so could a UI or plugin be."""

import json
from collections.abc import Iterator
from dataclasses import asdict
from functools import cache
from html import escape as html_escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from margin import ask as ask_mod
from margin import check as check_mod
from margin import gdocs
from margin import ingest as ingest_mod
from margin.config import DEMO_DIR, DEMO_TITLE, Settings
from margin.embed_cache import CachedEmbedder
from margin.embedding import FastEmbedder
from margin.index import ElasticIndex, SearchFailedError, SearchUnavailableError
from margin.llm import AnthropicClient, ModelBusyError, NoApiKeyError, api_key_present
from margin.manuscript import Chapter, NoChaptersError
from margin.retrieval import Mode, Retriever

PRIVACY = (
    "Sent to the model provider for each question: the question and the retrieved passages "
    "(at most {k}), never the whole manuscript. Indexing and embeddings stay on this machine."
)

app = FastAPI(title="Margin", description="Ask your manuscript questions; every quote verified.")


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
    return {**asdict(result), "label": label}


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
    replaces: int | None = None
    debug: bool = False


def _tab_chapter(name: str) -> dict[str, Any]:
    chapter, doc_title = ingest_mod.load_tab(name, docs=google_docs(), data_dir=settings().data_dir)
    stats = index().stats()
    same = [c["number"] for c in stats.chapters if c["title"] == chapter.title]
    replaces = same[0] if stats.manuscript == doc_title and len(same) == 1 else None
    return {
        "title": chapter.title,
        "paragraphs": chapter.paragraphs,
        "words": chapter.words,
        "replaces": replaces,
    }


@app.get("/google/status")
def google_status() -> dict[str, Any]:
    auth = google_auth()
    return {
        "configured": auth.oauth.configured,
        "signed_in": auth.signed_in,
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
    google_auth().logout()
    return {"signed_in": False}


@app.get("/google/tabs")
def google_tabs(doc: str) -> dict[str, Any]:
    """A document's tabs, with which are excluded, so a client can choose before ingesting."""
    return ingest_mod.tab_list(doc, docs=google_docs(), data_dir=settings().data_dir)


@app.get("/google/tab")
def google_tab(name: str) -> dict[str, Any]:
    """One tab of the ingested document as a chapter to check, with the chapter it replaces."""
    return _tab_chapter(name)


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
