import unittest

from slimon.agent import _for_model, worth_a_decision

WHITELIST = ["NVDAUSDT", "SP500USDT"]


def ev(etype="price_move", symbol="NVDAUSDT", payload=None):
    return {"id": f"evt-{etype}-{symbol}", "type": etype, "symbol": symbol, "payload": payload or {}}


class WorthADecision(unittest.TestCase):
    def test_no_events_never_calls(self):
        self.assertFalse(worth_a_decision([], WHITELIST, holding=False))
        self.assertFalse(worth_a_decision([], WHITELIST, holding=True))

    def test_watch_only_events_alone_are_skipped_when_flat(self):
        self.assertFalse(worth_a_decision([ev(symbol="MSTRUSDT"), ev("volume_spike", "CRCLUSDT")], WHITELIST, holding=False))

    def test_any_tradable_event_calls(self):
        self.assertTrue(worth_a_decision([ev(symbol="MSTRUSDT"), ev(symbol="NVDAUSDT")], WHITELIST, holding=False))

    def test_session_edge_calls(self):
        self.assertTrue(worth_a_decision([ev("us_regular_open", None)], WHITELIST, holding=False))

    def test_watch_only_event_still_calls_while_holding(self):
        # Crypto-proxy weakness can matter to a held position, so the model gets to see it.
        self.assertTrue(worth_a_decision([ev(symbol="MSTRUSDT")], WHITELIST, holding=True))


class ForModel(unittest.TestCase):
    def test_cross_section_is_not_sent_twice(self):
        e = ev("us_regular_close", None, {"cross_section": [{"symbol": "NVDAUSDT"}], "note": "kept"})
        sent = _for_model(e)
        self.assertNotIn("cross_section", sent["payload"])
        self.assertEqual(sent["payload"]["note"], "kept")
        self.assertIn("cross_section", e["payload"])  # the logged event is untouched

    def test_other_events_pass_through(self):
        e = ev(payload={"return_pct": 1.2})
        self.assertIs(_for_model(e), e)


if __name__ == "__main__":
    unittest.main()
