# Path: learn — explain Arena, bb/100, and the 4 stages before any code

> **First-turn handshake — abbreviated form for `learn`.** Per the
> `learn`-path exception in `SKILL.md`, do NOT print the full 4-bullet
> scope check. Surface ONE line: "I won't touch any files on this
> path — it's read-only. OK to proceed?" Wait for `yes`/`go`, then
> proceed to Section 1.

> Loaded when the user replies `learn` / `tell me more` / `explain` /
> `more`. Goal: answer the three questions every new user
> actually has, then route to `build` or `iterate`. No code, no clone.
> Each section ≤ 120 words. End every section with "ready to build one?"

---

## Section 1 — dev.fun Arena vs Poker Arena vs Poker Eval

```
**dev.fun Arena** is a public leaderboard where AI agents compete on
real benchmarks. Different game types live as separate competitions.

**Poker Arena** is the upcoming **tournament** — significant prize
pool (~$50K), top finishers may be invited to a Researcher Track.
Not open yet, date TBA.

**Poker Eval** is the **training arena** open right now: same engine,
same opponent reference panel, same scoring, no prize, no stakes. It's
where you build, iterate, and tune your bot before Poker Arena opens.
Leaderboard is daily and public — climbing it is proof your bot's
ready.

You build here. You compete there (later).
```

If the user asks "what does the bot actually do?", answer briefly:

```
Pure code-vs-code. Arena's server runs the poker engine, deals cards,
enforces rules. It sends your bot a JSON snapshot of the table state
("you have AhKd, pot is 300, opponent bet 150, board is Qh7c2s") and
asks "what's your action?"

Your bot is a Python `decide()` function that reads that snapshot and
returns one of: fold, call, raise <amount>, check, all-in. No vision,
no buttons, no LLM required.
```

---

## Section 2 — bb/100 and the test size

```
**bb/100** = big blinds won (or lost) per 100 hands. The standard
poker metric, used because session P/L is noisy.

  +10 bb/100 = winning ~10 big blinds per 100 hands — strong
    0 bb/100 = break-even
  -25 bb/100 = losing ~25 bb per 100 hands — normal first bot
  -200       = random play
  +50        = natural ceiling vs current panel

Test size against Arena's reference panel:

  500-hand match    ~15 min   ±20 bb/100 CI

500 hands is noisy (±20 means a bot at -10 and one at +5 might be
equal). Run the full 500 hands in one continuous run — disconnecting
mid-match can timeout the match and invalidate your score.
```

---

## Section 3 — The reference panel + the 4 stages

```
**The reference panel.** Every Arena run pits your bot against the
same 5 strong bots Arena maintains. Currently DeepCFR-style trained
agents — not LLMs, trained on millions of self-play hands. The lineup
may rotate; tuning vs the current panel transfers because strong
fundamentals win against all of them.

**The 4 stages — each closes ~10 bb/100 of the gap:**

  Stage 1  Style          ~-25 bb/100   (style label, decide() updated)
  Stage 2  Strategy.md    ~-15 bb/100   (real ranges + sizing, yours to edit)
  Stage 3  Auto Research  ~-5  bb/100   (GTO + HUD data baked into decide())
  Stage 4  Curriculum     ~+3  bb/100   (run → analyze → patch → repeat)

Anchors used in every score render:

  random bot           ~-200
  Stage 1              ~-25
  Stage 2              ~-15
  Stage 3              ~-5
  Stage 4              ~+3
  Top human-designed   ~+10

Most users walk through 1 → 2 → 3 → 4 in ~1 hour. All free.
```

---

## Where to look in the repo

Since you're exploring before committing, here's the map — read-only
inspection, agent will touch these for you later if you pick `build`
or `iterate`:

```
GitHub: https://github.com/devfun-org/poker-arena-starter-kit

Key files:
  SKILL.md                          — top-level entrypoint
  paths/{learn,build,iterate}.md    — what your agent follows
  examples/agent.py                 — your bot, your decide()
  examples/STRATEGY.md.template     — template Stage 2 fills in
  examples/research_static_chart.py — example Stage 3 data pull
  assets/decide_{baseline,ranged,textured}.py — reference impls
  references/agent-rules.md         — operating rules (security)
  references/network-policy.md      — host allowlist
  .env.example                      — env vars (no secrets shipped)
  pokerkit                          — CLI wrapper script
```

---

## After all three sections — route the user

```
That's the setup. Ready to actually build one?

  • `build`   — write a fresh bot from scratch (20-45 min). I'll ask
               one more question after install: fast mode (defaults)
               or hands-on mode (4 EV decisions + edit STRATEGY.md).
               ← default if you press enter

  • `iterate` — improve a bot you already have in this repo (25 min
               to 1 hr). I'll look at your last match's logs and
               patch the biggest leak per round.

  • `stop`    — chew on this and come back later. Nothing is saved
               from this `learn` pass — re-trigger the kit any time
               and start clean.

Type one.
```

---

## Topics to expand on if asked (not unprompted)

| User asks | Quick answer | Deeper file |
|---|---|---|
| "what's the test size?" | 500-hand = ~15 min, ±20 CI. Run the full 500 hands in one go. | `references/poker-eval-arena.md` |
| "what's an Auto Research source?" | GTO preflop chart, board-texture buckets, opponent HUD via `/texas/agent-stats`. All offline lookups; zero LLM calls at runtime. | `references/optimization-levels.md` Level 3 |
| "what's Curriculum / HL loop?" | Stage 4 loop: run 500-hand → analyze → patch one losing pattern → re-run. To plateau. | `references/heuristic-learning.md` |
| "can I use an LLM in decide()?" | Yes — Level 5 (paid, slower). Most strong bots are pure Python. L5 is on top of Stage 4. | `references/optimization-levels.md` L5 |
| "prize on Poker Arena?" | ~$50K pool, tournament not open yet. Poker Eval has no prize. | (Danny will confirm public number) |

---

## Beyond Stage 4 — only if asked

```
The Stage 4 HL loop ceiling is roughly -3 to +5 bb/100. The leaderboard
top lives above that — solver-lookup + trained-weights territory, not
hand-written heuristics. Open-source landmarks worth knowing:

  • Pluribus (CMU/Facebook 2019) — MCCFR self-play, beat human pros
  • DeepMind open_spiel — DeepCFR / NFSP / CFR+
  • rlcard — RL training framework
  • TexasSolver — open-source GTO post-flop solver
  • Slumbot — public HU NLHE bot
  • PokerBench (Penn State 2025) — academic 6-max benchmark

~1 week + GPU project. This kit doesn't take you there; it gets you
ready for that roadmap.
```

---

## What `learn` does NOT do

- Walk through all 6 levels — that ladder is revealed during Stage 4
- Quote a specific Poker Arena prize beyond ~$50K
- Teach poker theory — the agent writes code, not runs a poker school
- Start any code or file changes — read-only until path pick
