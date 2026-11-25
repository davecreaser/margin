from margin.passages import Passage
from margin.retrieval import Retriever, reciprocal_rank_fusion
from tests.fakes import FixedEmbedder, InMemoryStore


def test_rrf_rewards_agreement_and_keeps_single_list_items() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"]], k=60))
    assert fused["b"] > fused["a"] > fused["d"]
    assert set(fused) == {"a", "b", "c", "d"}


def _passages() -> list[Passage]:
    filler = "The kettle sang and the lamp was lit in the street by the canal."
    texts = [f"{filler} Evening number {i} passed quietly." for i in range(11)]
    texts[7] = "A letter came from old Mr Duncalf about the lease, signed in green ink."
    return [Passage(1, "One", i + 1, i + 1, t) for i, t in enumerate(texts)]


def test_rare_proper_noun_is_retrieved_even_when_its_embedding_ranks_it_last() -> None:
    passages = _passages()
    query = [1.0, 0.0]
    # Fixed vectors: every passage points along the query except the Duncalf one.
    vectors = [[1.0, 0.1 * i] for i in range(len(passages))]
    vectors[7] = [0.0, 1.0]
    store = InMemoryStore(passages, vectors)
    retriever = Retriever(store, FixedEmbedder(query), top_k=8, candidates=24, rrf_k=60)

    knn_only = [r.passage.id for r in retriever.retrieve("What did Duncalf send?", mode="knn")]
    assert "1:8-8" not in knn_only

    hybrid = retriever.retrieve("What did Duncalf send?")
    assert "1:8-8" in [r.passage.id for r in hybrid]
    hit = next(r for r in hybrid if r.passage.id == "1:8-8")
    assert hit.bm25_rank == 1
    assert hit.knn_rank == len(passages)
    assert len(hybrid) == 8


def test_bm25_only_mode_uses_no_embeddings() -> None:
    passages = _passages()
    store = InMemoryStore(passages, [[1.0, 0.0]] * len(passages))
    retriever = Retriever(store, FixedEmbedder([1.0, 0.0]), top_k=3, candidates=10, rrf_k=60)
    results = retriever.retrieve("Duncalf lease", mode="bm25")
    assert results[0].passage.id == "1:8-8"
    assert all(r.knn_rank is None for r in results)
