"""Example: how to unit-test YOUR `decide()` against canonical spots.

⚠️  DELETE THIS FILE when you ship your own tests — it exists only to
    show you the pattern. Copy the imports and one of the test bodies
    into your own `tests/test_my_decide.py`.

Why this exists: iterating "did my new bluff logic work?" through a
30-minute live S1 match is glacial. The scenarios in `examples/testing.py`
give you 20 canonical spots in the exact shape the live API returns,
so a full pass costs ~50ms.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make examples/ importable when running pytest from the repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples"))

import agent as agent_mod  # noqa: E402
from testing import Scenario, scenarios, get_scenario  # noqa: E402


# ─── 1. Smoke: every scenario produces a legal action ───────────────────────

def test_every_scenario_runs_through_decide():
    """Replace `agent_mod.decide` with YOUR decide() and run this test
    against the full canonical 20-spot corpus. Every action must be
    legal and the reasoning YAML must be present + under 150 chars."""
    count = 0
    for sc in scenarios():
        action = agent_mod.decide(sc.table, deadline_s=10.0)
        legal = set(sc.table["allowedActions"]["availableActions"])
        assert action["action"] in legal, (
            f"{sc.name}: illegal action {action['action']!r} "
            f"(legal={sorted(legal)})")
        assert "reasoning" in action and len(action["reasoning"]) <= 150, (
            f"{sc.name}: reasoning missing or too long: "
            f"{action.get('reasoning')!r}")
        assert "message" in action and 1 <= len(action["message"]) <= 500
        count += 1
    assert count == 20, f"expected 20 scenarios, got {count}"


# ─── 2. Targeted: AA UTG must raise (or call if no raise legal) ─────────────

def test_aa_utg_is_aggressive():
    sc: Scenario = get_scenario("preflop_premium_AA_utg")
    action = agent_mod.decide(sc.table, deadline_s=10.0)
    assert action["action"] in ("raise", "call", "all-in"), (
        f"AA UTG should not fold/check, got {action['action']!r}")


# ─── 3. Targeted: 72o vs 3-bet must fold ────────────────────────────────────

def test_72o_facing_3bet_not_a_value_raise():
    """L1 heuristic uses a default-0.45 equity for 72o (not in the chart),
    so the assertion is conservative: never raise/all-in junk hands vs a 3-bet.
    Swap to `action == 'fold'` once you wire a real equity estimator."""
    sc: Scenario = get_scenario("preflop_trash_72o_bb_facing_3bet")
    action = agent_mod.decide(sc.table, deadline_s=10.0)
    assert action["action"] not in ("raise", "all-in"), (
        f"72o vs 3-bet should never raise/jam, got {action['action']!r}")


# ─── 4. Skeleton agent integration (proves --agent <path> works) ────────────

def test_skeleton_agent_pluggable_and_returns_valid_action():
    """Load examples/skeletons/always_fold.py via the same loader the
    `--agent` CLI flag uses, run it against a scenario, and confirm the
    shape matches what /texas/action expects."""
    skeleton_path = ROOT / "examples" / "skeletons" / "always_fold.py"
    assert skeleton_path.exists(), skeleton_path
    fn = agent_mod.load_external_decide(str(skeleton_path))
    sc: Scenario = get_scenario("flop_top_pair_oop")
    action = fn(sc.table, deadline_s=10.0)
    assert isinstance(action, dict)
    assert action.get("action") in sc.table["allowedActions"]["availableActions"]
    assert isinstance(action.get("reasoning"), str) and 1 <= len(action["reasoning"]) <= 150
    assert isinstance(action.get("message"), str) and 1 <= len(action["message"]) <= 500
