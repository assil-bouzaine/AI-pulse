"""AI Pulse: what the AI engineering community is talking about right now.

The pipeline, top to bottom:

    1. FETCH   all sources in parallel threads (network-bound, so threads are ideal)
    2. MEMORY  star snapshots + "seen before" badges in SQLite
    3. RANK    score, merge duplicates (URL + embeddings), sort
    4. EDIT    one LLM call writes the narrative and notes (with fallback)
    5. RENDER  website (HTML) + Markdown -> reports/ folder, optionally open the browser

Run:  python -m ai_pulse            (see --help for options)
"""

import argparse
import logging
import sys
import time
import tomllib
import webbrowser
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown

from . import editor, llm, rank, report, site
from .models import label
from .report import SourceResult
from .sources import SOURCES
from .store import Store
from .utils import log_heat

ROOT = Path(__file__).resolve().parent.parent   # project folder, wherever it lives
console = Console()
log = logging.getLogger("ai_pulse")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ai_pulse", description=__doc__.split("\n")[1])
    parser.add_argument("--llm", choices=["auto", "gemini", "groq", "ollama", "none"],
                        help="which LLM writes the digest (default: config.toml, usually auto)")
    parser.add_argument("--sources", help=f"comma-separated subset of: {', '.join(SOURCES)}")
    parser.add_argument("--no-embed", action="store_true",
                        help="skip embedding-based de-duplication (faster, less smart)")
    parser.add_argument("--open", action="store_true", help="open the website in your browser when done")
    parser.add_argument("--print", action="store_true", help="also print the report in the terminal")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", default=str(ROOT / "config.toml"))
    return parser.parse_args()


# ---------- 1. FETCH ----------

def run_one_source(name: str, cfg: dict) -> SourceResult:
    started = time.perf_counter()
    try:
        items = SOURCES[name](cfg)
        error = ""
    except Exception as exc:   # the "one broken source never kills the run" rule
        items, error = [], f"{type(exc).__name__}: {exc}"
    return SourceResult(name, items, time.perf_counter() - started, error)


def fetch_all(names: list[str], cfg: dict) -> list[SourceResult]:
    timeout = cfg["general"]["source_timeout"]
    pool = ThreadPoolExecutor(max_workers=len(names))
    futures = {pool.submit(run_one_source, name, cfg): name for name in names}
    done, _ = wait(futures, timeout=timeout)

    results = []
    for future, name in futures.items():
        if future in done:
            result = future.result()
        else:   # still running past the deadline: give up on it, don't wait
            result = SourceResult(name, [], timeout, f"timed out after {timeout}s")
        icon = "[red]✗[/]" if result.error else "[green]✓[/]"
        console.print(f"  {icon} {label(name):<22} {len(result.items):>3} items "
                      f"[dim]{result.seconds:4.1f}s {result.error[:90]}[/]")
        results.append(result)
    pool.shutdown(wait=False, cancel_futures=True)
    return results


# ---------- main ----------

def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(message)s", handlers=[RichHandler(show_path=False)])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    llm_choice = args.llm or cfg["general"]["llm"]
    names = args.sources.split(",") if args.sources else list(SOURCES)
    unknown = set(names) - set(SOURCES)
    if unknown:
        console.print(f"[red]Unknown sources: {', '.join(unknown)}[/]")
        return 2

    started = time.perf_counter()
    console.rule("[bold cyan]⚡ AI Pulse")
    console.print(f"[bold]Fetching {len(names)} sources in parallel…[/]")
    results = fetch_all(names, cfg)
    items = [item for r in results for item in r.items]
    if not items:
        console.print("[red]Every source failed. Check your internet connection.[/]")
        return 1

    # 2. MEMORY
    store = Store(str(ROOT / cfg["general"]["db_path"]))
    store.add_star_velocity(items)
    repos = [it for it in items if it.source == "github"]
    for item, heat in zip(repos, log_heat([it.meta["per_day"] for it in repos])):
        item.heat = heat
    store.mark_seen(items)
    store.close()

    # 3. RANK
    with console.status("[bold]Ranking and de-duplicating stories…"):
        stories = rank.rank(items, cfg, use_embeddings=not args.no_embed)
    merged = sum(len(s.also_on) for s in stories)
    console.print(f"[bold]Ranked[/] {len(items)} items → {len(stories)} stories "
                  f"[dim]({merged} duplicates merged)[/]")

    # 4. EDIT
    digest, writer = None, "no LLM"
    with console.status("[bold]The editor is writing your briefing…"):
        try:
            digest, writer = llm.generate(
                cfg, llm_choice, editor.SYSTEM_PROMPT,
                build_prompt=lambda n: editor.build_prompt(stories, n),
                validate=editor.validate)
            console.print(f"[bold]Written by[/] {writer}")
        except llm.LLMError as exc:
            console.print(f"[yellow]No LLM summary ({exc}). Report will show raw ranking.[/]")

    # 5. RENDER: the same digest as a website and as Markdown
    elapsed = time.perf_counter() - started
    markdown = report.render(stories, results, digest, writer, cfg, elapsed)
    html = site.render(stories, results, digest, writer, cfg, elapsed)
    out_dir = ROOT / cfg["general"]["report_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"ai-pulse-{datetime.now():%Y-%m-%d_%H%M}"
    for name, content in [(f"{stamp}.md", markdown), (f"{stamp}.html", html),
                          ("latest.md", markdown), ("latest.html", html)]:
        (out_dir / name).write_text(content, encoding="utf-8")   # utf-8: emojis on Windows

    if args.print:
        console.print()
        console.print(Markdown(markdown, hyperlinks=True))
    page = out_dir / "latest.html"
    console.rule(f"[green]Done in {elapsed:.1f}s → {page.relative_to(ROOT)}")
    if args.open:
        webbrowser.open(page.as_uri())   # works on Windows, macOS and Linux
    return 0


if __name__ == "__main__":
    sys.exit(main())
