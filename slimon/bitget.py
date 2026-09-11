"""Minimal Bitget UTA v3 REST client.

Two venues share one host:
  - "live": production public market data (no auth). Used as the real-world signal.
  - "demo": the paper-trading venue. Every request carries `paptrading: 1`.
There is deliberately no code path that sends a signed request without `paptrading: 1`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

BASE_URL = "https://api.bitget.com"

# Bitget codes the docs say may mean "outcome unknown" — confirm by clientOid before retrying.
AMBIGUOUS_ORDER_CODES = {"40010", "40725", "45001"}


def _rows(data: object) -> list[dict]:
    """List endpoints return {"list": [...]}, {"list": null} when empty, or a bare list."""
    if isinstance(data, dict):
        return data.get("list") or []
    return data or []


class BitgetError(Exception):
    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class BitgetClient:
    def __init__(self, api_key: str = "", api_secret: str = "", passphrase: str = "", timeout: float = 10.0):
        self._key = api_key
        self._secret = api_secret
        self._passphrase = passphrase
        self._timeout = timeout
        self._http = requests.Session()

    def __repr__(self) -> str:  # never leak credentials through repr/logging
        return f"BitgetClient(authenticated={bool(self._key)})"

    # ---- public market data -------------------------------------------------

    def public_get(self, path: str, params: dict | None = None, *, venue: str) -> object:
        if venue not in ("live", "demo"):
            raise ValueError(venue)
        headers = {"paptrading": "1"} if venue == "demo" else {}
        return self._send("GET", path, params=params, headers=headers)

    def instruments(self, category: str, venue: str) -> list[dict]:
        return self.public_get("/api/v3/market/instruments", {"category": category}, venue=venue)

    def tickers(self, category: str, venue: str) -> list[dict]:
        return self.public_get("/api/v3/market/tickers", {"category": category}, venue=venue)

    def candles(self, category: str, symbol: str, interval: str, limit: int, venue: str) -> list[list[str]]:
        params = {"category": category, "symbol": symbol, "interval": interval, "limit": str(limit)}
        return self.public_get("/api/v3/market/candles", params, venue=venue)

    # ---- signed demo endpoints ---------------------------------------------

    def private(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> object:
        if not (self._key and self._secret and self._passphrase):
            raise BitgetError("Bitget demo credentials not configured")
        query = urlencode(sorted((params or {}).items()))
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        ts = str(int(time.time() * 1000))
        prehash = ts + method.upper() + path + (f"?{query}" if query else "") + body_str
        sign = base64.b64encode(hmac.new(self._secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        headers = {
            "ACCESS-KEY": self._key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
            "paptrading": "1",
        }
        return self._send(method, path, query=query, body=body_str, headers=headers)

    def account_info(self) -> dict:
        return self.private("GET", "/api/v3/account/info")

    def account_settings(self) -> dict:
        return self.private("GET", "/api/v3/account/settings")

    def account_assets(self) -> dict:
        return self.private("GET", "/api/v3/account/assets")

    def positions(self, category: str) -> list[dict]:
        data = self.private("GET", "/api/v3/position/current-position", {"category": category})
        return _rows(data)

    def position_history(self, category: str, symbol: str, limit: int = 5) -> list[dict]:
        data = self.private("GET", "/api/v3/position/history-position",
                            {"category": category, "symbol": symbol, "limit": str(limit)})
        return _rows(data)

    def set_leverage(self, category: str, symbol: str, leverage: int) -> object:
        return self.private("POST", "/api/v3/account/set-leverage",
                            body={"category": category, "symbol": symbol, "leverage": str(leverage)})

    def set_hold_mode(self, hold_mode: str) -> object:
        return self.private("POST", "/api/v3/account/set-hold-mode", body={"holdMode": hold_mode})

    def place_order(self, order: dict) -> dict:
        return self.private("POST", "/api/v3/trade/place-order", body=order)

    def order_info(self, client_oid: str) -> dict | None:
        try:
            return self.private("GET", "/api/v3/trade/order-info", {"clientOid": client_oid})
        except BitgetError as e:
            if e.http_status == 400 or (e.code and e.code.startswith("4")):
                return None  # not found
            raise

    # ---- transport ----------------------------------------------------------

    def _send(self, method: str, path: str, *, params: dict | None = None, query: str = "",
              body: str = "", headers: dict) -> object:
        url = BASE_URL + path
        if params:
            query = urlencode(sorted(params.items()))
        if query:
            url += "?" + query
        try:
            resp = self._http.request(method, url, data=body or None, headers=headers, timeout=self._timeout)
        except requests.RequestException as e:
            # Deliberately omits headers from the message.
            raise BitgetError(f"{method} {path}: transport error {type(e).__name__}") from None
        try:
            payload = resp.json()
        except ValueError:
            raise BitgetError(f"{method} {path}: HTTP {resp.status_code} non-JSON body",
                              http_status=resp.status_code) from None
        code = str(payload.get("code", ""))
        if resp.status_code != 200 or code != "00000":
            raise BitgetError(f"{method} {path}: HTTP {resp.status_code} code={code} msg={payload.get('msg')}",
                              code=code or None, http_status=resp.status_code)
        return payload.get("data")
