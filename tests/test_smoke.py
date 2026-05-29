"""End-to-end smoke test using respx to mock the Arena endpoints under
the new contract (pending-actions primary, benchmark/status for terminal).

Validates that examples/agent.py:
- registers exactly once (idempotent on rerun, verified via /agent/me)
- calls /__introspection at startup
- starts a benchmark match
- polls /texas/pending-actions and calls decide() on returned tables
- submits an action body with a valid `reasoning` YAML
- exits cleanly when match phase is terminal (from introspection enum)
- in --dry-run, only hits the mock base URL (never the real arena)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
import pytest
import respx

# Make examples/ importable when running pytest from the repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples"))

import agent as agent_mod  # noqa: E402
import arena_client as arena_client_mod  # noqa: E402


MOCK_BASE = "http://mock.local/api/arena"


def _introspection_payload() -> dict:
    return {
        "endpoints": [
            {"method": "POST", "path": "/api/arena/auth/register", "auth": False},
            {"method": "GET",  "path": "/api/arena/agent/me", "auth": True},
            {"method": "GET",  "path": "/api/arena/__introspection", "auth": True},
            {"method": "POST", "path": "/api/arena/texas/benchmark/start", "auth": True,
             "output": {
                 "properties": {
                     "match": {
                         "properties": {
                             "phase": {"enum": ["queued", "panel_acting",
                                                "waiting_user", "completed",
                                                "cancelled", "failed"]},
                             "status": {"enum": ["Running", "Completed",
                                                 "Cancelled", "Failed"]},
                         }
                     }
                 }
             }},
            {"method": "GET",  "path": "/api/arena/texas/benchmark/status", "auth": True},
            {"method": "GET",  "path": "/api/arena/texas/pending-actions", "auth": True},
            {"method": "POST", "path": "/api/arena/texas/action", "auth": True},
        ]
    }


def _table_state(deadline_at: float) -> dict:
    """Synthetic table where hero must act on the flop."""
    return {
        "id": "tbl_1",
        "tableId": "tbl_1",
        "tableNumber": 1,
        "competitionId": "comp_test",
        "status": "Active",
        "street": "Flop",
        "potChips": 300,
        "currentBet": 100,
        "minRaiseTo": 200,
        "startedAt": 1700000000000,
        "endedAt": None,
        "countdownEndsAt": None,
        "actionDeadlineAt": int(deadline_at * 1000),
        "currentSeatNumber": 1,
        "boardCards": ["Ah", "Kd", "7c"],
        "smallBlindChips": 10,
        "bigBlindChips": 20,
        "buyInChips": 2000,
        "winners": [],
        "seats": [
            {
                "seatId": "s1", "seatNumber": 1, "agentId": "me",
                "agentName": "Me", "agentHandle": "me", "status": "Active",
                "stackChips": 1800, "currentBetChips": 0,
                "totalCommittedChips": 0, "payoutChips": None,
                "holeCards": ["As", "Ks"],
            },
            {
                "seatId": "s2", "seatNumber": 2, "agentId": "opp",
                "agentName": "Opp", "agentHandle": "opp", "status": "Active",
                "stackChips": 1700, "currentBetChips": 100,
                "totalCommittedChips": 100, "payoutChips": None,
                "holeCards": None,
            },
        ],
        "actingSeatNumber": 1,
        "selfSeatNumber": 1,
        "allowedActions": {
            "canFold": True, "canCheck": False, "canCall": True,
            "canBet": False, "canRaise": True,
            "callAmount": 100, "callChips": 100, "callToAmount": 100,
            "minBet": None, "minRaiseTo": 200, "maxCommit": 1800,
            "allInToAmount": 1800,
            "betRange": None,
            "raiseRange": {"min": 200, "max": 1800},
            "canAllIn": True,
            "availableActions": ["fold", "call", "raise", "all-in"],
            "amountSemantics": "toAmount",
            "amountHint": "total committed this street",
            "actionHint": "fold/call/raise to >= 200 / all-in 1800",
        },
        "recentEvents": [],
    }


@pytest.fixture(autouse=True)
def _clean_state(tmp_path, monkeypatch):
    """Move CWD into a temp dir so .arena-credentials and .arena-poker-state
    don't pollute the repo."""
    monkeypatch.chdir(tmp_path)
    yield


def _reasoning_is_valid(reasoning: str) -> bool:
    """YAML flow style under 150 chars, contains at least vr/ke/pp."""
    if not reasoning:
        return False
    if len(reasoning) > 150:
        return False
    if not (reasoning.startswith("{") and reasoning.endswith("}")):
        return False
    for key in ("vr:", "ke:", "pp:"):
        if key not in reasoning:
            return False
    return True


def _start_payload(phase: str = "queued") -> dict:
    return {
        "match": {
            "id": "m1", "competitionId": "comp_test", "agentId": "agent_test",
            "status": "Running" if phase != "completed" else "Completed",
            "phase": phase,
            "targetHands": 10, "completedHands": 0,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": None, "adjustedBbPer100": None,
            "currentTableId": None, "startedAt": 1700000000000,
            "endedAt": None, "error": None,
        },
        "table": None,
        "participant": None,
    }


def _completed_status() -> httpx.Response:
    return httpx.Response(200, json={
        "match": {
            "id": "m1", "competitionId": "comp_test", "agentId": "agent_test",
            "status": "Completed", "phase": "completed",
            "targetHands": 10, "completedHands": 10,
            "rawChipDelta": 250, "rawBbPer100": 12.5,
            "adjustedChipDelta": 200.0, "adjustedBbPer100": 10.0,
            "currentTableId": None, "startedAt": 1700000000000,
            "endedAt": 1700000010000, "error": None,
        },
        "table": None,
        "participant": None,
    })


@respx.mock
def test_full_dry_run_happy_path():
    register_route = respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(200, json={
            "agentId": "agent_test", "apiKey": "test_key_xxx",
            "handle": "pokerkit-starter", "name": "PokerKit Starter",
        })
    )
    me_route = respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={
            "id": "agent_test", "handle": "pokerkit-starter",
        })
    )
    introspection_route = respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )

    start_route = respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json=_start_payload("queued"))
    )

    import time as _time
    deadline = _time.time() + 10.0
    table_state = _table_state(deadline)

    # pending-actions: returns the table on first call, then empty.
    pending_responses = [
        httpx.Response(200, json={"tables": [table_state]}),
        httpx.Response(200, json={"tables": []}),
        httpx.Response(200, json={"tables": []}),
    ]
    pending_route = respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(side_effect=pending_responses)

    # status: queued → completed (after the action lands).
    status_responses = [
        httpx.Response(200, json=_start_payload("queued")),
        _completed_status(),
        _completed_status(),
    ]
    status_route = respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(side_effect=status_responses)

    action_route = respx.post(f"{MOCK_BASE}/texas/action").mock(
        return_value=httpx.Response(200, json={
            "table": table_state, "participant": None,
        })
    )

    rc = agent_mod.main(["--dry-run", "--competition-id", "comp_test",
                         "--max-hands", "0"])
    assert rc == 0, f"agent main returned {rc}"

    assert register_route.call_count == 1, f"register called {register_route.call_count} times"
    # /agent/me only called when cached creds exist — first run does not.
    assert me_route.call_count == 0
    assert introspection_route.call_count == 1
    assert start_route.call_count == 1
    assert pending_route.call_count >= 1
    assert status_route.call_count >= 1
    assert action_route.call_count == 1, f"action called {action_route.call_count} times"

    body = json.loads(action_route.calls[0].request.content)
    assert body["tableId"] == "tbl_1"
    assert body["action"] in ("fold", "call", "raise", "all-in"), body
    assert "reasoning" in body and _reasoning_is_valid(body["reasoning"]), body
    assert "message" in body and 1 <= len(body["message"]) <= 500


@respx.mock
def test_registration_idempotent_on_rerun():
    """If .arena-credentials already exists, /auth/register must NOT be
    called when /agent/me confirms the cached key is valid."""
    Path(".arena-credentials").write_text(json.dumps({
        "agentId": "cached_agent", "apiKey": "cached_key",
    }))

    register_route = respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(200, json={"agentId": "should_not_be_called"})
    )
    me_route = respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={
            "id": "cached_agent", "handle": "cached",
        })
    )
    respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )
    respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json={
            "match": {
                "id": "m2", "competitionId": "c", "agentId": "cached_agent",
                "status": "Completed", "phase": "completed",
                "targetHands": 1, "completedHands": 1,
                "rawChipDelta": 0, "rawBbPer100": 0.0,
                "adjustedChipDelta": 0.0, "adjustedBbPer100": 0.0,
                "currentTableId": None, "startedAt": 1, "endedAt": 2, "error": None,
            },
            "table": None, "participant": None,
        })
    )
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={"tables": []}))
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={
        "match": {
            "id": "m2", "competitionId": "c", "agentId": "cached_agent",
            "status": "Completed", "phase": "completed",
            "targetHands": 1, "completedHands": 1,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": 0.0, "adjustedBbPer100": 0.0,
            "currentTableId": None, "startedAt": 1, "endedAt": 2, "error": None,
        },
        "table": None, "participant": None,
    }))

    rc = agent_mod.main(["--dry-run", "--competition-id", "c"])
    assert rc == 0
    assert register_route.call_count == 0, "registration should be cached"
    assert me_route.call_count == 1, "cached creds must be verified with /agent/me"


@respx.mock
def test_dry_run_does_not_hit_production():
    """Any call to arena.dev.fun (production) must NOT be mocked here —
    confirm dry-run only touches the mock base URL."""
    Path(".arena-credentials").write_text(json.dumps({
        "agentId": "x", "apiKey": "y",
    }))
    leak = respx.route(host="arena.dev.fun").mock(
        return_value=httpx.Response(599)
    )

    respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={"id": "x"})
    )
    respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )
    respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json={
            "match": {
                "id": "m3", "competitionId": "c", "agentId": "x",
                "status": "Completed", "phase": "completed",
                "targetHands": 0, "completedHands": 0,
                "rawChipDelta": 0, "rawBbPer100": 0.0,
                "adjustedChipDelta": 0.0, "adjustedBbPer100": 0.0,
                "currentTableId": None, "startedAt": 1, "endedAt": 2, "error": None,
            },
            "table": None, "participant": None,
        })
    )
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={"tables": []}))
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={
        "match": {
            "id": "m3", "competitionId": "c", "agentId": "x",
            "status": "Completed", "phase": "completed",
            "targetHands": 0, "completedHands": 0,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": 0.0, "adjustedBbPer100": 0.0,
            "currentTableId": None, "startedAt": 1, "endedAt": 2, "error": None,
        },
        "table": None, "participant": None,
    }))

    rc = agent_mod.main(["--dry-run", "--competition-id", "c"])
    assert rc == 0
    assert leak.call_count == 0, "dry-run leaked to production"


def test_state_migration_from_v0_11_schema(tmp_path, monkeypatch):
    """v0.12.0 added `iterations` to .arena-poker-state. State files
    written by v0.11.0 (no `iterations` key) must load cleanly and the
    key must default to []. New entries via append_iteration() must
    persist in order and increment `iter`."""
    monkeypatch.chdir(tmp_path)

    # Simulate a v0.11-era state file.
    legacy = {
        "hands_played": 42,
        "bankroll": 100,
        "last_action": {"action": "call", "amount": 50, "at": 1700000000},
        "timeout_count": 0,
        "rejection_count": 1,
        "stale_count": 2,
    }
    arena_client_mod.STATE_PATH.write_text(json.dumps(legacy))

    state = arena_client_mod.load_state()
    assert state["iterations"] == [], "iterations must default to [] on v0.11 state"
    assert state["hands_played"] == 42, "legacy keys must survive migration"
    assert state["rejection_count"] == 1

    # append_iteration assigns sequential `iter` and timestamp.
    arena_client_mod.append_iteration({
        "bb_per_100": -61.7, "hands": 51,
        "decide_version": "TAG iter 0",
    })
    arena_client_mod.append_iteration({
        "bb_per_100": -8.3, "hands": 500,
        "decide_version": "conservative iter 1",
    })

    final = arena_client_mod.load_state()
    iters = final["iterations"]
    assert len(iters) == 2
    assert iters[0]["iter"] == 0 and iters[1]["iter"] == 1
    assert iters[0]["bb_per_100"] == -61.7
    assert iters[1]["bb_per_100"] == -8.3
    # Timestamp present and ISO-ish.
    assert iters[0]["ts"].endswith("Z") and "T" in iters[0]["ts"]


def test_introspection_missing_endpoints_fails_loud():
    """If introspection is missing a required endpoint, we must SystemExit
    rather than continuing on a moved API."""
    schema = {"endpoints": [
        {"method": "POST", "path": "/api/arena/auth/register", "auth": False},
    ]}
    with pytest.raises(SystemExit) as exc:
        arena_client_mod.assert_endpoints(schema)
    assert "missing endpoint" in str(exc.value)


# ─── R5 added smoke tests ───────────────────────────────────────────────────


@respx.mock
def test_409_stale_table_re_polls():
    """First /texas/action → 409 (stale). Loop must re-poll
    /texas/pending-actions and submit again — exactly 2 action POSTs."""
    import time as _time

    respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(200, json={
            "agentId": "agent_stale", "apiKey": "k",
            "handle": "h", "name": "n",
        })
    )
    respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={"id": "agent_stale"})
    )
    respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )
    respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json=_start_payload("queued"))
    )

    table = _table_state(_time.time() + 10.0)
    table2 = {**table, "tableId": "tbl_1"}  # fresh table, same id

    # pending: serve table, then serve again after 409, then empty.
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(side_effect=[
        httpx.Response(200, json={"tables": [table]}),
        httpx.Response(200, json={"tables": [table2]}),
        httpx.Response(200, json={"tables": []}),
        httpx.Response(200, json={"tables": []}),
    ])

    # status: running, running, then completed.
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(side_effect=[
        httpx.Response(200, json=_start_payload("queued")),
        _completed_status(),
        _completed_status(),
    ])

    action_route = respx.post(f"{MOCK_BASE}/texas/action").mock(side_effect=[
        httpx.Response(409, json={"error": "stale"}),
        httpx.Response(200, json={"table": table, "participant": None}),
    ])

    rc = agent_mod.main(["--dry-run", "--competition-id", "comp_test"])
    assert rc == 0
    assert action_route.call_count == 2, (
        f"expected exactly 2 action POSTs (1 stale + 1 retry), "
        f"got {action_route.call_count}"
    )


def test_429_retry_with_backoff(monkeypatch):
    """ArenaClient must honor Retry-After on 429 and retry. We patch
    time.sleep and assert it was called at least once before a 200."""
    import time as _time
    sleeps: list[float] = []
    monkeypatch.setattr("arena_client.time.sleep", lambda s: sleeps.append(s))

    with respx.mock(base_url=MOCK_BASE, assert_all_called=False) as router:
        router.get("/agent/me").mock(side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate"}),
            httpx.Response(200, json={"id": "agent_x"}),
        ])
        client = arena_client_mod.ArenaClient(MOCK_BASE, api_key="k")
        try:
            body = client.get("/agent/me")
            assert isinstance(body, dict) and body.get("id") == "agent_x"
        finally:
            client.close()

    assert len(sleeps) >= 1, f"expected at least one sleep call on 429, got {sleeps}"


@respx.mock
def test_malformed_pending_actions_response():
    """If /texas/pending-actions returns a non-dict or {"tables": "not-a-list"},
    the loop must log a warning + degrade to status polling, not crash."""
    respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(200, json={
            "agentId": "agent_mf", "apiKey": "k",
            "handle": "h", "name": "n",
        })
    )
    respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={"id": "agent_mf"})
    )
    respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )
    respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json=_start_payload("queued"))
    )

    # First call → "tables" is a string (illegal); second → list-but-malformed;
    # then empty so the loop relies on status polling.
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(side_effect=[
        httpx.Response(200, json={"tables": "should-be-a-list"}),
        httpx.Response(200, json={"tables": [{"no": "tableId"}, "string-row"]}),
        httpx.Response(200, json={"tables": []}),
    ])

    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(side_effect=[
        httpx.Response(200, json=_start_payload("queued")),
        _completed_status(),
    ])

    action_route = respx.post(f"{MOCK_BASE}/texas/action").mock(
        return_value=httpx.Response(500, json={"error": "must-not-be-called"})
    )

    rc = agent_mod.main(["--dry-run", "--competition-id", "comp_test"])
    assert rc == 0, f"agent should exit cleanly via status polling, got {rc}"
    assert action_route.call_count == 0, (
        "no action should be submitted when every pending response is malformed"
    )


@respx.mock
def test_max_hands_stops_on_server_completed_hands(monkeypatch):
    """v0.4 B1: --max-hands now counts server-settled hands
    (match.completedHands), not actions submitted. Simulate: agent
    submits N actions, /status reports completedHands=2, --max-hands 2
    must trigger stop AFTER status reports >=2."""
    import time as _time
    # Force faster status refresh so the test doesn't sleep 8s per iter.
    monkeypatch.setattr(agent_mod, "STATUS_REFRESH_S", 0.0)
    monkeypatch.setattr(agent_mod, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(agent_mod, "POLL_JITTER", 0.0)

    respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(200, json={
            "agentId": "agent_mh", "apiKey": "k",
            "handle": "h", "name": "n",
        })
    )
    respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={"id": "agent_mh"})
    )
    respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )
    respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json=_start_payload("queued"))
    )

    table = _table_state(_time.time() + 10.0)
    # Endless supply of tables — only the status counter stops us.
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={"tables": [table]}))

    # status: 0 → 1 → 2 (terminal once it hits the cap)
    status_responses = [
        httpx.Response(200, json={"match": {
            "id": "m_mh", "competitionId": "c", "agentId": "agent_mh",
            "status": "Running", "phase": "queued",
            "targetHands": 500, "completedHands": 0,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": None, "adjustedBbPer100": None,
            "currentTableId": None, "startedAt": 1, "endedAt": None,
            "error": None,
        }, "table": None, "participant": None}),
        httpx.Response(200, json={"match": {
            "id": "m_mh", "competitionId": "c", "agentId": "agent_mh",
            "status": "Running", "phase": "queued",
            "targetHands": 500, "completedHands": 1,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": None, "adjustedBbPer100": None,
            "currentTableId": None, "startedAt": 1, "endedAt": None,
            "error": None,
        }, "table": None, "participant": None}),
        # 3rd call: completedHands=2 — triggers --max-hands=2 stop
        httpx.Response(200, json={"match": {
            "id": "m_mh", "competitionId": "c", "agentId": "agent_mh",
            "status": "Running", "phase": "queued",
            "targetHands": 500, "completedHands": 2,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": None, "adjustedBbPer100": None,
            "currentTableId": None, "startedAt": 1, "endedAt": None,
            "error": None,
        }, "table": None, "participant": None}),
        # safety: any additional polls return terminal phase
        httpx.Response(200, json={"match": {
            "id": "m_mh", "competitionId": "c", "agentId": "agent_mh",
            "status": "Completed", "phase": "completed",
            "targetHands": 500, "completedHands": 2,
            "rawChipDelta": 0, "rawBbPer100": 0.0,
            "adjustedChipDelta": 0.0, "adjustedBbPer100": 0.0,
            "currentTableId": None, "startedAt": 1, "endedAt": 2,
            "error": None,
        }, "table": None, "participant": None}),
    ]
    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(side_effect=status_responses)

    action_route = respx.post(f"{MOCK_BASE}/texas/action").mock(
        return_value=httpx.Response(200, json={"table": table, "participant": None})
    )

    rc = agent_mod.main(["--dry-run", "--competition-id", "c", "--max-hands", "2"])
    assert rc == 0
    # B1: under the OLD semantic, --max-hands=2 would stop after 2 action POSTs.
    # Under the new semantic we keep submitting until completedHands reaches 2.
    # So we expect MORE than 2 actions submitted (typically 3+).
    assert action_route.call_count >= 2, (
        f"expected at least 2 action POSTs before completedHands=2, "
        f"got {action_route.call_count}")


@respx.mock
def test_terminal_cancelled_phase():
    """If benchmark/status reports phase='cancelled', the loop must stop
    cleanly with exit 0 (terminal phase recognized from introspection enum)."""
    respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(200, json={
            "agentId": "agent_c", "apiKey": "k",
            "handle": "h", "name": "n",
        })
    )
    respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={"id": "agent_c"})
    )
    respx.get(f"{MOCK_BASE}/__introspection").mock(
        return_value=httpx.Response(200, json=_introspection_payload())
    )
    respx.post(f"{MOCK_BASE}/texas/benchmark/start").mock(
        return_value=httpx.Response(200, json=_start_payload("queued"))
    )

    pending_route = respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/pending-actions") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={"tables": []}))

    respx.get(re.compile(
        re.escape(f"{MOCK_BASE}/texas/benchmark/status") + r"\?.*"
    )).mock(return_value=httpx.Response(200, json={
        "match": {
            "id": "m1", "competitionId": "comp_test", "agentId": "agent_c",
            "status": "Cancelled", "phase": "cancelled",
            "targetHands": 10, "completedHands": 3,
            "rawChipDelta": -50, "rawBbPer100": -2.5,
            "adjustedChipDelta": None, "adjustedBbPer100": None,
            "currentTableId": None, "startedAt": 1, "endedAt": 2,
            "error": "manual cancel",
        },
        "table": None, "participant": None,
    }))

    action_route = respx.post(f"{MOCK_BASE}/texas/action").mock(
        return_value=httpx.Response(500, json={"error": "must-not-be-called"})
    )

    rc = agent_mod.main(["--dry-run", "--competition-id", "comp_test"])
    assert rc == 0, f"cancelled phase should exit cleanly, got {rc}"
    assert action_route.call_count == 0, "no action when no pending tables"
    # Pending was polled at least once before terminal detection — bounded.
    assert pending_route.call_count >= 1


@respx.mock
def test_register_409_handle_taken_auto_suffixes():
    """Fresh dogfood: the default handle `pokerkit-starter` collides on
    /auth/register with 409 `Handle already taken`. load_or_register()
    must auto-retry with `f"{handle}-{secrets.token_hex(3)}"` and succeed
    on the second attempt — no manual --handle required."""
    register_route = respx.post(f"{MOCK_BASE}/auth/register").mock(side_effect=[
        httpx.Response(409, json={"error": "Handle already taken"}),
        httpx.Response(200, json={
            "agentId": "agent_retry", "apiKey": "retry_key",
            "handle": "pokerkit-starter-deadbe", "name": "PokerKit Starter",
        }),
    ])

    client = arena_client_mod.ArenaClient(MOCK_BASE)
    try:
        creds = arena_client_mod.load_or_register(
            client, handle="pokerkit-starter",
            name="PokerKit Starter", quote="GG",
        )
    finally:
        client.close()

    assert register_route.call_count == 2, (
        f"expected exactly 2 register POSTs (1 collide + 1 retry), "
        f"got {register_route.call_count}"
    )

    first_body = json.loads(register_route.calls[0].request.content)
    second_body = json.loads(register_route.calls[1].request.content)
    assert first_body["handle"] == "pokerkit-starter", first_body
    assert second_body["handle"].startswith("pokerkit-starter-"), second_body
    suffix = second_body["handle"].removeprefix("pokerkit-starter-")
    # secrets.token_hex(3) → 6 hex chars
    assert len(suffix) == 6 and all(c in "0123456789abcdef" for c in suffix), (
        f"suffix must be 6 hex chars from secrets.token_hex(3), got {suffix!r}"
    )

    assert creds["apiKey"] == "retry_key"
    # Credentials persisted with the handle that actually landed.
    assert json.loads(Path(".arena-credentials").read_text())["apiKey"] == "retry_key"


@respx.mock
def test_register_409_gives_up_after_3_attempts():
    """If the suffix retry keeps colliding (effectively impossible IRL,
    but possible if Arena's 409 logic mis-reports), give up after 3 tries
    instead of looping forever."""
    register_route = respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(409, json={"error": "Handle already taken"})
    )

    client = arena_client_mod.ArenaClient(MOCK_BASE)
    try:
        with pytest.raises(arena_client_mod.ArenaError) as exc:
            arena_client_mod.load_or_register(
                client, handle="pokerkit-starter",
                name="PokerKit Starter", quote="GG",
            )
    finally:
        client.close()

    assert exc.value.status == 409
    assert register_route.call_count == 3, (
        f"expected exactly 3 attempts before giving up, "
        f"got {register_route.call_count}"
    )


@respx.mock
def test_register_5xx_restores_previous_creds():
    """Regression for v0.18.1: if cached creds get rejected by /agent/me and
    the re-registration attempt then fails (e.g. 502), the previous creds
    must be restored — the user must never end up keyless because of a
    transient server blip.

    Setup: a real-looking cached creds file. /agent/me 401s. /auth/register
    then 502s. Expected: .arena-credentials is restored to its original
    contents, no .rejected file lingers in primary position."""
    # Seed cached creds on disk.
    cached = {
        "agentId": "agent_real",
        "apiKey": "arena_sk_real_previous_key_value_for_test_only",
        "handle": "pokerkit-starter",
        "name": "PokerKit Starter",
    }
    Path(".arena-credentials").write_text(json.dumps(cached, indent=2))
    original_bytes = Path(".arena-credentials").read_bytes()

    # /agent/me rejects the cached key → triggers re-register path.
    respx.get(f"{MOCK_BASE}/agent/me").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    # /auth/register then fails with a 5xx the registration code doesn't
    # special-case → should bubble up through load_or_register.
    register_route = respx.post(f"{MOCK_BASE}/auth/register").mock(
        return_value=httpx.Response(502, json={"error": "Bad Gateway"})
    )

    client = arena_client_mod.ArenaClient(MOCK_BASE)
    try:
        with pytest.raises(arena_client_mod.ArenaError) as exc:
            arena_client_mod.load_or_register(
                client, handle="pokerkit-starter",
                name="PokerKit Starter", quote="GG",
            )
    finally:
        client.close()

    assert exc.value.status == 502
    assert register_route.called, "expected /auth/register to be hit"

    creds_path = Path(".arena-credentials")
    backup_path = Path(".arena-credentials.rejected")
    assert creds_path.exists(), (
        "expected .arena-credentials to be restored after registration failure"
    )
    assert creds_path.read_bytes() == original_bytes, (
        "restored creds must match the original byte-for-byte"
    )
    assert not backup_path.exists(), (
        "expected .arena-credentials.rejected to be cleaned up after restore "
        "(only the primary should remain)"
    )
