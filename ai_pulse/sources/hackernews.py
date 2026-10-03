"""Hacker News via the free Algolia API (no key needed).

HN's front page covers everything (startups, space, politics...), so we keep
only stories whose title matches AI keywords. A regex is crude but instant,
free and predictable. Using an LLM to filter 200 titles would be none of those.
"""

import re
import time

from ..models import Item
from ..net import get_json
from ..utils import log_heat, to_datetime

API = "https://hn.algolia.com/api/v1/search_by_date"

AI_TITLE = re.compile(
    r"\b(ai|a\.i\.|agi|llms?|gpts?|gpt-\S+|chatgpt|claude|gemini|gemma|llama|qwen|mistral|"
    r"deepseek|kimi|grok|openai|anthropic|hugging ?face|agents?|agentic|rag|embeddings?|"
    r"transformers?|diffusion|inference|fine-?tun\w*|neural|machine learning|deep learning|"
    r"language models?|reasoning models?|mcp|copilot|cursor|vllm|ollama|llama\.cpp|gguf|"
    r"tokens?|tokenizer|prompts?|prompting|vibe.?cod\w*|evals?|benchmarks?|gpus?|cuda|"
    r"nvidia|ml|nlp|chatbots?|vector (db|database|search)|context window|lora|rlhf|"
    r"multimodal|speech.to.text|text.to.speech|tts|world models?|robotics)\b",
    re.IGNORECASE)


def _search(tags: str, hours: int, min_points: int) -> list[dict]:
    since = int(time.time()) - hours * 3600
    data = get_json(API, params={
        "tags": tags,
        "numericFilters": f"created_at_i>{since},points>={min_points}",
        "hitsPerPage": 300,
    })
    hits = [hit for hit in data["hits"] if AI_TITLE.search(hit.get("title") or "")]
    if tags == "story":   # Show HN posts are stories too; count them once, as show_hn
        hits = [hit for hit in hits if "show_hn" not in hit.get("_tags", [])]
    return hits


def _to_items(hits: list[dict], source: str) -> list[Item]:
    heats = log_heat([hit["points"] for hit in hits])
    items = []
    for hit, heat in zip(hits, heats):
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        items.append(Item(
            source=source,
            title=hit["title"],
            url=hit.get("url") or discussion,
            summary="",
            heat=heat,
            published=to_datetime(hit.get("created_at_i")),
            meta={"points": hit["points"], "comments": hit.get("num_comments") or 0,
                  "discussion": discussion},
        ))
    return items


def fetch(cfg: dict) -> list[Item]:
    c = cfg["hackernews"]
    return _to_items(_search("story", c["hours"], c["min_points"]), "hackernews")


def fetch_show_hn(cfg: dict) -> list[Item]:
    """`Show HN` is where people launch new tools, so it's a separate source."""
    c = cfg["hackernews"]
    return _to_items(_search("show_hn", c["hours"], c["show_hn_min_points"]), "show_hn")
