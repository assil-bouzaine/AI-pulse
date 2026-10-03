"""Hugging Face: trending models and Daily Papers, via the public JSON API.

We call the HTTP endpoints directly instead of installing `huggingface_hub`:
two GET requests don't justify a dependency, and seeing the raw JSON is more
educational.
  * /api/models?sort=trendingScore  -> what the Hub's trending page shows
  * /api/daily_papers               -> papers curated by AK & the community
"""

from ..models import Item
from ..net import get_json
from ..utils import compact_number, log_heat, to_datetime

API = "https://huggingface.co/api"


def fetch_models(cfg: dict) -> list[Item]:
    c = cfg["huggingface"]
    models = get_json(f"{API}/models", params={"sort": "trendingScore",
                                                "limit": c["models_limit"]})
    heats = log_heat([m.get("trendingScore", 0) for m in models])
    items = []
    for model, heat in zip(models, heats):
        task = model.get("pipeline_tag") or "model"
        items.append(Item(
            source="hf_models",
            title=model["id"],
            url=f"https://huggingface.co/{model['id']}",
            summary=f"{compact_number(model.get('downloads', 0))} downloads · "
                    f"{model.get('library_name') or 'n/a'}",
            heat=heat,
            published=to_datetime(model.get("createdAt")),
            meta={"task": task, "likes": model.get("likes", 0),
                  "downloads": model.get("downloads", 0),
                  "trending": model.get("trendingScore", 0)},
        ))
    return items


def fetch_papers(cfg: dict) -> list[Item]:
    c = cfg["huggingface"]
    entries = get_json(f"{API}/daily_papers", params={"limit": 100})
    entries.sort(key=lambda e: e["paper"].get("upvotes", 0), reverse=True)
    entries = entries[: c["papers_limit"]]
    heats = log_heat([e["paper"].get("upvotes", 0) for e in entries])
    items = []
    for entry, heat in zip(entries, heats):
        paper = entry["paper"]
        summary = paper.get("ai_summary") or paper.get("summary") or ""
        items.append(Item(
            source="hf_papers",
            title=paper["title"],
            url=f"https://huggingface.co/papers/{paper['id']}",
            summary=" ".join(summary.split())[:350],
            heat=heat,
            published=to_datetime(entry.get("publishedAt")),
            meta={"upvotes": paper.get("upvotes", 0), "comments": entry.get("numComments", 0),
                  "github": paper.get("githubRepo"), "arxiv": paper["id"]},
        ))
    return items
