# Elasticsearch for hybrid retrieval

Passages are stored in Elasticsearch with their text, chapter, paragraph range and a dense embedding. Retrieval is **hybrid**: BM25 keyword search and kNN vector search, merged with reciprocal rank fusion.

Why hybrid: fiction questions are full of two kinds of difficulty.
- **Names and rare words** (a character's surname, an invented place) are found exactly by keyword search and blurred by embeddings.
- **Paraphrase** ("what does the sign over the inn look like?") is only found by embeddings.

Each side's contribution is measured in the Ask eval (BM25 only, vector only, hybrid) rather than assumed.

Why Elasticsearch over pgvector or a vector-only database: it does both kinds of search in one engine and one query, chapter filters are ordinary filters, and its BM25 analysis (stemming, phrase matching) is mature. It runs as a single-node container (ADR 0002).
