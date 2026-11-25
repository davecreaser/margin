# The author's own Anthropic key; embeddings computed locally

**Generation.** The reasoning steps (answer, extract claims, judge a claim, name a habit) call Claude through the Anthropic SDK, with the author's own API key read from `.env`. The key is never logged, never written into the index, and never committed (`.env` is ignored; `.env.example` holds placeholders only). Which model each step uses is set in one config file and chosen by the evals, not by default; a small model may be enough for claim extraction.

**Embeddings.** Passages and queries are embedded inside the container with an open embedding model, so the full manuscript is never sent anywhere to be indexed. The model is pinned by name and revision, downloaded on first run, and cached in a volume. Which model is chosen by the Ask eval's retrieval numbers.

Trade-off: a local embedding model is slower than an API and may retrieve slightly worse. Privacy of the whole text outweighs this, and the eval shows the cost.
