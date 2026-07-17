# Rada Modeli (Model Council) 🗳️

One local hub where your AI coding agents — **Claude Code, Codex, Gemini CLI and
Grok Build** — decide *together* who should do the task. Instead of you switching
between four apps, the models bid, vote blind, one executes, another reviews.
Vendor-neutral. Zero dependencies. Fully audited.

> Models bid anonymously for a task, vote on the best plan, and the runner-up
> reviews the winner.

## How it works

```
          your task
              │
   ┌──────────┼──────────┬──────────┐
   ▼          ▼          ▼          ▼
 claude     codex      gemini     grok      [1/3] BIDDING — every agent submits:
   │          │          │          │             confidence 0-100, plan, risks, effort
   └────┬─────┴────┬─────┴────┬─────┘
        ▼          ▼          ▼
      BLIND VOTE (bids anonymized,          [2/3] COUNCIL — each agent ranks the bids
      shuffled, Borda count)                      without knowing which one is its own
        │
        ▼
      WINNER executes in your repo          [3/3] EXECUTION — one run, not four
        │
        ▼
      RUNNER-UP reviews the result          + shared memory & full audit trail
```

Why anonymous? Ask a model "can you do it?" and it says yes. Let it judge rival
plans blind and it gets honest. Ties are broken deterministically; duplicate
entries in a juror's ranking are deduplicated (no vote-stuffing); every run is
recorded in `rada_memory/runs/*.json` — bids, votes, anonymization map, result,
review.

## Requirements

- Python 3.9+ (standard library only — nothing to install)
- Logged-in agent CLIs you want on the council: `claude`, `codex`, `gemini`, `grok`
  (missing CLIs are detected and skipped)
- No CLIs at all? Use `--mock` — a full simulated council, great for a first look.

## Quick start

```bash
python3 rada.py --mock "refactor the payments module and add tests"   # simulation
python3 web.py --mock                # browser messenger; try:  :rada add a --version flag

cd ~/your-project                    # the real thing, in your repo
python3 /path/to/rada.py --review "add dark mode to the settings panel"
```

## Usage (rada.py)

```
python3 rada.py [task] [flags]

  "@codex task"          manual routing — skip the council, send straight to one agent
  --mock                 simulate agents (no CLIs, no cost)
  --review               runner-up reviews the winner's work
  --no-vote              skip voting; highest self-declared confidence wins
  --only claude,codex    limit the council
  --cwd /path            working directory for agents (your project)
  --timeout-bid 300      seconds per bid/vote
  --timeout-exec 3600    seconds for execution
  --init                 write agents.json for editing
```

## The other two faces

- **`pokoj.py` — group chat.** All models in one thread; messages carry
  "from → to" signatures. Address one agent (`@grok …`) and the others act as
  quality control: they may interject a correction or answer `PASS`.
  `:debata topic` runs a discussion round. Anti-cacophony rules built in.
- **`web.py` — browser messenger.** Same room plus the full council:
  `:rada task` renders bid cards with confidence bars, votes, a trophy tally
  board, execution and review. Local server on 127.0.0.1, single HTML page.

## Configuration (agents.json)

`python3 rada.py --init` writes the defaults. Commands are argument arrays
(never a shell string); `{prompt}` is substituted with the query. Add any agent
that reads a prompt and prints a reply — e.g. local models via
`["ollama", "run", "llama3.1", "{prompt}"]`. `bid_cmd` is used for cheap
bids/votes (no write permissions); `exec_cmd` carries the auto-approve flags.

## Safety & cost

The council overhead is ~2 short calls per agent (bid + vote); only the winner
executes. `exec_cmd` lets agents modify files in `--cwd` — run inside a git
repo and review diffs. Full audit of every decision is kept locally.

## Scoreboard

```bash
python3 ranking.py        # wins, review verdicts, juror accuracy per agent
```

## Tests

```bash
python3 -m unittest test_rada -v     # 22 regression tests
```

Covers: exit-code handling, config validation, Borda dedup, brace-safe JSON
parsing, Borda-based reviewer selection, error-vs-PASS separation, one-shot
`:debata`, unified audit schema, Windows portability.

## Windows

Stdout/stderr are switched to UTF-8 automatically; on older terminals run
`chcp 65001` first. Tests are portable (no `sh` required).

## Roadmap

SQLite event store → streaming of the winner's work → per-run cost accounting →
ACP transport → benchmark (success@1, regret, Brier) → history-weighted voting.

---

Polish documentation: see `README.pl.md` (oryginalna dokumentacja po polsku).
Built during OpenAI Build Week with Codex on GPT‑5.6 — which also sits on the
council and has to win the blind vote like everyone else.
