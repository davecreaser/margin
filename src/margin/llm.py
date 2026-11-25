"""The model client: Claude through the Anthropic SDK, with the author's own key (ADR 0006).

Steps depend on the `ModelClient` protocol, so tests use a fake that returns canned output.
"""

import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, TypeAdapter, ValidationError

KEY_PLACEHOLDERS = {"", "your-key-here"}
STREAM_ABOVE = 16000

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class NoApiKeyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("No Anthropic API key: add ANTHROPIC_API_KEY to .env (see .env.example)")


class ModelBusyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("The model provider is busy; try again in a minute")


@dataclass
class ModelReply[T: BaseModel]:
    output: T | None
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    error: str | None = None


class ModelClient(Protocol):
    def structured[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        effort: str,
        max_tokens: int,
    ) -> ModelReply[T]: ...


def _schema(model: type[BaseModel]) -> dict[str, object]:
    """The JSON schema the API's structured outputs accept, as the SDK builds it."""
    from anthropic.lib._parse._transform import transform_schema

    return transform_schema(TypeAdapter(model).json_schema())


def api_key_present() -> bool:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() not in KEY_PLACEHOLDERS


class AnthropicClient:
    def __init__(self, max_retries: int = 4) -> None:
        if not api_key_present():
            raise NoApiKeyError()
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(max_retries=max_retries)

    def structured[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        effort: str,
        max_tokens: int,
    ) -> ModelReply[T]:
        a = self._anthropic
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": cast(Effort, effort),
                "format": {"type": "json_schema", "schema": _schema(schema)},
            },
        }
        try:
            if max_tokens > STREAM_ABOVE:  # the SDK requires streaming for long outputs
                with self._client.messages.stream(**request) as stream:
                    response = stream.get_final_message()
            else:
                response = self._client.messages.create(**request)
        except a.AuthenticationError as e:
            raise NoApiKeyError() from e
        except (a.RateLimitError, a.InternalServerError, a.APIConnectionError) as e:
            raise ModelBusyError() from e
        except a.APIStatusError as e:
            if e.status_code in (429, 529) or e.status_code >= 500:
                raise ModelBusyError() from e
            raise
        # Usage and stop reason are read before validation, so a truncated or refused
        # reply is still counted and reported (and a refusal is not retried).
        usage = response.usage
        output: T | None = None
        error = None
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason in ("refusal", "max_tokens"):
            error = f"no usable output (stop reason: {response.stop_reason})"
        else:
            try:
                output = schema.model_validate_json(text)
            except ValidationError as e:
                error = f"invalid structured output: {e.error_count()} error(s)"
        return ModelReply(
            output=output,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            stop_reason=response.stop_reason,
            error=error,
        )
