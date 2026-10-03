"""GitHub: rising new repos + what trusted engineers starred this week.

There is no official "trending" API, so we build it:
  * Search API: repos created in the last N days with a topic, sorted by stars.
    Stars-per-day is computed later from SQLite snapshots (see store.py).
  * The starred-repos API with the `star+json` media type adds `starred_at`, so
    we can see what karpathy, simonw & co. starred *this week*. When two or
    more of them star the same repo, that's a strong signal.

Without a token GitHub allows 60 req/hour (and ~10 searches/minute), shared
by everyone on your IP. A free GITHUB_TOKEN in .env removes that worry.
"""

import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from ..models import Item
from ..net import RateLimited, get_json
from ..utils import now, to_datetime

log = logging.getLogger(__name__)
API = "https://api.github.com"


def _headers(star_dates: bool = False) -> dict:
    headers = {"Accept": "application/vnd.github.star+json" if star_dates
               else "application/vnd.github+json"}
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_rising(cfg: dict) -> list[Item]:
    c = cfg["github"]
    since = (now() - timedelta(days=c["days"])).date().isoformat()
    repos: dict[str, dict] = {}
    errors = []
    for topic in c["topics"]:
        try:
            data = get_json(f"{API}/search/repositories", headers=_headers(), params={
                "q": f"topic:{topic} created:>{since}",
                "sort": "stars", "order": "desc", "per_page": c["per_topic"]})
        except RateLimited as exc:   # the other topics would hit the same wall
            errors.append(f"{topic}: {exc}")
            break
        except Exception as exc:   # one topic failing shouldn't lose the others
            errors.append(f"{topic}: {exc}")
            continue
        for repo in data["items"]:
            repos.setdefault(repo["full_name"], repo)
    if errors and not repos:
        hint = "" if os.getenv("GITHUB_TOKEN") else " (add a free GITHUB_TOKEN to .env)"
        raise RuntimeError("; ".join(errors) + hint)
    for error in errors:
        log.warning("github search %s", error)

    items = []
    for repo in repos.values():
        if repo["stargazers_count"] < c["min_stars"]:
            continue
        items.append(Item(
            source="github",
            title=repo["full_name"],
            url=repo["html_url"],
            summary=(repo.get("description") or "")[:300],
            published=to_datetime(repo["created_at"]),
            meta={"repo": repo["full_name"], "stars": repo["stargazers_count"],
                  "created_at": repo["created_at"], "language": repo.get("language"),
                  "topics": repo.get("topics", [])[:5]},
        ))
    return items   # heat is set in main.py once star velocity is known


def fetch_expert_stars(cfg: dict) -> list[Item]:
    c = cfg["github"]
    cutoff = now() - timedelta(days=c["expert_days"])
    starred_by: dict[str, list[str]] = defaultdict(list)
    repo_info: dict[str, dict] = {}
    failed = []

    def recent_stars(user: str) -> list[dict]:
        return get_json(f"{API}/users/{user}/starred", headers=_headers(star_dates=True),
                        params={"per_page": 30, "sort": "created", "direction": "desc"})

    # 7 independent requests: run them side by side instead of one after another.
    with ThreadPoolExecutor(max_workers=len(c["experts"])) as pool:
        futures = {user: pool.submit(recent_stars, user) for user in c["experts"]}

    for user, future in futures.items():
        try:
            stars = future.result()
        except Exception as exc:
            failed.append(user)
            log.warning("github stars of %s: %s", user, exc)
            continue
        for star in stars:
            if (to_datetime(star["starred_at"]) or cutoff) < cutoff:
                break   # sorted newest first, so everything after is older
            name = star["repo"]["full_name"]
            starred_by[name].append(user)
            repo_info[name] = star["repo"]

    if len(failed) == len(c["experts"]):
        raise RuntimeError("could not read any expert's stars")

    items = []
    for name, users in starred_by.items():
        repo = repo_info[name]
        items.append(Item(
            source="github_experts",
            title=name,
            url=repo["html_url"],
            summary=(repo.get("description") or "")[:300],
            heat=min(len(users) / 2, 1.0),   # 1 expert -> 0.5, 2+ -> 1.0
            meta={"repo": name, "experts": users, "stars": repo["stargazers_count"],
                  "language": repo.get("language")},
        ))
    return items
