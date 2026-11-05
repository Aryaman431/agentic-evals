"""FastAPI backend for the Voice Agent Evaluation scenario lab."""

import itertools
import os
from datetime import datetime
from typing import Any

import uvicorn
from dataset import VOICE_TEST_CASES
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scenario_runner import evaluate_scenario
from scenarios import (
    FAULT_KEYS,
    Scenario,
    create_scenario,
    delete_scenario,
    get_scenario,
    list_scenarios,
    slugify,
    update_scenario,
    validate_scenario,
)

# -----------------------------
# Request models
# -----------------------------


class ScenarioCreate(BaseModel):
    name: str
    description: str = ""
    input: str
    expected_transcript: str | None = None
    expected_intent: str | None = None
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] | None = None
    expected_response_criteria: list[str] = []
    rules: dict[str, bool] | None = None
    fault: str = "none"
    max_latency_ms: float = 5000.0


class ScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    input: str | None = None
    expected_transcript: str | None = None
    expected_intent: str | None = None
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] | None = None
    expected_response_criteria: list[str] | None = None
    rules: dict[str, bool] | None = None
    fault: str | None = None
    max_latency_ms: float | None = None


class EvaluateRequest(BaseModel):
    scenario_id: str | None = None
    scenario_name: str | None = None
    input: str | None = None
    expected_intent: str | None = None
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] | None = None
    expected_response_criteria: list[str] | None = None
    expected_transcript: str | None = None
    rules: dict[str, bool] | None = None
    fault: str | None = None
    max_latency_ms: float | None = None


# -----------------------------
# App setup
# -----------------------------

app = FastAPI(title="Voice Agent Evaluation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("EVAL_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_RUNS: list[dict[str, Any]] = []
_RUN_COUNTER = itertools.count(1)


# -----------------------------
# Scenario resolution helpers
# -----------------------------


def _default_rules(request: EvaluateRequest) -> dict[str, bool]:
    """All rules that the provided fields can support default to enabled."""
    return {
        "transcript_accuracy": request.expected_transcript is not None,
        "intent_accuracy": request.expected_intent is not None,
        "tool_selection": request.expected_tool is not None,
        "tool_arguments": request.expected_tool is not None
        and request.expected_arguments is not None,
        "response_quality": bool(request.expected_response_criteria),
        "groundedness": True,
        "reliability": True,
        "latency": True,
    }


def _resolve_scenario(request: EvaluateRequest) -> Scenario:
    """Stored scenario (with overrides) or a scenario built from raw fields."""
    if request.fault is not None and request.fault not in FAULT_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown fault mode: {request.fault!r}")

    if request.scenario_id is not None:
        stored = get_scenario(request.scenario_id)
        if stored is None:
            raise HTTPException(
                status_code=404, detail=f"Scenario '{request.scenario_id}' not found"
            )

        data = stored.model_dump()
        overrides = {
            "name": request.scenario_name,
            "input": request.input,
            "expected_transcript": request.expected_transcript,
            "expected_intent": request.expected_intent,
            "expected_tool": request.expected_tool,
            "expected_arguments": request.expected_arguments,
            "expected_response_criteria": request.expected_response_criteria,
            "rules": request.rules,
            "fault": request.fault,
            "max_latency_ms": request.max_latency_ms,
        }
        data.update({key: value for key, value in overrides.items() if value is not None})
        try:
            scenario = Scenario(**data)
            validate_scenario(scenario)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return scenario

    if not (request.input or "").strip():
        raise HTTPException(
            status_code=400, detail="input is required when scenario_id is not provided"
        )

    data = {
        "id": slugify(request.scenario_name or "Untitled Scenario"),
        "name": request.scenario_name or "Untitled Scenario",
        "input": request.input,
        "expected_transcript": request.expected_transcript,
        "expected_intent": request.expected_intent,
        "expected_tool": request.expected_tool,
        "expected_arguments": request.expected_arguments,
        "expected_response_criteria": request.expected_response_criteria or [],
        "rules": request.rules if request.rules is not None else _default_rules(request),
        "fault": request.fault or "none",
        "max_latency_ms": request.max_latency_ms if request.max_latency_ms is not None else 5000.0,
    }
    try:
        scenario = Scenario(**data)
        validate_scenario(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scenario


# -----------------------------
# Routes
# -----------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "voice-agent-eval-api"}


@app.get("/scenarios")
def scenarios_endpoint() -> dict[str, list[dict[str, Any]]]:
    return {"scenarios": [scenario.model_dump() for scenario in list_scenarios()]}


@app.get("/dataset")
def dataset_endpoint() -> dict[str, list[dict[str, Any]]]:
    return {"cases": list(VOICE_TEST_CASES)}


@app.post("/scenarios")
def create_scenario_endpoint(body: ScenarioCreate) -> dict[str, Any]:
    try:
        scenario = create_scenario(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scenario.model_dump()


@app.put("/scenarios/{scenario_id}")
def update_scenario_endpoint(scenario_id: str, body: ScenarioUpdate) -> dict[str, Any]:
    if get_scenario(scenario_id) is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")
    payload = body.model_dump(exclude_unset=True)
    try:
        scenario = update_scenario(scenario_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return scenario.model_dump()


@app.delete("/scenarios/{scenario_id}")
def delete_scenario_endpoint(scenario_id: str) -> dict[str, str]:
    try:
        delete_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    return {"deleted": scenario_id}


@app.post("/evaluate")
def evaluate_endpoint(request: EvaluateRequest) -> dict[str, Any]:
    scenario = _resolve_scenario(request)

    try:
        evaluation = evaluate_scenario(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now()
    run_id = f"RUN-{next(_RUN_COUNTER):03d}"
    # Full evaluation payload (metrics/failures/agent_result/trace/report) plus the
    # run id - byte-identical shape to what POST /evaluate has always returned.
    payload = {**evaluation, "run_id": run_id}
    run = {
        "run_id": run_id,
        "scenario_id": scenario.id,
        "scenario": scenario.name,
        "time": now.strftime("%H:%M:%S"),
        "iso": now.isoformat(),
        "status": "PASSED" if evaluation["passed"] else "FAILED",
        "score": round(evaluation["score"], 4),
        "latency_ms": round(evaluation["latency_ms"], 3),
        "fault": scenario.fault,
        # Full payload stored on the summary row so the dashboard can rebuild the
        # "View Evaluation" report after a page reload (in-memory only, no DB).
        "evaluation": payload,
    }
    _RUNS.insert(0, run)

    return payload


@app.get("/runs")
def runs_endpoint() -> dict[str, list[dict[str, Any]]]:
    # Rows are returned by reference: each row carries its "evaluation" payload,
    # so clients automatically receive the full report alongside the summary fields.
    return {"runs": _RUNS}


@app.get("/stats")
def stats_endpoint() -> dict[str, Any]:
    # Rows are returned by reference, so "latest" also carries its "evaluation"
    # payload - no extra code needed here (see POST /evaluate and GET /runs).
    total = len(_RUNS)
    passed = sum(1 for run in _RUNS if run["status"] == "PASSED")
    avg_score = sum(run["score"] for run in _RUNS) / total if total else 0
    return {
        "total_runs": total,
        "passed": passed,
        "failed": total - passed,
        "avg_score": avg_score,
        "latest": _RUNS[0] if _RUNS else None,
    }


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=os.getenv("EVAL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("EVAL_API_PORT", "8001")),
        log_level="info",
    )
