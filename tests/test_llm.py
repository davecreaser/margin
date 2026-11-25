"""AnthropicClient against a stubbed SDK client: usage survives bad or truncated output."""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from margin.llm import AnthropicClient, ModelBusyError, NoApiKeyError
from margin.steps.answer import AnswerOutput


def _client(create: Any) -> AnthropicClient:
    c = object.__new__(AnthropicClient)
    c._anthropic = anthropic
    c._client = SimpleNamespace(messages=SimpleNamespace(create=create))  # type: ignore[assignment]
    return c


def _response(text: str, stop_reason: str) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=5000, output_tokens=4000),
    )


def _call(c: AnthropicClient) -> Any:
    return c.structured(
        model="claude-opus-5-5",
        system="s",
        user="u",
        schema=AnswerOutput,
        effort="low",
        max_tokens=4000,
    )


def test_valid_output_is_parsed() -> None:
    r = _call(
        _client(
            lambda **kw: _response('{"kind": "not_in_manuscript", "statements": []}', "end_turn")
        )
    )
    assert r.output is not None and r.output.kind == "not_in_manuscript"
    assert r.input_tokens == 5000


def test_truncated_output_keeps_its_usage() -> None:
    r = _call(_client(lambda **kw: _response('{"kind": "answer", "statem', "max_tokens")))
    assert r.output is None and r.stop_reason == "max_tokens"
    assert (r.input_tokens, r.output_tokens) == (5000, 4000)


def test_invalid_json_keeps_its_usage() -> None:
    r = _call(_client(lambda **kw: _response("HELLO", "end_turn")))
    assert r.output is None and r.error and "invalid structured output" in r.error
    assert r.output_tokens == 4000


def _raise(exc: Exception) -> Any:
    def create(**kw: Any) -> Any:
        raise exc

    return create


def _status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("error", response=httpx.Response(status, request=request), body=None)


def test_invalid_key_is_reported_without_the_key() -> None:
    with pytest.raises(NoApiKeyError) as e:
        _call(_client(_raise(_status_error(anthropic.AuthenticationError, 401))))
    assert str(e.value) == "No Anthropic API key: add ANTHROPIC_API_KEY to .env (see .env.example)"


@pytest.mark.parametrize(
    ("cls", "status"), [(anthropic.RateLimitError, 429), (anthropic.InternalServerError, 529)]
)
def test_busy_provider(cls: type[anthropic.APIStatusError], status: int) -> None:
    with pytest.raises(ModelBusyError, match="busy; try again in a minute"):
        _call(_client(_raise(_status_error(cls, status))))
