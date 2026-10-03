"""YouTube via each channel's public RSS feed: free, no API key, no quota.

    https://www.youtube.com/feeds/videos.xml?channel_id=UC...

The feed has the latest ~15 uploads with title, description, thumbnail and
view count. Channel IDs (not @handles) are what the feed needs; they're
stored in config.toml.

Ranking idea: "breakout ratio". Raw views would let a 3M-subscriber channel
win every day, so instead we compare each video's views/day with the
*same channel's* median views/day. A small channel's video doing 5x its
normal is a stronger signal than a big channel's average upload.
"""

import logging
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import feedparser

from ..models import Item
from ..net import get_text
from ..utils import log_heat, now, shorten, to_datetime
from .hackernews import AI_TITLE

log = logging.getLogger(__name__)
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def _views_per_day(entry) -> float:
    views = int(entry.get("media_statistics", {}).get("views", 0) or 0)
    published = to_datetime(entry.get("published_parsed"))
    age_days = max((now() - published).total_seconds() / 86400, 0.25) if published else 1
    return views / age_days


# Sentences that are ads, link lists or channel plumbing, not content.
NOISE = re.compile(
    r"sponsor|use code|promo|discount|free trial|for free|% off|first month|free \d+|"
    r"\btry \w+[’']s\b|\btry \w+ (and|for|free)|see what|want me to|great news\?|"
    r"patreon|merch|subscribe|follow me|my links|newsletter|discord|twitter|instagram|"
    r"tiktok|linkedin|socials?:|sources?:|timestamps|chapters|second channel|explore ai tools|"
    r"free credits?|credit card|\bsetup\b|resources from|_{3,}|-{3,}|"
    r"\b\d{1,2}:\d{2}\b",
    re.IGNORECASE)


def _clean_description(text: str) -> str:
    """Keep the first couple of sentences that actually describe the video."""
    text = re.sub(r"https?://\S+", "", text or "")
    # Split into sentences (and at line breaks / "label:" ends, where link lists live).
    pieces = re.split(r"(?<=[.!?])\s+|\n+|(?<=:)\s+", text)
    useful = [p.strip() for p in pieces if len(p.strip()) > 25 and not NOISE.search(p)]
    return shorten(" ".join(" ".join(useful[:2]).split()), 300)


def _read_channel(channel: dict, days: int, per_channel: int) -> list[Item]:
    feed = feedparser.parse(get_text(FEED.format(channel["id"])))
    if not feed.entries:
        raise RuntimeError("empty feed")
    videos = [e for e in feed.entries if "/shorts/" not in e.link]
    baseline = statistics.median(_views_per_day(e) for e in videos) or 1

    cutoff = now() - timedelta(days=days)
    items = []
    for entry in videos:
        published = to_datetime(entry.get("published_parsed"))
        if published is None or published < cutoff:
            continue
        description = _clean_description(entry.get("summary", ""))
        # General-tech channels (Fireship, Prime) also cover non-AI topics.
        if channel.get("ai_filter") and not AI_TITLE.search(f"{entry.title} {description}"):
            continue
        thumbnails = entry.get("media_thumbnail") or [{}]
        items.append(Item(
            source="youtube",
            title=entry.title,
            url=entry.link,
            summary=description,
            published=published,
            meta={"channel": channel["name"],
                  "views": int(entry.get("media_statistics", {}).get("views", 0) or 0),
                  "breakout": _views_per_day(entry) / baseline,
                  "thumbnail": thumbnails[0].get("url")},
        ))
    items.sort(key=lambda it: it.published, reverse=True)
    return items[:per_channel]


def fetch(cfg: dict) -> list[Item]:
    c = cfg["youtube"]

    def safe_read(channel: dict) -> list[Item]:
        try:
            return _read_channel(channel, c["days"], c["per_channel"])
        except Exception as exc:   # one dead channel never stops the others
            log.warning("youtube %s failed: %s", channel["name"], exc)
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        items = [item for result in pool.map(safe_read, c["channels"]) for item in result]
    if not items and c["channels"]:
        log.info("no recent AI videos in the last %s days", c["days"])
    for item, heat in zip(items, log_heat([it.meta["breakout"] for it in items])):
        item.heat = heat
    return items
