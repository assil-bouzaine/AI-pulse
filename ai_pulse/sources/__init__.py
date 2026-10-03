"""Source registry: name -> fetch function.

Every fetcher has the same signature, `fetch(cfg) -> list[Item]`, and is
allowed to raise. main.py runs them all in parallel and turns exceptions into
a ❌ in the report's source-health table, so one broken source never kills
the run. Adding a source = write one function, add one line here.
"""

from . import ainews, blogs, github, hackernews, huggingface, reddit

SOURCES = {
    "hackernews": hackernews.fetch,
    "show_hn": hackernews.fetch_show_hn,
    "reddit": reddit.fetch,
    "ainews": ainews.fetch,
    "github": github.fetch_rising,
    "github_experts": github.fetch_expert_stars,
    "hf_models": huggingface.fetch_models,
    "hf_papers": huggingface.fetch_papers,
    "blogs": blogs.fetch,
}
