# Self-hosted: one Python service and Elasticsearch, run with Docker Compose

Margin is open source and runs on the author's own computer. There is no hosted version.

`docker compose up` starts two containers:
- **Elasticsearch**, with its data in a named volume
- **the Margin service**: Python 3.12, FastAPI, with a CLI (`margin`) that talks to it

The CLI is the interface. The HTTP API exists so that a UI, an editor plugin or an MCP server can be added later without touching the pipeline.

Why one Python service: all of the work (ingestion, retrieval, the reasoning steps, the habits patterns, the evals) sits in the Python AI ecosystem: LlamaIndex, the Elasticsearch client, spaCy, pytest. A second language for a web front end would add a toolchain without serving the CLI-first product.

Why self-hosted: an unpublished manuscript is private, and authors are right to be wary of uploading one. Self-hosting means the text, index and embeddings never leave the author's machine. Only the passages a request needs go to the model provider, under the author's own key.

Trade-off: Elasticsearch needs about 1–2 GB of memory, which is heavy for a personal tool. This is accepted for hybrid retrieval (ADR 0003). The compose file sets a modest heap.
