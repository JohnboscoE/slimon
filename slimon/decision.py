"""Decision layer: the LLM (Qwen or Claude, see [llm] in config/agent.toml) reads the events and
proposes exactly one structured decision.

The model's output is constrained by a JSON schema (never regex-parsed prose). It is a
proposal only: the deterministic risk gate in risk.py decides whether anything happens.
"""

from __future__ import annotations

import json
import time
from typing import Literal

import requests
from pydantic import BaseModel, ValidationError

ACTIONS = ("OPEN_LONG", "OPEN_SHORT", "CLOSE", "NO_TRADE")


class Decision(BaseModel):
    action: Literal["OPEN_LONG", "OPEN_SHORT", "CLOSE", "NO_TRADE"]
    instrument: str
    notional_usdt: float
    confidence: float
    time_horizon_hours: float
    triggering_event_ids: list[str]
    reasoning: str
    invalidation: str


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "instrument": {"type": "string", "description": "Symbol, e.g. NVDAUSDT. Empty string for NO_TRADE."},
        "notional_usdt": {"type": "number", "description": "USDT notional for OPEN_*; 0 for CLOSE and NO_TRADE."},
        "confidence": {"type": "number", "description": "0-1, calibrated."},
        "time_horizon_hours": {"type": "number"},
        "triggering_event_ids": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        "invalidation": {"type": "string", "description": "What would prove this decision wrong."},
    },
    "required": ["action", "instrument", "notional_usdt", "confidence", "time_horizon_hours",
                 "triggering_event_ids", "reasoning", "invalidation"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are the decision-maker inside an autonomous, event-driven trading agent. It trades \
USDT-margined perpetual futures on US stocks and US indices on Bitget's demo (paper-trading) \
venue. You are called only when the perception layer has detected events; each call you return \
exactly one decision.

What you receive:
- Triggering events, each with an ID. Price, range and volume events are computed from closed 5-minute \
candles on Bitget's live venue. Session events mark the US cash open and close. Position reviews \
fire when a held position's PnL moves or it has been held for a while.
- A cross-section of the watched universe, so you can tell an idiosyncratic move from an index-wide one.
- The portfolio, the risk limits, the current risk state, and your recent decisions and their outcomes.

Your actions:
- OPEN_LONG / OPEN_SHORT: open, or add to a position in the same direction. To reverse a position, CLOSE it first.
- CLOSE: close the whole position in `instrument`.
- NO_TRADE: stand aside. This is a normal outcome. Most 5-minute events are noise, and a clearly \
reasoned pass is worth more than a marginal trade.

Execution facts: signals come from the live venue, but orders fill on the demo venue at demo prices \
(the demo book can be thin and can diverge from live). Every open order carries an exchange-side \
hard stop. Stock perps also trade outside US cash hours on thinner liquidity.

A deterministic risk gate evaluates your decision after you. It enforces the limits shown to you and \
vetoes anything outside them, whatever the reasoning. The limits are ceilings, not targets: size \
according to conviction.

Field guidance:
- triggering_event_ids: only IDs from the events provided to you in this call.
- confidence: for OPEN_*, a calibrated probability that the trade is profitable over time_horizon_hours; \
for CLOSE or NO_TRADE, your confidence that the action is right.
- reasoning: under 150 words. Name the specific events, say whether the cross-section confirms or \
contradicts them, and say why now. This text is published in the decision log, so it must stand on its own.
- invalidation: a concrete, observable condition.
"""

# How much of a model's reasoning text to keep in the decision log.
REASONING_LOG_CHARS = 4000


class DecisionMaker:
    """Asks the configured model for one decision.

    Two transports share one contract: the same system prompt, the same JSON schema, the same
    validation, and the same `llm` record shape in the log. Only the wire format differs.
    """

    def __init__(self, provider: str, settings: dict, api_key: str):
        self.provider = provider
        self.model = settings["model"]
        self.settings = settings
        self.api_key = api_key
        self._anthropic = None
        self._http = None
        if not api_key:
            return
        if provider == "anthropic":
            import anthropic

            self._anthropic = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=2)
        else:
            self._http = requests.Session()

    @classmethod
    def from_config(cls, cfg) -> "DecisionMaker":
        llm = cfg.llm
        return cls(llm["provider"], llm, cfg.secrets.llm_key(llm["provider"]))

    def decide(self, context: dict) -> dict:
        """Returns the `llm` section of the tick record; `decision` is None if no valid decision came back."""
        out: dict = {"called": True, "provider": self.provider, "model": self.model, "decision": None, "error": None}
        if not self.api_key:
            out["error"] = f"{self.provider} API key not configured"
            return out
        # Compact JSON: indentation alone was ~18% of the input tokens.
        user = json.dumps(context, separators=(",", ":"), default=str)
        started = time.monotonic()
        text = self._ask_anthropic(user, out) if self.provider == "anthropic" else self._ask_qwen(user, out)
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
        if text is None:
            return out
        try:
            out["decision"] = Decision.model_validate(json.loads(text)).model_dump()
        except (json.JSONDecodeError, ValidationError) as e:
            out["error"] = f"malformed_output: {type(e).__name__}"
            out["raw_output"] = text[:4000]
        return out

    # --- transports: return the response text, or None with out["error"] set ---

    def _ask_anthropic(self, user: str, out: dict) -> str | None:
        import anthropic

        effort = self.settings.get("effort", "high")
        try:
            resp = self._anthropic.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIStatusError as e:
            out["error"] = f"api_status_{e.status_code}: {e.message}"
            return None
        except anthropic.APIConnectionError as e:
            out["error"] = f"api_connection: {type(e).__name__}"
            return None
        out["request_id"] = getattr(resp, "_request_id", None)
        out["served_by"] = resp.model
        out["fallback_used"] = any(getattr(it, "type", None) == "fallback_message"
                                   for it in (getattr(resp.usage, "iterations", None) or []))
        out["stop_reason"] = resp.stop_reason
        out["usage"] = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        out["effort"] = effort
        if "price_input_per_mtok" in self.settings:
            out["cost_usd"] = round((resp.usage.input_tokens * self.settings["price_input_per_mtok"]
                                     + resp.usage.output_tokens * self.settings["price_output_per_mtok"]) / 1e6, 6)
        out["thinking_summary"] = "\n".join(b.thinking for b in resp.content
                                            if b.type == "thinking" and getattr(b, "thinking", "")) or None
        if resp.stop_reason == "refusal":
            out["error"] = f"refusal: {getattr(getattr(resp, 'stop_details', None), 'category', None)}"
            return None
        return next((b.text for b in resp.content if b.type == "text"), "")

    def _ask_qwen(self, user: str, out: dict) -> str | None:
        budget = int(self.settings.get("thinking_budget", 0))
        body = {
            "model": self.model,
            "max_tokens": 16000,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "decision", "strict": True, "schema": DECISION_SCHEMA}},
            **({"enable_thinking": True, "thinking_budget": budget} if budget > 0 else {"enable_thinking": False}),
        }
        out["thinking_budget"] = budget
        url = self.settings["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = (10, float(self.settings.get("timeout_seconds", 120)))
        resp = None
        for attempt in (1, 2, 3):  # a decision is idempotent, so transient failures are retried
            try:
                resp = self._http.post(url, json=body, headers=headers, timeout=timeout)
            except requests.Timeout:
                # A slow answer is already a stale one; retrying would only make the tick later.
                out["error"] = f"api_timeout: no answer within {timeout[1]:.0f}s"
                return None
            except requests.RequestException as e:
                out["error"] = f"api_connection: {type(e).__name__}"
                resp = None
            if resp is not None and resp.status_code != 429 and resp.status_code < 500:
                break
            if attempt < 3:
                time.sleep(2 * attempt)
        if resp is None:
            return None
        if not resp.ok:
            out["error"] = f"api_status_{resp.status_code}: {resp.text[:300]}"
            return None
        out["error"] = None
        try:
            data = resp.json()
            choice = data["choices"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            out["error"] = "malformed_response"
            out["raw_output"] = resp.text[:4000]
            return None
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        out["request_id"] = data.get("id")
        out["served_by"] = data.get("model")
        out["stop_reason"] = choice.get("finish_reason")
        out["usage"] = {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}
        # Qwen returns its full reasoning, not a summary; keep a bounded excerpt for the log.
        reasoning = msg.get("reasoning_content") or ""
        out["reasoning_excerpt"] = reasoning[:REASONING_LOG_CHARS] or None
        return msg.get("content") or ""


