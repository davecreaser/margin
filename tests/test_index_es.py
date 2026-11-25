"""ElasticIndex against a real Elasticsearch on localhost:9200. Skipped when none is running
(as in CI); run `docker compose up -d` first to include it."""

import uuid
from collections.abc import Iterator

import pytest

from margin.index import EMBEDDING_CHANGED, ElasticIndex, SearchFailedError
from margin.passages import Passage

URL = "http://localhost:9200"


@pytest.fixture
def index() -> Iterator[ElasticIndex]:
    idx = ElasticIndex(URL, f"margin-test-{uuid.uuid4().hex[:8]}")
    if not idx.ping():
        pytest.skip("Elasticsearch isn't running on localhost:9200")
    yield idx
    for name in idx.es.indices.get(index=f"{idx.alias}-*"):
        idx.es.indices.delete(index=name)


def _passages(prefix: str, n: int) -> list[Passage]:
    return [
        Passage(1, "One", i, i, f"{prefix} passage number {i} about the canal.")
        for i in range(1, n + 1)
    ]


def test_reingest_replaces_everything(index: ElasticIndex) -> None:
    index.replace("old", [{"number": 1}], _passages("old", 5), [[1.0, 0.0]] * 5)
    index.replace("new", [{"number": 1}], _passages("new", 2), [[1.0, 0.0]] * 2)
    stats = index.stats()
    assert (stats.manuscript, stats.passages) == ("new", 2)
    assert all(p.text.startswith("new") for p, _ in index.bm25("canal passage", 10))
    assert len(index.es.indices.get_alias(name=index.alias)) == 1


def test_empty_index_and_changed_embedding_model(index: ElasticIndex) -> None:
    assert index.stats().passages == 0
    assert index.bm25("anything", 5) == []
    index.replace("m", [{"number": 1}], _passages("p", 2), [[1.0, 0.0]] * 2)
    with pytest.raises(SearchFailedError, match=EMBEDDING_CHANGED):
        index.knn([1.0, 0.0, 0.0], 5)
