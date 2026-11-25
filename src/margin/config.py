"""Settings, read from the environment (prefix MARGIN_) and `.env`.

The model for each reasoning step is set here, and chosen by the evals (ADR 0006).
"""

from pathlib import Path

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


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost in US dollars, or None for a model without a known price."""
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
