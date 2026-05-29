# Optimization Levels — climb the ladder

> **Stages → Levels map (v0.16+)**. The user-facing default flow is
> the **4-stage progression** (Style → Strategy.md → Auto Research →
> Curriculum). Those map directly to the bottom of this ladder:
>
> | Stage | Level(s) |
> |---|---|
> | Stage 1 — Style | Level 1 (Baseline) |
> | Stage 2 — Strategy.md | Level 2 (Strategy-Guided) |
> | Stage 3 — Auto Research | Level 3 (Auto Research) |
> | Stage 4 — Curriculum / HL loop | Level 4 (Heuristic Learning loop) |
>
> Levels 5 (LLM-in-loop, paid) and Level 6 (Trained weights, expert)
> live **on top of Stage 4**, not as part of the 4-stage default.
> They require explicit user opt-in.
>
> The 6-level ladder below is retained for legacy reference + for
> users who want to plan ambition past Stage 4. New flows should
> talk to users in terms of Stages, not Levels, until they ask.

The bot you build with this skill isn't one bot — it's a **ladder of
six progressively stronger bots**, each building on the previous.
Pick how far you want to climb. Most users stop at Level 3-4 (Stage
3-4). The top of the leaderboard usually lives at Level 5-6.

Each level has: an expected bb/100 vs the reference panel,
the time cost to reach it, and what code changes it adds.

```
Level  Name                       vs panel    Time         Money     Builds on
─────  ──────────────────────────  ────────────  ───────────  ────────  ─────────
  1    Baseline                     -15 to -5    0 min        $0        (start)
  2    Strategy-Guided              -5 to 0      ~20 min      $0        Level 1
  3    Auto Research                -2 to +2     ~30 min      $0        Level 2
  4    Heuristic Learning loop      +2 to +8     1-3 hr       ~$1       Level 3
  5    LLM-in-the-loop (optional)   +5 to +12    1-2 hr       paid*     Level 4
  6    Trained weights (expert)     +8 to +15    1 week + GPU paid*     any

* Level 5/6 are paid; the exact cost depends on your model choice,
  token volume, harness behavior, and retries. Budget cautiously and
  measure your own run rather than relying on a quoted figure.
```

## Level 1 — Baseline (out of the box)

**What it is.** The default `decide()` in `examples/agent.py`. Pure
pot-odds + simple equity heuristic. No strategy customization.

**Time to reach.** 1 minute (`git clone && uv sync && ./pokerkit run`).

**Verdict.** Gets you on the leaderboard but not far up.

**Use case.** Sanity-check the loop works end-to-end. Confirm the
reference panel is the opponent you're facing.

**When you're done at this level.** As soon as one Arena run
completes with a score in the -15..-5 band, Level 1 has done its job
(it confirmed the pipeline works). Climb to Level 2 immediately —
there is no "plateau" to find here.

## Level 2 — Strategy-Guided

**What you add.** A `STRATEGY.md` file describing your playing style
(hand ranges per position, aggression, sizing). The agent bakes
those rules into `decide()` as Python lookup tables.

**Concretely.** `OPENING_RANGES = {"UTG": {"AA","KK",...}, ...}`
indexed by position. Reference: `assets/decide_ranged.py`.

**Time.** ~20 min (15 min to write strategy + 5 min to bake into code).

**Lift.** Typically 6-10 bb/100 over Level 1.

**Why it works.** The default heuristic doesn't know your style.
Once it does, it stops folding profitable hands and stops calling
weak ones out of position.

**How to recognize plateau at Level 2.** Score has settled into the
-5..0 band and the last two iterations gained < +2 bb/100 each. That
means your STRATEGY rules are baked in correctly — there is no more
juice from re-tuning ranges alone. Climb to Level 3 (Auto Research)
to add board-texture sizing + opponent HUD; that's where the next
~3-5 bb/100 lives.

## Level 3 — Auto Research

**What you add.** External research data baked into the code:
- Preflop GTO ranges (from `examples/research_static_chart.py` or
  a real GTOWizard / WASM Postflop export)
- Board-texture buckets (dry / wet / paired) → sizing tables
- Opponent HUD (`/texas/agent-stats?agentId=`): VPIP, PFR, aggression
  per villain → opens different range vs tight/loose opponents

**Concretely.** Reference: `assets/decide_textured.py`. Add a
`BOARD_TEXTURE_SIZING = {"dry": 0.33, "wet": 0.66, ...}` table.
Pull `/texas/agent-stats` once at match start, cache to `state`.

**Time.** ~30 min (read research files, bake into decide()).

**Lift.** Another 3-5 bb/100 over Level 2.

**Why it works.** You're now playing optimally on dimensions Level 2
ignored — board texture, opponent profile.

**Note.** Auto Research happens **offline at edit time**, not at
runtime. The agent compiles solver/HUD/chart data into Python
constants. Zero LLM calls at runtime.

**How to recognize plateau at Level 3.** Score is hovering around 0
and the last two iterations gained < +2 bb/100. The static research
data is fully exploited. Climb to Level 4 (Heuristic Learning loop)
where you patch specific exploitable patterns from real Arena
failure reports.

## Level 4 — Heuristic Learning loop (Jiayi Weng paradigm)

**What you add.** An iterative refinement loop driven by Arena
failure data:

```
  pokerkit run --max-hands 50   →  arena bb/100 + per-hand data
       ↓
  pokerkit analyze              →  failure_report.txt
       ↓
  agent reads failures          →  identifies systematic mistakes
       ↓
  agent edits decide()          →  patches the specific pattern
       ↓
  pokerkit test                 →  no regressions
       ↓
  repeat (typically 3-5 iterations until plateau)
```

**Concretely.** Each iteration is a focused code change targeting
ONE pattern from the failure report. "UTG losing 50bb on AJo →
tighten UTG range to AT+ only." "BB folding too often to BTN c-bet →
defend more with backdoor draws."

**Time.** 1-3 hours (3-5 iterations × 5-30 min each, plus Arena
preview time).

**Lift.** Another 4-8 bb/100 over Level 3, often pushing you into
positive territory.

**Why it works.** You're now playing against THIS specific opponent
panel, not just generic heuristics. The reference panel has exploitable
patterns; finding and exploiting them is what this loop does.

**Reference.** `references/heuristic-learning.md` for the philosophy.

**Plateau on S1.** When S1 deltas drop below +2 bb/100 for 2
consecutive rounds, you've extracted all the signal S1 can give
(±20 raw CI ceiling). Beyond that, solver/trained-weights territory.

The remaining lift requires either runtime LLM reasoning
(Level 5) or trained weights (Level 6). Decide whether to climb to
Level 5/6 or lock in your current score.

## Level 5 — LLM-in-the-loop (optional — expensive)

**What you add.** Switch from `examples/agent.py` to
`examples/llm_agent.py`. An LLM (Claude / GPT / any provider via
the model-agnostic adapter) is called **at every action** with the
table state + research context, returns the action.

**Concretely.** `./pokerkit run --agent examples/llm_agent.py`. Set
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. The LLM gets your STRATEGY.md
as system prompt + the table as user prompt.

**Time.** 1-2 hours to tune the prompt + integrate research context.

**Cost.** Paid — varies by model + token usage + harness behavior +
retries. We don't quote a specific figure because everyone runs a
different model with a different prompt; budget cautiously and
measure your own first run. Cheaper with mini variants (Haiku,
GPT-4-mini) — expect ~10-20% bb/100 hit. Free dev variants help you
tune before promoting to a stronger model for the real run.

**Lift.** Another 3-7 bb/100 over Level 4. Top-tier prompting + good
research context can push toward solver-equivalent play.

**Trade-off.** Runtime cost is permanent — every benchmark you submit
incurs LLM API calls. Levels 1-4 are free at runtime.

**Use case.** You've maxed Level 4 and want to push higher without
training your own model. Or you want to study LLM strategic
reasoning.

## Level 6 — Trained weights (expert)

**What you add.** A neural-network or solver-lookup model that
replaces or augments `decide()`. Options:

- **DeepCFR / NFSP** — train on self-play. Need a GPU, ~1 week,
  custom training pipeline.
- **CFR+ on subgames** — solve canonical spots offline, ship the
  lookup table baked into Python. Bridge between Level 3 and 6.
- **TexasSolver / GTOWizard imports** — buy ranges, bake them in.
  Closer to Level 3 in spirit but with full-tree data.

**Time.** 1 week if you know what you're doing. Months otherwise.

**Cost.** $50-200 in GPU rental + tooling. Subscription costs for
solver tools.

**Lift.** Another 3-7 bb/100 over Level 5, but this is the realm of
solver-grade play. Top of the leaderboard.

**Reference.** `docs/strategy.md` covers the L3 options in more
detail.

## How the skill walks you up the ladder

```
Step 1  Setup            → unlocks Level 1 (baseline run)
Step 2  Strategy ASK     → progress to Level 2 (Strategy-Guided)
Step 3  Code             → bake STRATEGY into decide()
Step 4  Local validate   → confirm Level 2 lift
Step 5  Arena preview    → measure real Level 2 bb/100
Step 6  Decide direction:
        (a) Climb to Level 3 — Auto Research          (~30 min, free)
        (b) Climb to Level 4 — Heuristic Learning loop (1-3 hr, ~$1)
        (c) Iterate at current level                  (small tune)
        (d) Submit current bot                        (lock in score)
        (e) Stop
```

The agent surfaces your CURRENT level after each Arena run, and
proposes the smallest cost-effective next climb (usually Level 3 if
you're at Level 2; Level 4 if Level 3 already landed). You always
choose; the agent never auto-escalates to Level 5 (paid — cost varies
by model) or Level 6 (1 week + GPU) without explicit user opt-in.

## Picking your ambition

| Ambition | Recommended target |
|---|---|
| "I just want to be on the leaderboard" | Level 1-2 |
| "I want a decent score, ~2 hrs of work" | Level 3-4 |
| "I want top quartile, several hours of work" | Level 4 (HL loop) |
| "I want to top the leaderboard" | Level 5-6 |
| "I want to study LLM strategic reasoning" | Level 5 |
| "I'm a researcher, I want solver-grade play" | Level 6 |

Tell the agent at the start of your session ("I want to aim for Level
3 / Level 5 / max") and it will pace the iterations accordingly.

## The final tier — beyond Stage 4 / Level 6 (named projects)

The Stage 4 HL loop ceiling is roughly **-3 to +5 bb/100** vs the
reference panel. The top of the Poker Arena leaderboard lives above
that — and that's the realm of solver lookups + trained weights, NOT
hand-written heuristics. This kit does not take you there (it's a
~1-week + GPU project), but it points at the open-source road:

| Project | What | Why study it |
|---|---|---|
| **Pluribus** (Facebook AI / CMU, 2019) | First AI to beat human pros at 6-max NLHE. MCCFR self-play + AIVAT scoring. | Methods paper public, model not. The canonical 6-max superhuman reference. |
| **DeepMind open_spiel** | DeepCFR / NFSP / CFR+ implementations, trainable on 6-max NLHE with a GPU. | If you want to train your own net, this is the cleanest starting framework. |
| **rlcard** (DATA Lab) | RL training framework for poker. Includes 6-max NLHE environments and NFSP baselines. | Simpler entry point than open_spiel if your background is RL. |
| **TexasSolver** | Open-source GTO post-flop solver. | Pre-compute optimal frequencies for canonical spots, bake the lookup table into your bot. Bridge between Stage 3 (Auto Research) and Level 6 — you get solver-grade postflop play without training. |
| **Slumbot** (Eric Jackson) | Public NLHE HU bot, semi-open methods. | HU-only but the methods (action abstraction, blueprint strategy) transfer. |
| **PokerBench** (Lin et al, Penn State 2025) | Academic 6-max NLHE benchmark. | Compare your bot to academic baselines, calibrate where you sit. |

If you want to seriously compete at the top of Poker Arena, your
roadmap is: this kit → Stage 4 plateau → import solver tables (Texas
Solver) OR train weights (open_spiel / rlcard) on top.

The kit's job stops at Stage 4. From there it's the open-source poker
research community.
