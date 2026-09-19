"""News perception: public headlines turned into timestamped events, like any other signal.

Sources are free public RSS feeds that need no key: Google News searches per traded company, the
Federal Reserve's press releases, and CNBC's markets feed. Each new headline becomes a `news`
event carrying its publisher, publication time and the moment it was received, so the log shows
exactly when the agent learned of it.

Three safeguards, because a headline is the least reliable input the agent has:

- Relevance: a per-company headline must name the company or its ticker; general-market headlines
  must mention a market-moving topic. Feeds carry a lot of loosely related items.
- Market confirmation: each event lists the price, range and volume shocks seen on its symbol in
  the same tick. A headline the market has not reacted to is weak evidence, and the model is told so.
- Untrusted text: headlines are cleaned and truncated, and the model is instructed to treat them
  as data, never as instructions. The risk gate applies to anything a headline provokes.

It cannot see what no public feed carries: a post on X or Truth Social reaches it only when a news
outlet reports it, or as the price move that follows.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from .journal import iso

USER_AGENT = "Mozilla/5.0 (compatible; slimon-agent/1.0; +https://github.com/JohnboscoE/slimon)"
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}+when:1d&hl=en-US&gl=US&ceid=US:en"
HEADLINE_CHARS = 200
SEEN_KEEP = 800


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")          # stray markup
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)         # control characters
    return re.sub(r"\s+", " ", text).strip()[:HEADLINE_CHARS]


def parse_rss(xml_bytes: bytes) -> list[dict]:
    """Items as {title, link, published, publisher}. Unparseable items are dropped, not guessed."""
    out = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        pub = item.findtext("pubDate")
        if not title or not pub:
            continue
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        publisher = _clean(item.findtext("source") or "")
        # Google News appends " - Publisher" to the title; keep the headline itself clean.
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        out.append({"title": title, "link": (item.findtext("link") or "").strip(),
                    "published": published, "publisher": publisher})
    return out


def _item_id(title: str) -> str:
    # By headline, not link: the same story arrives through several feeds with different links.
    return hashlib.sha1(re.sub(r"\W+", " ", title.lower()).strip().encode()).hexdigest()[:12]


def _mentions(title: str, terms: list[str]) -> bool:
    t = title.lower()
    return any(re.search(rf"\b{re.escape(term.lower())}\b", t) for term in terms if term)


class NewsFeed:
    def __init__(self, cfg: dict, state, fetch=None):
        self.cfg = cfg
        self.state = state
        self._fetch = fetch or self._http_get
        self._http = requests.Session()

    def _http_get(self, url: str) -> bytes:
        r = self._http.get(url, headers={"User-Agent": USER_AGENT}, timeout=12)
        r.raise_for_status()
        return r.content

    def _sources(self, symbols: list[str]) -> list[dict]:
        out = []
        queries = self.cfg.get("symbol_queries", {})
        for sym in symbols:
            q = queries.get(sym)
            if q:
                terms = [t.strip() for t in q.split(" OR ")] + [sym.removesuffix("USDT")]
                out.append({"name": f"google_news:{sym}", "url": GOOGLE_NEWS.format(q=quote_plus(f"{q} stock")),
                            "symbol": sym, "terms": terms})
        for feed in self.cfg.get("macro_feeds", []):
            out.append({"name": feed["name"], "url": feed["url"], "symbol": None,
                        "keywords": feed.get("keywords")})
        return out

    def poll(self, now: datetime, session: str, symbols: list[str], held: set[str],
             market_events: list[dict]) -> tuple[list[dict], dict]:
        """New, relevant headlines as events, most important first, plus a status record for the log."""
        max_age = timedelta(minutes=self.cfg.get("max_age_minutes", 30))
        seen: list = self.state.get("news_seen", [])
        seen_set = set(seen)
        sources = self._sources(symbols)
        status = {"feeds": len(sources), "failed": [], "items_read": 0, "new": 0}

        def read(src):
            try:
                return src, parse_rss(self._fetch(src["url"])), None
            except Exception as e:  # a feed being down must never cost a tick
                return src, [], f"{src['name']}: {type(e).__name__}"

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(read, sources))

        candidates = []
        for src, items, err in results:
            if err:
                status["failed"].append(err)
                continue
            status["items_read"] += len(items)
            for it in items:
                age = now - it["published"]
                if age > max_age or age < timedelta(minutes=-5):
                    continue
                if src["symbol"] and not _mentions(it["title"], src["terms"]):
                    continue
                if src["symbol"] is None and src.get("keywords") and not _mentions(it["title"], src["keywords"]):
                    continue
                iid = _item_id(it["title"])
                if iid in seen_set:
                    continue
                seen_set.add(iid)
                seen.append(iid)
                candidates.append((src, it, iid))
        del seen[:-SEEN_KEEP]

        # Held positions first (they may need closing), then tradable names, then the wider market.
        def rank(c):
            sym = c[0]["symbol"]
            return (0 if sym in held else 1 if sym else 2, -c[1]["published"].timestamp())
        candidates.sort(key=rank)
        per_symbol: dict = {}
        kept = []
        for c in candidates:
            sym = c[0]["symbol"]
            if per_symbol.get(sym, 0) < self.cfg.get("max_per_symbol", 2):
                per_symbol[sym] = per_symbol.get(sym, 0) + 1
                kept.append(c)
        candidates = kept[: self.cfg.get("max_events_per_tick", 5)]
        status["new"] = len(candidates)

        shocks: dict[str, list[str]] = {}
        for e in market_events:
            if e.get("symbol") and e.get("type") in ("price_move", "range_expansion", "volume_spike"):
                shocks.setdefault(e["symbol"], []).append(e["summary"])

        events = []
        for src, it, iid in candidates:
            sym = src["symbol"]
            confirm = shocks.get(sym, []) if sym else []
            subject = sym.removesuffix("USDT") if sym else "Market"
            by = f" ({it['publisher']})" if it["publisher"] else ""
            events.append({
                "id": f"evt-news-{sym or 'mkt'}-{iid}",
                "type": "news",
                "symbol": sym,
                "received_at": iso(now),
                "source_ts": iso(it["published"]),
                "session": session,
                "summary": f"{subject} news{by}: {it['title']}",
                "payload": {
                    "headline": it["title"], "publisher": it["publisher"] or None, "url": it["link"],
                    "feed": src["name"], "published_at": iso(it["published"]),
                    "age_minutes": round((now - it["published"]).total_seconds() / 60, 1),
                    "held_position": bool(sym and sym in held),
                    "market_confirmation": confirm,
                },
            })
        return events, status
