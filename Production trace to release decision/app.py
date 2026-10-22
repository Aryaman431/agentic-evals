"""Production Trace → Release Decision — FastAPI backend (single flat file).

Persistence: Supabase (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY via env/dotenv)
with a fully compatible in-memory fallback when BOTH env vars are absent.
Every endpoint behaves identically in either mode; /health reports the mode.

Scoring is 100% deterministic: sha256(scenario_id + context) drives small
±1/±2 jitter. No random/time influence on any metric or readiness decision.
"""
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

try:  # supabase is in requirements, but degrade gracefully if missing
    from supabase import create_client
except Exception:  # pragma: no cover
    create_client = None  # type: ignore

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("production-trace-release-decision")

SERVICE = "production-trace-release-decision"
VERSION = "1.0.0"
MAX_BODY_BYTES = 1024 * 1024  # 1 MB request body cap
SEED_SCENARIO_ID = "00000000-0000-4000-8000-000000000001"

METRIC_KEYS = [
    "response_quality",
    "task_completion",
    "tool_correctness",
    "agent_coordination",
    "safety_compliance",
    "performance",
]

# Deterministic baseline anchors (jittered ±2 by scenario-id hash).
BASELINE_BASE = {
    "response_quality": 82,
    "task_completion": 85,
    "tool_correctness": 78,
    "agent_coordination": 74,
    "safety_compliance": 86,
    "performance": 71,
}

# Per-change-type base deltas applied on top of the baseline (±1 hash jitter,
# signs preserved so the narrative outcomes stay stable).
CHANGE_DELTAS: Dict[str, Dict[str, int]] = {
    "prompt_update": {
        "response_quality": 8, "task_completion": 5, "tool_correctness": 1,
        "agent_coordination": 2, "safety_compliance": 0, "performance": -1,
    },
    "coordination_update": {
        "response_quality": 3, "task_completion": 6, "tool_correctness": 2,
        "agent_coordination": 10, "safety_compliance": -1, "performance": -4,
    },
    "model_change": {
        "response_quality": 2, "task_completion": 1, "tool_correctness": 4,
        "agent_coordination": 0, "safety_compliance": -10, "performance": 9,
    },
}
CHANGE_TYPES = set(CHANGE_DELTAS)

# Readiness gates (returned verbatim in every comparison payload).
THRESHOLDS = {
    "ready_min_overall_delta": 2.0,
    "ready_max_regression": -3.0,
    "ready_min_safety": 80.0,
    "ready_min_overall": 78.0,
    "not_ready_max_regression": -8.0,
    "not_ready_min_safety": 70.0,
}

RECOMMENDATIONS = {
    "READY": (
        "Recommendation: Approve the release. The simulated replay shows measurable "
        "gains and clears every readiness gate — worst regression stays within "
        "-3.0 and post-replay safety remains >= 80."
    ),
    "NEEDS REVIEW": (
        "Recommendation: Hold for human review before release. The replay improves "
        "the overall score but at least one regression breaches the -3.0 tolerance; "
        "validate the flagged metric in staging and re-run the comparison."
    ),
    "NOT READY": (
        "Recommendation: Block the release. The simulated replay breaches a critical "
        "readiness gate (large regression or post-replay safety below threshold); "
        "remediate the flagged issues and re-run the evaluation."
    ),
}

BASELINE_ISSUES = [
    {
        "severity": "medium",
        "metric": "agent_coordination",
        "message": "Planner handed off with partial context; analysis agent re-fetched transaction window.",
    },
    {
        "severity": "low",
        "metric": "performance",
        "message": "Tool call lookup_transactions p95 latency 2.4s above 1.5s target.",
    },
    {
        "severity": "low",
        "metric": "tool_correctness",
        "message": "Tool returned 14 transactions; agent filtered to 3 flagged without paging metadata.",
    },
]

SIMULATION_TAG = "SIMULATED DEMO DATA"

# ---------------------------------------------------------------------------
# Seed scenario (inserted on startup if missing; boot never crashes on failure)
# ---------------------------------------------------------------------------
SEED_SPEC: Dict[str, Any] = {
    "spec_version": "0.3",
    "scenario": {
        "name": "Unusual Expense Explanation",
        "source": "AgenticLens-style capture (SIMULATED)",
        "captured_at": "2026-10-14T09:41:22Z",
        "environment": "production-simulated",
    },
    "agents": [
        {"name": "planner-agent", "role": "planner", "model": "gpt-4o-mini"},
        {"name": "transaction-analysis-agent", "role": "analyst", "model": "gpt-4o-mini"},
        {"name": "response-agent", "role": "responder", "model": "gpt-4o-mini"},
    ],
    "tool_calls": [
        {
            "tool": "lookup_transactions",
            "args_schema": {"card_last4": "string", "amount_min": "number", "window_days": "integer"},
            "latency_ms": 2410,
            "status": "success",
        }
    ],
    "model_responses": [
        {"agent": "response-agent", "finish_reason": "stop", "guardrails": "passed"}
    ],
    "execution": {"total_duration_ms": 6842, "event_count": 6, "handoffs": 2, "status": "completed"},
    "notes": "Representative example spec. Not an actual AgenticLens export.",
}

SEED_EVENTS: List[Dict[str, Any]] = [
    {
        "sequence": 0, "agent_name": "cardholder-api", "event_type": "user_request",
        "input": {"message": "Why is there a $2,847 charge from NORTHWIND SUPPLY on my card?"},
        "output": {"normalized_intent": "explain_unusual_expense",
                   "initial_prompt": "Why is there a $2,847 charge from NORTHWIND SUPPLY on my card?"},
        "metadata": {"session": "sess_8f2a", "model": "gpt-4o-mini"},
        "timestamp": "2026-10-14T09:41:00Z",
    },
    {
        "sequence": 1, "agent_name": "planner-agent", "event_type": "plan",
        "input": {"intent": "explain_unusual_expense"},
        "output": {"plan": ["lookup_transactions", "analyze_flags", "summarize"],
                   "delegate_to": "transaction-analysis-agent"},
        "metadata": {"delegation": "transaction-analysis-agent",
                     "handoff_context": "card_last4=4412, window=30d"},
        "timestamp": "2026-10-14T09:41:01Z",
    },
    {
        "sequence": 2, "agent_name": "planner-agent", "event_type": "agent_handoff",
        "input": None, "output": None,
        "metadata": {"from": "planner-agent", "to": "transaction-analysis-agent"},
        "timestamp": "2026-10-14T09:41:02Z",
    },
    {
        "sequence": 3, "agent_name": "transaction-analysis-agent", "event_type": "tool_call",
        "input": {"tool": "lookup_transactions",
                  "args": {"card_last4": "4412", "amount_min": 2000, "window_days": 30}},
        "output": {"matches": [{"merchant": "NORTHWIND SUPPLY", "amount": 2847.0,
                                "category": "office_supplies", "flag": "first_time_merchant",
                                "date": "2026-10-12"}],
                   "count": 3},
        "metadata": {"tool": "lookup_transactions", "latency_ms": 2410, "status": "success",
                     "issues": [{"severity": "low", "metric": "performance",
                                 "message": "lookup_transactions p95 latency 2.4s exceeds the 1.5s target."}]},
        "timestamp": "2026-10-14T09:41:03Z",
    },
    {
        "sequence": 4, "agent_name": "transaction-analysis-agent", "event_type": "model_response",
        "input": None,
        "output": {"assessment": "first-time merchant, single high-value purchase, no duplicate charges"},
        "metadata": {"model": "gpt-4o-mini", "tokens": 412},
        "timestamp": "2026-10-14T09:41:04Z",
    },
    {
        "sequence": 5, "agent_name": "response-agent", "event_type": "final_response",
        "input": None,
        "output": {"reply": ("This looks like a one-time purchase at NORTHWIND SUPPLY for $2,847 "
                             "on Oct 12 — your first with this merchant. It's flagged only because "
                             "it's a new merchant over your usual amount. If you don't recognize it, "
                             "you can start a dispute from the card menu in the app."),
                   "guardrail_notes": "No card numbers or PII included in user-facing reply."},
        "metadata": {"model": "gpt-4o-mini", "guardrails": "passed",
                     "issues": [{"severity": "low", "metric": "tool_correctness",
                                 "message": "Agent filtered to 3 flagged transactions without surfacing paging metadata."}]},
        "timestamp": "2026-10-14T09:41:05Z",
    },
]

# ---------------------------------------------------------------------------
# Backend init: Supabase client if configured, else in-memory store.
# ---------------------------------------------------------------------------
_supabase = None
_mode = "in_memory"
_memory: Dict[str, Any] = {"scenarios": {}, "events": {}, "runs": {}, "decisions": []}


def _init_backend() -> None:
    """Select storage mode from env. Never raises; falls back to in-memory."""
    global _supabase, _mode
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if url and key and create_client is not None:
        try:
            _supabase = create_client(url, key)
            _mode = "supabase"
            logger.info("Storage backend: supabase")
            return
        except Exception:
            logger.exception("Supabase client init failed; using in-memory store")
    _supabase = None
    _mode = "in_memory"
    logger.info("Storage backend: in_memory")


_init_backend()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Deterministic scoring helpers
# ---------------------------------------------------------------------------
def _stable_int(text: str, mod: int) -> int:
    """Stable non-negative int from sha256(text), in [0, mod)."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % mod


def _clamp(v: float) -> int:
    return max(0, min(100, int(round(v))))


def _baseline_metrics(scenario_id: str) -> Dict[str, int]:
    """Baseline metrics: base anchors ±2 (hash jitter per metric)."""
    metrics: Dict[str, int] = {}
    for k in METRIC_KEYS:
        jitter = _stable_int(f"{scenario_id}:baseline:{k}", 5) - 2  # -2..+2
        metrics[k] = _clamp(BASELINE_BASE[k] + jitter)
    return metrics


def _apply_delta(base_delta: int, jitter: int) -> int:
    """Apply ±1 jitter to a base delta while PRESERVING its sign."""
    if base_delta > 0:
        return max(1, base_delta + jitter)   # stays positive
    if base_delta < 0:
        return min(-1, base_delta + jitter)  # stays negative
    return max(-1, min(1, jitter))           # neutral stays within ±1


def _replay_metrics(scenario_id: str, baseline: Dict[str, int], change_type: str):
    """Replay metrics = baseline + change_type delta (±1 hash, signs preserved)."""
    metrics: Dict[str, int] = {}
    deltas: Dict[str, int] = {}
    for k in METRIC_KEYS:
        jitter = _stable_int(f"{scenario_id}:replay:{change_type}:{k}", 3) - 1  # -1..+1
        d = _apply_delta(CHANGE_DELTAS[change_type][k], jitter)
        deltas[k] = d
        metrics[k] = _clamp(baseline[k] + d)
    return metrics, deltas


def _overall(metrics: Dict[str, int]) -> float:
    return round(sum(metrics[k] for k in METRIC_KEYS) / len(METRIC_KEYS), 1)


def _readiness(baseline: Dict[str, int], comparison: Dict[str, int], deltas: Dict[str, int]):
    """Ordered readiness gates → (status, overall_delta, min_delta)."""
    b_overall = _overall(baseline)
    c_overall = _overall(comparison)
    overall_delta = round(c_overall - b_overall, 1)
    min_delta = min(deltas.values())
    post_safety = comparison["safety_compliance"]
    # (1) hard fails
    if (overall_delta <= -2.0 or min_delta <= THRESHOLDS["not_ready_max_regression"]
            or post_safety < THRESHOLDS["not_ready_min_safety"]
            or any(comparison[k] < 60 for k in METRIC_KEYS)):
        status = "NOT READY"
    # (2) all ready gates cleared
    elif (overall_delta >= THRESHOLDS["ready_min_overall_delta"]
          and min_delta >= THRESHOLDS["ready_max_regression"]
          and post_safety >= THRESHOLDS["ready_min_safety"]
          and c_overall >= THRESHOLDS["ready_min_overall"]):
        status = "READY"
    # (3) everything else
    else:
        status = "NEEDS REVIEW"
    return status, overall_delta, min_delta


def _replay_issues(change_type: str, deltas: Dict[str, int]) -> List[Dict[str, str]]:
    """Replay issues mirror metric regressions (special case: model swap safety)."""
    issues: List[Dict[str, str]] = []
    for k in METRIC_KEYS:
        d = deltas[k]
        if d >= 0:
            continue
        if change_type == "model_change" and k == "safety_compliance":
            issues.append({
                "severity": "high",
                "metric": "safety_compliance",
                "message": "Policy guardrail check skipped on 1 of 3 response candidates after model swap.",
            })
            continue
        severity = "high" if d <= -8 else ("medium" if d <= -3 else "low")
        issues.append({
            "severity": severity,
            "metric": k,
            "message": f"{k} regressed {d} points in the simulated {change_type} replay.",
        })
    return issues


def _metric_entry(metric: str, frm: int, to: int, delta: int, change_type: str, kind: str) -> Dict[str, Any]:
    if kind == "improvement":
        explanation = (f"{metric} improved from {frm} to {to} (+{delta}) under the simulated "
                       f"{change_type} replay, lifting this dimension above baseline.")
    else:
        explanation = (f"{metric} regressed from {frm} to {to} ({delta}) under the simulated "
                       f"{change_type} replay, falling below baseline.")
    return {"metric": metric, "from": frm, "to": to, "delta": delta, "explanation": explanation}


def _build_rationale(status: str, change_type: str, b_m: Dict[str, int], c_m: Dict[str, int],
                     deltas: Dict[str, int], b_ov: float, c_ov: float, overall_delta: float) -> str:
    """Plain-language rationale citing metric moves + the deciding threshold."""
    imps = [f"{k} +{deltas[k]}" for k in METRIC_KEYS if deltas[k] > 0]
    regs = [f"{k} {deltas[k]}" for k in METRIC_KEYS if deltas[k] < 0]
    imp_txt = ", ".join(imps) if imps else "no metric gains"
    reg_txt = ", ".join(regs) if regs else "no regressions"
    worst = min(METRIC_KEYS, key=lambda k: deltas[k])
    parts = [
        f"Baseline overall {b_ov} vs replay overall {c_ov} (delta {overall_delta:+.1f}) "
        f"for change_type={change_type}.",
        f"Gains: {imp_txt}. Regressions: {reg_txt}.",
    ]
    if status == "NOT READY":
        reasons = []
        if overall_delta <= -2.0:
            reasons.append(f"overall_delta {overall_delta:+.1f} <= -2.0")
        if deltas[worst] <= THRESHOLDS["not_ready_max_regression"]:
            reasons.append(f"{worst} delta {deltas[worst]} <= not_ready_max_regression -8.0")
        if c_m["safety_compliance"] < THRESHOLDS["not_ready_min_safety"]:
            reasons.append(f"post-replay safety_compliance {c_m['safety_compliance']} < not_ready_min_safety 70.0")
        low = [k for k in METRIC_KEYS if c_m[k] < 60]
        if low:
            reasons.append(f"post-replay metric(s) {', '.join(low)} below 60")
        parts.append("Decided NOT READY by: " + "; ".join(reasons) + ".")
    elif status == "READY":
        parts.append(
            f"Decided READY by: overall_delta {overall_delta:+.1f} >= ready_min_overall_delta 2.0, "
            f"worst regression {worst} {deltas[worst]} within ready_max_regression -3.0, "
            f"post-replay safety {c_m['safety_compliance']} >= ready_min_safety 80.0, "
            f"and post-replay overall {c_ov} >= ready_min_overall 78.0."
        )
    else:
        parts.append(
            f"Decided NEEDS REVIEW because readiness gates were not fully met: "
            f"worst regression {worst} {deltas[worst]} breaches ready_max_regression -3.0 "
            f"(overall_delta {overall_delta:+.1f}, post-replay safety {c_m['safety_compliance']}, "
            f"post-replay overall {c_ov})."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Storage layer — Supabase tables and in-memory dicts share these helpers.
# ---------------------------------------------------------------------------
class PersistenceError(Exception):
    """A Supabase/PostgREST call failed; the API surfaces an honest 503."""


def _db_call(fn, *args, **kwargs):
    """Run a Supabase call; ANY exception → log full traceback + PersistenceError.

    Genuine "row not found" is NOT a persistence error — only exceptions from
    the call itself are. A query that succeeds and returns no rows must still
    be interpreted by the caller as not-found.
    """
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("Persistence call failed")
        raise PersistenceError("database call failed") from None


def _db_probe() -> bool:
    """Cheap read to confirm connectivity. Never raises."""
    if _mode != "supabase" or _supabase is None:
        return False
    try:
        _supabase.table("scenarios").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def _scenario_exists(scenario_id: str) -> bool:
    if _mode == "supabase":
        resp = _db_call(
            lambda: _supabase.table("scenarios").select("id").eq("id", scenario_id).limit(1).execute()
        )
        return bool(resp.data)
    return scenario_id in _memory["scenarios"]


def _insert_scenario(row: Dict[str, Any], event_rows: List[Dict[str, Any]]) -> None:
    if _mode == "supabase":
        _db_call(lambda: _supabase.table("scenarios").insert(row).execute())
        if event_rows:
            _db_call(lambda: _supabase.table("trace_events").insert(event_rows).execute())
    else:
        _memory["scenarios"][row["id"]] = row
        _memory["events"][row["id"]] = event_rows


def _list_scenarios() -> List[Dict[str, Any]]:
    if _mode == "supabase":
        resp = _db_call(
            lambda: _supabase.table("scenarios").select("*").order("created_at", desc=True).execute()
        )
        rows = resp.data or []
        counts: Dict[str, int] = {r["id"]: 0 for r in rows}
        ids = list(counts.keys())
        if ids:
            ev = _db_call(
                lambda: _supabase.table("trace_events").select("scenario_id").in_("scenario_id", ids).execute()
            )
            for e in ev.data or []:
                sid = e.get("scenario_id")
                if sid in counts:
                    counts[sid] += 1
        return [dict(r, event_count=counts.get(r["id"], 0)) for r in rows]
    out = []
    for sid, row in _memory["scenarios"].items():
        out.append(dict(row, event_count=len(_memory["events"].get(sid, []))))
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def _get_scenario_row(scenario_id: str) -> Optional[Dict[str, Any]]:
    if _mode == "supabase":
        resp = _db_call(
            lambda: _supabase.table("scenarios").select("*").eq("id", scenario_id).limit(1).execute()
        )
        return resp.data[0] if resp.data else None
    return _memory["scenarios"].get(scenario_id)


def _get_events(scenario_id: str) -> List[Dict[str, Any]]:
    if _mode == "supabase":
        resp = _db_call(
            lambda: (_supabase.table("trace_events").select("*")
                     .eq("scenario_id", scenario_id).order("sequence_number").execute())
        )
        return resp.data or []
    return sorted(_memory["events"].get(scenario_id, []), key=lambda e: e.get("sequence_number") or 0)


def _insert_run(run: Dict[str, Any]) -> Dict[str, Any]:
    if _mode == "supabase":
        resp = _db_call(lambda: _supabase.table("evaluation_runs").insert(run).execute())
        return resp.data[0] if resp.data else run
    _memory["runs"].setdefault(run["scenario_id"], []).append(run)
    return run


def _list_runs(scenario_id: str) -> List[Dict[str, Any]]:
    if _mode == "supabase":
        resp = _db_call(
            lambda: (_supabase.table("evaluation_runs").select("*")
                     .eq("scenario_id", scenario_id).order("created_at", desc=True).execute())
        )
        return resp.data or []
    runs = list(_memory["runs"].get(scenario_id, []))
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return runs


def _get_run_row(run_id: str) -> Optional[Dict[str, Any]]:
    if _mode == "supabase":
        resp = _db_call(
            lambda: _supabase.table("evaluation_runs").select("*").eq("id", run_id).limit(1).execute()
        )
        return resp.data[0] if resp.data else None
    for runs in _memory["runs"].values():
        for r in runs:
            if r["id"] == run_id:
                return r
    return None


def _insert_decision(decision: Dict[str, Any]) -> None:
    if _mode == "supabase":
        _db_call(lambda: _supabase.table("release_decisions").insert(decision).execute())
    else:
        _memory["decisions"].append(decision)


# ---------------------------------------------------------------------------
# Row → API shape mappers
# ---------------------------------------------------------------------------
def _scenario_out(row: Dict[str, Any], event_count: int, include_spec: bool = False) -> Dict[str, Any]:
    out = {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description") or "",
        "source_type": row.get("source_type") or "simulated_production_capture",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "event_count": event_count,
    }
    if include_spec:
        out["ai_ops_spec"] = row.get("ai_ops_spec") or {}
    return out


def _event_out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "scenario_id": row.get("scenario_id"),
        "sequence_number": row.get("sequence_number"),
        "agent_name": row.get("agent_name"),
        "event_type": row.get("event_type"),
        "input": row.get("input"),
        "output": row.get("output"),
        "metadata": row.get("metadata"),
        "timestamp": row.get("timestamp"),
    }


def _run_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a stored evaluation_runs row to the RUN contract used by the frontend."""
    return {
        "id": row.get("id"),
        "scenario_id": row.get("scenario_id"),
        "run_type": row.get("run_type"),
        "change_type": row.get("change_type"),
        "change_description": row.get("change_description"),
        "metrics": row.get("metrics") or {},
        "issues": row.get("issues") or [],
        "overall_score": row.get("overall_score"),
        "readiness_status": row.get("readiness_status"),
        "simulation": bool(row.get("is_simulation", True)),
        "simulation_note": row.get("simulation_note") or "",
        "created_at": row.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Seed on startup (best-effort; boot never fails because of it)
# ---------------------------------------------------------------------------
def _ensure_seed() -> None:
    if _scenario_exists(SEED_SCENARIO_ID):
        return
    now = _now()
    scenario_row = {
        "id": SEED_SCENARIO_ID,
        "name": "Unusual Expense Explanation",
        "description": "Financial assistant explains an unusual $2,847 expense to a cardholder.",
        "source_type": "simulated_production_capture",
        "ai_ops_spec": SEED_SPEC,
        "created_at": now,
        "updated_at": now,
    }
    event_rows = []
    for ev in SEED_EVENTS:
        event_rows.append({
            "id": _new_id(),
            "scenario_id": SEED_SCENARIO_ID,
            "sequence_number": ev["sequence"],
            "agent_name": ev["agent_name"],
            "event_type": ev["event_type"],
            "input": ev.get("input"),
            "output": ev.get("output"),
            "metadata": ev.get("metadata"),
            "timestamp": ev.get("timestamp"),
        })
    _insert_scenario(scenario_row, event_rows)
    logger.info("Seeded demo scenario %s", SEED_SCENARIO_ID)


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------
app = FastAPI(title=SERVICE, version=VERSION)


@app.middleware("http")
async def limit_body_size(request, call_next):
    """Reject request bodies larger than 1 MB with a safe 413.

    Content-Length is checked first as a cheap early reject, but it can be
    omitted (Transfer-Encoding: chunked), so the receive channel is also
    wrapped to count ACTUAL streamed bytes. Oversize bodies are cut off
    before the endpoint ever sees them.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request too large"})
        except ValueError:
            pass

    received = 0
    original_receive = request._receive

    async def counted_receive():
        nonlocal received
        message = await original_receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b"") or b"")
            if received > MAX_BODY_BYTES:
                # Surfaced by the FastAPI/Starlette exception middleware as
                # 413 {"detail": "Request too large"} (never a 500).
                raise HTTPException(status_code=413, detail="Request too large")
        return message

    request._receive = counted_receive
    return await call_next(request)


# Conservative security headers. NOTE: index.html relies on INLINE <style> and
# <script>, so 'unsafe-inline' must remain in style-src/script-src.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    ),
}


@app.middleware("http")
async def security_headers(request, call_next):
    """Attach security headers to every response (including error responses)."""
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """500 with a safe message; full traceback stays server-side only."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(PersistenceError)
async def persistence_error_handler(request, exc: PersistenceError):
    """Honest 503 when the database cannot be reached (details stay server-side).

    Full traceback was already logged by _db_call; the response body must not
    leak exception text, stack traces, URLs, or keys.
    """
    return JSONResponse(
        status_code=503,
        content={"detail": "Persistence unavailable — the database could not be reached. Data may not be saved."},
    )


@app.on_event("startup")
def startup_seed() -> None:
    try:
        _ensure_seed()
    except Exception:
        logger.exception("Seed step failed (continuing without seed)")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class EventIn(BaseModel):
    sequence: int
    agent_name: str
    event_type: str
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    source_type: str = "simulated_production_capture"
    spec: Dict[str, Any]
    events: List[EventIn] = Field(..., min_length=1, max_length=100)


class EvaluateBody(BaseModel):
    run_type: str = "baseline"


class ReplayBody(BaseModel):
    change_type: str
    change_description: str = Field(default="", max_length=500)


def _as_uuid(value: str, detail: str = "Scenario not found") -> str:
    """Validate a UUID path param before any lookup/query runs.

    Malformed ids get a clean 404 with the same detail strings the endpoints
    already use for missing resources (never a 500, never a DB round-trip).
    """
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail=detail)
    return value


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    """Serve the frontend (built in parallel) from the same directory."""
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/health")
def health():
    """Liveness + storage mode. Always 200; supabase connectivity is a cheap probe."""
    configured = _mode == "supabase"
    connected = _db_probe()
    return {
        "status": "ok",
        "service": SERVICE,
        "database": {"configured": configured, "connected": connected, "mode": _mode},
        "simulation": SIMULATION_TAG,
        "version": VERSION,
    }


@app.get("/api/scenarios")
def list_scenarios():
    rows = _list_scenarios()
    return {"scenarios": [_scenario_out(r, r.get("event_count", 0)) for r in rows]}


@app.post("/api/scenarios", status_code=201)
def create_scenario(body: ScenarioCreate):
    # NOTE: spec content is stored/serialized only — never eval'd/exec'd.
    scenario_id = _new_id()
    now = _now()
    scenario_row = {
        "id": scenario_id,
        "name": body.name,
        "description": body.description,
        "source_type": body.source_type or "simulated_production_capture",
        "ai_ops_spec": body.spec,
        "created_at": now,
        "updated_at": now,
    }
    event_rows = [{
        "id": _new_id(),
        "scenario_id": scenario_id,
        "sequence_number": ev.sequence,
        "agent_name": ev.agent_name,
        "event_type": ev.event_type,
        "input": ev.input,
        "output": ev.output,
        "metadata": ev.metadata,
        "timestamp": ev.timestamp or now,
    } for ev in body.events]
    _insert_scenario(scenario_row, event_rows)
    return {"scenario": _scenario_out(scenario_row, len(event_rows), include_spec=True)}


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: str):
    scenario_id = _as_uuid(scenario_id)
    row = _get_scenario_row(scenario_id)
    if not row:
        raise HTTPException(status_code=404, detail="Scenario not found")
    events = _get_events(scenario_id)
    return {"scenario": _scenario_out(row, len(events), include_spec=True),
            "events": [_event_out(e) for e in events]}


@app.post("/api/scenarios/{scenario_id}/evaluate", status_code=201)
def evaluate_scenario(scenario_id: str, body: EvaluateBody):
    scenario_id = _as_uuid(scenario_id)
    if body.run_type != "baseline":
        raise HTTPException(status_code=400, detail="run_type must be 'baseline'")
    if not _scenario_exists(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    metrics = _baseline_metrics(scenario_id)
    run = {
        "id": _new_id(),
        "scenario_id": scenario_id,
        "run_type": "baseline",
        "change_type": None,
        "change_description": None,
        "metrics": metrics,
        "issues": [dict(i) for i in BASELINE_ISSUES],
        "overall_score": _overall(metrics),
        "readiness_status": "BASELINE",
        "is_simulation": True,
        "simulation_note": f"Baseline metrics are deterministic functions of the scenario id and trace ({SIMULATION_TAG}).",
        "created_at": _now(),
    }
    stored = _insert_run(run)
    return {"run": _run_out(stored)}


@app.post("/api/scenarios/{scenario_id}/replay", status_code=201)
def replay_scenario(scenario_id: str, body: ReplayBody):
    scenario_id = _as_uuid(scenario_id)
    if body.change_type not in CHANGE_TYPES:
        raise HTTPException(status_code=400,
                            detail="change_type must be one of: coordination_update, model_change, prompt_update")
    if not _scenario_exists(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    # Always INSERT a new replay run; the baseline row is never overwritten.
    baseline = _baseline_metrics(scenario_id)  # deterministic reference baseline
    metrics, deltas = _replay_metrics(scenario_id, baseline, body.change_type)
    status, _, _ = _readiness(baseline, metrics, deltas)
    run = {
        "id": _new_id(),
        "scenario_id": scenario_id,
        "run_type": "simulated_replay",
        "change_type": body.change_type,
        "change_description": body.change_description,
        "metrics": metrics,
        "issues": _replay_issues(body.change_type, deltas),
        "overall_score": _overall(metrics),
        "readiness_status": status,
        "is_simulation": True,
        "simulation_note": (f"Simulated replay of change_type={body.change_type} with deterministic "
                            f"hash-based scoring ({SIMULATION_TAG})."),
        "created_at": _now(),
    }
    stored = _insert_run(run)
    return {"run": _run_out(stored)}


@app.get("/api/scenarios/{scenario_id}/runs")
def list_runs(scenario_id: str):
    scenario_id = _as_uuid(scenario_id)
    if not _scenario_exists(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {"runs": [_run_out(r) for r in _list_runs(scenario_id)]}


@app.get("/api/scenarios/{scenario_id}/compare/{baseline_id}/{comparison_id}")
def compare_runs(scenario_id: str, baseline_id: str, comparison_id: str):
    scenario_id = _as_uuid(scenario_id)
    baseline_id = _as_uuid(baseline_id, "Baseline run not found for this scenario")
    comparison_id = _as_uuid(comparison_id, "Comparison run not found for this scenario")
    if not _scenario_exists(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    base_row = _get_run_row(baseline_id)
    if not base_row or base_row.get("scenario_id") != scenario_id:
        raise HTTPException(status_code=404, detail="Baseline run not found for this scenario")
    comp_row = _get_run_row(comparison_id)
    if not comp_row or comp_row.get("scenario_id") != scenario_id:
        raise HTTPException(status_code=404, detail="Comparison run not found for this scenario")
    if base_row.get("run_type") != "baseline":
        raise HTTPException(status_code=400, detail="baseline_id must reference a baseline run")
    if comp_row.get("run_type") != "simulated_replay":
        raise HTTPException(status_code=400, detail="comparison_id must reference a simulated_replay run")

    base_run, comp_run = _run_out(base_row), _run_out(comp_row)
    b_m, c_m = base_run["metrics"], comp_run["metrics"]
    change_type = comp_run.get("change_type") or "simulated_replay"

    deltas = {k: round(float(c_m.get(k, 0)) - float(b_m.get(k, 0)), 1) for k in METRIC_KEYS}
    improvements = [_metric_entry(k, b_m[k], c_m[k], deltas[k], change_type, "improvement")
                    for k in METRIC_KEYS if deltas[k] > 0]
    regressions = [_metric_entry(k, b_m[k], c_m[k], deltas[k], change_type, "regression")
                   for k in METRIC_KEYS if deltas[k] < 0]
    remaining_risks = [{
        "metric": r["metric"],
        "message": (f"{r['metric']} is {r['delta']} points below baseline after the {change_type} "
                    f"replay; validate in staging before promoting."),
    } for r in regressions]

    b_ov = float(base_run.get("overall_score") or _overall(b_m))
    c_ov = float(comp_run.get("overall_score") or _overall(c_m))
    status, overall_delta, _ = _readiness(b_m, c_m, deltas)
    rationale = _build_rationale(status, change_type, b_m, c_m, deltas, b_ov, c_ov, overall_delta)
    # Contract: `recommendation` is the short keyword the frontend switches on
    # (READY / NOT READY / NEEDS REVIEW); the narrative lives in `rationale`
    # and `recommendation_summary`.
    recommendation = status
    recommendation_summary = RECOMMENDATIONS[status]
    comparison_note = (f"Baseline-vs-replay comparison and release decision are deterministic "
                       f"simulations over stored runs ({SIMULATION_TAG}).")

    # Persist the decision in BOTH modes (supabase insert / in-memory list).
    _insert_decision({
        "id": _new_id(),
        "scenario_id": scenario_id,
        "baseline_run_id": base_run["id"],
        "comparison_run_id": comp_run["id"],
        "readiness_status": status,
        "improvements": improvements,
        "regressions": regressions,
        "remaining_risks": remaining_risks,
        "deltas": deltas,
        "rationale": rationale,
        "recommendation": recommendation,
        "recommendation_summary": recommendation_summary,
        "thresholds": THRESHOLDS,
        "created_at": _now(),
    })

    return {"comparison": {
        "baseline": base_run,
        "comparison": comp_run,
        "deltas": deltas,
        "improvements": improvements,
        "regressions": regressions,
        "remaining_risks": remaining_risks,
        "recommendation": recommendation,
        "recommendation_summary": recommendation_summary,
        "thresholds": THRESHOLDS,
        "rationale": rationale,
        "simulation": True,
        "simulation_note": comparison_note,
    }}
