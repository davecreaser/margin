"""Local embeddings (ADR 0006): the manuscript is never sent anywhere to be indexed."""

from typing import Protocol


class Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """An open embedding model run on CPU with ONNX, through LlamaIndex's FastEmbed wrapper."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from llama_index.embeddings.fastembed import FastEmbedEmbedding

        self._model = FastEmbedEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            self._dimensions = len(self.embed_query("dimensions"))
        return self._dimensions

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._model.get_text_embedding_batch(texts)]

    def embed_query(self, text: str) -> list[float]:
        return list(self._model.get_query_embedding(text))
