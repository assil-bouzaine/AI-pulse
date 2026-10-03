"""The LLM's job: be the editor, not the researcher.

Code already found, de-duplicated and ranked the stories. The LLM gets a
compact numbered list and writes the parts code can't: the narrative, short
"why it matters" notes, themes and a must-read pick. One call per run.

Short story IDs ("s1", "s2"...) let the model refer to items cheaply and let
us attach its notes back to the right story without fuzzy matching.
"""

import re

from .llm import LLMError
from .models import SOURCE_LABELS, Item
from .utils import compact_number, shorten

SYSTEM_PROMPT = """You are the editor of "AI Pulse", a daily briefing for someone learning AI engineering.
Voice: a sharp, friendly senior AI engineer talking to a colleague over coffee. Concrete and
specific (name the models, tools, numbers). No hype words ("revolutionary", "game-changer"),
no filler, no emojis. Never invent facts that aren't in the stories.

Reply with ONLY a JSON object of this shape:
{
  "big_picture": "3-4 sentences: the day's main storyline(s) and how they connect. Mention specific items.",
  "themes": ["3 to 5 short lowercase tags, e.g. 'open-weight models'"],
  "notes": {"s1": "one sentence (max 25 words): what it is AND why an AI engineer should care", "...": "..."},
  "must_read": {"id": "the single best story for a learner today", "reason": "one sentence why"},
  "try_this": "one concrete hands-on thing to try this week based on today's stories (one sentence)"
}
Write a note for EVERY story id you are given. Never mention story ids (like "s3") in big_picture,
reasons or try_this: those are read by humans."""


def _signals(story: Item) -> str:
    m = story.meta
    parts = []
    if "points" in m:
        parts.append(f"{m['points']} points, {m['comments']} comments")
    if "per_day" in m:
        parts.append(f"{m['stars']} stars, +{m['per_day']:.0f}/day")
    if "upvotes" in m:
        parts.append(f"{m['upvotes']} upvotes")
    if "trending" in m:
        parts.append(f"{compact_number(m['likes'])} likes, {m['task']}")
    if m.get("all_experts"):
        parts.append("starred by " + ", ".join(m["all_experts"]))
    if "author" in m:
        parts.append(f"by {m['author']}")
    if "channel" in m:
        parts.append(f"YouTube video by {m['channel']}, {compact_number(m['views'])} views")
    others = sorted(SOURCE_LABELS[s][1] for s in story.sources - {story.source})
    if others:
        parts.append("ALSO ON " + ", ".join(others))
    return "; ".join(parts)


def build_prompt(stories: list[Item], max_items: int) -> str:
    lines = [f"Today's top {min(max_items, len(stories))} stories, best first:\n"]
    for story in stories[:max_items]:
        source = SOURCE_LABELS[story.source][1]
        summary = shorten(story.summary, 220)
        lines.append(f"[{story.id}] ({source}) {story.title}"
                     + (f" | {_signals(story)}" if _signals(story) else "")
                     + (f"\n    {summary}" if summary else ""))
    return "\n".join(lines)


def validate(data: dict) -> None:
    """Small models sometimes skip fields. Fail loudly so the next provider is tried."""
    if not isinstance(data.get("big_picture"), str) or len(data["big_picture"]) < 40:
        raise LLMError("missing or too-short big_picture")
    if not isinstance(data.get("notes"), dict) or len(data["notes"]) < 3:
        raise LLMError("missing notes")
    # Belt and braces: strip any "(s3)" / "(s7, s18)" ids that slipped into the prose.
    for key in ("big_picture", "try_this"):
        if isinstance(data.get(key), str):
            data[key] = re.sub(r"\s*\((?:s\d+[,\s]*)+\)", "", data[key])
    data.setdefault("themes", [])
    data.setdefault("try_this", "")
    if not isinstance(data.get("must_read"), dict):
        data["must_read"] = {}
