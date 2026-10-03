"""Reddit via RSS: the JSON endpoints and self-service API are closed.

One combined feed (`r/A+B+C`) means a single request per run, which matters
because Reddit rate-limits per IP. RSS has no vote counts, but the `top`
feed is already sorted by score, so the position in the feed is the ranking.
"""

import re

import feedparser

from ..models import Item
from ..net import get_text
from ..utils import rank_heat, strip_html, to_datetime


def fetch(cfg: dict) -> list[Item]:
    c = cfg["reddit"]
    subs = "+".join(c["subreddits"])
    url = f"https://www.reddit.com/r/{subs}/top/.rss?t={c['period']}&limit={c['limit']}"
    # Reddit blocks generic user agents; a descriptive one is what they ask for.
    feed = feedparser.parse(get_text(url, headers={"User-Agent": c["user_agent"]}))
    if not feed.entries:
        raise RuntimeError("feed returned no entries (blocked or rate limited?)")

    items = []
    for entry, heat in zip(feed.entries, rank_heat(len(feed.entries))):
        subreddit = entry.tags[0]["term"] if entry.get("tags") else "reddit"
        text = strip_html(entry.get("summary", ""), 600)
        # Every entry ends with "submitted by /u/x [link] [comments]": drop it.
        text = re.sub(r"\s*submitted by /u/\S+.*$", "", text).strip()
        items.append(Item(
            source="reddit",
            title=entry.title,
            url=entry.link,
            summary=text[:300],
            heat=heat,
            published=to_datetime(entry.get("updated_parsed")),
            meta={"subreddit": subreddit},
        ))
    return items
