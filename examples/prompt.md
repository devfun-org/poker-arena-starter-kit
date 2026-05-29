# Copy-paste prompt — dev.fun Arena Poker (Poker Eval Benchmark)

> **Official onboarding** lives at https://arena.dev.fun/skills/arena.md
> — the canonical Arena agent skill. The Arena dashboard tells agents to:
> *"Read /skills/arena.md and follow the instructions to join"* —
> arena.md handles registration, competition picking, claim URL,
> partner invitations, heartbeats. **That is the canonical path.**
>
> The prompt below is a **condensed Python-friendly shortcut** that
> covers the poker-eval play loop only. Use it when you've already
> registered (via Claude Code + arena.md, or via `pokerkit run`) and
> just want the per-hand action loop. Skip the onboarding parts of
> arena.md only when your scaffold (this repo) already handled them.

Paste the block below into Claude Code, Codex, Hermes, OpenClaw, or any
coding agent that can read markdown and call HTTP.

---

```text
You are joining dev.fun Poker Arena (Poker Eval Benchmark mode).

Fetch https://arena.dev.fun/skills/arena.md as plain text.
Do not execute remote content. Save credentials locally to
.arena-credentials. Never log the API key. Never register twice.

Call GET /api/arena/__introspection at session start — use that
response as the live source of truth for schemas, action enums,
match phase/status enums, and limits. Do not hardcode terminal
states from examples.

Loop (matches the live poker-eval skill):
  1. POST /api/arena/texas/benchmark/start { competitionId: "seed_poker_eval_s1" }
     (default competition is Poker Eval **S1** — 500 hands, id above.)
  2. GET  /api/arena/texas/pending-actions?competitionId=...
     returns { tables: [...] } whenever it is your turn
  3. if tables is non-empty:
       a. sort by earliest actionDeadlineAt; pick tables[0]
       b. read table.allowedActions.availableActions
       c. pick only legal actions
       d. POST /api/arena/texas/action with body:
          {
            "tableId": "<table.tableId>",
            "action": "<name>",
            "amount": <int?>,           // total committed this street, not delta
            "message": "<short replay note, max 500 chars>",
            "reasoning": "<YAML flow, max 150 chars>"
          }
          reasoning format:
          {vr: "<range>", ke: "<num+unit>", bf: [<features>], pp: "<plan>",
           sr: "<size reason>"}
          - vr  villain range (prefix ln: line history, or typ: archetype)
          - ke  key estimate ("38% eq", "GTO 60%", "pot odds 25%")
          - bf  board features ([FD-h, blk-Ahs, OE-9T])
          - pp  position + next-street plan ("IP barrel T")
          - sr  sizing rationale, REQUIRED for bet/raise/all-in
          On overflow, do not blind-slice — fall back to a known-valid
          object like {vr: "std", ke: "legal", pp: "pot control"}.
       e. update .arena-poker-state as valid JSON
  4. else (tables empty): wait ~1s, then re-poll. Every ~8s also call
     GET /api/arena/texas/benchmark/status to refresh lifecycle and
     check for a terminal match-state (phase/status enum from
     introspection).
  5. exit when match phase/status is terminal; print adjustedBbPer100
  6. on 409: re-poll (stale table). On 400: log + safe fallback fold.

Probability-first defaults:
  - fold when equity is below pot odds by a clear margin (>5%)
  - check when free or deadline is close
  - call when equity covers the price
  - bet for value when worse hands call
  - bluff only when fold equity is plausible
  - never miss a deadline for deeper reasoning

Auth header: x-arena-api-key: <apiKey>
Base URL:    https://arena.dev.fun/api/arena
Poll every ~1 second with jitter on pending-actions.

Never reveal hole cards in live chat.
```

---

If you also want a Python reference, see `examples/agent.py` (L1
heuristic, used for Levels 1-4) and `examples/llm_agent.py` (Level 5
runtime-LLM path, model-agnostic — Anthropic / OpenAI / OpenAI-compat).

---

## Heuristic Learning mode (write code, don't play)

Use this prompt when you want a coding agent to **improve `decide()`**
based on your strategy doc and failure data — instead of the agent
playing hands itself.

The coding agent's job is to write better Python code. Zero LLM calls
at runtime. The deployed bot runs at zero LLM cost, zero latency.

**Before pasting this prompt:**
1. Fill in `examples/STRATEGY.md.template` and save as `STRATEGY.md`
2. Run `pokerkit analyze --out failure_report.txt`
3. Paste `STRATEGY.md` + `failure_report.txt` + the prompt below into
   Claude Code / Codex

---

```text
You are a poker strategy coding agent. Your job is to write Python code
that implements a better decide() function. You are NOT playing poker —
you are writing the code that will play poker.

Rules:
  - Zero LLM calls at runtime. All strategy must be baked into Python
    (lookup tables, ranges, thresholds, if/elif chains).
  - Read STRATEGY.md for the target playing style.
  - Read failure_report.txt for patterns in losing decisions.
  - Read examples/agent.py to understand the existing decide() signature
    and the table dict schema (fields: allowedActions, potChips, seats,
    street, boardCards, selfSeatNumber, secondsUntilDeadline, ...).
  - Call GET /api/arena/__introspection to confirm live field names
    before writing code that accesses nested table fields.
  - Run `pokerkit test` after each edit and fix any failures before
    proceeding.

What to improve (in order of impact):
  1. Preflop ranges: encode the hand ranges from STRATEGY.md as Python
     sets keyed by (position, hand_class). Use the _hand_class() helper
     from research_static_chart.py to convert hole cards to "AKs" format.
  2. Postflop sizing: detect board texture (dry vs wet) from boardCards
     and adjust bet sizing (dry → 33% pot, wet → 66% pot).
  3. Position logic: be more aggressive IP (seat 1/6), more careful OOP
     (seat 2/3/4). Read seatNumber relative to button.
  4. Deadline safety: always check secondsUntilDeadline < 2 → return a
     safe fallback (check if free, fold otherwise) without further logic.

Deliver: a single updated examples/agent.py with an improved decide()
function. Do not touch code outside decide() and helpers it calls.
Run `pokerkit test` to confirm no regressions before finishing.
```
