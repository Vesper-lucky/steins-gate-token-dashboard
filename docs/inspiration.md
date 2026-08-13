# Inspiration: phuryn/claude-usage

Source: https://github.com/phuryn/claude-usage

## What it does

A local dashboard that reads Claude Code's JSONL session transcripts and shows token usage, cost estimates, and session history. Works on API, Pro, and Max plans.

## Tech stack

- **Python 3.8+**, standard library only (no pip install, no venv)
- `sqlite3` — persistent storage at `~/.claude/usage.db`
- `http.server` — serves a single-page HTML/JS dashboard
- Chart.js on the frontend for visualizations

## Core files

- `scanner.py` — parses JSONL into SQLite, incremental (tracks file mtime)
- `dashboard.py` — HTTP server, single-page UI
- `cli.py` — command dispatcher

## CLI commands

- `python cli.py scan` — populate the DB from JSONL files
- `python cli.py today` — today's breakdown by model (terminal)
- `python cli.py stats` — all-time stats (terminal)
- `python cli.py dashboard` — scan + open browser at `localhost:8081`
- Env vars: `HOST`, `PORT`, `--projects-dir` for custom paths

## What it captures

- Claude Code CLI (`claude` in terminal)
- VS Code extension (Claude Code sidebar)
- Dispatched Code sessions

## What it does NOT capture

- **Cowork sessions** — server-side, no local JSONL
- Cost calculations for non-standard model names (only matches `opus`/`sonnet`/`haiku` — others show `n/a`)

## Data shape

Each JSONL line is a message. Usage lives at `message.usage`:
- input tokens, output tokens
- cache creation tokens, cache read tokens

Model identifier at `message.model`.

## Limitations worth addressing in our version

1. **Cost for Pro/Max users is misleading** — API rates shown, but those users pay a flat subscription. The original admits this in its README.
2. **Unknown models show `n/a`** — no fallback pricing, no way to add custom pricing.
3. **UI is a single HTML page with Chart.js** — functional but dated.
4. **No session drill-down** — can't easily click into a session and see what happened.
5. **No per-project comparison** — aggregates are global.
6. **30-second auto-refresh** only; no live tailing of the active session.

These are candidates (not commitments) for what our version could do better.
