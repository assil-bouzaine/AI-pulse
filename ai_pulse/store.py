"""SQLite memory between runs.

Two jobs:
  1. GitHub star snapshots, so we can measure stars *gained per day*
     (GitHub has no trending API, so we build our own).
  2. Remembering which links we've already shown, to badge fresh ones 🆕.

sqlite3 ships with Python, needs no server and is a single file: ideal here.
"""

import sqlite3
from datetime import timedelta
from pathlib import Path

from .models import Item
from .utils import normalize_url, now, to_datetime


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS stars (
                repo TEXT NOT NULL, taken_at TEXT NOT NULL, stars INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS stars_repo ON stars (repo, taken_at);
            CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY, title TEXT, source TEXT,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
        """)

    # ---------- GitHub star velocity ----------

    def add_star_velocity(self, items: list[Item]) -> None:
        """Set meta['per_day'] on GitHub search results and save a snapshot.

        With history: (stars now - oldest snapshot this week) / days between.
        First run:    stars / repo age. The search only returns repos created
                      in the last week, so that's already an honest velocity.
        """
        timestamp = now()
        week_ago = (timestamp - timedelta(days=7)).isoformat()
        for item in items:
            if item.source != "github":
                continue
            repo, stars = item.meta["repo"], item.meta["stars"]
            row = self.db.execute(
                "SELECT taken_at, stars FROM stars WHERE repo = ? AND taken_at >= ? "
                "ORDER BY taken_at LIMIT 1", (repo, week_ago)).fetchone()
            days = 0.0
            if row:
                days = (timestamp - to_datetime(row[0])).total_seconds() / 86400
            if row and days >= 0.25:   # at least 6h apart, or the number is noise
                item.meta["per_day"] = max(stars - row[1], 0) / days
                item.meta["velocity_from"] = "history"
            else:
                created = to_datetime(item.meta.get("created_at")) or timestamp
                age_days = max((timestamp - created).total_seconds() / 86400, 1.0)
                item.meta["per_day"] = stars / age_days
                item.meta["velocity_from"] = "age"
            self.db.execute("INSERT INTO stars VALUES (?, ?, ?)",
                            (repo, timestamp.isoformat(), stars))
        self.db.commit()

    # ---------- "have we shown this before?" ----------

    def mark_seen(self, items: list[Item]) -> None:
        """Set item.is_new, then remember every item for next time."""
        stamp = now().isoformat()
        for item in items:
            key = normalize_url(item.url)
            known = self.db.execute("SELECT 1 FROM seen WHERE key = ?", (key,)).fetchone()
            item.is_new = known is None
            self.db.execute(
                "INSERT INTO seen VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET last_seen = excluded.last_seen",
                (key, item.title, item.source, stamp, stamp))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
