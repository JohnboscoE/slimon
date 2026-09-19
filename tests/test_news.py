import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from slimon.agent import worth_a_decision
from slimon.news import NewsFeed, parse_rss

NOW = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)

CFG = {
    "max_age_minutes": 30,
    "max_events_per_tick": 5,
    "symbol_queries": {"NVDAUSDT": "Nvidia", "TSLAUSDT": "Tesla"},
    "macro_feeds": [{"name": "federal_reserve", "url": "https://fed.example/rss", "keywords": ["FOMC", "interest rate"]}],
}


def rss(*items) -> bytes:
    body = "".join(
        f"<item><title>{t}</title><link>https://news.example/{i}</link>"
        f"<pubDate>{format_datetime(NOW - timedelta(minutes=age))}</pubDate>"
        f"{f'<source>{src}</source>' if src else ''}</item>"
        for i, (t, age, src) in enumerate(items))
    return f"<rss><channel>{body}</channel></rss>".encode()


class StubState:
    def __init__(self):
        self.data = {}

    def get(self, key, default):
        return self.data.setdefault(key, default)


def feed(pages: dict, state=None):
    """pages: url substring -> RSS bytes, or an Exception to raise."""
    def fetch(url):
        for key, page in pages.items():
            if key in url:
                if isinstance(page, Exception):
                    raise page
                return page
        return rss()
    return NewsFeed(CFG, state or StubState(), fetch=fetch)


class Parsing(unittest.TestCase):
    def test_publisher_suffix_is_stripped_from_google_titles(self):
        items = parse_rss(rss(("Nvidia beats estimates - Reuters", 5, "Reuters")))
        self.assertEqual(items[0]["title"], "Nvidia beats estimates")
        self.assertEqual(items[0]["publisher"], "Reuters")

    def test_markup_and_control_characters_are_cleaned_and_length_capped(self):
        items = parse_rss(rss(("Nvidia &lt;b&gt;soars&lt;/b&gt; " + "x" * 400, 5, None)))
        self.assertNotIn("<b>", items[0]["title"])
        self.assertLessEqual(len(items[0]["title"]), 200)


class Polling(unittest.TestCase):
    def poll(self, nf, held=frozenset(), market_events=()):
        return nf.poll(NOW, "regular", ["NVDAUSDT", "TSLAUSDT"], set(held), list(market_events))

    def test_a_fresh_relevant_headline_becomes_an_event(self):
        nf = feed({"Nvidia": rss(("Nvidia raises guidance on data-center demand - Reuters", 4, "Reuters"))})
        events, status = self.poll(nf)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e["type"], e["symbol"]), ("news", "NVDAUSDT"))
        self.assertTrue(e["id"].startswith("evt-news-NVDAUSDT-"))
        self.assertEqual(e["payload"]["publisher"], "Reuters")
        self.assertEqual(e["source_ts"], (NOW - timedelta(minutes=4)).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        self.assertEqual(status["new"], 1)

    def test_headlines_that_do_not_name_the_company_are_dropped(self):
        nf = feed({"Nvidia": rss(("Three chip stocks to buy this week", 4, None))})
        self.assertEqual(self.poll(nf)[0], [])

    def test_stale_headlines_are_dropped(self):
        nf = feed({"Nvidia": rss(("Nvidia shares slip", 45, None))})
        self.assertEqual(self.poll(nf)[0], [])

    def test_the_same_story_is_reported_once(self):
        state = StubState()
        page = {"Nvidia": rss(("Nvidia shares slip", 4, None))}
        self.assertEqual(len(self.poll(feed(page, state))[0]), 1)
        self.assertEqual(self.poll(feed(page, state))[0], [])

    def test_market_confirmation_lists_same_symbol_shocks(self):
        shock = {"type": "price_move", "symbol": "NVDAUSDT", "summary": "NVDAUSDT -1.80% over 30m on the live venue"}
        nf = feed({"Nvidia": rss(("Nvidia faces export curbs", 3, None))})
        events, _ = self.poll(nf, market_events=[shock])
        self.assertEqual(events[0]["payload"]["market_confirmation"], [shock["summary"]])

    def test_held_positions_come_first_and_are_flagged(self):
        nf = feed({"Nvidia": rss(("Nvidia gains", 2, None)), "Tesla": rss(("Tesla recalls vehicles", 10, None))})
        events, _ = self.poll(nf, held={"TSLAUSDT"})
        self.assertEqual(events[0]["symbol"], "TSLAUSDT")
        self.assertTrue(events[0]["payload"]["held_position"])
        self.assertFalse(events[1]["payload"]["held_position"])

    def test_macro_feed_needs_a_market_moving_keyword(self):
        nf = feed({"fed.example": rss(("FOMC statement: interest rate held", 5, None),
                                     ("Board announces staff appointment", 5, None))})
        events, _ = self.poll(nf)
        self.assertEqual([e["symbol"] for e in events], [None])
        self.assertIn("FOMC", events[0]["summary"])

    def test_a_feed_that_is_down_is_recorded_not_fatal(self):
        nf = feed({"Nvidia": ConnectionError("down"), "Tesla": rss(("Tesla shares jump", 3, None))})
        events, status = self.poll(nf)
        self.assertEqual([e["symbol"] for e in events], ["TSLAUSDT"])
        self.assertEqual(len(status["failed"]), 1)

    def test_one_busy_symbol_cannot_crowd_out_the_rest(self):
        many = rss(*((f"Nvidia headline number {i}", 2, None) for i in range(12)))
        events, _ = self.poll(feed({"Nvidia": many, "Tesla": rss(("Tesla shares jump", 20, None))}))
        self.assertEqual([e["symbol"] for e in events].count("NVDAUSDT"), 2)
        self.assertIn("TSLAUSDT", [e["symbol"] for e in events])

    def test_events_per_tick_are_capped(self):
        cfg = {**CFG, "max_per_symbol": 99}
        many = rss(*((f"Nvidia headline number {i}", 2, None) for i in range(12)))
        nf = NewsFeed(cfg, StubState(), fetch=lambda url: many if "Nvidia" in url else rss())
        self.assertEqual(len(nf.poll(NOW, "regular", ["NVDAUSDT"], set(), [])[0]), 5)


class NewsTriggersDecisions(unittest.TestCase):
    WL = ["NVDAUSDT", "TSLAUSDT"]

    def test_news_on_a_tradable_name_calls_the_model(self):
        self.assertTrue(worth_a_decision([{"type": "news", "symbol": "NVDAUSDT"}], self.WL, holding=False))

    def test_market_wide_news_calls_the_model(self):
        self.assertTrue(worth_a_decision([{"type": "news", "symbol": None}], self.WL, holding=False))

    def test_news_while_holding_always_calls_the_model(self):
        self.assertTrue(worth_a_decision([{"type": "news", "symbol": "MSTRUSDT"}], self.WL, holding=True))


if __name__ == "__main__":
    unittest.main()
