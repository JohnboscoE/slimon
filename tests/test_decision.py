import json
import unittest

import requests

from slimon.decision import DecisionMaker

SETTINGS = {"model": "qwen3.8-max", "base_url": "https://gateway.example/v1/"}
GOOD = {"action": "NO_TRADE", "instrument": "", "notional_usdt": 0, "confidence": 0.7, "time_horizon_hours": 1,
        "triggering_event_ids": ["evt-1"], "reasoning": "quiet", "invalidation": "a real move"}


class FakeResponse:
    def __init__(self, status: int, payload=None, text: str | None = None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def completion(content: str, reasoning: str = "thinking it over") -> dict:
    return {"id": "chatcmpl-1", "model": "qwen3.8-max",
            "choices": [{"finish_reason": "stop", "message": {"content": content, "reasoning_content": reasoning}}],
            "usage": {"prompt_tokens": 700, "completion_tokens": 500, "completion_tokens_details": {"reasoning_tokens": 300}}}


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def maker(*responses) -> tuple[DecisionMaker, FakeSession]:
    dm = DecisionMaker("qwen", SETTINGS, "k" * 16)
    dm._http = FakeSession(*responses)
    return dm, dm._http


class QwenTransport(unittest.TestCase):
    def setUp(self):
        # Retries back off with time.sleep; don't actually wait in tests.
        import slimon.decision as d
        self._sleep = d.time.sleep
        d.time.sleep = lambda s: None

    def tearDown(self):
        import slimon.decision as d
        d.time.sleep = self._sleep

    def test_valid_decision_is_parsed_and_logged(self):
        dm, http = maker(FakeResponse(200, completion(json.dumps(GOOD))))
        out = dm.decide({"events": []})
        self.assertIsNone(out["error"])
        self.assertEqual(out["decision"]["action"], "NO_TRADE")
        self.assertEqual(out["served_by"], "qwen3.8-max")
        self.assertEqual(out["usage"], {"input_tokens": 700, "output_tokens": 500, "reasoning_tokens": 300})
        self.assertEqual(out["reasoning_excerpt"], "thinking it over")
        call = http.calls[0]
        self.assertEqual(call["url"], "https://gateway.example/v1/chat/completions")
        self.assertEqual(call["json"]["response_format"]["type"], "json_schema")
        self.assertTrue(call["json"]["response_format"]["json_schema"]["strict"])

    def test_server_error_is_retried(self):
        dm, http = maker(FakeResponse(502, text="bad gateway"), requests.ConnectionError("reset"),
                         FakeResponse(200, completion(json.dumps(GOOD))))
        out = dm.decide({})
        self.assertEqual(len(http.calls), 3)
        self.assertIsNone(out["error"])
        self.assertIsNotNone(out["decision"])

    def test_thinking_is_bounded_by_the_configured_budget(self):
        dm, http = maker(FakeResponse(200, completion(json.dumps(GOOD))))
        dm.settings = {**SETTINGS, "thinking_budget": 1000}
        dm.decide({})
        self.assertEqual(http.calls[0]["json"]["enable_thinking"], True)
        self.assertEqual(http.calls[0]["json"]["thinking_budget"], 1000)

        dm, http = maker(FakeResponse(200, completion(json.dumps(GOOD))))
        dm.settings = {**SETTINGS, "thinking_budget": 0}
        dm.decide({})
        self.assertEqual(http.calls[0]["json"]["enable_thinking"], False)
        self.assertNotIn("thinking_budget", http.calls[0]["json"])

    def test_timeout_is_logged_and_not_retried(self):
        dm, http = maker(requests.Timeout("read timed out"), FakeResponse(200, completion(json.dumps(GOOD))))
        out = dm.decide({})
        self.assertEqual(len(http.calls), 1)
        self.assertIsNone(out["decision"])
        self.assertTrue(out["error"].startswith("api_timeout"))

    def test_auth_error_is_not_retried(self):
        dm, http = maker(FakeResponse(401, text='{"error":"invalid key"}'))
        out = dm.decide({})
        self.assertEqual(len(http.calls), 1)
        self.assertIsNone(out["decision"])
        self.assertTrue(out["error"].startswith("api_status_401"))

    def test_output_failing_the_schema_is_rejected(self):
        dm, _ = maker(FakeResponse(200, completion(json.dumps({**GOOD, "action": "BUY_EVERYTHING"}))))
        out = dm.decide({})
        self.assertIsNone(out["decision"])
        self.assertEqual(out["error"], "malformed_output: ValidationError")

    def test_missing_key_never_calls(self):
        dm = DecisionMaker("qwen", SETTINGS, "")
        out = dm.decide({})
        self.assertIsNone(out["decision"])
        self.assertIn("not configured", out["error"])


if __name__ == "__main__":
    unittest.main()
