"""LLM judge, eval-pack, release-gate, dataset-store and history tests
(design section 9, items 14-24).

No fastapi import: these run in CI where only ``uv sync --extra dev`` is
installed. Several modules keep module-level in-memory stores, so every
test restores them through the autouse fixture below.
"""

import copy
import os
from collections.abc import Iterator
from typing import Any

import chat_pipeline
import dataset
import dataset_store
import history
import live_targets
import pytest
from dataset_store import (
    DATASET_DEFAULT_COUNT,
    build_dataset_suite,
    create_case,
    delete_case,
    duplicate_case,
    get_case,
    list_cases,
    update_case,
)
from evaluators import build_registry
from gate_runner import evaluate_release_gate
from llm_judge import judge_status
from packs_runner import list_packs, run_pack
from run_evals import build_test_suite

from agentic_evals import EvalTrace, PythonTarget, TestCase, run_live_suite

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
    """Pin the clean-env judge state unless a test opts in explicitly."""
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


def _complete_a(prompt: str) -> str:
    """Deterministic judge stand-in: verdict A (score 1.0) for any prompt."""
    return "(A)"


def _complete_broken(prompt: str) -> str:
    raise RuntimeError("judge offline")


def _metric(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return next(metric for metric in payload["metrics"] if metric["key"] == key)


def _chat_payload(eval_id: str, run_id: str, *, passed: bool, score: float) -> dict[str, Any]:
    trace_id = run_id.replace("CHAT-", "trace-chat-")
    return {
        "eval_id": eval_id,
        "kind": "chat",
        "run_id": run_id,
        "trace_id": trace_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "passed": passed,
        "score": score,
        "latency_ms": 0.4,
        "cost_usd": None,
        "case": {"input": "Where is my order 1234?"},
        "agent": {"fault": "none", "intent": "order_status", "tool_name": "get_order"},
        "trace": {"trace_id": trace_id, "spans": []},
        "steps": [{"key": "input", "status": "ok"}],
    }


# -----------------------------
# LLM judge (section 7)
# -----------------------------


def test_judge_status_unavailable_in_a_clean_environment() -> None:
    status = judge_status()

    assert status.available is False
    assert status.provider is None
    assert status.model is None
    assert status.reason == "EVAL_JUDGE_API_KEY not set"


def test_judge_status_available_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "unit-test-key")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "judge-test-model")

    status = judge_status()

    assert status.available is True
    assert status.provider == "openai-compatible"
    assert status.model == "judge-test-model"
    assert status.reason is None


def test_judge_enabled_zero_disables_even_with_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "unit-test-key")
    monkeypatch.setenv("EVAL_JUDGE_ENABLED", "0")

    status = judge_status()

    assert status.available is False
    assert status.reason == "EVAL_JUDGE_ENABLED=0"


def test_build_registry_registers_judge_scorers_only_with_a_complete_fn() -> None:
    with_judge = build_registry(complete_fn=_complete_a)
    assert "response_quality" in with_judge.names()
    assert "factuality" in with_judge.names()

    plain = build_registry()
    assert "response_quality" not in plain.names()
    assert "factuality" not in plain.names()
    assert "groundedness" in plain.names()
    assert "reliability" in plain.names()


def test_evaluate_chat_scores_response_quality_when_judge_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "unit-test-key")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "judge-test-model")
    monkeypatch.setattr(chat_pipeline, "build_complete_fn", lambda: _complete_a)

    payload = chat_pipeline.evaluate_chat("Where is my order 1234?")

    quality = _metric(payload, "response_quality")
    assert quality["status"] == "passed"
    assert quality["value"] == 1.0
    assert quality["scores"][0]["name"] == "response_quality"
    assert quality["scores"][0]["evaluator_type"] == "llm_judge"
    assert payload["judge"]["available"] is True
    assert payload["judge"]["model"] == "judge-test-model"
    assert payload["passed"] is True


def test_judge_call_failure_degrades_one_metric_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "unit-test-key")
    monkeypatch.setattr(chat_pipeline, "build_complete_fn", lambda: _complete_broken)

    payload = chat_pipeline.evaluate_chat("Where is my order 1234?")

    quality = _metric(payload, "response_quality")
    assert quality["status"] == "unavailable"
    assert quality["value"] is None
    assert quality["passed"] is None
    assert quality["scores"] == []
    assert quality["reason"] is not None
    assert "LLM Judge call failed" in quality["reason"]
    assert "judge offline" in quality["reason"]

    # An outage never fails the evaluation itself.
    assert payload["passed"] is True
    for key in (
        "groundedness",
        "intent_accuracy",
        "tool_selection",
        "tool_arguments",
        "task_completion",
        "latency",
    ):
        assert _metric(payload, key)["status"] == "passed", key


# -----------------------------
# Eval packs (section 5)
# -----------------------------


def test_list_packs_reports_three_packs_with_honest_statuses() -> None:
    packs = list_packs()

    assert len(packs) == 3
    assert [pack["name"] for pack in packs] == sorted(pack["name"] for pack in packs)
    assert {pack["name"] for pack in packs} == {
        "factual-qa",
        "json-output-contract",
        "tool-use-correctness",
    }

    by_name = {pack["name"]: pack for pack in packs}
    factual = by_name["factual-qa"]
    assert factual["status"] == "requires_llm_judge"
    assert factual["requires_llm_judge"] is True
    assert factual["missing_scorers"] == ["factuality"]
    assert by_name["tool-use-correctness"]["status"] == "ready"
    assert by_name["json-output-contract"]["status"] == "ready"

    for pack in packs:
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
        assert pack["suite"]["case_count"] == len(pack["suite"]["cases"])
        assert pack["last_run"] is None


def test_list_packs_marks_factual_qa_ready_when_judge_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "unit-test-key")

    by_name = {pack["name"]: pack for pack in list_packs()}

    assert by_name["factual-qa"]["status"] == "ready"
    assert by_name["factual-qa"]["missing_scorers"] == []


def test_run_pack_tool_use_correctness_fails_honestly() -> None:
    result = run_pack("tool-use-correctness")

    assert result["status"] == "failed"
    assert result["run_id"] is not None
    assert result["run_id"].startswith("PACK-")
    assert result["report"] is not None
    assert result["report"]["summary"]["pass_rate"] == 0.0

    notes = " ".join(result["notes"])
    assert "outside this agent's toolset" in notes
    assert "lookup_refund" in notes
    assert "delete_order" in notes


def test_run_pack_json_output_contract_fails_on_plain_text() -> None:
    result = run_pack("json-output-contract")

    assert result["status"] == "failed"
    assert result["report"] is not None
    assert result["report"]["summary"]["pass_rate"] < 1.0

    scores = {
        score["name"]: score for case in result["report"]["cases"] for score in case["scores"]
    }
    assert {"exact_match", "valid_json", "json_diff"} <= set(scores)
    assert scores["exact_match"]["passed"] is False
    assert scores["valid_json"]["passed"] is False
    assert scores["json_diff"]["passed"] is False


def test_run_pack_factual_qa_without_judge_has_no_report() -> None:
    result = run_pack("factual-qa")

    assert result["status"] == "requires_llm_judge"
    assert result["run_id"] is None
    assert result["report"] is None
    assert result["explanation"] is not None
    assert "factuality" in result["explanation"]
    assert "EVAL_JUDGE_API_KEY" in result["explanation"]


def test_run_pack_unknown_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown eval pack"):
        run_pack("does-not-exist")


# -----------------------------
# Release gate (section 6)
# -----------------------------


def test_release_gate_passes_and_reports_cost_as_unavailable() -> None:
    payload = evaluate_release_gate()

    assert payload["passed"] is True
    assert payload["verdict"] == "RELEASE PASSED"
    assert payload["reasons"] == []
    assert payload["run_id"].startswith("GATE-")
    assert payload["config"] == {
        "min_pass_rate": 0.95,
        "min_average_score": 0.95,
        "max_failed_cases": 0,
        "max_average_latency_ms": 1500.0,
        "max_total_cost_usd": 0.25,
    }
    assert payload["observed"]["pass_rate"] == 1.0
    assert payload["observed"]["failed_cases"] == 0
    assert payload["observed"]["total_cost_usd"] is None
    assert payload["report"]["summary"]["passed_cases"] == 10

    cost = payload["cost"]
    assert cost["threshold_usd"] == 0.25
    assert cost["observed_usd"] is None
    assert cost["status"] == "unavailable"
    assert cost["blocking"] is False

    assert set(payload["context"]) == {"scenario", "chat", "dataset"}
    assert payload["basis"]["suite"].startswith("agentic-evals-dashboard")


def test_release_gate_blocks_when_a_case_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_target(input: str, case: TestCase) -> dict[str, Any]:
        return {
            "output": "wrong answer for every case",
            "trace": EvalTrace(trace_id="trace-broken").model_dump(mode="json"),
        }

    monkeypatch.setattr(live_targets, "agent_target", broken_target)

    payload = evaluate_release_gate()

    assert payload["passed"] is False
    assert payload["verdict"] == "RELEASE BLOCKED"
    assert payload["reasons"]
    assert payload["observed"]["failed_cases"] > 0
    # Cost stays honestly unavailable and non-blocking even when blocked.
    assert payload["cost"]["status"] == "unavailable"
    assert payload["cost"]["blocking"] is False


# -----------------------------
# Dataset store (section 4)
# -----------------------------


def test_dataset_store_crud_round_trip() -> None:
    assert len(list_cases()) == DATASET_DEFAULT_COUNT

    created = create_case(
        {"id": "zz-case", "audio": "Where is my order 1234?", "expected_intent": "order_status"}
    )
    assert created["id"] == "zz-case"
    assert get_case("zz-case") == created

    with pytest.raises(ValueError, match="at least one expectation"):
        create_case({"id": "zz-no-expectations", "audio": "hello"})
    with pytest.raises(ValueError, match="already exists"):
        create_case({"id": "zz-case", "audio": "other", "expected_intent": "order_status"})

    updated = update_case("zz-case", {"expected_response_contains": ["1234"]})
    assert updated["expected_response_contains"] == ["1234"]
    assert updated["expected_intent"] == "order_status"

    first_copy = duplicate_case("zz-case")
    assert first_copy["id"] == "zz-case-copy"
    second_copy = duplicate_case("zz-case")
    assert second_copy["id"] == "zz-case-copy-2"

    delete_case("zz-case-copy-2")
    delete_case("zz-case-copy")
    delete_case("zz-case")
    assert get_case("zz-case") is None
    assert len(list_cases()) == DATASET_DEFAULT_COUNT

    with pytest.raises(KeyError, match="not found"):
        delete_case("zz-case")
    with pytest.raises(KeyError, match="not found"):
        update_case("zz-case", {"audio": "hello"})


def test_dataset_edits_never_leak_into_the_frozen_baseline() -> None:
    original_ids = [case["id"] for case in dataset.VOICE_TEST_CASES]

    create_case(
        {"id": "zz-iso", "audio": "Tell me something interesting.", "expected_intent": "chitchat"}
    )
    update_case("stt-basic", {"expected_response_contains": ["mutated"]})
    duplicate_case("intent-cancel")
    delete_case("missing-order")

    # The frozen baseline is untouched...
    baseline_suite = build_test_suite()
    assert len(baseline_suite.cases) == 10
    assert [case.id for case in baseline_suite.cases] == original_ids
    assert len(dataset.VOICE_TEST_CASES) == 10
    assert [case["id"] for case in dataset.VOICE_TEST_CASES] == original_ids

    # ...while the editable store did change.
    assert get_case("zz-iso") is not None
    assert get_case("missing-order") is None
    dataset_suite = build_dataset_suite()
    assert len(dataset_suite.cases) == len(list_cases())
    assert len(dataset_suite.cases) == len(original_ids) + 1


def test_build_dataset_suite_requires_unique_nonempty_ids() -> None:
    suite = build_dataset_suite()
    ids = [case.id for case in suite.cases]
    assert len(ids) == len(set(ids))
    assert len(ids) == DATASET_DEFAULT_COUNT

    dataset_store._CASES.append(copy.deepcopy(dataset_store._CASES[0]))
    with pytest.raises(ValueError, match="must be unique"):
        build_dataset_suite()

    dataset_store._CASES.clear()
    with pytest.raises(ValueError, match="no cases"):
        build_dataset_suite()


def test_run_live_suite_round_trip_produces_a_report_with_ten_cases() -> None:
    report = run_live_suite(
        build_dataset_suite(),
        PythonTarget(callable_path="live_targets:agent_target"),
        registry=build_registry(),
    )

    assert report.summary.total_cases == DATASET_DEFAULT_COUNT
    assert len(report.cases) == DATASET_DEFAULT_COUNT
    assert report.summary.passed_cases == DATASET_DEFAULT_COUNT
    assert report.summary.pass_rate == 1.0
    assert report.summary.average_score == 1.0
    assert report.summary.total_cost_usd is None
    assert all(case.latency_ms is not None for case in report.cases)


# -----------------------------
# History aggregation (section 4)
# -----------------------------


def test_history_record_chat_and_summarize_by_kind() -> None:
    history.record_chat(_chat_payload("EVAL-9001", "CHAT-9001", passed=True, score=1.0))
    history.record_chat(_chat_payload("EVAL-9002", "CHAT-9002", passed=False, score=0.5))

    summary = history.summarize("chat")
    assert summary["total"] == 2
    assert summary["evaluations"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["average_score"] == 0.75
    assert summary["average_latency_ms"] == 0.4
    assert summary["cost_usd"] is None

    # Kinds stay separated and rows are stored newest-first.
    assert history.summarize("scenario")["total"] == 0
    assert [row["eval_id"] for row in history.list_evaluations("chat")] == [
        "EVAL-9002",
        "EVAL-9001",
    ]
    assert len(history.list_chat_runs()) == 2
    assert len(history.list_traces(kind="chat")) == 2
    assert len(history.recent()) == 2


def test_history_recent_returns_newest_activity_first() -> None:
    history.record_activity("chat", "first", "PASSED", 1.0, "ACT-1")
    history.record_activity("scenario", "second", "FAILED", 0.0, "ACT-2")
    history.record_activity("dataset", "third", "PASSED", 1.0, "ACT-3")

    rows = history.recent()
    assert [row["label"] for row in rows[:3]] == ["third", "second", "first"]
    seqs = [row["seq"] for row in rows]
    assert seqs == sorted(seqs, reverse=True)


def test_history_baseline_report_is_cached_and_matches_run_evals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(history, "_BASELINE_CACHE", None)

    first = history.baseline_report()
    second = history.baseline_report()

    assert first is second
    assert first.summary.total_cases == 10
    assert first.summary.passed_cases == 10
    assert first.summary.pass_rate == 1.0
    assert first.summary.average_score == 1.0


def test_history_stores_drop_oldest_rows_past_the_cap() -> None:
    first_eval_id: str | None = None
    for _ in range(505):
        row = history.record_evaluation(
            {"passed": True, "score": 1.0, "latency_ms": 0.1}, "cap-kind", "cap run"
        )
        if first_eval_id is None:
            first_eval_id = str(row["eval_id"])

    # Each record_evaluation also appends an activity row; fill _ACTIVITY
    # afterwards so its final contents come only from the labels below.
    for index in range(505):
        history.record_activity("cap", f"activity {index}", "PASSED", 1.0, f"ACT-{index}")

    assert history.MAX_ROWS == 500
    assert len(history._EVALUATIONS) == history.MAX_ROWS
    assert len(history._ACTIVITY) == history.MAX_ROWS

    # Newest rows survive; the oldest were evicted.
    assert history._EVALUATIONS[0]["kind"] == "cap-kind"
    assert first_eval_id is not None
    assert all(str(row["eval_id"]) != first_eval_id for row in history._EVALUATIONS)
    assert history._ACTIVITY[0]["label"] == "activity 504"
    labels = [str(row["label"]) for row in history._ACTIVITY]
    assert all(label.startswith("activity ") for label in labels)
    assert "activity 5" in labels
    assert "activity 4" not in labels
