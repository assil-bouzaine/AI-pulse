"""Render the digest as Markdown.

Markdown because it reads well in three places at once: the terminal (via
`rich`), any editor, and GitHub/Obsidian if you keep your reports there.
"""

from dataclasses import dataclass
from datetime import datetime

from .models import Item, label
from .utils import compact_number, shorten, time_ago


@dataclass
class SourceResult:
    name: str
    items: list[Item]
    seconds: float
    error: str = ""


@dataclass
class Section:
    key: str
    emoji: str
    title: str
    intro: str
    stories: list[Item]


# (key, emoji, title, intro, sources, max items or None for the config default)
SECTIONS = [
    ("models", "🤖", "Models", "Trending on Hugging Face this week.", ("hf_models",), None),
    ("repos", "🛠️", "Rising Repos", "New this week, ranked by stars gained per day.", ("github",), None),
    ("launches", "🚀", "Launches", "Tools people built and shipped (Show HN).", ("show_hn",), 4),
    ("papers", "📄", "Papers", "Top Hugging Face Daily Papers by upvotes.", ("hf_papers",), 5),
    ("community", "💬", "Community", "Hottest AI threads on HN and Reddit.", ("hackernews", "reddit"), None),
    ("videos", "🎥", "YouTube", "Latest from AI & dev creators, ranked by how much each video beats its channel's usual views.", ("youtube",), 8),
    ("x", "🐦", "Heard on X", "Via the AINews Twitter recap.", ("ainews",), 5),
    ("posts", "✍️", "Expert Posts", "Fresh writing from respected AI engineers.", ("blogs",), 6),
    ("starred", "⭐", "Expert Stars", "Repos trusted engineers starred this week.", ("github_experts",), 6),
]


def organize(stories: list[Item], cfg: dict) -> tuple[list[Item], list[Section]]:
    """Split ranked stories into the Top N plus one list per section.

    Both the Markdown and the HTML renderers use this, so they always agree.
    Top stories are left out of the sections to avoid showing them twice.
    """
    g = cfg["general"]
    # Diversity: at most N per source in the Top, or HN alone can fill it.
    top, per_source = [], {}
    for story in stories:
        if per_source.get(story.source, 0) < g["top_max_per_source"]:
            top.append(story)
            per_source[story.source] = per_source.get(story.source, 0) + 1
        if len(top) == g["top_n"]:
            break
    shown = {s.id for s in top}
    sections = []
    for key, emoji, title, intro, sources, limit in SECTIONS:
        chosen = [s for s in stories if s.source in sources and s.id not in shown]
        chosen = chosen[: limit or g["per_section"]]
        if key == "repos":
            chosen.sort(key=lambda s: s.meta.get("per_day", 0), reverse=True)
        if key == "starred":
            chosen.sort(key=lambda s: len(s.meta["experts"]), reverse=True)
        if chosen:
            sections.append(Section(key, emoji, title, intro, chosen))
    return top, sections


def _md(text: str) -> str:
    """Stop titles like `[R] foo | bar` from breaking links or tables."""
    return text.replace("[", "(").replace("]", ")").replace("|", "/").replace("\n", " ")


def _meta_line(story: Item) -> str:
    m = story.meta
    bits = [label(story.source)]
    if "points" in m:
        bits.append(f"▲ {m['points']} · 💬 {m['comments']} · [thread]({m['discussion']})")
    if "subreddit" in m:
        bits.append(f"r/{m['subreddit']}")
    if "per_day" in m:
        bits.append(f"⭐ {compact_number(m['stars'])} (+{compact_number(m['per_day'])}/day)")
    elif "stars" in m:
        bits.append(f"⭐ {compact_number(m['stars'])}")
    if "upvotes" in m:
        bits.append(f"▲ {m['upvotes']} upvotes")
    if "trending" in m:
        bits.append(f"❤️ {compact_number(m['likes'])} · {m['task']}")
    if "author" in m:
        bits.append(f"by **{m['author']}**")
    if "channel" in m:
        bits.append(f"**{m['channel']}** · 👁 {compact_number(m['views'])} views")
    if m.get("all_experts"):
        bits.append("👀 starred by " + ", ".join(f"@{e}" for e in m["all_experts"]))
    if story.published:
        bits.append(time_ago(story.published))
    others = story.sources - {story.source}
    if others:
        bits.append("🔗 also on " + ", ".join(label(s) for s in sorted(others)))
    if story.is_new:
        bits.append("🆕")
    return " · ".join(bits)


def _note(story: Item, notes: dict) -> str:
    return notes.get(story.id) or shorten(story.summary, 180)


def _card(story: Item, notes: dict, heading: str = "", simple: dict | None = None) -> list[str]:
    """A story as a big card (with `heading`, used for the Top N) or a list entry.

    `simple` holds the 5-year-old explanations (🧸). A trailing backslash is a
    Markdown hard line break.
    """
    link = f"[{_md(story.title)}]({story.url})"
    note = _md(_note(story, notes))
    eli5 = _md((simple or {}).get(story.id, ""))
    if heading:
        lines = [f"{heading}{link}", _meta_line(story)]
        lines += ["", f"> {note}"] if note else []
        return lines + ([">", f"> 🧸 _{eli5}_"] if eli5 else [])
    lines = [f"- **{link}** \\", f"  {_meta_line(story)}" + (" \\" if note or eli5 else "")]
    lines += [f"  _{note}_" + (" \\" if eli5 else "")] if note else []
    return lines + ([f"  🧸 {eli5}"] if eli5 else [])


def _section(title: str, intro: str, stories: list[Item], notes: dict,
             simple: dict) -> list[str]:
    if not stories:
        return []
    out = ["", f"## {title}", f"_{intro}_", ""]
    for story in stories:
        out += _card(story, notes, simple=simple)
    return out


def render(stories: list[Item], results: list[SourceResult], digest: dict | None,
           writer: str, cfg: dict, elapsed: float) -> str:
    notes = (digest or {}).get("notes", {})
    simple = (digest or {}).get("simple", {})
    by_id = {s.id: s for s in stories}
    top, section_list = organize(stories, cfg)
    sections = {sec.key: sec.stories for sec in section_list}

    today = datetime.now().strftime("%A, %B %d %Y").replace(" 0", " ")
    total = sum(len(r.items) for r in results)
    ok = sum(1 for r in results if not r.error)
    out = [
        f"# ⚡ AI Pulse — {today}",
        f"> {total} items from {ok}/{len(results)} sources → **{len(stories)} distinct stories** "
        f"in {elapsed:.1f}s · edited by `{writer}`",
    ]

    # --- The editor's take ---
    if digest:
        out += ["", "## 🔥 The Big Picture", "", digest["big_picture"]]
        if digest.get("big_picture_simple"):
            out += ["", f"> 🧸 **In simple words:** {digest['big_picture_simple']}"]
        if digest.get("themes"):
            out += ["", "**Today's themes:** " + " · ".join(f"`{t}`" for t in digest["themes"][:5])]
        if digest.get("glossary"):
            out += ["", "**📖 Words of the day**", ""]
            out += [f"- **{term}**: {meaning}" for term, meaning in list(digest["glossary"].items())[:6]]
    else:
        out += ["", "> ⚠️ No LLM was available, so this is the raw ranking without commentary. "
                    "Add a key to `.env` or start Ollama for the full briefing."]

    # --- Top N, as big cards ---
    out += ["", f"## 🏆 Top {len(top)} Right Now", ""]
    for rank, story in enumerate(top, start=1):
        out += _card(story, notes, heading=f"### {rank}. ", simple=simple)
        out.append("")

    # --- Browse by type ---
    models = sections.get("models", [])
    if models:
        out += ["", "## 🤖 Models Trending on Hugging Face",
                "_What people are downloading and liking this week._", "",
                "| Model | Task | ❤️ Likes | Why look |", "|---|---|---:|---|"]
        for s in models:
            out.append(f"| [{_md(s.title)}]({s.url}) | {s.meta['task']} | "
                       f"{compact_number(s.meta['likes'])} | {_md(shorten(_note(s, notes), 90))} |")

    repos = sections.get("repos", [])
    if repos:
        out += ["", "## 🛠️ Rising Repos",
                "_New this week, ranked by stars gained per day._", "",
                "| Repo | ⭐ Stars | 📈 Per day | What it is |", "|---|---:|---:|---|"]
        for s in repos:
            out.append(f"| [{_md(s.title)}]({s.url}){' 🆕' if s.is_new else ''} | "
                       f"{compact_number(s.meta['stars'])} | +{compact_number(s.meta['per_day'])} | "
                       f"{_md(shorten(_note(s, notes), 90))} |")

    out += _section("🚀 Fresh Launches (Show HN)", "Tools people built and shipped this week.",
                    sections.get("launches", []), notes, simple)
    out += _section("📄 Papers Worth Your Time", "Top of Hugging Face Daily Papers by upvotes.",
                    sections.get("papers", []), notes, simple)
    out += _section("💬 What the Community Is Debating", "Hottest AI threads on HN and Reddit.",
                    sections.get("community", []), notes, simple)
    out += _section("🎥 On YouTube", "Latest videos from AI & dev creators.",
                    sections.get("videos", []), notes, simple)
    out += _section("🐦 Heard on X", "Via the AINews Twitter recap (latest issues).",
                    sections.get("x", []), notes, simple)

    # --- Expert corner: what respected engineers write and star ---
    blog_posts = sections.get("posts", [])
    expert_repos = sections.get("starred", [])
    if blog_posts or expert_repos:
        out += ["", "## 🧠 Expert Corner", "_What respected AI engineers are writing and starring._"]
        if blog_posts:
            out += ["", "**✍️ Fresh posts**", ""]
            for s in blog_posts:
                out += _card(s, notes, simple=simple)
        if expert_repos:
            out += ["", "**⭐ Starred this week**", ""]
            for s in expert_repos:
                who = ", ".join(f"@{e}" for e in s.meta["experts"])
                out.append(f"- **[{_md(s.title)}]({s.url})** · ⭐ {compact_number(s.meta['stars'])}"
                           f" · 👀 {who}")
                if s.summary:
                    out.append(f"  _{_md(shorten(s.summary, 140))}_")

    # --- Takeaways ---
    if digest:
        must = digest.get("must_read", {})
        story = by_id.get(str(must.get("id", "")))
        if story or digest.get("try_this"):
            out += ["", "## 🎯 Your Move"]
            if story:
                out += ["", f"**📌 If you read one thing:** [{_md(story.title)}]({story.url})",
                        f"> {_md(must.get('reason', ''))}"]
            if digest.get("try_this"):
                out += ["", f"**🧪 Try this week:** {digest['try_this']}"]

    # --- Source health, so a silent failure never goes unnoticed ---
    out += ["", "---", "", "## 📡 Source Health", "",
            "| Source | Status | Items | Time |", "|---|---|---:|---:|"]
    for r in results:
        status = f"❌ {_md(shorten(r.error, 70))}" if r.error else "✅"
        out.append(f"| {label(r.name)} | {status} | {len(r.items)} | {r.seconds:.1f}s |")
    out.append("")
    return "\n".join(out)
