"""Decision layer: Claude reads the events and proposes exactly one structured decision.

The model's output is constrained by a JSON schema (never regex-parsed prose). It is a
proposal only: the deterministic risk gate in risk.py decides whether anything happens.
"""

from __future__ import annotations

import json
import time
from typing import Literal

import anthropic
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


class DecisionMaker:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key or None, timeout=180.0, max_retries=2) if api_key else None

    def decide(self, context: dict) -> dict:
        """Returns the `llm` section of the tick record; `decision` is None if no valid decision came back."""
        out: dict = {"called": True, "model": self.model, "decision": None, "error": None}
        if self.client is None:
            out["error"] = "ANTHROPIC_API_KEY not configured"
            return out
        started = time.monotonic()
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(context, indent=1, default=str)}],
            )
        except anthropic.APIStatusError as e:
            out["error"] = f"api_status_{e.status_code}: {e.message}"
            return out
        except anthropic.APIConnectionError as e:
            out["error"] = f"api_connection: {type(e).__name__}"
            return out
        out["latency_ms"] = int((time.monotonic() - started) * 1000)
        out["request_id"] = getattr(resp, "_request_id", None)
        out["served_by"] = resp.model
        out["fallback_used"] = any(getattr(it, "type", None) == "fallback_message"
                                   for it in (getattr(resp.usage, "iterations", None) or []))
        out["stop_reason"] = resp.stop_reason
        out["usage"] = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        out["thinking_summary"] = "\n".join(b.thinking for b in resp.content
                                            if b.type == "thinking" and getattr(b, "thinking", "")) or None
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            out["error"] = f"refusal: {getattr(details, 'category', None)}"
            return out
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            out["decision"] = Decision.model_validate(json.loads(text)).model_dump()
        except (json.JSONDecodeError, ValidationError) as e:
            out["error"] = f"malformed_output: {type(e).__name__}"
            out["raw_output"] = text[:4000]
        return out
