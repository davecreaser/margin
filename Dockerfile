FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# The embedding model is downloaded once, at build time, so later starts work offline.
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
ENV MARGIN_EMBED_MODEL=${EMBED_MODEL} MARGIN_EMBED_CACHE=/models HF_HUB_OFFLINE=1
RUN HF_HUB_OFFLINE=0 python -c "from margin.embedding import FastEmbedder; \
    print(FastEmbedder('${EMBED_MODEL}', '/models').dimensions)"

# Manuscripts are mounted read-only under /work; relative paths match the host's.
WORKDIR /work
EXPOSE 8000
CMD ["uvicorn", "margin.api:app", "--host", "0.0.0.0", "--port", "8000"]
