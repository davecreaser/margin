"""Live smoke test against a real Google Doc: run by hand with
MARGIN_LIVE_GDOC=<link> uv run pytest -m live tests/test_gdocs_live.py
after ./margin google login has stored a token in MARGIN_DATA_DIR. CI never runs it."""

import os

import pytest

from margin import gdocs
from margin.config import Settings


@pytest.mark.live
def test_reads_tabs_of_a_real_document() -> None:
    link = os.environ.get("MARGIN_LIVE_GDOC")
    if not link:
        pytest.skip("set MARGIN_LIVE_GDOC")
    s = Settings()
    oauth = gdocs.OAuthClient(s.google_client_id, s.google_client_secret, s.google_redirect_uri)
    docs = gdocs.GoogleDocs(gdocs.GoogleAuth(oauth, s.data_dir))
    title, revision = docs.revision(gdocs.doc_id(link))
    assert title and revision
    assert gdocs.tabs(docs.fetch(gdocs.doc_id(link)))  # no text is printed
