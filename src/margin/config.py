"""Settings, read from the environment (prefix MARGIN_) and `.env`.

The model for each reasoning step is set here, and chosen by the evals (ADR 0006).
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_DIR = Path(__file__).parent / "demo" / "the-card"
DEMO_TITLE = "The Card (Arnold Bennett, 1911), public domain"

# US dollars per million tokens: (input, output).
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARGIN_", env_file=".env", extra="ignore")

    es_url: str = "http://localhost:9200"
    index: str = "margin-passages"
    service_url: str = "http://localhost:8000"
    # Token, Google Docs state and the passage-vector cache. /data (a volume) in Docker.
    data_dir: Path = Path(".margin")
    # Where the web page lists local manuscripts from (mounted read-only in Docker).
    manuscripts_dir: Path = Path("manuscripts")

    # Google Docs (spec 0003): the author's own OAuth client, from .env.
    google_client_id: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = "http://localhost:8000/google/callback"

    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache: str | None = None

    min_passage_words: int = 150
    max_passage_words: int = 400

    top_k: int = 8
    candidates_per_method: int = 24
    rrf_k: int = 60

    answer_model: str = "claude-opus-5-5"
    answer_effort: str = "low"
    answer_max_tokens: int = 4000

    # Continuity check (spec 0002)
    claims_model: str = "claude-sonnet-5-5"
    claims_effort: str = "low"
    claims_max_tokens: int = 6000
    judge_model: str = "claude-sonnet-5-5"
    judge_effort: str = "low"
    judge_max_tokens: int = 1500
    claim_cap: int = 40
    check_top_k: int = 6
    section_words: int = 3000
    check_concurrency: int = 4
    confirm_above_usd: float = 0.25

    # Progress tracker (spec 0005): a chapter under this many words is a stub.
    stub_words: int = 200

    # Timeline (spec 0006): built only on request.
    events_model: str = "claude-sonnet-5-5"
    events_effort: str = "low"
    events_max_tokens: int = 6000
    event_cap: int = 25
    place_model: str = "claude-opus-5-5"  # chosen by eval: Sonnet left 99% of a long book unplaced
    place_effort: str = "low"
    place_max_tokens: int = 64000  # the ceiling; each call asks for room for its events


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost in US dollars, or None for a model without a known price."""
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
