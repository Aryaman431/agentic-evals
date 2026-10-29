"""FastAPI route tests (design section 9, items 25-28).

CI installs only ``uv sync --extra dev`` (no fastapi/uvicorn), so the module
skips wholesale via ``importorskip``; the fastapi-dependent demo modules are
bound with ``importlib`` afterwards because ruff E402 forbids real imports
once statements have run. Endpoints are exercised by calling the route
functions directly with constructed pydantic bodies -- no starlette
TestClient (which would require httpx, a new dependency).
"""

import importlib
import os
from collections.abc import Iterator
from typing import Any

import dataset_store
import history
import pytest
from chat_pipeline import PANEL_ORDER
from dataset_store import DATASET_DEFAULT_COUNT
from scenarios import PRESET_SCENARIOS

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

fastapi = importlib.import_module("fastapi")
server = importlib.import_module("server")
routes_chat = importlib.import_module("routes_chat")
routes_dataset = importlib.import_module("routes_dataset")
routes_evals = importlib.import_module("routes_evals")

HTTPException = fastapi.HTTPException

MSG = "Where is my order 1234?"
_HISTORY_STORES = (
    "_RUNS",
    "_CHAT_RUNS",
    "_EVALUATIONS",
    "_TRACES",
    "_PACK_RUNS",
    "_GATE_DECISIONS",
    "_ACTIVITY",
)


@pytest.fixture(autouse=True)
def _clean_judge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the clean-env judge state so probes are deterministic."""
    for key in [name for name in os.environ if name.startswith("EVAL_JUDGE_")]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolated_stores() -> Iterator[None]:
    """Snapshot every module-level store and restore it after the test."""
    snapshots = {name: list(getattr(history, name)) for name in _HISTORY_STORES}
    baseline_cache = history._BASELINE_CACHE
    cases = list(dataset_store._CASES)
    results = dict(dataset_store._LAST_RESULTS)
    yield
    for name, rows in snapshots.items():
        store: list[dict[str, Any]] = getattr(history, name)
        store[:] = rows
    history._BASELINE_CACHE = baseline_cache
    dataset_store._CASES[:] = cases
    dataset_store._LAST_RESULTS.clear()
    dataset_store._LAST_RESULTS.update(results)


# -----------------------------
# POST /chat (item 25)
# -----------------------------


def test_chat_endpoint_returns_agent_trace_and_eight_metric_evaluation() -> None:
    response = routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG, fault="none"))

    assert set(response) == {"run_id", "created_at", "agent", "trace", "evaluation"}
    assert response["run_id"].startswith("CHAT-")

    agent = response["agent"]
    assert set(agent) == {
        "transcript",
        "intent",
        "tool_name",
        "tool_args",
        "tool_result",
        "response",
        "latency_ms",
        "recovered",
        "fault",
    }
    assert agent["intent"] == "order_status"
    assert agent["fault"] == "none"

    trace_row = response["trace"]
    assert set(trace_row) == {
        "created_at",
        "kind",
        "run_id",
        "source",
        "steps",
        "summary",
        "trace",
        "trace_id",
    }
    assert trace_row["kind"] == "chat"
    assert trace_row["run_id"] == response["run_id"]

    evaluation = response["evaluation"]
    assert set(evaluation) == {
        "case",
        "cost_usd",
        "created_at",
        "eval_id",
        "failures",
        "judge",
        "kind",
        "latency_ms",
        "metrics",
        "passed",
        "report",
        "run_id",
        "score",
        "trace_id",
    }
    assert evaluation["kind"] == "chat"
    assert evaluation["passed"] is True
    assert evaluation["score"] == 1.0
    assert evaluation["trace_id"] == trace_row["trace_id"]
    assert [metric["key"] for metric in evaluation["metrics"]] == PANEL_ORDER
    # The section-4 evaluation core never leaks the route-only extras.
    assert "agent" not in evaluation
    assert "trace" not in evaluation
    assert "steps" not in evaluation
    assert evaluation["judge"]["available"] is False

    # Exactly one chat run, one evaluation row and one trace row were stored.
    assert [row["run_id"] for row in history.list_chat_runs()] == [response["run_id"]]
    assert [row["eval_id"] for row in history.list_evaluations("chat")] == [evaluation["eval_id"]]
    assert routes_evals.traces_endpoint(kind="chat")["total"] == 1


def test_chat_endpoint_rejects_blank_message() -> None:
    with pytest.raises(HTTPException) as excinfo:
        routes_chat.chat_endpoint(routes_chat.ChatRequest(message="   "))

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "message must not be blank"
    assert history.list_chat_runs() == []


def test_chat_endpoint_rejects_unknown_fault() -> None:
    with pytest.raises(HTTPException) as excinfo:
        routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG, fault="not-a-fault"))

    assert excinfo.value.status_code == 400
    assert "Unknown fault mode" in str(excinfo.value.detail)
    assert history.list_chat_runs() == []


def test_chat_endpoint_evaluate_false_returns_null_evaluation() -> None:
    response = routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG, evaluate=False))

    assert set(response) == {"run_id", "created_at", "agent", "trace", "evaluation"}
    assert response["evaluation"] is None
    assert response["agent"]["intent"] == "order_status"
    assert response["trace"]["kind"] == "chat"
    # An unevaluated run records only its trace: a chat-run row requires an
    # evaluation payload, which this mode deliberately does not produce.
    assert history.list_chat_runs() == []
    assert routes_evals.traces_endpoint(kind="chat")["total"] == 1


# -----------------------------
# POST /chat/evaluate (item 26)
# -----------------------------


def test_chat_evaluate_run_id_mode_rescores_without_rerunning() -> None:
    first = routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG))
    stored = history.list_chat_runs()[0]

    second = routes_chat.chat_evaluate_endpoint(
        routes_chat.ChatEvaluateRequest(run_id=first["run_id"])
    )

    assert set(second) == {"evaluation", "run_id", "trace_id"}
    assert second["run_id"] == first["run_id"]
    assert second["trace_id"] == first["evaluation"]["trace_id"]

    # Fresh evaluation id, but the stored trace is reused: identical latency
    # and no second chat run proves the agent did not execute again.
    assert second["evaluation"]["eval_id"] != stored["eval_id"]
    assert second["evaluation"]["eval_id"].startswith("EVAL-")
    assert second["evaluation"]["latency_ms"] == first["evaluation"]["latency_ms"]
    assert second["evaluation"]["trace_id"] == second["trace_id"]
    assert second["evaluation"]["passed"] is first["evaluation"]["passed"]
    assert [row["run_id"] for row in history.list_chat_runs()] == [first["run_id"]]


def test_chat_evaluate_message_mode_records_a_new_evaluation() -> None:
    payload = routes_chat.chat_evaluate_endpoint(routes_chat.ChatEvaluateRequest(message=MSG))

    assert set(payload) == {"evaluation", "run_id", "trace_id"}
    assert payload["run_id"].startswith("CHAT-")
    assert payload["trace_id"].startswith("trace-chat-")
    assert payload["evaluation"]["run_id"] == payload["run_id"]
    assert payload["evaluation"]["trace_id"] == payload["trace_id"]
    assert payload["evaluation"]["eval_id"].startswith("EVAL-")
    assert len(history.list_chat_runs()) == 1


def test_chat_evaluate_unknown_run_id_is_404() -> None:
    with pytest.raises(HTTPException) as excinfo:
        routes_chat.chat_evaluate_endpoint(routes_chat.ChatEvaluateRequest(run_id="CHAT-9999"))

    assert excinfo.value.status_code == 404
    assert "not found" in str(excinfo.value.detail)


def test_chat_evaluate_without_message_or_run_is_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        routes_chat.chat_evaluate_endpoint(routes_chat.ChatEvaluateRequest())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "message must not be blank"


# -----------------------------
# Dataset CRUD + run (item 27)
# -----------------------------


def test_dataset_crud_endpoints_round_trip() -> None:
    created = routes_dataset.create_dataset_case(
        routes_dataset.DatasetCaseIn(
            id="zz-srv", audio="Tell me something.", expected_intent="chitchat"
        )
    )
    assert created["id"] == "zz-srv"

    fetched = routes_dataset.get_dataset_case("zz-srv")
    assert set(fetched) == {"case", "last_result"}
    assert fetched["case"] == created
    assert fetched["last_result"] is None

    updated = routes_dataset.update_dataset_case(
        "zz-srv", routes_dataset.DatasetCaseIn(expected_response_contains=["mutated"])
    )
    assert updated["expected_response_contains"] == ["mutated"]
    assert updated["expected_intent"] == "chitchat"  # partial update keeps other fields

    duplicate = routes_dataset.duplicate_dataset_case("zz-srv")
    assert duplicate["id"] == "zz-srv-copy"

    assert routes_dataset.delete_dataset_case("zz-srv-copy") == {"deleted": "zz-srv-copy"}
    assert routes_dataset.delete_dataset_case("zz-srv") == {"deleted": "zz-srv"}
    assert len(dataset_store.list_cases()) == DATASET_DEFAULT_COUNT


def test_dataset_endpoints_map_errors_to_400_and_404() -> None:
    for call in (
        lambda: routes_dataset.get_dataset_case("zz-missing"),
        lambda: routes_dataset.update_dataset_case(
            "zz-missing", routes_dataset.DatasetCaseIn(audio="x")
        ),
        lambda: routes_dataset.delete_dataset_case("zz-missing"),
        lambda: routes_dataset.duplicate_dataset_case("zz-missing"),
    ):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 404
        assert "not found" in str(excinfo.value.detail)

    with pytest.raises(HTTPException) as excinfo:
        routes_dataset.create_dataset_case(routes_dataset.DatasetCaseIn(id="zz-bad", audio="hi"))
    assert excinfo.value.status_code == 400
    assert "at least one expectation" in str(excinfo.value.detail)


def test_dataset_run_endpoint_runs_a_subset_and_records_last_results() -> None:
    result = routes_dataset.run_dataset(routes_dataset.DatasetRunRequest(case_ids=["stt-basic"]))

    assert set(result) == {
        "run_id",
        "created_at",
        "passed",
        "pass_rate",
        "average_score",
        "average_latency_ms",
        "cost_usd",
        "cases",
        "report",
    }
    assert result["run_id"].startswith("EVAL-")
    assert [case["case_id"] for case in result["cases"]] == ["stt-basic"]
    assert result["passed"] is True
    assert len(result["report"]["cases"]) == 1

    last = dataset_store.get_last_result("stt-basic")
    assert last is not None
    assert last["status"] == "PASSED"
    assert last["eval_id"] == result["run_id"]
    assert [row["eval_id"] for row in history.list_evaluations("dataset")] == [result["run_id"]]


def test_dataset_run_endpoint_rejects_empty_and_unknown_case_ids() -> None:
    for case_ids, detail in (
        ([], "case_ids must not be empty"),
        (["zz-ghost"], "unknown case ids"),
    ):
        with pytest.raises(HTTPException) as excinfo:
            routes_dataset.run_dataset(routes_dataset.DatasetRunRequest(case_ids=case_ids))
        assert excinfo.value.status_code == 400
        assert detail in str(excinfo.value.detail)


# -----------------------------
# Traces / metrics / packs / gate (items 27-28)
# -----------------------------


def test_traces_endpoint_includes_chat_and_scenario_kinds() -> None:
    chat = routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG))
    scenario = server.evaluate_endpoint(server.EvaluateRequest(scenario_id="normal-order-status"))
    assert scenario["run_id"].startswith("RUN-")
    assert scenario["passed"] is True

    payload = routes_evals.traces_endpoint()
    assert set(payload) == {"traces", "total", "kinds"}
    assert {"chat", "scenario"} <= set(payload["kinds"])
    assert {"chat", "scenario"} <= {row["kind"] for row in payload["traces"]}
    assert payload["total"] == len(payload["traces"])

    filtered = routes_evals.traces_endpoint(kind="chat")
    assert filtered["kinds"] == payload["kinds"]
    assert filtered["total"] == 1
    assert all(row["kind"] == "chat" for row in filtered["traces"])
    assert [row["trace_id"] for row in filtered["traces"]] == [chat["evaluation"]["trace_id"]]


def test_metrics_endpoint_separates_computed_baseline_from_live() -> None:
    routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG))

    payload = routes_evals.metrics_endpoint()

    assert set(payload) == {"baseline", "live", "totals", "by_metric", "recent", "judge"}
    baseline = payload["baseline"]
    assert baseline["source"] == "computed-baseline"
    assert baseline["total_cases"] == 10
    assert baseline["passed_cases"] == 10
    assert baseline["failed_cases"] == 0
    assert baseline["pass_rate"] == 1.0
    assert baseline["total_cost_usd"] is None

    assert set(payload["live"]) == {"chat", "dataset", "scenario"}
    assert payload["live"]["chat"]["total"] == 1
    assert payload["live"]["scenario"]["total"] == 0

    assert payload["judge"]["available"] is False
    assert payload["judge"]["reason"] == "EVAL_JUDGE_API_KEY not set"

    assert set(payload["totals"]) == {
        "evaluations",
        "passed",
        "failed",
        "pass_rate",
        "average_score",
        "average_latency_ms",
        "cost_usd",
    }
    assert payload["totals"]["evaluations"] == 1

    assert isinstance(payload["by_metric"], list) and payload["by_metric"]
    assert set(payload["by_metric"][0]) == {
        "name",
        "count",
        "passed",
        "na",
        "pass_rate",
        "average",
    }
    assert isinstance(payload["recent"], list) and payload["recent"]
    assert set(payload["recent"][0]) == {"eval_id", "kind", "name", "status", "score", "created_at"}
    assert payload["recent"][0]["kind"] == "chat"


def test_eval_packs_endpoint_lists_three_packs_with_judge_probe() -> None:
    payload = routes_evals.eval_packs_endpoint()

    assert set(payload) == {"judge", "packs"}
    assert payload["judge"]["available"] is False
    assert len(payload["packs"]) == 3

    by_name = {pack["name"]: pack for pack in payload["packs"]}
    assert by_name["factual-qa"]["status"] == "requires_llm_judge"
    assert by_name["tool-use-correctness"]["status"] == "ready"
    for pack in payload["packs"]:
        assert set(pack) == {
            "name",
            "description",
            "required_scorers",
            "status",
            "requires_llm_judge",
            "missing_scorers",
            "suite",
            "last_run",
        }


def test_run_eval_pack_endpoint_runs_tool_use_pack() -> None:
    result = routes_evals.run_eval_pack(routes_evals.PackRunRequest(pack="tool-use-correctness"))

    assert result["pack"] == "tool-use-correctness"
    assert result["status"] == "failed"
    assert result["run_id"] is not None
    assert result["run_id"].startswith("PACK-")
    assert result["report"] is not None
    assert result["report"]["summary"]["pass_rate"] == 0.0


def test_run_eval_pack_endpoint_gates_judge_packs_without_a_key() -> None:
    result = routes_evals.run_eval_pack(routes_evals.PackRunRequest(pack="factual-qa"))

    # The gated response shape promised by section 4: no run id, no report,
    # no fake pass -- just an explanation of what is missing.
    assert set(result) == {"pack", "run_id", "status", "report", "explanation"}
    assert result["pack"] == "factual-qa"
    assert result["status"] == "requires_llm_judge"
    assert result["run_id"] is None
    assert result["report"] is None
    assert "factuality" in str(result["explanation"])


def test_run_eval_pack_endpoint_unknown_pack_is_404() -> None:
    with pytest.raises(HTTPException) as excinfo:
        routes_evals.run_eval_pack(routes_evals.PackRunRequest(pack="does-not-exist"))

    assert excinfo.value.status_code == 404
    assert "unknown eval pack" in str(excinfo.value.detail)


def test_release_gate_endpoints_expose_config_and_record_decision() -> None:
    before = routes_evals.release_gate_endpoint()
    assert set(before) == {"config", "basis", "judge", "last"}
    assert before["last"] is None
    assert before["config"] == {
        "min_pass_rate": 0.95,
        "min_average_score": 0.95,
        "max_failed_cases": 0,
        "max_average_latency_ms": 1500.0,
        "max_total_cost_usd": 0.25,
    }
    assert before["judge"]["available"] is False

    decision = routes_evals.evaluate_release_gate_endpoint()
    assert decision["passed"] is True
    assert decision["verdict"] == "RELEASE PASSED"
    assert decision["run_id"].startswith("GATE-")
    assert decision["cost"]["status"] == "unavailable"
    assert decision["cost"]["blocking"] is False

    after = routes_evals.release_gate_endpoint()
    assert after["last"] is not None
    assert after["last"]["verdict"] == "RELEASE PASSED"
    assert after["last"]["run_id"] == decision["run_id"]


# -----------------------------
# Existing endpoint shapes (item 28)
# -----------------------------


def test_stats_and_runs_endpoint_shapes_survive_chat_traffic() -> None:
    scenario = server.evaluate_endpoint(server.EvaluateRequest(scenario_id="normal-order-status"))
    routes_chat.chat_endpoint(routes_chat.ChatRequest(message=MSG))
    routes_chat.chat_evaluate_endpoint(
        routes_chat.ChatEvaluateRequest(message="Tell me something.")
    )

    runs = server.runs_endpoint()
    assert set(runs) == {"runs"}
    # Chat traffic never adds scenario rows.
    assert [row["run_id"] for row in runs["runs"]] == [scenario["run_id"]]

    stats = server.stats_endpoint()
    assert set(stats) == {"total_runs", "passed", "failed", "avg_score", "latest"}
    assert stats["total_runs"] == 1
    assert stats["passed"] == 1
    assert stats["failed"] == 0
    assert stats["latest"] is not None
    assert stats["latest"]["run_id"] == scenario["run_id"]
    assert stats["avg_score"] == stats["latest"]["score"]


def test_health_and_listing_endpoint_shapes() -> None:
    assert server.health() == {"status": "ok", "service": "voice-agent-eval-api"}

    cases = server.dataset_endpoint()
    assert set(cases) == {"cases"}
    assert len(cases["cases"]) == DATASET_DEFAULT_COUNT

    scenarios_payload = server.scenarios_endpoint()
    assert set(scenarios_payload) == {"scenarios"}
    assert len(scenarios_payload["scenarios"]) == len(PRESET_SCENARIOS)


# -----------------------------
# Security hardening (appended): bearer-token middleware + message cap
# -----------------------------


def _auth_request(method: str, path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Any:
    """Minimal ASGI scope wrapped in a fastapi.Request, for middleware tests."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), *(headers or [])],
        "client": ("127.0.0.1", 4242),
        "server": ("testserver", 80),
    }
    return fastapi.Request(scope)


def test_api_token_middleware_gates_all_routes_except_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EVAL_API_TOKEN set -> 401 without a Bearer header, pass-through with one."""
    asyncio = importlib.import_module("asyncio")
    json = importlib.import_module("json")
    monkeypatch.setenv("EVAL_API_TOKEN", "secret123")
    seen: list[str] = []

    async def call_next(request: Any) -> Any:
        seen.append(request.url.path)
        return server.JSONResponse(status_code=200, content={"status": "ok"})

    async def attempt(
        method: str, path: str, headers: list[tuple[bytes, bytes]] | None = None
    ) -> Any:
        return await server.require_api_token(_auth_request(method, path, headers), call_next)

    missing = asyncio.run(attempt("POST", "/chat"))
    assert missing.status_code == 401
    assert json.loads(missing.body) == {"detail": "Not authenticated"}
    assert seen == []

    wrong = asyncio.run(attempt("POST", "/chat", [(b"authorization", b"Bearer nope")]))
    assert wrong.status_code == 401
    assert seen == []

    allowed = asyncio.run(attempt("POST", "/chat", [(b"authorization", b"Bearer secret123")]))
    assert allowed.status_code == 200
    assert seen == ["/chat"]

    health = asyncio.run(attempt("GET", "/health"))
    assert health.status_code == 200
    assert seen == ["/chat", "/health"]

    monkeypatch.delenv("EVAL_API_TOKEN")
    unguarded = asyncio.run(attempt("GET", "/scenarios"))
    assert unguarded.status_code == 200
    assert seen == ["/chat", "/health", "/scenarios"]


def test_chat_request_rejects_messages_over_the_size_cap() -> None:
    """POST /chat rejects messages beyond the 4000-char pydantic cap."""
    pydantic = importlib.import_module("pydantic")

    with pytest.raises(pydantic.ValidationError):
        routes_chat.ChatRequest(message="x" * 5000)

    with pytest.raises(pydantic.ValidationError):
        routes_chat.ChatRequest(message="x" * (routes_chat.MAX_MESSAGE_CHARS + 1))

    accepted = routes_chat.ChatRequest(message="x" * routes_chat.MAX_MESSAGE_CHARS)
    assert len(accepted.message) == routes_chat.MAX_MESSAGE_CHARS


def test_chat_evaluate_rejects_messages_over_the_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /chat/evaluate (mode A) answers 422 once ``message`` exceeds the cap."""
    asyncio = importlib.import_module("asyncio")
    json = importlib.import_module("json")
    monkeypatch.delenv("EVAL_API_TOKEN", raising=False)

    body = json.dumps({"message": "x" * 5000}).encode()
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat/evaluate",
        "raw_path": b"/chat/evaluate",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 4242),
        "server": ("testserver", 80),
    }
    sent: list[dict[str, Any]] = []
    delivered = {"body": False}

    async def receive() -> dict[str, Any]:
        if delivered["body"]:
            return {"type": "http.disconnect"}
        delivered["body"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(server.app(scope, receive, send))

    start = next(item for item in sent if item["type"] == "http.response.start")
    assert start["status"] == 422
    payload = json.loads(
        b"".join(item["body"] for item in sent if item["type"] == "http.response.body")
    )
    assert payload["detail"][0]["loc"] == ["body", "message"]
