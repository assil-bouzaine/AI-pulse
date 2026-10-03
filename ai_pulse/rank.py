"""Turn ~200 raw items into a ranked list of distinct stories.

    score = heat (0..1 within its source) x source weight
          + cross_source_bonus x (number of other sources covering it)
          + expert_bonus if 2+ trusted engineers starred it

Step 1 merges exact duplicates (same normalised URL).
Step 2 merges *semantic* duplicates using embeddings: "Qwen 4 released" on
Reddit and "Qwen4 tech report" on HN land close together in vector space.
We only merge items from *different* sources, so two distinct papers about
similar topics stay separate.
"""

import logging
import re

import numpy as np

from .models import Item
from .net import request
from .utils import normalize_url

log = logging.getLogger(__name__)


def embed(texts: list[str], cfg: dict) -> np.ndarray | None:
    """One batched call to Ollama. Returns None if Ollama isn't available."""
    try:
        response = request("POST", f"{cfg['llm']['ollama_url']}/api/embed", timeout=90,
                           retries=1, json={"model": cfg["ranking"]["embed_model"],
                                            "input": texts})
        vectors = np.array(response.json()["embeddings"], dtype=np.float32)
    except Exception as exc:
        log.warning("embeddings unavailable (%s), using URL de-duplication only", exc)
        return None
    # Normalise once so a dot product *is* the cosine similarity.
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _merge_same_urls(items: list[Item]) -> list[Item]:
    leaders: dict[str, Item] = {}
    for item in items:   # items arrive sorted best-first, so the leader is the best copy
        key = normalize_url(item.url)
        if key in leaders:
            leaders[key].also_on.append(item)
        else:
            leaders[key] = item
    return list(leaders.values())


def _embedding_text(item: Item) -> str:
    """Titles only: summaries add generic words ("AI", "model", "agents") that make
    unrelated items look alike. Measured on real data: true duplicates scored
    0.85+, merely-related topics 0.78-0.82."""
    title = item.title
    if item.source == "hf_models":
        title = title.split("/", 1)[-1]           # "Qwen/Qwen3.8-27B" -> "Qwen3.8-27B"
    title = re.sub(r"\s*·\s*Hugging Face.*$", "", title)   # Reddit link-post suffix
    # nomic-embed-text was trained with task prefixes; "clustering:" fits here.
    return f"clustering: {title}"


def _can_merge(item: Item) -> bool:
    # AINews topic headings ("Inference, Hardware and Systems") summarise many
    # stories at once, so they'd match everything. Keep them standalone.
    return item.meta.get("kind") != "topic"


def _merge_similar(items: list[Item], cfg: dict) -> list[Item]:
    vectors = embed([_embedding_text(it) for it in items], cfg)
    if vectors is None:
        return items

    threshold = cfg["ranking"]["similarity"]
    kept: list[Item] = []
    kept_rows: list[int] = []
    for row, item in enumerate(items):
        if kept_rows and _can_merge(item):
            sims = vectors[kept_rows] @ vectors[row]
            best = int(np.argmax(sims))
            leader = kept[best]
            if (sims[best] >= threshold and _can_merge(leader)
                    and not (item.sources & leader.sources)):
                leader.also_on += [item, *item.also_on]
                item.also_on = []
                continue
        kept.append(item)
        kept_rows.append(row)
    return kept


def rank(items: list[Item], cfg: dict, use_embeddings: bool = True) -> list[Item]:
    r = cfg["ranking"]
    for item in items:
        item.score = item.heat * r["weights"].get(item.source, 0.5)
    items = sorted(items, key=lambda it: it.score, reverse=True)

    stories = _merge_same_urls(items)
    if use_embeddings and len(stories) > 1:
        stories = _merge_similar(stories, cfg)

    for story in stories:
        story.score += r["cross_source_bonus"] * (len(story.sources) - 1)
        experts = {name for it in [story, *story.also_on] for name in it.meta.get("experts", [])}
        if len(experts) >= 2:
            story.score += r["expert_bonus"]
        story.meta["all_experts"] = sorted(experts)

    stories.sort(key=lambda it: it.score, reverse=True)
    for number, story in enumerate(stories, start=1):
        story.id = f"s{number}"
    return stories
