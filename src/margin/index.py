"""The passage index in Elasticsearch (ADR 0003).

Each ingest writes a fresh index and then moves the alias to it in one step, so a failed
ingest leaves the previous index untouched and a successful one leaves no stale passages.
"""

import time
from dataclasses import dataclass
from typing import Any, Protocol

from elastic_transport import ConnectionTimeout
from elasticsearch import ApiError, Elasticsearch, NotFoundError
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch.helpers import bulk

from margin.passages import Passage


class SearchUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Search index isn't running: start it with docker compose up -d")


class SearchFailedError(RuntimeError):
    pass


EMBEDDING_CHANGED = (
    "The index was built with a different embedding model: run ./margin ingest again"
)


@dataclass
class IndexStats:
    name: str
    manuscript: str | None
    chapters: list[dict[str, Any]]
    passages: int


class PassageStore(Protocol):
    def bm25(
        self, question: str, k: int, exclude_chapter: int | list[int] | None = None
    ) -> list[tuple[Passage, float]]: ...

    def knn(
        self, vector: list[float], k: int, exclude_chapter: int | list[int] | None = None
    ) -> list[tuple[Passage, float]]: ...

    def stats(self) -> IndexStats: ...


def _not_chapter(chapter: int | list[int]) -> dict[str, Any]:
    return {"terms": {"chapter": chapter if isinstance(chapter, list) else [chapter]}}


def _passage(source: dict[str, Any]) -> Passage:
    return Passage(
        chapter=source["chapter"],
        chapter_title=source["chapter_title"],
        para_start=source["para_start"],
        para_end=source["para_end"],
        text=source["text"],
    )


class ElasticIndex:
    def __init__(self, url: str, alias: str) -> None:
        self.es = Elasticsearch(url, request_timeout=30, retry_on_timeout=True, max_retries=2)
        self.alias = alias

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ESConnectionError, ConnectionTimeout) as e:
            raise SearchUnavailableError() from e

    def ping(self) -> bool:
        try:
            return bool(self.es.ping())
        except Exception:
            return False

    def replace(
        self,
        manuscript: str,
        chapters: list[dict[str, Any]],
        passages: list[Passage],
        vectors: list[list[float]],
    ) -> None:
        new = f"{self.alias}-{time.time_ns()}"
        mappings = {
            "_meta": {"manuscript": manuscript, "chapters": chapters},
            "properties": {
                "chapter": {"type": "integer"},
                "chapter_title": {"type": "keyword"},
                "para_start": {"type": "integer"},
                "para_end": {"type": "integer"},
                "text": {"type": "text", "analyzer": "english"},
                "vector": {
                    "type": "dense_vector",
                    "dims": len(vectors[0]),
                    "index": True,
                    "similarity": "cosine",
                },
            },
        }
        self._call(
            self.es.indices.create,
            index=new,
            mappings=mappings,
            settings={"number_of_shards": 1, "number_of_replicas": 0},
        )
        try:
            actions = (
                {
                    "_index": new,
                    "_id": p.id,
                    "_source": {
                        "chapter": p.chapter,
                        "chapter_title": p.chapter_title,
                        "para_start": p.para_start,
                        "para_end": p.para_end,
                        "text": p.text,
                        "vector": v,
                    },
                }
                for p, v in zip(passages, vectors, strict=True)
            )
            self._call(bulk, self.es, actions, chunk_size=200)
            self._call(self.es.indices.refresh, index=new)
            old = self._indices()
            remove = [{"remove": {"index": i, "alias": self.alias}} for i in old]
            self._call(
                self.es.indices.update_aliases,
                actions=[*remove, {"add": {"index": new, "alias": self.alias}}],
            )
        except Exception:
            self.es.indices.delete(index=new, ignore_unavailable=True)
            raise
        for i in old:
            self.es.indices.delete(index=i, ignore_unavailable=True)

    def _indices(self) -> list[str]:
        try:
            return list(self._call(self.es.indices.get_alias, name=self.alias).keys())
        except NotFoundError:
            return []

    def stats(self) -> IndexStats:
        indices = self._indices()
        if not indices:
            return IndexStats(name=self.alias, manuscript=None, chapters=[], passages=0)
        mapping = self._call(self.es.indices.get_mapping, index=indices[0])
        meta = mapping[indices[0]]["mappings"].get("_meta", {})
        count = self._call(self.es.count, index=self.alias)["count"]
        return IndexStats(
            name=self.alias,
            manuscript=meta.get("manuscript"),
            chapters=meta.get("chapters", []),
            passages=count,
        )

    def _hits(self, response: Any) -> list[tuple[Passage, float]]:
        return [(_passage(h["_source"]), float(h["_score"])) for h in response["hits"]["hits"]]

    def bm25(
        self, question: str, k: int, exclude_chapter: int | list[int] | None = None
    ) -> list[tuple[Passage, float]]:
        query: dict[str, Any] = {"match": {"text": question}}
        if exclude_chapter is not None:
            query = {"bool": {"must": query, "must_not": _not_chapter(exclude_chapter)}}
        try:
            response = self._call(
                self.es.search,
                index=self.alias,
                query=query,
                size=k,
                source_excludes=["vector"],
            )
        except NotFoundError:
            return []  # nothing indexed yet
        except ApiError as e:
            raise SearchFailedError(f"The search index returned an error ({e.meta.status})") from e
        return self._hits(response)

    def dimensions(self) -> int | None:
        indices = self._indices()
        if not indices:
            return None
        mapping = self._call(self.es.indices.get_mapping, index=indices[0])
        return int(mapping[indices[0]]["mappings"]["properties"]["vector"]["dims"])

    def knn(
        self, vector: list[float], k: int, exclude_chapter: int | list[int] | None = None
    ) -> list[tuple[Passage, float]]:
        dims = self.dimensions()
        if dims is not None and dims != len(vector):
            raise SearchFailedError(EMBEDDING_CHANGED)
        try:
            response = self._call(
                self.es.search,
                index=self.alias,
                knn={
                    "field": "vector",
                    "query_vector": vector,
                    "k": k,
                    "num_candidates": k * 10,
                    **(
                        {"filter": {"bool": {"must_not": _not_chapter(exclude_chapter)}}}
                        if exclude_chapter is not None
                        else {}
                    ),
                },
                size=k,
                source_excludes=["vector"],
            )
        except NotFoundError:
            return []
        except ApiError as e:
            raise SearchFailedError(f"The search index returned an error ({e.meta.status})") from e
        return self._hits(response)
