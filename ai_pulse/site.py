"""Render the digest as a small, self-contained website (one HTML file).

Design choices:
  * One file, no CDN fonts or JS frameworks: opens instantly, works offline,
    and you could host it anywhere (e.g. GitHub Pages) as-is.
  * Jinja2 templates with autoescaping: titles come from the internet, so a
    Reddit post titled "<script>..." must render as text, never run as code.
  * Python prepares a simple "view model" (plain dicts with ready-to-show
    strings), so the template stays dumb and readable: no logic in HTML.
"""

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import SOURCE_LABELS, Item
from .report import SourceResult, organize
from .utils import compact_number, shorten, time_ago

TEMPLATES = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]),
                  trim_blocks=True, lstrip_blocks=True)


def _stat(story: Item) -> tuple[str, str]:
    """The one number that matters most for this kind of item: (value, label)."""
    m = story.meta
    if "per_day" in m:
        return f"+{compact_number(m['per_day'])}", "stars/day"
    if "points" in m:
        return str(m["points"]), "points"
    if "upvotes" in m:
        return str(m["upvotes"]), "upvotes"
    if "trending" in m:
        return compact_number(m["likes"]), "likes"
    if "views" in m:
        return compact_number(m["views"]), "views"
    if "experts" in m:
        return str(len(m["experts"])), "expert" + ("s" if len(m["experts"]) > 1 else "")
    return "", ""


def _details(story: Item) -> list[str]:
    """Small secondary facts shown as a muted line under the title."""
    m = story.meta
    bits = []
    if "subreddit" in m:
        bits.append(f"r/{m['subreddit']}")
    if "comments" in m and "points" in m:
        bits.append(f"{m['comments']} comments")
    if "stars" in m:
        bits.append(f"★ {compact_number(m['stars'])}")
    if m.get("language"):
        bits.append(m["language"])
    if "task" in m:
        bits.append(m["task"])
    if "author" in m:
        bits.append(m["author"])
    if "channel" in m:
        bits.append(m["channel"])
    if m.get("breakout", 0) >= 1.5:
        bits.append(f"🔥 {m['breakout']:.1f}× its usual views")
    if m.get("issue"):
        bits.append(f"AINews: {shorten(m['issue'], 50)}")
    if m.get("all_experts"):
        bits.append("starred by " + ", ".join(f"@{e}" for e in m["all_experts"]))
    if story.published:
        bits.append(time_ago(story.published))
    return bits


def _view(story: Item, notes: dict, simple: dict) -> dict:
    value, unit = _stat(story)
    return {
        "id": story.id,
        "title": story.title,
        "url": story.url,
        "note": notes.get(story.id) or shorten(story.summary, 200),
        "simple": simple.get(story.id, ""),   # the 🧸 explain-like-I'm-5 version
        "source": story.source,
        "source_label": SOURCE_LABELS[story.source][1],
        "emoji": SOURCE_LABELS[story.source][0],
        "also_on": [SOURCE_LABELS[s][1] for s in sorted(story.sources - {story.source})],
        "discussion": story.meta.get("discussion"),
        "details": _details(story),
        "stat": value,
        "stat_unit": unit,
        "is_new": story.is_new,
        "thumbnail": story.meta.get("thumbnail"),
    }


def render(stories: list[Item], results: list[SourceResult], digest: dict | None,
           writer: str, cfg: dict, elapsed: float) -> str:
    notes = (digest or {}).get("notes", {})
    simple = (digest or {}).get("simple", {})
    top, sections = organize(stories, cfg)
    by_id = {s.id: s for s in stories}
    must = (digest or {}).get("must_read", {})
    must_story = by_id.get(str(must.get("id", "")))

    return env.get_template("report.html").render(
        date=datetime.now().strftime("%A, %B %d").replace(" 0", " "),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        digest=digest,
        writer=writer,
        elapsed=f"{elapsed:.0f}",
        total_items=sum(len(r.items) for r in results),
        story_count=len(stories),
        sources_ok=sum(1 for r in results if not r.error),
        sources_total=len(results),
        top=[_view(s, notes, simple) for s in top],
        sections=[{"key": sec.key, "emoji": sec.emoji, "title": sec.title, "intro": sec.intro,
                   "stories": [_view(s, notes, simple) for s in sec.stories]} for sec in sections],
        must_read=_view(must_story, notes, simple) | {"reason": must.get("reason", "")} if must_story else None,
        try_this=(digest or {}).get("try_this", ""),
        glossary=list((digest or {}).get("glossary", {}).items())[:6],
        health=[{"label": f"{SOURCE_LABELS[r.name][0]} {SOURCE_LABELS[r.name][1]}",
                 "count": len(r.items), "seconds": f"{r.seconds:.1f}",
                 "error": shorten(r.error, 120)} for r in results],
    )
