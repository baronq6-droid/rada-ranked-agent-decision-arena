# Devpost submission — RADA — Ranked Agent Decision Arena

Wypełniasz formularz na Devpost tym tekstem. Miejsca do uzupełnienia oznaczone `[...]`.

---

**Project name:** RADA — Ranked Agent Decision Arena

**Tagline:** Built with Codex. Open to every model.

**Category:** Developer Tools

---

## What it does

RADA is a local, vendor-neutral control plane for
AI coding agents. It connects Claude Code, Codex CLI, Gemini CLI and Grok Build —
four agents from four competing vendors — in one decision arena:

1. **Bidding.** Your task goes to every agent. Each returns a structured bid:
   confidence (0–100), plan, risks, effort — without executing anything.
2. **Blind voting.** Bids are anonymized and shuffled; agents rank each other's plans
   (Borda count). No agent knows which bid is its own — this matters, because models
   asked "can you do it?" always say yes. Judging rivals' plans blind, they get honest.
3. **Execution.** Only the vote winner executes, in your repo. One execution instead
   of four — this is what makes the arena cheap compared to "run everything and
   compare" orchestrators.
4. **Deterministic verification.** A project-defined argv command produces
   PASS, FAIL or INCONCLUSIVE; only this result determines the run's final status.
5. **Review.** The vote runner-up independently reviews the winner's work.
6. **Audit trail.** Every bid, vote, mapping, result, verifier result and review lands in
   `rada_memory/runs/*.json`; `ranking.py` turns history into a scoreboard —
   wins, review verdicts, and how often each juror's vote picked the final winner.

An optional terminal mode, **`:sztab` (RADA 8S)**, adds collaboration without
concurrent writes: the winner remains the only lead executor, the runner-up is
reserved for independent final review, and the next two ranked agents provide
read-only test-strategy and UX/red-team packages. The run records every role,
advisory package and the SHA-256 of the exact prompt delivered to the lead.

Three interfaces share one core: a terminal CLI (`rada.py`), a group-chat room where
agents can interject corrections (`pokoj.py`), and a browser messenger with live
bid cards, vote tallies and the trophy board (`web.py`). Zero dependencies —
pure Python standard library. A `--mock` mode simulates all agents, so judges can
try the full flow in seconds without any API keys.

## Inspiration

I use four AI coding agents daily and I was the router between them: switching apps,
copying context, guessing who's best for each task. I wanted the models to settle it
themselves — and to leave a paper trail of why. No vendor will build a neutral router
that sometimes says "a competitor is better for this one," so it had to be independent.

## How we built it — Codex + GPT‑5.6

The project was built during Build Week in a tight loop between Codex (GPT‑5.6) and
other assistants, with Codex doing the hands-on engineering on the final repo:

- Codex executed the initial **five written work orders** end-to-end, one commit each:
  - `2e05439` — reviewer selection by Borda runner-up (not self-declared confidence)
  - `fd12a54` — agent failure is reported as an error, never counted as a silent PASS
  - `66a1c7a` — one-shot `:debata` command routed correctly outside the REPL
  - `473551b` — unified audit record schema for manual routing runs
  - `f2f91f7` — Windows portability: portable tests (`sys.executable`), UTF‑8 stdio
- Codex also wrote the accompanying regression tests — the suite grew from 17 to
  **22 tests**, all green natively on Windows, Linux and macOS.
- A final hardening pass added the public-name sweep (`6c8b6dd`), isolated malformed
  agent configs and worker failures (`316d0ac`), and added the deterministic verifier.
  The suite now has **54 tests** and is green natively on Windows and Linux.
- Codex implemented the optional RADA 8S collaboration mode, including role
  isolation, failure-tolerant advisory packages and reconstructable prompt audits.
  A live run produced the offline **NEFARIN Core Defense** artifact: the first
  degraded run created it, and a subsequent three-agent staff run audited and
  verified it with separate lead, advisor and reviewer roles.
- Codex ran the verification loop itself (unit tests, mock RADA runs, web smoke).
- **Codex Session ID (`/feedback`):** `019f71df-f990-71c2-976b-5020868ba57f`

Meta-twist: GPT‑5.6 isn't just the build tool — **Codex is one of the four agents
inside the product**. It bids, votes, executes and reviews like the others, and the
audit log shows it competing (and sometimes losing the blind vote) fairly.

## Challenges we ran into

Normalizing four different CLIs behind one contract (flags, JSON envelopes, exit
codes); making self-assessment honest (solved by anonymized blind voting — models
over-rate themselves, but judge rivals' plans soberly); preventing model-chat
cacophony (interjection rules: one correction max, PASS by default, no auto-replies);
Windows portability (cp1250 console vs Unicode UI); and keeping bids untrusted —
strict JSON parsing that survives braces inside strings and vote-stuffing attempts
(duplicate rankings are deduplicated before Borda counting).

## Accomplishments we're proud of

The project was **code-reviewed by the very models that participate in RADA** — an
external review found 4 critical/high bugs, all reproduced, fixed and locked with
regression tests. The selection mechanism is not marketing: anonymization, shuffled
order, Borda with dedup, tie-breaks, and juror-accuracy tracking are all implemented
and tested. The optional staff mode preserves a single writer while letting other
models contribute attributable, read-only advice. The repository also contains a
self-contained offline browser game and its tests, created and audited during live
RADA runs. The orchestration remains pure Python standard library with zero runtime
dependencies.

## What we learned

"Run everything and compare" is easy but expensive; **choosing before executing** —
one execution instead of N — needs exactly the machinery we built: honest bids, blind
votes and an audit trail. And models really do vote against their own bids when they
can't recognize them.

## What's next

SQLite event store (ordering + metrics), live streaming of the winner's work,
per-run token/cost accounting, ACP as a second transport, and a proper benchmark
(success@1, regret, Brier-calibrated confidence) to prove RADA beats both
random choice and "pick the most confident" — data first, then weighted voting.

---

## How to test (for judges)

```bash
# no keys needed — full simulated arena in the browser:
python3 web.py --mock          # open http://localhost:8787 and type:  :rada add a --version flag

# terminal flow with review:
python3 rada.py --mock --review "refactor the payments module"

# regression suite (54 tests):
python3 -m unittest test_rada test_game -v

# with real agents: install & log in claude / codex / gemini / grok CLIs, then drop --mock
```

**Repo:** https://github.com/baronq6-droid/rada-ranked-agent-decision-arena
· **Video:** https://www.youtube.com/watch?v=YVQv31UsZos
