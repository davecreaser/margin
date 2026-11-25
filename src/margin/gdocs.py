"""Google Docs as a manuscript source (spec 0003): sign-in, reading tabs, and change detection.

Read-only: the only OAuth scope is documents.readonly, and Margin never writes to a document.
The token lives in the data directory (a Docker volume), never in the repo, and is never logged.
"""

import base64
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

SCOPE = "https://www.googleapis.com/auth/documents.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DOCS_URL = "https://docs.googleapis.com/v1/documents/"

DOC_LINK = re.compile(r"docs\.google\.com/document/(?:u/\d+/)?d/(?P<id>[A-Za-z0-9_-]{20,})")
DOC_ID = re.compile(r"^[A-Za-z0-9_-]{25,}$")


class GoogleError(RuntimeError):
    status = 400


class NotSetUpError(GoogleError):
    status = 412

    def __init__(self) -> None:
        super().__init__("Google Docs isn't set up: see README, Google Docs")


class SignInNeededError(GoogleError):
    status = 401

    def __init__(self) -> None:
        super().__init__("Sign in to Google first: ./margin google login")


class BadClientError(GoogleError):
    status = 412

    def __init__(self) -> None:
        super().__init__(
            "Google rejected the OAuth client: check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "in .env, then docker compose up -d"
        )


class NoAccessError(GoogleError):
    status = 403

    def __init__(self) -> None:
        super().__init__("Your Google account can't open that document")


class NotAGoogleDocError(GoogleError):
    def __init__(self) -> None:
        super().__init__("That isn't a Google Doc link")


class GoogleUnreachableError(GoogleError):
    status = 503

    def __init__(self) -> None:
        super().__init__("Couldn't reach Google; try again in a minute")


def doc_id(link: str) -> str:
    link = link.strip()
    if m := DOC_LINK.search(link):
        return m.group("id")
    if DOC_ID.match(link):
        return link
    raise NotAGoogleDocError()


def looks_like_google_doc(text: str) -> bool:
    try:
        doc_id(text)
    except NotAGoogleDocError:
        return False
    return "docs.google.com" in text or not Path(text).exists()


# --- Reading a document's tabs ---------------------------------------------------------


@dataclass
class Tab:
    id: str
    title: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def words(self) -> int:
        return len(re.sub(r"(?m)^#+ ", "", self.text).split())

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def _paragraph_line(paragraph: dict[str, Any]) -> str:
    text = "".join(e.get("textRun", {}).get("content", "") for e in paragraph.get("elements", []))
    text = text.replace("\u000b", " ").replace("\n", " ").strip()
    style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "")
    if text and (style == "TITLE" or style.startswith("HEADING_")):
        level = 1 if style == "TITLE" else min(int(style.rsplit("_", 1)[1]), 3)
        return "#" * level + " " + text
    return text


def _body_lines(body: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for element in body.get("content", []):
        if "paragraph" in element:
            lines.append(_paragraph_line(element["paragraph"]))
            lines.append("")  # each Docs paragraph is its own paragraph
    return lines


def tabs(document: dict[str, Any]) -> list[Tab]:
    """Every tab in reading order: each parent before its children."""
    out: list[Tab] = []

    def walk(items: list[dict[str, Any]]) -> None:
        for t in items:
            props = t.get("tabProperties", {})
            body = t.get("documentTab", {}).get("body", {})
            out.append(
                Tab(props.get("tabId", ""), props.get("title", "Untitled"), _body_lines(body))
            )
            walk(t.get("childTabs", []))

    if "tabs" in document:
        walk(document["tabs"])
    else:  # a document fetched without tabs: one body
        out.append(
            Tab("", document.get("title", "Untitled"), _body_lines(document.get("body", {})))
        )
    return out


def excluded(title: str, patterns: list[str]) -> bool:
    return any(p and fnmatch.fnmatch(title.casefold(), p.casefold()) for p in patterns)


# --- Sign-in (OAuth 2.0 with PKCE) -----------------------------------------------------


@dataclass
class OAuthClient:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


class GoogleAuth:
    """Holds the token in <data_dir>/google-token.json (mode 0600) and refreshes it."""

    def __init__(
        self, oauth: OAuthClient, data_dir: Path, http: httpx.Client | None = None
    ) -> None:
        self.oauth = oauth
        self.path = data_dir / "google-token.json"
        self.http = http or httpx.Client(timeout=30)
        self._pending: dict[str, str] = {}  # state -> PKCE verifier

    def _require_client(self) -> None:
        if not self.oauth.configured:
            raise NotSetUpError()

    def login_url(self) -> str:
        self._require_client()
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        self._pending[state] = verifier
        params = {
            "client_id": self.oauth.client_id,
            "redirect_uri": self.oauth.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge.decode().rstrip("="),
            "code_challenge_method": "S256",
        }
        return AUTH_URL + "?" + urlencode(params)

    def finish(self, code: str, state: str) -> None:
        self._require_client()
        verifier = self._pending.pop(state, None)
        if verifier is None:
            raise GoogleError("That sign-in link has expired: run ./margin google login again")
        token = self._post(
            TOKEN_URL,
            {
                "client_id": self.oauth.client_id,
                "client_secret": self.oauth.client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self.oauth.redirect_uri,
            },
        )
        self._save(token)

    @property
    def signed_in(self) -> bool:
        return self.path.exists()

    def access_token(self) -> str:
        self._require_client()
        if not self.path.exists():
            raise SignInNeededError()
        token = json.loads(self.path.read_text())
        if token.get("expires_at", 0) > time.time() + 60:
            return str(token["access_token"])
        if not token.get("refresh_token"):
            raise SignInNeededError()
        try:
            fresh = self._post(
                TOKEN_URL,
                {
                    "client_id": self.oauth.client_id,
                    "client_secret": self.oauth.client_secret,
                    "refresh_token": token["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
        except SignInNeededError:
            self.path.unlink(missing_ok=True)  # revoked or expired: sign in again
            raise
        fresh.setdefault("refresh_token", token["refresh_token"])
        self._save(fresh)
        return str(fresh["access_token"])

    @property
    def signed_in_at(self) -> float | None:
        return self.path.stat().st_mtime if self.path.exists() else None

    def logout(self) -> bool:
        """Delete the token, and revoke it with Google. True if Google confirmed the revoke."""
        if not self.path.exists():
            return True
        token = json.loads(self.path.read_text())
        self.path.unlink()
        revoke = token.get("refresh_token") or token.get("access_token")
        if not revoke:
            return False
        try:
            return self.http.post(REVOKE_URL, data={"token": revoke}).status_code == 200
        except httpx.HTTPError:
            return False

    def _post(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self.http.post(url, data=data)
        except httpx.HTTPError as e:
            raise GoogleUnreachableError() from e
        if r.status_code in (400, 401):
            error = ""
            with contextlib.suppress(ValueError):
                error = str(r.json().get("error", ""))
            if error in ("invalid_client", "unauthorized_client"):
                raise BadClientError()
            raise SignInNeededError()
        if r.status_code >= 400:
            raise GoogleUnreachableError()
        return dict(r.json())

    def _save(self, token: dict[str, Any]) -> None:
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(token, f)


# --- The Docs API ----------------------------------------------------------------------


class GoogleDocs:
    def __init__(self, auth: GoogleAuth) -> None:
        self.auth = auth

    def _get(self, doc: str, params: dict[str, str]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
        try:
            r = self.auth.http.get(DOCS_URL + doc, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise GoogleUnreachableError() from e
        if r.status_code == 401:
            raise SignInNeededError()
        if r.status_code in (403, 404):
            raise NoAccessError()
        if r.status_code >= 400:
            raise GoogleUnreachableError()
        return dict(r.json())

    def revision(self, doc: str) -> tuple[str, str]:
        """(title, revisionId): a tiny request, used to skip unchanged documents."""
        d = self._get(doc, {"fields": "title,revisionId"})
        return str(d.get("title", "Untitled")), str(d.get("revisionId", ""))

    def fetch(self, doc: str) -> dict[str, Any]:
        return self._get(doc, {"includeTabsContent": "true"})
