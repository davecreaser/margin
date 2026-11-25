"""A passage-vector cache keyed by the passage text's hash, so unchanged passages are never
embedded twice (spec 0003). One SQLite file per embedding model, in the data directory."""

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from margin.embedding import Embedder


class CachedEmbedder:
    def __init__(
        self, inner: Embedder | Callable[[], Embedder], data_dir: Path, model_name: str
    ) -> None:
        self._inner = inner  # a factory defers loading the model until a passage is new
        data_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", model_name).strip("-")
        self.db = sqlite3.connect(data_dir / f"vectors-{slug}.sqlite", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS v (hash TEXT PRIMARY KEY, vector TEXT)")
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def inner(self) -> Embedder:
        if callable(self._inner) and not hasattr(self._inner, "embed_passages"):
            self._inner = self._inner()
        return self._inner  # type: ignore[return-value]

    @property
    def dimensions(self) -> int:
        return self.inner.dimensions

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        with self.lock:
            found: dict[str, list[float]] = {}
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                rows = self.db.execute(
                    f"SELECT hash, vector FROM v WHERE hash IN ({','.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
                found.update((h, json.loads(v)) for h, v in rows)
            todo = [i for i, k in enumerate(keys) if k not in found]
            if todo:
                vectors = self.inner.embed_passages([texts[i] for i in todo])
                for i, vec in zip(todo, vectors, strict=True):
                    found[keys[i]] = vec
                self.db.executemany(
                    "INSERT OR REPLACE INTO v VALUES (?, ?)",
                    [(keys[i], json.dumps(found[keys[i]])) for i in todo],
                )
                self.db.commit()
            self.hits += len(keys) - len(todo)
            self.misses += len(todo)
            return [found[k] for k in keys]
