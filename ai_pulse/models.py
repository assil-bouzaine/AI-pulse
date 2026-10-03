"""The one data shape every source produces.

Keeping a single `Item` type means ranking, de-duplication, the LLM prompt and
the report never need to know which website an item came from.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Item:
    source: str            # registry name, e.g. "hackernews", "hf_papers"
    title: str
    url: str
    summary: str = ""
    heat: float = 0.0      # 0..1, how hot this item is *within its own source*
    published: datetime | None = None
    meta: dict = field(default_factory=dict)   # source-specific numbers (points, stars...)

    # Filled in later by the ranking step.
    id: str = ""
    score: float = 0.0
    is_new: bool = True
    also_on: list["Item"] = field(default_factory=list)   # same story, other sources

    @property
    def sources(self) -> set[str]:
        return {self.source} | {other.source for other in self.also_on}


# Emoji + human label per source, used by the report and the LLM prompt.
SOURCE_LABELS = {
    "hackernews": ("🟠", "Hacker News"),
    "show_hn": ("🟠", "Show HN"),
    "reddit": ("🔴", "Reddit"),
    "ainews": ("🐦", "AINews (X recap)"),
    "github": ("🐙", "GitHub"),
    "github_experts": ("⭐", "Expert stars"),
    "hf_models": ("🤗", "HF Models"),
    "hf_papers": ("📄", "HF Papers"),
    "blogs": ("✍️", "Expert blogs"),
    "youtube": ("🎥", "YouTube"),
}


def label(source: str) -> str:
    emoji, name = SOURCE_LABELS.get(source, ("•", source))
    return f"{emoji} {name}"
