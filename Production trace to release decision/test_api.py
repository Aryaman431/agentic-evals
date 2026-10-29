"""Automated test suite for the Production Trace → Release Decision FastAPI app.

Covers: the five-stage workflow contract (in-memory mode), error honesty
(404/400/503 with no secret leaks), determinism of scoring, and config
consistency across schema.sql / render.yaml / requirements.txt.
"""
import os
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

# Ensure import-time backend selection is in_memory: clear any ambient
# SUPABASE_* env vars BEFORE importing the app module (app.py picks the
# storage mode at import).
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

import app as app_module  # noqa: E402

BASE = "http://testserver"
SEED_ID = "00000000-0000-4000-8000-000000000001"
METRIC_KEYS = {
    "response_quality", "task_completion", "tool_correctness",
    "agent_coordination", "safety_compliance", "performance",
}
READINESS = {"READY", "NEEDS REVIEW", "NOT READY"}
ROOT = Path(__file__).parent


@pytest.fixture(scope="module")
def client():
    # Context manager triggers the startup hook (seeds the demo scenario).
    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture(scope="module")
def seed_workflow(client):
    """One baseline + one replay on the seeded scenario; shared by later tests."""
    b = client.post(f"{BASE}/api/scenarios/{SEED_ID}/evaluate", json={"run_type": "baseline"})
    assert b.status_code == 200 or b.status_code == 201
    r = client.post(f"{BASE}/api/scenarios/{SEED_ID}/replay", json={"change_type": "prompt_update"})
    assert r.status_code == 200 or r.status_code == 201
    return b.json()["run"], r.json()["run"]


# ---------------------------------------------------------------------------
# A. Five-stage workflow contract (in-memory mode)
# ---------------------------------------------------------------------------
def test_health_shape(client):
    resp = client.get(f"{BASE}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"]["mode"] == "in_memory"
    assert isinstance(body["database"]["connected"], bool)
    # In-memory mode: the supabase probe is False by design.
    assert body["database"]["connected"] is False
    assert body["simulation"]


def test_root_serves_real_ui(client):
    resp = client.get(f"{BASE}/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert "Production Trace" in html
    assert "<script" in html


def test_scenarios_contains_seeded_scenario(client):
    resp = client.get(f"{BASE}/api/scenarios")
    assert resp.status_code == 200
    scenarios = resp.json()["scenarios"]
    seed = next(s for s in scenarios if s["id"] == SEED_ID)
    assert seed["event_count"] == 6


def test_create_scenario_and_retrieve(client):
    payload = {
        "name": "Test Scenario",
        "description": "created by test_api.py",
        "spec": {"execution": {"event_count": 2}},
        "events": [
            {"sequence": 0, "agent_name": "a1", "event_type": "user_request"},
            {"sequence": 1, "agent_name": "a2", "event_type": "final_response"},
        ],
    }
    resp = client.post(f"{BASE}/api/scenarios", json=payload)
    assert resp.status_code == 201
    created = resp.json()["scenario"]
    assert created["name"] == "Test Scenario"
    assert created["event_count"] == 2

    got = client.get(f"{BASE}/api/scenarios/{created['id']}")
    assert got.status_code == 200
    body = got.json()
    assert body["scenario"]["id"] == created["id"]
    assert len(body["events"]) == 2


def test_evaluate_baseline_contract(client):
    resp = client.post(f"{BASE}/api/scenarios/{SEED_ID}/evaluate", json={"run_type": "baseline"})
    assert resp.status_code == 201
    run = resp.json()["run"]
    assert set(run["metrics"].keys()) == METRIC_KEYS
    assert isinstance(run["overall_score"], (int, float))
    assert run["readiness_status"] == "BASELINE"
    assert run["simulation"] is True
    assert run["run_type"] == "baseline"


def test_replay_contract(client):
    resp = client.post(f"{BASE}/api/scenarios/{SEED_ID}/replay",
                       json={"change_type": "prompt_update"})
    assert resp.status_code == 201
    run = resp.json()["run"]
    assert run["run_type"] == "simulated_replay"
    assert run["readiness_status"] in READINESS
    assert run["simulation"] is True
    assert set(run["metrics"].keys()) == METRIC_KEYS


def test_runs_list_has_both_runs(client, seed_workflow):
    resp = client.get(f"{BASE}/api/scenarios/{SEED_ID}/runs")
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert len(runs) >= 2
    assert {r["run_type"] for r in runs} >= {"baseline", "simulated_replay"}


def test_compare_contract(client, seed_workflow):
    baseline, replay = seed_workflow
    resp = client.get(
        f"{BASE}/api/scenarios/{SEED_ID}/compare/{baseline['id']}/{replay['id']}"
    )
    assert resp.status_code == 200
    cmp = resp.json()["comparison"]
    assert cmp["recommendation"] in READINESS
    assert set(cmp["deltas"].keys()) == METRIC_KEYS
    assert cmp["rationale"].strip()
    assert cmp["recommendation_summary"].strip()
    assert cmp["simulation"] is True


def test_replay_is_deterministic(client):
    """Same scenario + change_type ⇒ identical metrics (hash scoring, no RNG)."""
    sid = client.get(f"{BASE}/api/scenarios/{SEED_ID}").json()["scenario"]["id"]
    r1 = client.post(f"{BASE}/api/scenarios/{sid}/replay", json={"change_type": "model_change"})
    r2 = client.post(f"{BASE}/api/scenarios/{sid}/replay", json={"change_type": "model_change"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["run"]["metrics"] == r2.json()["run"]["metrics"]


# ---------------------------------------------------------------------------
# B. Error honesty
# ---------------------------------------------------------------------------
def test_malformed_uuid_is_404_not_500(client):
    resp = client.get(f"{BASE}/api/scenarios/not-a-uuid")
    assert resp.status_code == 404


def test_unknown_valid_uuid_is_404(client):
    resp = client.get(f"{BASE}/api/scenarios/00000000-0000-4000-8000-ffffffffffff")
    assert resp.status_code == 404


def test_bad_run_type_is_400(client):
    resp = client.post(f"{BASE}/api/scenarios/{SEED_ID}/evaluate", json={"run_type": "chaos"})
    assert resp.status_code == 400


def test_unknown_change_type_is_400(client):
    resp = client.post(f"{BASE}/api/scenarios/{SEED_ID}/replay", json={"change_type": "nope"})
    assert resp.status_code == 400


_LEAKY_EXC = "connection refused to https://abcdefg.supabase.co/rest/v1 with key eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.leak"


class _BoomClient:
    """Fake supabase client: every DB call raises a leaky exception."""
    def table(self, *args, **kwargs):
        raise RuntimeError(_LEAKY_EXC)


@pytest.fixture
def forced_supabase_mode():
    """Force supabase mode with an exploding client; always restore in-memory."""
    orig_mode, orig_client = app_module._mode, app_module._supabase
    app_module._mode = "supabase"
    app_module._supabase = _BoomClient()
    yield
    app_module._mode, app_module._supabase = orig_mode, orig_client


def _assert_503_no_leak(resp):
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "Persistence unavailable" in detail
    assert "supabase.co" not in detail
    assert "eyJ" not in detail
    assert "Traceback" not in detail
    assert "connection refused" not in detail.lower()
    assert _LEAKY_EXC not in detail


def test_persistence_errors_are_honest_503s(client, forced_supabase_mode):
    _assert_503_no_leak(client.get(f"{BASE}/api/scenarios"))
    _assert_503_no_leak(client.get(f"{BASE}/api/scenarios/{SEED_ID}"))
    _assert_503_no_leak(client.post(f"{BASE}/api/scenarios", json={
        "name": "x", "spec": {},
        "events": [{"sequence": 0, "agent_name": "a", "event_type": "e"}],
    }))
    _assert_503_no_leak(client.post(f"{BASE}/api/scenarios/{SEED_ID}/evaluate",
                                    json={"run_type": "baseline"}))
    _assert_503_no_leak(client.get(f"{BASE}/api/scenarios/{SEED_ID}/runs"))


def test_health_survives_persistence_outage(client, forced_supabase_mode):
    resp = client.get(f"{BASE}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"]["mode"] == "supabase"
    assert body["database"]["connected"] is False


def test_in_memory_unaffected_after_outage_fixture(client):
    """Fixture teardown restored in-memory mode; the API still works."""
    resp = client.get(f"{BASE}/health")
    assert resp.status_code == 200
    assert resp.json()["database"]["mode"] == "in_memory"
    resp = client.get(f"{BASE}/api/scenarios")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# C. Config consistency
# ---------------------------------------------------------------------------
def _schema_tables():
    sql = (ROOT / "schema.sql").read_text(encoding="utf-8")
    tables = {}
    for name, block in re.findall(
            r"create table if not exists\s+(\w+)\s*\((.*?)\);", sql, re.S | re.I):
        cols = set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\s+\w", block, re.M | re.I))
        tables[name.lower()] = cols
    return tables


def test_schema_has_all_columns_the_app_writes():
    tables = _schema_tables()
    assert {"recommendation_summary"} <= tables["release_decisions"]
    assert {"ai_ops_spec"} <= tables["scenarios"]
    assert {"is_simulation", "simulation_note", "overall_score"} <= tables["evaluation_runs"]
    assert {"sequence_number"} <= tables["trace_events"]


def test_render_yaml_structure():
    cfg = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    assert set(cfg.keys()) == {"services"}  # no stray root-level runtime etc.
    svc = cfg["services"][0]
    assert svc["type"] == "web"
    assert svc["runtime"] == "python"
    assert "--host 0.0.0.0" in svc["startCommand"]
    assert "$PORT" in svc["startCommand"]
    assert svc["healthCheckPath"] == "/health"
    env = {e["key"]: e for e in svc["envVars"]}
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        assert env[key]["sync"] is False
        assert "value" not in env[key]


def test_requirements_excludes_pytest():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pytest" not in req


def test_no_secret_looking_strings_in_sources():
    pat = re.compile(r"eyJ[A-Za-z0-9_-]{20,}")
    for fname in ("app.py", "index.html", "render.yaml"):
        text = (ROOT / fname).read_text(encoding="utf-8", errors="ignore")
        assert pat.search(text) is None, f"secret-looking string in {fname}"
