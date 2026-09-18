import unittest

import requests

import slimon.bitget as bitget
from slimon.bitget import BitgetClient, BitgetError


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Replays a scripted sequence of responses/exceptions and records the calls."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout})
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


OK = FakeResponse(200, {"code": "00000", "data": [{"symbol": "NVDAUSDT", "lastPrice": "180"}]})


class PublicReads(unittest.TestCase):
    def setUp(self):
        self._sleep = bitget.time.sleep
        bitget.time.sleep = lambda s: None

    def tearDown(self):
        bitget.time.sleep = self._sleep

    def client(self, *outcomes) -> tuple[BitgetClient, FakeSession]:
        c = BitgetClient()
        c._http = FakeSession(*outcomes)
        return c, c._http

    def test_timeout_is_retried_until_it_succeeds(self):
        # The failure that cost four trades: the live ticker read timing out from a cloud runner.
        c, http = self.client(requests.ReadTimeout("read timed out"), requests.ConnectionError("reset"), OK)
        rows = c.tickers("USDT-FUTURES", venue="live")
        self.assertEqual(rows[0]["symbol"], "NVDAUSDT")
        self.assertEqual(len(http.calls), 3)

    def test_public_reads_get_the_longer_timeout(self):
        c, http = self.client(OK)
        c.tickers("USDT-FUTURES", venue="live")
        self.assertEqual(http.calls[0]["timeout"], bitget.PUBLIC_TIMEOUT)

    def test_demo_venue_sends_the_paptrading_header(self):
        c, http = self.client(OK)
        c.tickers("USDT-FUTURES", venue="demo")
        self.assertEqual(http.calls[0]["headers"].get("paptrading"), "1")
        c, http = self.client(OK)
        c.tickers("USDT-FUTURES", venue="live")
        self.assertNotIn("paptrading", http.calls[0]["headers"])

    def test_client_errors_are_not_retried(self):
        c, http = self.client(FakeResponse(400, {"code": "40001", "msg": "bad request"}))
        with self.assertRaises(BitgetError):
            c.tickers("USDT-FUTURES", venue="live")
        self.assertEqual(len(http.calls), 1)

    def test_persistent_failure_still_raises(self):
        c, http = self.client(*(requests.ReadTimeout("nope"),) * 3)
        with self.assertRaises(BitgetError):
            c.tickers("USDT-FUTURES", venue="live")
        self.assertEqual(len(http.calls), 3)


if __name__ == "__main__":
    unittest.main()
