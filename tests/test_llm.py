import copy
import json
import os
import unittest
from unittest import mock

from tests import _paths  # noqa: F401
from medperplexity import llm
from medperplexity.llm import (AnthropicProvider, FallbackLLM, GeminiProvider, LLMError, LLMUnavailable,
                               OpenAIProvider, OpenRouterProvider, extract_json)

SECRET = "sk-secret-key-123"


def ok_openrouter(text='{"ok": true}', model="anthropic/x"):
    return 200, {"choices": [{"message": {"content": text}}], "model": model}


class Http:
    """Scripted replacement for llm._http_post that records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        # snapshot: the code under test may legitimately mutate the payload for a retry
        self.calls.append({"url": url, "headers": dict(headers), "payload": copy.deepcopy(payload), "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def run_provider(provider, http, **kw):
    with mock.patch.object(llm, "_http_post", http):
        return provider.complete("sys JSON", "user", max_tokens=100, temperature=0.0, json_mode=True,
                                 timeout=5, **kw)


class ExtractJsonTests(unittest.TestCase):
    def test_plain_fenced_and_surrounded(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Here you go: {"a": {"b": [1, 2]}} hope it helps'), {"a": {"b": [1, 2]}})
        self.assertEqual(extract_json('noise {not json} then {"a": 2}'), {"a": 2})

    def test_failures(self):
        for bad in ("", "   ", "no json here", None, 5, "{unclosed"):
            with self.assertRaises(ValueError):
                extract_json(bad)


class ProviderRequestTests(unittest.TestCase):
    def test_openrouter_with_fallback_models(self):
        p = OpenRouterProvider(api_key=SECRET, model="a/primary", fallback_models=["b/second", "c/third", "a/primary"])
        http = Http(ok_openrouter(model="b/second"))
        text, model_used = run_provider(p, http)
        call = http.calls[0]
        self.assertEqual(call["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {SECRET}")
        self.assertEqual(call["payload"]["models"], ["a/primary", "b/second", "c/third"])
        self.assertEqual(call["payload"]["route"], "fallback")
        self.assertNotIn("model", call["payload"])
        self.assertEqual(call["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(call["payload"]["messages"][0]["role"], "system")
        self.assertEqual(model_used, "b/second")  # reports the model that actually answered

    def test_openrouter_single_model_and_optional_headers(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_SITE_URL": "https://example.org", "OPENROUTER_APP_NAME": "App"}):
            p = OpenRouterProvider(api_key=SECRET, model="a/primary", fallback_models=[])
            http = Http(ok_openrouter())
            run_provider(p, http)
        self.assertEqual(http.calls[0]["payload"]["model"], "a/primary")
        self.assertNotIn("models", http.calls[0]["payload"])
        self.assertEqual(http.calls[0]["headers"]["HTTP-Referer"], "https://example.org")
        self.assertEqual(http.calls[0]["headers"]["X-Title"], "App")

    def test_openrouter_error_inside_200(self):
        p = OpenRouterProvider(api_key=SECRET, model="a/m", fallback_models=[])
        with self.assertRaises(LLMError) as ctx:
            run_provider(p, Http((200, {"error": {"code": 502, "message": "upstream down"}})))
        self.assertTrue(ctx.exception.retryable)

    def test_anthropic(self):
        p = AnthropicProvider(api_key=SECRET, model="claude-x")
        http = Http((200, {"content": [{"type": "text", "text": '{"a":'}, {"type": "text", "text": " 1}"}],
                           "model": "claude-x"}))
        text, _ = run_provider(p, http)
        call = http.calls[0]
        self.assertEqual(text, '{"a": 1}')
        self.assertEqual(call["headers"]["x-api-key"], SECRET)
        self.assertEqual(call["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(call["payload"]["system"], "sys JSON")
        self.assertEqual(call["payload"]["messages"], [{"role": "user", "content": "user"}])
        self.assertEqual(AnthropicProvider(api_key="k").model, llm.DEFAULT_ANTHROPIC_MODEL)

    def test_openai(self):
        p = OpenAIProvider(api_key=SECRET, model="gpt-x")
        http = Http((200, {"choices": [{"message": {"content": '{"a": 1}'}}], "model": "gpt-x"}))
        run_provider(p, http)
        payload = http.calls[0]["payload"]
        self.assertNotIn("temperature", payload)  # some current OpenAI models reject non-default values
        self.assertEqual(payload["max_completion_tokens"], 100)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(http.calls[0]["headers"]["Authorization"], f"Bearer {SECRET}")

    def test_gemini(self):
        p = GeminiProvider(api_key=SECRET, model="gem-x")
        body = {"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}], "modelVersion": "gem-x-001"}
        http = Http((200, body))
        text, model_used = run_provider(p, http)
        call = http.calls[0]
        self.assertIn("models/gem-x:generateContent", call["url"])
        self.assertEqual(call["headers"]["x-goog-api-key"], SECRET)
        self.assertNotIn(SECRET, call["url"])  # key travels in a header, not the URL
        self.assertEqual(call["payload"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(call["payload"]["systemInstruction"]["parts"][0]["text"], "sys JSON")
        self.assertEqual(len(call["payload"]["safetySettings"]), 1)
        self.assertEqual(model_used, "gem-x-001")

    def test_gemini_blocked_and_empty(self):
        p = GeminiProvider(api_key=SECRET, model="gem-x")
        with self.assertRaises(LLMError) as ctx:
            run_provider(p, Http((200, {"promptFeedback": {"blockReason": "SAFETY"}})))
        self.assertIn("safety", str(ctx.exception).lower())
        with self.assertRaises(LLMError):
            run_provider(p, Http((200, {"candidates": []})))
        with self.assertRaises(LLMError):
            run_provider(p, Http((200, {"candidates": [{"finishReason": "SAFETY"}]})))

    def test_http_errors_are_classified(self):
        p = OpenAIProvider(api_key=SECRET, model="m")
        for status, retryable in ((429, True), (503, True), (401, False), (402, False), (400, False)):
            with self.assertRaises(LLMError) as ctx:
                run_provider(p, Http((status, {"error": {"message": "nope"}})))
            self.assertEqual(ctx.exception.retryable, retryable, status)
            self.assertEqual(ctx.exception.status, status)

    def test_availability_needs_key_and_model(self):
        self.assertFalse(OpenRouterProvider(api_key="", model="a/m", fallback_models=[]).available())
        self.assertFalse(OpenRouterProvider(api_key="k", model="", fallback_models=[]).available())
        self.assertFalse(OpenAIProvider(api_key="k", model="").available())
        self.assertTrue(AnthropicProvider(api_key="k").available())


def make_llm(*providers, **kw):
    kw.setdefault("sleep", lambda _s: None)
    return FallbackLLM(list(providers), **kw)


def provider(name="openrouter", model="m/1"):
    cls = {"openrouter": OpenRouterProvider, "anthropic": AnthropicProvider, "openai": OpenAIProvider,
           "gemini": GeminiProvider}[name]
    if name == "openrouter":
        return cls(api_key=SECRET, model=model, fallback_models=[])
    return cls(api_key=SECRET, model=model)


def positive(value):
    if not isinstance(value, dict) or value.get("n", 0) <= 0:
        raise ValueError("n must be positive")
    return value


class PrivacyAndParameterFallbackTests(unittest.TestCase):
    def test_openrouter_requests_deny_data_collection_by_default(self):
        p = OpenRouterProvider(api_key=SECRET, model="a/m", fallback_models=[])
        http = Http(ok_openrouter())
        run_provider(p, http)
        self.assertEqual(http.calls[0]["payload"]["provider"], {"data_collection": "deny"})

    def test_openrouter_zdr_and_policy_from_environment(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_ZDR": "true", "OPENROUTER_DATA_COLLECTION": "allow"}):
            p = OpenRouterProvider(api_key=SECRET, model="a/m", fallback_models=[])
        http = Http(ok_openrouter())
        run_provider(p, http)
        self.assertEqual(http.calls[0]["payload"]["provider"], {"data_collection": "allow", "zdr": True})
        with mock.patch.dict(os.environ, {"OPENROUTER_DATA_COLLECTION": "nonsense"}):
            self.assertEqual(OpenRouterProvider(api_key="k", model="m").data_collection, "deny")  # invalid -> safe default

    def test_openai_retries_without_a_rejected_response_format(self):
        p = OpenAIProvider(api_key=SECRET, model="gpt-x")
        http = Http((400, {"error": {"message": "Unsupported parameter: 'response_format' is not supported"}}),
                    (200, {"choices": [{"message": {"content": '{"a": 1}'}}], "model": "gpt-x"}))
        text, _ = run_provider(p, http)
        self.assertEqual(len(http.calls), 2)
        self.assertIn("response_format", http.calls[0]["payload"])
        self.assertNotIn("response_format", http.calls[1]["payload"])
        self.assertEqual(text, '{"a": 1}')

    def test_gemini_retries_without_a_rejected_temperature(self):
        p = GeminiProvider(api_key=SECRET, model="gem-x")
        http = Http((400, {"error": {"message": "temperature is not supported for this model"}}),
                    (200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}))
        run_provider(p, http)
        self.assertIn("temperature", http.calls[0]["payload"]["generationConfig"])
        self.assertNotIn("temperature", http.calls[1]["payload"]["generationConfig"])
        self.assertIn("responseMimeType", http.calls[1]["payload"]["generationConfig"])  # only the offender is dropped

    def test_anthropic_retries_without_a_rejected_temperature(self):
        p = AnthropicProvider(api_key=SECRET, model="claude-x")
        http = Http((400, {"error": {"message": "`temperature` may not be set for this model"}}),
                    (200, {"content": [{"type": "text", "text": "{}"}]}))
        run_provider(p, http)
        self.assertNotIn("temperature", http.calls[1]["payload"])

    def test_unrelated_400_is_not_retried(self):
        p = OpenAIProvider(api_key=SECRET, model="gpt-x")
        http = Http((400, {"error": {"message": "context length exceeded"}}))
        with self.assertRaises(LLMError):
            run_provider(p, http)
        self.assertEqual(len(http.calls), 1)

    def test_each_parameter_is_dropped_at_most_once(self):
        p = OpenAIProvider(api_key=SECRET, model="gpt-x")
        bad = (400, {"error": {"message": "response_format invalid"}})
        http = Http(bad, bad)
        with self.assertRaises(LLMError):
            run_provider(p, http)
        self.assertEqual(len(http.calls), 2)

    def test_default_claude_model_is_opus(self):
        self.assertEqual(llm.DEFAULT_ANTHROPIC_MODEL, "claude-opus-5-5")


class FallbackTests(unittest.TestCase):
    def test_first_provider_wins(self):
        http = Http(ok_openrouter('{"n": 1}'))
        with mock.patch.object(llm, "_http_post", http):
            value, result = make_llm(provider("openrouter"), provider("anthropic")).complete_json("s", "u", positive)
        self.assertEqual(value, {"n": 1})
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(len(http.calls), 1)

    def test_transient_error_retried_then_falls_back(self):
        sleeps = []
        http = Http((503, {}), (503, {}),                                     # openrouter: initial + 1 retry
                    (200, {"content": [{"type": "text", "text": '{"n": 2}'}], "model": "claude-x"}))
        client = make_llm(provider("openrouter"), provider("anthropic", "claude-x"), sleep=sleeps.append)
        with mock.patch.object(llm, "_http_post", http):
            value, result = client.complete_json("s", "u", positive)
        self.assertEqual(result.provider, "anthropic")
        self.assertEqual(len(sleeps), 1)
        self.assertEqual([a["ok"] for a in result.attempts], [False, True])
        self.assertIn("503", result.attempts[0]["error"])

    def test_auth_error_is_not_retried(self):
        http = Http((401, {"error": {"message": "bad key"}}), ok_openrouter('{"n": 1}'))
        client = make_llm(provider("openai", "g"), provider("openrouter"))
        with mock.patch.object(llm, "_http_post", http):
            _, result = client.complete_json("s", "u", positive)
        self.assertEqual(len(http.calls), 2)  # one call per provider, no retry on 401
        self.assertEqual(result.provider, "openrouter")

    def test_invalid_json_gets_one_repair_attempt_on_same_provider(self):
        http = Http(ok_openrouter("sorry, I cannot"), ok_openrouter('{"n": 3}'))
        with mock.patch.object(llm, "_http_post", http):
            value, result = make_llm(provider("openrouter")).complete_json("s", "u", positive)
        self.assertEqual(value, {"n": 3})
        self.assertIn("rejected", http.calls[1]["payload"]["messages"][1]["content"])
        self.assertEqual(result.attempts[0]["error"].split(":")[0], "invalid output")

    def test_schema_violation_triggers_repair_then_fallback(self):
        http = Http(ok_openrouter('{"n": 0}'), ok_openrouter('{"n": -1}'),   # openrouter fails twice
                    (200, {"content": [{"type": "text", "text": '{"n": 5}'}]}))
        client = make_llm(provider("openrouter"), provider("anthropic", "claude-x"))
        with mock.patch.object(llm, "_http_post", http):
            value, result = client.complete_json("s", "u", positive)
        self.assertEqual((value, result.provider), ({"n": 5}, "anthropic"))
        self.assertEqual(len(http.calls), 3)

    def test_network_error_falls_back(self):
        http = Http(LLMError("network error: URLError", retryable=True), LLMError("network error", retryable=True),
                    (200, {"candidates": [{"content": {"parts": [{"text": '{"n": 9}'}]}}]}))
        client = make_llm(provider("openrouter"), provider("gemini", "gem"))
        with mock.patch.object(llm, "_http_post", http):
            value, result = client.complete_json("s", "u", positive)
        self.assertEqual(result.provider, "gemini")

    def test_all_providers_fail(self):
        http = Http(*[(500, {})] * 4)
        client = make_llm(provider("openrouter"), provider("openai", "g"))
        with mock.patch.object(llm, "_http_post", http):
            with self.assertRaises(LLMUnavailable) as ctx:
                client.complete_json("s", "u", positive)
        self.assertEqual(len(http.calls), 4)                      # each provider: first try + one retry
        self.assertEqual([a["provider"] for a in ctx.exception.attempts], ["openrouter", "openai"])  # one audit entry each

    def test_nothing_configured(self):
        with self.assertRaises(LLMUnavailable) as ctx:
            FallbackLLM([OpenRouterProvider(api_key="", model="", fallback_models=[])]).complete_json("s", "u")
        self.assertIn("No LLM provider", str(ctx.exception))

    def test_audit_never_contains_secrets_or_prompts(self):
        http = Http((500, {"error": {"message": "x"}}), (500, {}), ok_openrouter('{"n": 1}'))
        client = make_llm(provider("openrouter"), provider("openai", "g"))
        with mock.patch.object(llm, "_http_post", http):
            _, result = client.complete_json("SECRET-SYSTEM-PROMPT", "PATIENT-DATA-HERE", positive)
        blob = json.dumps(result.audit())
        for forbidden in (SECRET, "SECRET-SYSTEM-PROMPT", "PATIENT-DATA-HERE"):
            self.assertNotIn(forbidden, blob)

    def test_from_env_order_and_skipping(self):
        env = {"LLM_PROVIDERS": "gemini, openrouter ,bogus,openai", "OPENROUTER_API_KEY": "k", "OPENROUTER_MODEL": "a/m",
               "OPENROUTER_FALLBACK_MODELS": "b/n, c/o", "GOOGLE_API_KEY": "g", "GEMINI_MODEL": "gem"}
        with mock.patch.dict(os.environ, env, clear=True):
            client = FallbackLLM.from_env()
        self.assertEqual(client.configured, ["gemini:gem", "openrouter:a/m"])  # openai skipped (no key), bogus ignored
        self.assertEqual(client.providers[1].fallback_models, ["b/n", "c/o"])

    def test_gemini_accepts_either_key_name(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "from-gemini-var", "GEMINI_MODEL": "m"}, clear=True):
            self.assertEqual(GeminiProvider().api_key, "from-gemini-var")

    def test_check_reports_each_provider(self):
        http = Http(ok_openrouter('{"ok": true}'), (401, {"error": {"message": "bad"}}))
        client = make_llm(provider("openrouter"), provider("openai", "g"))
        with mock.patch.object(llm, "_http_post", http):
            results = client.check()
        self.assertEqual([r["ok"] for r in results], [True, False])
        self.assertIn("401", results[1]["error"])

    def test_default_http_function_maps_network_failures(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(LLMError) as ctx:
                llm._http_post("https://x.invalid", {}, {}, 1)
        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
