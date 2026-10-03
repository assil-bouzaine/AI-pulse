# ⚡ AI Pulse

An agent that tells you what the AI engineering community is talking about **right now**:
new models, tools, repos, papers, debates, and what respected engineers are reading and
starring. It uses only free sources and free (or local) LLMs, and builds a small
website with the results (light/dark, works offline).

## ▶️ One-click run

- **Windows:** double-click `run.bat`
- **macOS / Linux:** `./run.sh` (once: `chmod +x run.sh`)
- **Desktop shortcut (Windows):** right-click `run.bat` → *Send to → Desktop (create shortcut)*, then
  *Properties → Change Icon…* → pick `assets/ai-pulse.ico`.

The first launch sets everything up. Every launch collects, ranks, writes the briefing
and **opens the site in your browser** (about 30s with a cloud key).

**New to AI? Press 🧸 Simple** in the site's header. Every story gets an "explain it like I'm 5"
version (an everyday analogy, no jargon), the big picture gets one too, and a **📖 Words of the
day** card explains today's jargon in one plain sentence each.

```
 Hacker News ─┐
 Show HN ─────┤                ┌──────────┐   ┌──────────────┐   ┌──────────┐
 Reddit RSS ──┤   parallel     │ SQLite   │   │ rank + merge │   │ LLM      │   reports/
 AINews (X) ──┼──  fetch   ──▶ │ stars &  │──▶│ duplicates   │──▶│ editor   │──▶ latest.md
 GitHub ──────┤  (threads)     │ seen log │   │ (embeddings) │   │ (1 call) │   + terminal
 HF models ───┤                └──────────┘   └──────────────┘   └──────────┘
 HF papers ───┤                                                  Gemini → Groq → Ollama
 Blogs ───────┤
 YouTube ─────┘                                                  (automatic fallback)
                                                                  → reports/latest.html
```

## Manual setup (Windows, macOS, Linux)

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows (cmd): copy .env.example .env
```

Then add whichever keys you have to `.env`. **All of them are optional:**

| Key | What it gives you | Where |
|---|---|---|
| `GEMINI_API_KEY` | Best-quality briefing, ~10s | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GROQ_API_KEY` | Very fast fallback | [console.groq.com/keys](https://console.groq.com/keys) |
| `GITHUB_TOKEN` | Reliable repo search (no scopes needed) | [github.com/settings/tokens](https://github.com/settings/tokens) |

With no LLM keys, it uses your local Ollama (`qwen3.5:4b`). For de-duplication, also run
`ollama pull nomic-embed-text`.

## Run

```bash
python -m ai_pulse --open                # full run, then open the website
python -m ai_pulse --print               # also print the briefing in the terminal
python -m ai_pulse --llm groq            # force a provider: gemini | groq | ollama | none
python -m ai_pulse --sources hackernews,reddit --llm none   # quick, no LLM
python -m ai_pulse -v                    # debug logs (see every retry and fallback)
```

All tuning (subreddits, GitHub topics, expert list, thresholds, weights) lives in `config.toml`.

## How it works (read the code in this order)

| File | What to learn from it |
|---|---|
| `models.py` | One `Item` shape for every source keeps the rest of the code source-agnostic. |
| `net.py` | Timeouts, retries, exponential backoff with jitter, `Retry-After`, and failing fast on long rate limits. |
| `sources/*.py` | One function per source. Each may raise; `main.py` turns that into a ❌, never a crash. |
| `store.py` | SQLite snapshots turn "total stars" into "stars per day", i.e. a homemade trending API. |
| `rank.py` | Scoring, plus **embeddings for semantic de-duplication** (the same story on HN + Reddit becomes one story with a cross-source bonus). |
| `llm.py` | Three providers behind one function. Gemini and Groq share the OpenAI-compatible format. JSON validation, with fallback on bad output. |
| `editor.py` | Prompt design: code does the research, the LLM only edits. Short IDs (`s1`, `s2`) map notes back to stories. The LLM gets exactly the stories shown on the page, interleaved across sections so a capped prompt still covers every section, and writes a pro note + a 🧸 simple version for each. |
| `report.py` | Decides which story goes in which section (shared by both outputs), plus the Markdown version. |
| `site.py` + `templates/report.html` | The website: a Python "view model" + a Jinja2 template with autoescaping (internet titles can't inject HTML). One self-contained file, light/dark via CSS variables. |

### Key decisions

- **Deterministic pipeline, one LLM call.** Fetching, filtering and ranking are plain code:
  fast, free, testable, and identical every run. The LLM writes only what code can't (the
  narrative and the "why it matters" notes). That makes it fast and keeps free-tier quotas safe.
- **Fallback, not failure.** A broken source is skipped. A failed LLM model (e.g. HTTP 503
  "overloaded") hands over to the provider's next model, then to the next provider
  (Gemini → Groq → Ollama). Invalid JSON counts as a failure too. With no LLM at all you
  still get the ranked report.
- **Embeddings on titles only, threshold 0.84.** Tuned on real data: true duplicates scored
  0.85+, while merely-related items scored 0.78–0.82. Summaries added generic words that blurred
  the two together.
- **Prompt size per provider.** Groq's free tier allows ~6–8K tokens/min, and a 4B model on a
  laptop CPU writes ~6 tokens/s, so each provider gets a different number of stories
  (`max_items` in `config.toml`).

## Source notes (as of Oct 2026)

- **Reddit:** RSS only (the API and `.json` endpoints are closed). There are no vote counts, so feed order is used as the rank.
- **X/Twitter:** via the AINews "AI Twitter Recap" in the Latent Space feed (only the free part of each item).
- **GitHub:** no trending API exists. Repos come from the Search API and are ranked by stars/day from SQLite history. Repos starred by 2+ of the trusted engineers this week get a boost.
- **YouTube:** each channel's free RSS feed (no API key). Videos are ranked by *breakout ratio*: views/day compared with that channel's median, so small channels compete fairly. Fireship and Prime are filtered to AI topics. Add channels in `config.toml`.
- **Blogs:** Eugene Yan and Chip Huyen post rarely, so on most days they won't show up. The lookback window is 21 days.
