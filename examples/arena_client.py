"""Arena HTTP client + introspection + credential helpers.

This module is the "plumbing" you usually don't need to read or edit.
It wraps the Arena REST API with:

  - httpx client with 429/5xx retry + Retry-After honored
  - typed ArenaError for surfaced 4xx
  - introspection fetch + required-endpoint assertion (fail loud, not 404 mid-hand)
  - terminal phase/status resolution from the live schema
  - idempotent credential cache (re-verifies cached key via /agent/me)
  - small JSON state cache for cross-run continuity

Builders normally only touch `examples/agent.py` — this file is shared by
`agent.py`, `llm_agent.py`, and `mock.py`.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import httpx


DEFAULT_BASE = "https://arena.dev.fun/api/arena"
MOCK_BASE = "http://mock.local/api/arena"  # --dry-run rebinds to this
CREDS_PATH = Path(".arena-credentials")
# Holds the previous creds while we attempt re-registration. Restored if
# re-registration fails so a transient 5xx can't leave the user keyless.
CREDS_BACKUP_PATH = Path(".arena-credentials.rejected")
STATE_PATH = Path(".arena-poker-state")
RETRY_MAX = 3


def _move_creds_aside() -> bool:
    """Rename `.arena-credentials` -> `.arena-credentials.rejected` (replacing
    any pre-existing backup). Returns True if a file was actually moved.

    Use BEFORE re-registering so a failure can be reversed via
    `_restore_creds_backup()`. Use `_discard_creds_backup()` once new creds
    are durably on disk."""
    if not CREDS_PATH.exists():
        return False
    try:
        # os.replace permits crossing an existing file on the target.
        os.replace(str(CREDS_PATH), str(CREDS_BACKUP_PATH))
        return True
    except OSError as e:
        print(f"[arena-pokerkit] failed to back up creds aside: {e}",
              file=sys.stderr)
        return False


def _restore_creds_backup() -> bool:
    """Move `.arena-credentials.rejected` back to `.arena-credentials` if the
    primary file is missing. Returns True on restore. No-op if there's no
    backup or the primary already exists."""
    if not CREDS_BACKUP_PATH.exists():
        return False
    if CREDS_PATH.exists():
        return False
    try:
        os.replace(str(CREDS_BACKUP_PATH), str(CREDS_PATH))
        print("[arena-pokerkit] restored previous .arena-credentials "
              "after registration failure", file=sys.stderr)
        return True
    except OSError as e:
        print(f"[arena-pokerkit] failed to restore creds backup: {e}",
              file=sys.stderr)
        return False


def _discard_creds_backup() -> None:
    """Best-effort cleanup of the `.rejected` backup once the new creds are
    durably on disk."""
    if CREDS_BACKUP_PATH.exists():
        try:
            CREDS_BACKUP_PATH.unlink()
        except OSError:
            pass

# Required endpoints we expect introspection to expose. If any are missing,
# the live API has moved and we fail fast rather than 404 mid-hand.
# Note: /__introspection is intentionally excluded — it's a meta-endpoint that
# does not list itself in its own output.
REQUIRED_ENDPOINTS = (
    ("POST", "/api/arena/auth/register"),
    ("GET",  "/api/arena/agent/me"),
    ("POST", "/api/arena/texas/benchmark/start"),
    ("GET",  "/api/arena/texas/benchmark/status"),
    ("GET",  "/api/arena/texas/pending-actions"),
    ("POST", "/api/arena/texas/action"),
)

# Cached-from-build-time terminal phases. We overwrite this with introspection
# values when available. Listed in references/poker-eval-arena.md as "may be
# stale, derived from cached examples" — introspection wins.
FALLBACK_TERMINAL_PHASES = ("completed", "cancelled", "failed")
FALLBACK_TERMINAL_STATUSES = ("Completed", "Cancelled", "Failed")


# ─── HTTP client ────────────────────────────────────────────────────────────

class ArenaError(Exception):
    def __init__(self, status: int, body: Any, where: str = ""):
        super().__init__(f"{where} status={status} body={body}")
        self.status = status
        self.body = body
        self.where = where


class ArenaClient:
    """Thin httpx wrapper. Auto-attaches x-arena-api-key, retries 5xx,
    surfaces 4xx as exceptions."""

    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-arena-api-key"] = self.api_key
        return h

    def _req(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base}{path}"
        backoff = 0.5
        last_exc: Optional[Exception] = None
        for attempt in range(RETRY_MAX):
            try:
                r = self._client.request(method, url, headers=self._headers(), **kwargs)
            except httpx.HTTPError as e:
                last_exc = e
                time.sleep(backoff)
                backoff *= 2
                continue
            try:
                body = r.json()
            except Exception:
                body = r.text
            # 429 rate limit — honor Retry-After then retry.
            if r.status_code == 429 and attempt < RETRY_MAX - 1:
                ra = r.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra else backoff
                except ValueError:
                    wait = backoff
                time.sleep(max(wait, 0.0))
                backoff *= 2
                continue
            if r.status_code >= 500 and attempt < RETRY_MAX - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            if not r.is_success:
                raise ArenaError(r.status_code, body, where=f"{method} {path}")
            return body
        raise ArenaError(0, str(last_exc), where=f"{method} {path}")

    def get(self, path: str, **kwargs) -> Any:
        return self._req("GET", path, **kwargs)

    def post(self, path: str, json_body: Optional[dict] = None) -> Any:
        return self._req("POST", path, json=json_body)


# ─── Introspection ──────────────────────────────────────────────────────────

def fetch_introspection(client: ArenaClient) -> dict:
    """GET /__introspection at startup. Returns a parsed dict with at least
    {endpoints: [...]} so callers can resolve terminal phases / statuses."""
    try:
        schema = client.get("/__introspection")
    except ArenaError as e:
        raise SystemExit(
            f"[arena-pokerkit] introspection unreachable ({e.where} -> "
            f"{e.status}). The live API may be down; cannot continue safely."
        )
    if not isinstance(schema, dict):
        raise SystemExit("[arena-pokerkit] introspection returned non-object — refusing to continue.")
    return schema


def assert_endpoints(schema: dict, required: tuple[tuple[str, str], ...] = REQUIRED_ENDPOINTS) -> None:
    """Verify every (method, path) we plan to call is present in introspection.
    If anything is missing we fail loud, not silently 404 mid-hand."""
    endpoints = schema.get("endpoints") or []
    present = {(e.get("method"), e.get("path")) for e in endpoints if isinstance(e, dict)}
    missing = [pair for pair in required if pair not in present]
    if missing:
        raise SystemExit(
            "[arena-pokerkit] live API schema missing endpoint(s): "
            + ", ".join(f"{m} {p}" for m, p in missing)
            + ". The schema may have moved — read /api/arena/__introspection "
            "and update REQUIRED_ENDPOINTS in examples/arena_client.py."
        )


def resolve_terminal_phases(schema: dict) -> tuple[set[str], set[str]]:
    """Pull match.phase enum and match.status enum from the
    /texas/benchmark/start output schema. Falls back to cached lists if the
    schema can't be parsed. Returns (terminal_phases, terminal_statuses)."""
    phase_enum: list[str] = []
    status_enum: list[str] = []
    for ep in (schema.get("endpoints") or []):
        if not isinstance(ep, dict):
            continue
        if ep.get("path") != "/api/arena/texas/benchmark/start":
            continue
        out = ep.get("output") or {}
        match = ((out.get("properties") or {}).get("match")) or {}
        # match may be inside an anyOf
        candidates = match.get("anyOf") or [match]
        for cand in candidates:
            props = (cand.get("properties") or {})
            ph = props.get("phase") or {}
            st = props.get("status") or {}
            if ph.get("enum"):
                phase_enum = ph["enum"]
            if st.get("enum"):
                status_enum = st["enum"]
            if phase_enum and status_enum:
                break
        break

    if not phase_enum:
        phase_enum = list(FALLBACK_TERMINAL_PHASES) + ["queued", "panel_acting", "waiting_user"]
    if not status_enum:
        status_enum = list(FALLBACK_TERMINAL_STATUSES) + ["Running"]

    # Heuristic for "terminal" — anything other than Running/queued/panel_acting/waiting_user.
    live_phases = {"queued", "panel_acting", "waiting_user"}
    terminal_phases = {p for p in phase_enum if p.lower() not in live_phases and p != "Running"}
    terminal_statuses = {s for s in status_enum if s != "Running"}
    if not terminal_phases:
        terminal_phases = set(FALLBACK_TERMINAL_PHASES)
    if not terminal_statuses:
        terminal_statuses = set(FALLBACK_TERMINAL_STATUSES)
    return terminal_phases, terminal_statuses


# ─── Credentials + state ────────────────────────────────────────────────────

def load_or_register(client: ArenaClient, handle: str, name: str, quote: str) -> dict:
    """Idempotent: returns cached creds (verified with /agent/me) if
    .arena-credentials exists, otherwise POSTs /auth/register and caches
    the response. On 401/403 the cached key is discarded and we register
    fresh — matches arena.md auth-repair guidance."""
    if CREDS_PATH.exists():
        try:
            creds = json.loads(CREDS_PATH.read_text())
        except Exception:
            creds = {}
        # Refuse mock/dry-run creds for a live run — they'll 401 instantly and
        # cause confusing errors. Auto-clear them and re-register fresh.
        # Use rename-on-replace (creds -> .rejected) instead of unlink so a
        # registration failure can still recover the previous state.
        key = creds.get("apiKey") or ""
        agent_id_str = str(creds.get("agentId") or creds.get("id") or "")
        if agent_id_str == "agent_dry" or key.startswith("dry_") or key.startswith("mock_"):
            print(f"[arena-pokerkit] detected stale mock creds (agentId={agent_id_str}); "
                  "moving .arena-credentials aside and re-registering fresh",
                  file=sys.stderr)
            _move_creds_aside()
            creds = {}
            key = None
        if key:
            client.api_key = key
            try:
                me = client.get("/agent/me")
                if isinstance(me, dict) and (me.get("id") or me.get("agentId") or me.get("handle")):
                    return creds
            except ArenaError as e:
                if e.status in (401, 403):
                    print(f"[arena-pokerkit] cached key rejected ({e.status}); re-registering",
                          file=sys.stderr)
                    client.api_key = None
                    _move_creds_aside()
                else:
                    raise
    # Handles are globally unique. On a fresh dogfood the default
    # "pokerkit-starter" collides; auto-suffix and retry so the skill's
    # "one-shot setup" promise holds. Cap at 3 retries (cap chosen so
    # 24 bits of entropy * 3 tries makes a collision effectively
    # impossible without masking a real config problem like a bad base URL).
    attempt_handle = handle
    body = None
    try:
        for attempt in range(3):
            try:
                body = client.post("/auth/register", {
                    "handle": attempt_handle, "name": name, "quote": quote,
                    "description": "",
                })
                break
            except ArenaError as e:
                if e.status == 409 and _is_handle_taken(e.body) and attempt < 2:
                    suffix = secrets.token_hex(3)
                    attempt_handle = f"{handle}-{suffix}"
                    print(f"[arena-pokerkit] handle {handle!r} taken; "
                          f"retrying as {attempt_handle!r}", file=sys.stderr)
                    continue
                raise
        if isinstance(body, dict) and "apiKey" in body:
            client.api_key = body["apiKey"]
        _atomic_write(CREDS_PATH, json.dumps(body, indent=2))
        # New creds are durable on disk — drop the previous .rejected backup.
        _discard_creds_backup()
        return body if isinstance(body, dict) else {}
    except Exception:
        # Registration blew up after we already moved the old creds aside.
        # Restore them so the caller / next run isn't left credential-less.
        _restore_creds_backup()
        raise


def _is_handle_taken(body: Any) -> bool:
    """Return True if a 409 body looks like a handle-collision error.
    Matches Arena's "Handle already taken" message and tolerates dict
    or string shapes."""
    if isinstance(body, dict):
        text = " ".join(
            str(v) for v in (
                body.get("error"), body.get("message"), body.get("detail"),
            ) if v
        )
    else:
        text = str(body or "")
    text = text.lower()
    return "already taken" in text or "handle" in text


def _default_state() -> dict:
    return {
        "hands_played": 0,
        "bankroll": 0,
        "last_action": None,
        "timeout_count": 0,
        "rejection_count": 0,
        "stale_count": 0,
        "iterations": [],
    }


def load_state() -> dict:
    """Load .arena-poker-state with schema migration.

    v0.12.0 added `iterations: list[dict]` (per-Arena-run score history).
    Older state files (v0.11 and earlier) lack this key; we default it to
    [] so the read path keeps working without a manual reset. All other
    legacy keys are preserved as-is."""
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            if isinstance(state, dict):
                # v0.12 migration: ensure iterations key exists.
                if "iterations" not in state or not isinstance(
                        state.get("iterations"), list):
                    state["iterations"] = []
                # Fill in any other missing defaults so callers don't KeyError.
                for k, v in _default_state().items():
                    state.setdefault(k, v)
                return state
        except Exception:
            pass
    return _default_state()


def save_state(state: dict) -> None:
    _atomic_write(STATE_PATH, json.dumps(state, indent=2))


def append_iteration(entry: dict) -> dict:
    """Append a single iteration record to .arena-poker-state['iterations']
    atomically. Returns the updated state dict so callers can inspect the
    iteration count / previous entries.

    Entry shape (v0.12.0):
      {
        "iter": int,              # 0-indexed iteration number
        "ts": "ISO-8601 string",  # UTC timestamp
        "bb_per_100": float|None, # adjusted bb/100 (None if missing)
        "hands": int|None,        # completed hands this run
        "decide_version": str,    # short label for the decide() variant
      }

    Caller supplies `bb_per_100`, `hands`, `decide_version`; this helper
    fills in `iter` (next sequential) and `ts` if missing.
    """
    state = load_state()
    iters = state.get("iterations") or []
    if not isinstance(iters, list):
        iters = []
    record = dict(entry)
    record.setdefault("iter", len(iters))
    if "ts" not in record:
        import datetime as _dt
        record["ts"] = _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    iters.append(record)
    state["iterations"] = iters
    save_state(state)
    return state


def _atomic_write(path: Path, contents: str) -> None:
    """Write atomically using a unique per-process tempfile so two concurrent
    agents in the same cwd cannot clobber each other's `.tmp` file."""
    parent = path.parent if str(path.parent) else Path(".")
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(parent) if str(parent) else None,
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(contents)
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
