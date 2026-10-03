"""What AI Twitter/X is talking about, via AINews (part of Latent Space).

The X API is pay-per-use, but AINews already reads ~500 AI accounts daily and
writes an "AI Twitter Recap". Issues are paywalled after the opening, so we
parse only what the RSS item itself contains:
  * the issue headline (the editors' pick for the day's biggest story)
  * each recap topic: a bold heading followed by bullet points
"""

import re
from datetime import timedelta

import feedparser

from ..models import Item
from ..net import get_text
from ..utils import now, strip_html, to_datetime

FEED = "https://www.latent.space/feed"
# A topic heading is a paragraph that is *only* bold plain text.
TOPIC_HEADING = re.compile(r"<p><strong>([^<]{12,200})</strong></p>")


def _topics(html: str) -> list[tuple[str, str]]:
    """Return (heading, plain-text body) pairs from the Twitter recap."""
    start = html.find("AI Twitter Recap")
    if start == -1:
        return []
    recap = html[start:]
    matches = list(TOPIC_HEADING.finditer(recap))
    topics = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(recap)
        body = strip_html(recap[match.end():end], 450)
        if body:
            topics.append((strip_html(match.group(1)), body))
    return topics


def fetch(cfg: dict) -> list[Item]:
    c = cfg["ainews"]
    feed = feedparser.parse(get_text(FEED))
    cutoff = now() - timedelta(days=c["days"])

    issues = [e for e in feed.entries if e.title.startswith("[AINews]")]
    issues = [e for e in issues if (to_datetime(e.get("published_parsed")) or now()) >= cutoff]

    items = []
    for age_rank, entry in enumerate(issues):
        freshness = 1.0 if age_rank == 0 else 0.75   # today's issue outranks yesterday's
        published = to_datetime(entry.get("published_parsed"))
        html = entry.content[0].value if entry.get("content") else entry.get("summary", "")
        headline = entry.title.removeprefix("[AINews]").strip()

        # "not much happened today" is honest, but not a story.
        if "not much happened" not in headline.lower():
            intro = strip_html(html.split("<blockquote>")[0], 300)
            items.append(Item(source="ainews", title=headline, url=entry.link,
                              summary=intro, heat=freshness, published=published,
                              meta={"kind": "headline"}))

        for position, (heading, body) in enumerate(_topics(html)[: c["max_topics"]]):
            items.append(Item(source="ainews", title=heading, url=f"{entry.link}#topic-{position + 1}",
                              summary=body, heat=freshness * (0.9 - 0.08 * position),
                              published=published,
                              meta={"kind": "topic", "issue": headline}))
    return items
