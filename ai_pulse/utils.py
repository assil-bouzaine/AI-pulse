"""Small helpers shared by the sources and the report."""

import html
import math
import re
from datetime import datetime, timezone
from time import struct_time
from urllib.parse import urlsplit


def now() -> datetime:
    return datetime.now(timezone.utc)


def strip_html(text: str, limit: int = 400) -> str:
    """Turn an HTML snippet into one line of plain text."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return shorten(text, limit)


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def log_heat(values: list[float]) -> list[float]:
    """Scale raw numbers (points, stars...) to 0..1 on a log curve.

    Log scale stops one viral 3,000-point post from flattening everything
    else to ~0.
    """
    top = max(values, default=0)
    if top <= 0:
        return [0.0 for _ in values]
    return [math.log1p(max(v, 0)) / math.log1p(top) for v in values]


def rank_heat(count: int) -> list[float]:
    """For feeds with no numbers (Reddit RSS): position 0 -> 1.0, last -> ~0.2."""
    if count <= 1:
        return [1.0] * count
    return [1.0 - 0.8 * i / (count - 1) for i in range(count)]


def normalize_url(url: str) -> str:
    """A stable key so the same link from two sources is recognised as one item."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host == "github.com":
        # github.com/owner/repo/tree/main/... -> github.com/owner/repo
        path = "/".join(path.split("/")[:3]).lower()
    if host == "news.ycombinator.com" and parts.query:
        path += "?" + parts.query   # item?id=... is the whole identity
    if host == "arxiv.org":
        path = re.sub(r"^/(abs|pdf)/", "/abs/", path).removesuffix(".pdf")
        path = re.sub(r"v\d+$", "", path)
    fragment = f"#{parts.fragment}" if parts.fragment else ""
    return host + path + fragment


def to_datetime(value) -> datetime | None:
    """Accept feedparser's struct_time, ISO strings or unix seconds."""
    try:
        if value is None:
            return None
        if isinstance(value, struct_time):
            return datetime(*value[:6], tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def time_ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    seconds = (now() - dt).total_seconds()
    if seconds < 3600:
        return f"{max(int(seconds // 60), 1)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def compact_number(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n:.0f}" if n == int(n) else f"{n:.1f}"
