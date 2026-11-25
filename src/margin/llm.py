"""The model client: Claude through the Anthropic SDK, with the author's own key (ADR 0006).

Steps depend on the `ModelClient` protocol, so tests use a fake that returns canned output.
"""

import os
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from pydantic import BaseModel

KEY_PLACEHOLDERS = {"", "your-key-here"}

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
        try:
            response = self._client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": cast(Effort, effort)},
            )
        except a.AuthenticationError as e:
            raise NoApiKeyError() from e
        except (a.RateLimitError, a.InternalServerError, a.APIConnectionError) as e:
            raise ModelBusyError() from e
        except a.APIStatusError as e:
            if e.status_code in (429, 529) or e.status_code >= 500:
                raise ModelBusyError() from e
            raise
        except ValueError as e:  # structured output that fails validation
            return ModelReply(None, 0, 0, None, error=f"invalid structured output: {e}")
        usage = response.usage
        output = response.parsed_output
        error = None
        if response.stop_reason in ("refusal", "max_tokens") or output is None:
            error = f"no usable output (stop reason: {response.stop_reason})"
            output = None
        return ModelReply(
            output=output,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            stop_reason=response.stop_reason,
            error=error,
        )
