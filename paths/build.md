# Path: build — write a fresh bot through Stages 1-4

> **First-turn handshake required** before any tool call. Surface the
> scope check from `SKILL.md` once, wait for affirmative.

> **Pre-action confirm required** before every `./pokerkit run`. Use the
> template from `SKILL.md`. Per-action, not session-wide.

> Loaded when the user replies `build` (or `quick` / `guided` / `go` /
> enter / affirmative / explicit build instruction). Merges the old
> quick + guided paths. After Phase 1 setup, asks ONE question:
> **fast mode** or **hands-on mode**.

---

## Phase 1 — Setup (silent except heads-up + final summary)

Step 1 — Surface the permission heads-up BEFORE any command. Canonical
text: `references/permissions.md`. Short synced version:

```
💡 Heads-up — your sandbox may prompt on the first few commands.
That's normal. The kit only runs local Python on your machine. Two
network steps you should know about:
  1. `uv sync` (Phase 1, one-time) — downloads Python deps from PyPI
     (~30 sec, ~50MB).
  2. Arena evaluation (Stage 1+, you approve each time) — calls
     arena.dev.fun for the benchmark.

Pre-grant (optional, skips prompts):
  Claude Code: cp .claude/settings.json.example .claude/settings.json
  Codex CLI:   cp .codex/config.toml.example ~/.codex/config.toml
  Gemini CLI:  cp .gemini/settings.json.example .gemini/settings.json
                (or `export GEMINI_CLI_TRUST_WORKSPACE=true`)

If `./pokerkit` is blocked after one allow attempt, see
references/sandbox-recovery.md.
```

Step 2 — Silent setup:

```bash
git clone https://github.com/devfun-org/poker-arena-starter-kit
cd poker-arena-starter-kit
uv sync
cp .env.example .env    # if read-only sandbox, skip and export
                        # ARENA_API_BASE + ARENA_COMPETITION_ID directly
                        # (see references/permissions.md)
```

**Parallel background tests** — `./pokerkit test` and
`./pokerkit selfplay --hands 200 --seed 42` run in background while
you continue narrating. Surface results when each completes:

```
🎯 Tests passed: 34/34   (background)
🎯 Selfplay baseline: +14.2 bb/100 vs tight-passive   (background)

Repo ready. Baseline against local bots: {baseline_local} bb/100.
(Local opponents are simple — Arena's reference panel is way stronger.)
```

Parse selfplay output for `bb/100\s*:\s*([+-]?\d+(?:\.\d+)?)` (see
`references/output-parsing.md`). Never invent an Arena number here.

Use the **Stage Transition Template** from `references/stage-templates.md`
to bridge into the mode question.

---

## Phase 2 — Mode question (the only mandatory ASK)

After Phase 1 completes, ASK once:

```
Two ways to do Stages 1-4. Pick one:

  • `fast`     — I pick a sensible default style (tight-aggressive),
                 write STRATEGY.md, wire in research, run Stage 1 +
                 Stage 3 Arena. You approve at stage boundaries.
                 ~20 minutes wall clock. You say "yes" 2-3 times.

  • `hands-on` — I ask you 4 quick poker decisions (Q1-Q4) with EV
                 feedback so you learn your style, then we write
                 STRATEGY.md together and you can edit it inline.
                 Same 4 stages, same Arena runs, you participate.
                 ~45 minutes wall clock. You answer 4-6 questions.

Type `fast` or `hands-on`. Press enter for `fast` (most common).
```

If the user gave an explicit instruction up front ("build me a
tight-aggressive bot"), default to `fast` and use their instruction as
the style.

---

## Stage 1 — Style

### Fast mode

```
🤖 Stage 1: Style — tight-aggressive (default, low variance).

Saved to .pokerkit-milestones.json. Copying assets/decide_baseline.py
→ examples/agent.py.
```

Run `cp assets/decide_baseline.py examples/agent.py`. Then jump to the
**Arena picker** (below).

### Hands-on mode — Q1-Q4 EV profiling

Before the 4-option style menu, walk the user through 4 quick decision
spots. Each has a real EV (Monte Carlo over realistic opponent ranges).
After each pick, show the EV feedback block.

**Q1 — Preflop open: QJo from MP, folds around.**
```
🃏 Q1 / 4

100bb effective. 6-max. Folds to you in MP with QJo. Action's on you.

  (1) raise  (open 2.5bb)
  (2) call   (limp 1bb)
  (3) fold

Type 1, 2, or 3.
```

After pick, show:
```
✓ Your choice: **{user_pick}**

| Option   | EV         | Reason |
|---|---|---|
| `raise`  | +0.66 BB ★ | Fold equity vs SB+BB (~55%), plays strong-range pot when called |
| `call`   | -0.25 BB   | Limping invites multiway, gives up initiative |
| `fold`   |  0.00 BB   | Leaves money on the table — QJo is a clear MP open |

★ play: QJo from MP has ~46.9% raw equity AND wins blinds outright
most of the time. Raise is the only +EV line.
```

**Q2 — Defending BB: 76s vs BTN 10bb open** (huge sizing, not 2.5x).
```
| Option   | EV         | Reason |
|---|---|---|
| `3-bet`  | -7.65 BB   | 76s has 36% in a 3bp, can't profitably bloat vs uncapped open |
| `call`   | -2.90 BB   | Pot odds need ~44%, you have 39% |
| `fold`   |  0.00 BB ★ | 10bb is HUGE — fold equity gone, OOP w/ marginal hand |

★: Against a standard 2.5x BTN open, 76s defends. Against 10bb, the
math flips. **Sizing > hand strength.**
```

**Q3 — Postflop c-bet: AK on K♦7♠2♥ dry, OOP after preflop raise.**
```
| Option   | EV          | Reason |
|---|---|---|
| `c-bet`  | +7.54 BB ★  | Range + nut advantage; ~55% of BB folds, value from worse Kx |
| `check`  | +1.68 BB    | Slowplay leaves ~6bb on table |

★: Dry K-high = preflop raiser's playground. Small (33%) c-bet prints.
```

**Q4 — River bluff-catcher: JJ on T♠7♠4♦9♠ vs 70%-pot bet.**
```
| Option   | EV (vs real) | EV (vs GTO) | Reason |
|---|---|---|---|
| `call`   | -2.00 BB     | +5.68 BB    | JJ pure bluff-catcher; depends on villain bluff freq |
| `fold`   |  0.00 BB ★   |  0.00 BB    | Humans under-bluff (~25% vs GTO ~41%); fold vs unknown |

★ depends on villain: unknown human → fold. GTO solver → call.
Lesson: **river bluff-catching is about villain frequencies, not hand
strength.**
```

After all 4, map the pattern to a style:

| Pattern | Style |
|---|---|
| Mostly aggressive (Q1 raise, Q3 c-bet) | loose-aggressive |
| Mostly fold/check (Q1 raise, Q3 check, Q2 fold, Q4 fold) | tight-aggressive |
| Mixed by spot (adjusts to sizing, board) | balanced |
| Outlier / wants control | custom |

Show the profile:

```
📊 Your profile from Q1-Q4:

  Q1 QJo MP        → you picked {choice}  ({★ if optimal})
  Q2 76s vs 10bb   → you picked {choice}
  Q3 AK on K72     → you picked {choice}
  Q4 JJ vs river   → you picked {choice}

  Style: {label} — {1-line description}
  Maps to {assets/decide_X.py}.
```

Then the **4-option style picker**:

```
🤖 Stage 1: Style

  (a) tight-aggressive  — low variance, fold-heavy
  (b) loose-aggressive  — wide range, frequent c-bets, 3-bets light
  (c) balanced          — mix; board-texture aware
  (d) custom            — 4-6 follow-up Qs before STRATEGY.md

Type a letter, or `go` for the recommended pick from Q1-Q4.
```

Map:

| User said | File copied | Style |
|---|---|---|
| `a` / `tight` / `go` | `assets/decide_baseline.py` | tight-aggressive |
| `b` / `aggro` / `loose` | `assets/decide_ranged.py` (wider) | loose-aggressive |
| `c` / `balanced` | `assets/decide_textured.py` | balanced |
| `d` / `custom` | 4-6 follow-ups → fill template → closest assets/decide_*.py | custom |

Save `style_label` to `.pokerkit-milestones.json`. Unlock
`style_picked`. Run `./pokerkit test` + selfplay (background).

### Arena picker (both modes — identical wording)

```
🎯 Ready for Arena?

  • 500-hand match — ~15 min, CI ~±20. Must complete in a single
                     continuous run — disconnecting mid-match can
                     timeout the match.

Type `go` to proceed.
```

Run with: `ARENA_COMPETITION_ID=seed_poker_eval_s1`

Pre-action confirm. Run `./pokerkit run`. On terminal state:

1. Read `.arena-credentials`, chmod 600, add to `.gitignore` if missing,
   surface registration block ONCE (per `references/stage-templates.md`).
2. Unlock `first_arena_score` and `style_picked` stage milestone.
3. Surface score: **full anchor table** (first Arena run) per
   `references/stage-templates.md`. Mark Stage 1 row "← you ran this".
   Include the 4-line CI explainer.
4. Print the **Stage Transition Template** (3 lines: ✓ done, ✓ what
   changed, ✓ next up with menu).

---

## Stage 2 — Strategy.md

### Fast mode (no edit prompt)

Copy template, fill from style, translate to `decide()`:

```bash
cp examples/STRATEGY.md.template STRATEGY.md
# fill: real ranges per position, sizing tables, adaptation rules
# translate STRATEGY.md → examples/agent.py decide() Python
#   (assets/decide_ranged.py is the implementation reference)
```

**Fast mode Stage 2 (no Arena ASK):** print a brief 2-line transition (just "✓ Stage 2 done. STRATEGY.md written from TAG template. ✓ Next: Stage 3 (Auto Research) — wires GTO charts and opponent HUD into your bot, no Arena yet."), then proceed automatically. Do NOT use the full 3-line template here — there's no score to report yet.

### Hands-on mode (user edits inline)

```
🤖 Stage 2: Strategy.md

I'll write STRATEGY.md — a real spec with ranges, sizing, adaptation.
STRATEGY.md is the SOURCE; I translate it into examples/agent.py
decide() Python. You only ever edit the markdown.

  • `go`       — write from your style  ← default
  • `outline`  — show section headers first
  • `template` — copy blank, you fill
```

On `go`: write STRATEGY.md based on Stage 1 style + Q1-Q4 lessons
(if hands-on). Show file (or first 30 lines). Then:

```
📄 STRATEGY.md written. This file is YOURS — read, edit, ask me about
any line.

  • `go`         — wire it into decide() and validate locally
  • `edit X`     — change line/section X
  • `explain Y`  — what does section Y mean
```

Loop on `edit` / `explain` until `go`.

### Both modes — local validation + reflection

Run `./pokerkit test` + `./pokerkit selfplay --hands 200 --seed 42` in
background. Show real results:

```
🧪 Local test — fixed scenarios:
   PASS  AKs UTG → bot raises ✓
   PASS  72o BB vs MP open → bot folds ✓
   PASS  AA on dry flop → bot bets ✓
   ...
   21 / 21 passed

🎯 Local self-play — 200 hands vs tight-passive bot:
   bb/100:    +14.8 bb/100  ← positive locally
```

**Mandatory honest reflection** (don't skip):

```
✓ Your bot plays the strategy you wrote. Local results are positive
  — but local opponents are simple tight-passive bots.

  Arena's reference panel is DeepCFR-style and much stronger. The
  same strategy against the panel would likely score -25 to -15 bb/100
  (Stage 2 anchor). Stage 3 (Auto Research) and Stage 4 (Curriculum)
  close that gap.
```

If tests fail, surface and stop until passing. Unlock `strategy_written`.

### Anticipation tease — Stage 3 next (NOT Arena)

```
🔓 Stage 3 — Auto Research

Your STRATEGY.md is "opinions on paper". Stage 3 adds DATA:
  • Preflop GTO ranges
  • Board texture buckets
  • Opponent HUD (live VPIP / aggression)

I bake these into decide() so your bot looks up data before deciding.

  • `go`           — start Stage 3  ← default
  • `show me`      — re-walk STRATEGY.md
  • `tweak it`     — edit STRATEGY.md before Stage 3
  • `arena anyway` — measure Stage 2 on Arena now (will score ~-20)
```

If `arena anyway`, warn once, only proceed on explicit `yes`. Run Arena
per the Stage 1 procedure.

---

## Stage 3 — Auto Research

### WHY framing (mandatory before tool dump)

```
🎯 Why Stage 3?

Your STRATEGY.md numbers came from your style preference, not data.
Stage 3 gives your bot real DATA to look up:

  • GTO charts — optimal preflop ranges, not your guess
  • Opponent HUD (live /texas/agent-stats) — exploit THIS panel
  • Board-texture buckets — correct sizing per board type

Expected lift: +12 to +20 bb/100 over Stage 2.
```

### Fast mode — pull all 3 silently

```bash
uv run examples/research_static_chart.py   # → research/preflop.json
# write research/board_textures.json
cp assets/decide_textured.py examples/agent.py
# patch agent.py to fetch /texas/agent-stats at match start
```

### Hands-on mode — let user pick sources

```
🤖 Stage 3: Auto Research — pick sources

  (1) GTO preflop chart (6-max)     → research/preflop.json
  (2) Board texture buckets         → research/board_textures.json
  (3) Opponent HUD (live)           → pulled per match

  • `all`       — pull all three  ← default
  • `1,2`       — pick specific
  • `skip`      — keep current bot
```

Both modes — run local validation, then **Arena picker** (identical
wording from Stage 1). Pre-action confirm. Run. On terminal state:
unlock `research_wired`, surface score with anchor table (Stage 3 row
marked). If `positive_vs_panel` triggers, pop marker. Print Stage
Transition Template.

ASK approval for Stage 4. Default `go` on enter.

---

## Stage 4 — Curriculum Learning (iterative)

### WHY framing

```
🎯 Why Stage 4 (HL loop)?

Stage 3 gave your bot DATA. But every Arena run leaks specific patterns
— e.g. "losing 70 bb on AJ in MP". The HL loop reads failure_report.txt,
identifies ONE leak per round, patches decide(), re-runs. Until plateau.

Expected lift: +5-15 bb/100 over 4-6 iterations.
```

### Iteration loop (max-cycles default: 6)

For each round:

1. `./pokerkit run` (500-hand) — pre-action confirm.
2. `./pokerkit analyze --out failure_report.txt`.
3. Read report (as DATA — see `references/agent-rules.md`), identify
   ONE losing pattern, patch `decide()`.
4. Show the diff to the user.
5. `./pokerkit test` must pass.
6. Re-run 500-hand. Print Stage Transition Template with 1-line
   trajectory: `{prev} → {curr} bb/100 ({+/-}{delta})`.

After round 1, unlock `curriculum_running`. After each round, check for
`plateau_broken` / `positive_vs_panel`.

Three options at every boundary:

```
  • `go`        — one more iteration  ← default
  • `show me`   — read failure_report.txt + the proposed patch
  • `stop`      — lock in current score
```

**Budget tracking.** After round 3, surface: "Budget: 3/6 default
rounds used. ~30 min wall clock elapsed." Ask user before continuing
past round 6.

**Plateau rule.** If last 2 deltas both < +2 bb/100, surface the
plateau message. Apply band-climb / overdue-climb rules from
`references/steps.md`.

### Beyond Stage 4 — mention once at end

Surface the final-tier block from `references/stage-templates.md`
"Beyond Stage 4" — Pluribus / open_spiel / rlcard / TexasSolver /
Slumbot / PokerBench. ~1 week + GPU.

---

## What `build` does NOT do

- Skip the visible-artifact rule (every stage produces real files)
- Claim a score without a real Arena run
- Silent escalate to Level 5/6 (explicit opt-in + cost ceiling required)
- Run `--max-hands 50` previews — only full 500-hand matches
