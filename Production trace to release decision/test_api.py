"""Automated test suite for the Production Trace → Release Decision FastAPI app.

Covers: the five-stage workflow contract over the hardcoded sample data,
error honesty (404/400), determinism of scoring, and config consistency
across render.yaml / requirements.txt. No environment variables needed.
"""

import re
from pathlib import Path

import app as app_module
import pytest
import yaml
from fastapi.testclient import TestClient

BASE = "http://testserver"
SEED_ID = "00000000-0000-4000-8000-000000000001"
SAMPLE2_ID = "00000000-0000-4000-8000-000000000002"
METRIC_KEYS = {
    "response_quality",
    "task_completion",
    "tool_correctness",
    "agent_coordination",
    "safety_compliance",
    "performance",
}
READINESS = {"READY", "NEEDS REVIEW", "NOT READY"}
ROOT = Path(__file__).parent


@pytest.fixture(scope="module")
def client():
    # Context manager triggers the startup hook (seeds sample_data.py records).
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
# A. Five-stage workflow contract (sample data, no env vars)
# ---------------------------------------------------------------------------
def test_health_reports_sample_data_mode(client):
    """Always 200 + mode sample_data; works with zero configuration."""
    resp = client.get(f"{BASE}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"]["mode"] == "sample_data"
    assert body["simulation"]


def test_root_serves_real_ui(client):
    resp = client.get(f"{BASE}/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text
    assert "Production Trace" in html
    assert "<script" in html


def test_scenarios_list_non_empty(client):
    resp = client.get(f"{BASE}/api/scenarios")
    assert resp.status_code == 200
    scenarios = resp.json()["scenarios"]
    assert len(scenarios) >= 2  # both seeded sample scenarios


def test_scenarios_contains_seeded_scenario(client):
    resp = client.get(f"{BASE}/api/scenarios")
    assert resp.status_code == 200
    scenarios = resp.json()["scenarios"]
    seed = next(s for s in scenarios if s["id"] == SEED_ID)
    assert seed["event_count"] == 6


def test_get_seeded_scenario_with_events(client):
    resp = client.get(f"{BASE}/api/scenarios/{SEED_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scenario"]["id"] == SEED_ID
    assert body["scenario"]["ai_ops_spec"]["spec_version"] == "0.3"
    assert len(body["events"]) == 6
    assert body["events"][0]["sequence_number"] == 0


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
    resp = client.post(
        f"{BASE}/api/scenarios/{SEED_ID}/replay", json={"change_type": "prompt_update"}
    )
    assert resp.status_code == 201
    run = resp.json()["run"]
    assert run["run_type"] == "simulated_replay"
    assert run["readiness_status"] in READINESS
    assert run["simulation"] is True
    assert set(run["metrics"].keys()) == METRIC_KEYS


def test_seeded_runs_out_of_the_box(client):
    """Seeded sample runs exist before any evaluate/replay call is made.

    SAMPLE2_ID is never written to by this suite, so its runs prove the
    startup seed ships a baseline AND a simulated-replay run per scenario.
    """
    resp = client.get(f"{BASE}/api/scenarios/{SAMPLE2_ID}/runs")
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert {r["run_type"] for r in runs} >= {"baseline", "simulated_replay"}


def test_runs_list_has_both_runs(client, seed_workflow):
    resp = client.get(f"{BASE}/api/scenarios/{SEED_ID}/runs")
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert len(runs) >= 2
    assert {r["run_type"] for r in runs} >= {"baseline", "simulated_replay"}


def test_seeded_compare_returns_payload(client):
    """Compare works out of the box on the seeded runs of SAMPLE2_ID."""
    runs = client.get(f"{BASE}/api/scenarios/{SAMPLE2_ID}/runs").json()["runs"]
    baseline = next(r for r in runs if r["run_type"] == "baseline")
    replay = next(r for r in runs if r["run_type"] == "simulated_replay")
    resp = client.get(f"{BASE}/api/scenarios/{SAMPLE2_ID}/compare/{baseline['id']}/{replay['id']}")
    assert resp.status_code == 200
    cmp = resp.json()["comparison"]
    assert cmp["recommendation"] in READINESS
    assert set(cmp["deltas"].keys()) == METRIC_KEYS
    assert cmp["rationale"].strip()


def test_compare_contract(client, seed_workflow):
    baseline, replay = seed_workflow
    resp = client.get(f"{BASE}/api/scenarios/{SEED_ID}/compare/{baseline['id']}/{replay['id']}")
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


# ---------------------------------------------------------------------------
# C. Config consistency
# ---------------------------------------------------------------------------
def test_render_yaml_structure():
    cfg = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    assert set(cfg.keys()) == {"services"}  # no stray root-level runtime etc.
    svc = cfg["services"][0]
    assert svc["type"] == "web"
    assert svc["runtime"] == "python"
    assert svc["rootDir"] == "Production trace to release decision"
    assert "--host 0.0.0.0" in svc["startCommand"]
    assert "$PORT" in svc["startCommand"]
    assert svc["healthCheckPath"] == "/health"
    # CORS is configured through the allowed-origins env var; no DB credentials.
    env = {item["key"]: item["value"] for item in (svc.get("envVars") or [])}
    assert "EVAL_CORS_ORIGINS" in env
    assert not any(
        marker in key.upper()
        for key in env
        for marker in ("DATABASE", "SUPABASE", "SECRET", "PASSWORD", "TOKEN")
    )


def test_requirements_excludes_pytest():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pytest" not in req


def test_sample_data_covers_required_records():
    """sample_data.py ships ≥2 scenarios, events, runs, and decisions."""
    import sample_data

    assert len(sample_data.SCENARIOS) >= 2
    for sc in sample_data.SCENARIOS:
        assert sample_data.EVENTS.get(sc["id"]), f"no events for {sc['id']}"
        run_types = {r["run_type"] for r in sample_data.RUNS.get(sc["id"], [])}
        assert run_types >= {"baseline", "simulated_replay"}
    assert len(sample_data.DECISIONS) >= 1


def test_no_secret_looking_strings_in_sources():
    pat = re.compile(r"eyJ[A-Za-z0-9_-]{20,}")
    for fname in ("app.py", "index.html", "render.yaml", "sample_data.py"):
        text = (ROOT / fname).read_text(encoding="utf-8", errors="ignore")
        assert pat.search(text) is None, f"secret-looking string in {fname}"
