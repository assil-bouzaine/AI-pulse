"""Expert blogs via RSS/Atom. `feedparser` handles both formats.

The feeds are fetched in parallel (each one is a slow-ish network call), and
a broken feed is logged and skipped, never fatal.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import feedparser

from ..models import Item
from ..net import get_text
from ..utils import now, strip_html, to_datetime

log = logging.getLogger(__name__)


def _read_feed(feed: dict, days: int, per_blog: int) -> list[Item]:
    parsed = feedparser.parse(get_text(feed["url"]))
    cutoff = now() - timedelta(days=days)
    items = []
    for entry in parsed.entries:
        published = to_datetime(entry.get("published_parsed") or entry.get("updated_parsed"))
        if published is None or published < cutoff:
            continue
        age_days = (now() - published).total_seconds() / 86400
        items.append(Item(
            source="blogs",
            title=entry.get("title") or "(untitled)",
            url=entry.link,
            summary=strip_html(entry.get("summary", ""), 300),
            heat=max(1.0 - age_days / days, 0.1),   # newer posts are hotter
            published=published,
            meta={"author": feed["name"]},
        ))
    items.sort(key=lambda item: item.published, reverse=True)
    return items[:per_blog]


def fetch(cfg: dict) -> list[Item]:
    c = cfg["blogs"]

    def safe_read(feed: dict) -> list[Item]:
        try:
            return _read_feed(feed, c["days"], c["per_blog"])
        except Exception as exc:
            log.warning("blog %s failed: %s", feed["name"], exc)
            return []

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(safe_read, c["feeds"]))
    return [item for items in results for item in items]
