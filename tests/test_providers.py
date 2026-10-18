"""The adapters against fake HTTP responses shaped like the providers' documented ones (no network)."""

import json

import httpx
import pytest

from econ.answer import providers
from econ.answer.providers import GeminiModel, OpenAIModel, ProviderError
from econ.config import service

OPENAI, GEMINI = service().llm.providers
ARGS = {
    "system": "sys",
    "user": "usr",
    "schema": {"type": "object"},
    "schema_name": "answer",
    "effort": "medium",
    "max_output_tokens": 100,
}


class Fake:
    def __init__(self, status, body):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, url, json=None, timeout=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(self.status, json=self.body, request=httpx.Request("POST", url))


def test_openai_request_is_pinned_and_strict(monkeypatch):
    body = {
        "status": "completed",
        "id": "resp_1",
        "output": [
            {"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": '{"a": 1}'}]},
        ],
        "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 400},
            "output_tokens": 200,
            "output_tokens_details": {"reasoning_tokens": 50},
        },
    }
    fake = Fake(200, body)
    monkeypatch.setattr(httpx, "post", fake)
    m = OpenAIModel(OPENAI, "sk-test", 30)
    rep = m.generate_json(model="gpt-6.1-sol", **ARGS)
    sent = fake.calls[0]
    assert sent["url"] == "https://api.openai.com/v1/responses"
    assert sent["json"]["store"] is False and sent["json"]["text"]["format"]["strict"] is True
    assert sent["json"]["reasoning"] == {"effort": "medium"}
    assert set(sent["headers"]) == {"Authorization"}
    assert rep.data == {"a": 1}
    assert (rep.usage.input, rep.usage.cached_input, rep.usage.output) == (600, 400, 200)
    assert rep.usage.cost_usd == pytest.approx((600 * 2 + 400 * 2 + 200 * 10) / 1e6)


@pytest.mark.parametrize(
    "body,msg",
    [
        ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "incomplete"),
        (
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            },
            "refused",
        ),
    ],
)
def test_openai_failures_raise(monkeypatch, body, msg):
    monkeypatch.setattr(httpx, "post", Fake(200, body))
    with pytest.raises(ProviderError, match=msg):
        OpenAIModel(OPENAI, "k", 30).generate_json(model="gpt-6.1-sol", **ARGS)


def test_gemini_skips_thought_parts_and_bills_thinking_as_output(monkeypatch):
    body = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [{"text": "thinking...", "thought": True}, {"text": json.dumps({"b": 2})}]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 1000,
            "cachedContentTokenCount": 0,
            "candidatesTokenCount": 100,
            "thoughtsTokenCount": 300,
        },
    }
    fake = Fake(200, body)
    monkeypatch.setattr(httpx, "post", fake)
    rep = GeminiModel(GEMINI, "g-test", 30).generate_json(model="gemini-3.8-flash", **ARGS)
    sent = fake.calls[0]
    assert sent["url"].endswith("/models/gemini-3.8-flash:generateContent")
    assert sent["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert sent["headers"] == {"x-goog-api-key": "g-test"}
    assert rep.data == {"b": 2} and rep.usage.output == 400 and rep.usage.reasoning == 300


def test_gemini_non_stop_finish_raises(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", Fake(200, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]})
    )
    with pytest.raises(ProviderError, match="MAX_TOKENS"):
        GeminiModel(GEMINI, "k", 30).generate_json(model="gemini-3.8-flash", **ARGS)


def test_http_errors_raise_without_leaking_the_key(monkeypatch):
    monkeypatch.setattr(httpx, "post", Fake(401, {"error": "bad key"}))
    with pytest.raises(ProviderError) as e:
        OpenAIModel(OPENAI, "sk-secret-value", 30).generate_json(model="gpt-6.1-sol", **ARGS)
    assert "sk-secret-value" not in str(e.value)


def test_configured_picks_the_first_provider_with_a_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    m, p = providers.configured()
    assert p.name == "gemini" and isinstance(m, GeminiModel)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert providers.configured() is None
