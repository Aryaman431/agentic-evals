"""Chat pipeline tests (design section 9, items 1-13).

Covers case derivation, the eight-metric panel, fault detection, trace
shape, the frozen-baseline regression, groundedness generalization and the
scenario presets. Nothing here imports fastapi, so these run in CI where
only ``uv sync --extra dev`` is installed.
"""

import os
from typing import Any

import pytest
from chat_pipeline import (
    CHAT_MAX_LATENCY_MS,
    PANEL_ORDER,
    build_chat_trace,
    chat_target,
    derive_case,
    evaluate_chat,
    execute_chat,
)
from evaluators import build_registry, groundedness_evaluator
from run_evals import build_test_suite, run_agent_and_create_samples
from scenario_runner import evaluate_scenario
from scenarios import PRESET_SCENARIOS, Scenario

from agentic_evals import (
    EvalSpan,
    EvalTrace,
    EvaluationContext,
    EvaluationSample,
    EvaluatorConfig,
    TestCase,
    evaluate_suite,
)


@pytest.fixture(autouse=True)
def _clean_judge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the clean-env judge state so "unavailable" is deterministic."""
    for key in [name for name in os.environ if name.startswith("EVAL_JUDGE_")]:
        monkeypatch.delenv(key, raising=False)


def _metrics_by_key(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {metric["key"]: metric for metric in payload["metrics"]}


def _preset(scenario_id: str) -> Scenario:
    return next(scenario for scenario in PRESET_SCENARIOS if scenario.id == scenario_id)


# -----------------------------
# Case derivation (section 2.3)
# -----------------------------


@pytest.mark.parametrize(
    ("message", "intent", "tool", "required", "forbidden", "tool_arguments", "contains"),
    [
        (
            "Where is my order 1234?",
            "order_status",
            "get_order",
            ["get_order"],
            ["cancel_order", "refund_order"],
            {"get_order": ["order_id"]},
            ["1234"],
        ),
        (
            "Please cancel order 1234",
            "cancel_order",
            "cancel_order",
            ["cancel_order"],
            ["get_order", "refund_order"],
            {"cancel_order": ["order_id"]},
            ["1234", "cancel"],
        ),
        (
            "I need a refund for order 1234",
            "refund_order",
            "refund_order",
            ["refund_order"],
            ["get_order", "cancel_order"],
            {"refund_order": ["order_id"]},
            ["1234", "refund"],
        ),
    ],
)
def test_derive_case_for_known_intents(
    message: str,
    intent: str,
    tool: str,
    required: list[str],
    forbidden: list[str],
    tool_arguments: dict[str, list[str]],
    contains: list[str],
) -> None:
    derived = derive_case(message)

    assert derived.expected_intent == intent
    assert derived.order_id == "1234"
    assert derived.order_id_missing is False
    assert derived.category == "chat"
    assert derived.expected_tool == tool
    assert derived.expected_arguments == {"order_id": "1234"}
    assert derived.required_tools == required
    assert derived.forbidden_tools == forbidden
    assert derived.required_tool_arguments == tool_arguments
    assert derived.expected_contains == contains
    assert derived.max_latency_ms == CHAT_MAX_LATENCY_MS


def test_derive_case_unknown_intent_forbids_every_tool() -> None:
    derived = derive_case("Tell me something interesting.")

    assert derived.expected_intent == "unknown"
    assert derived.order_id is None
    assert derived.order_id_missing is True
    assert derived.category == "reliability"
    assert derived.expected_tool is None
    assert derived.expected_arguments is None
    assert derived.required_tools == []
    assert derived.forbidden_tools == ["get_order", "cancel_order", "refund_order"]
    assert derived.required_tool_arguments == {}
    assert derived.expected_contains == ["didn't understand"]


def test_derive_case_missing_order_id_uses_recovery_criteria() -> None:
    derived = derive_case("Where is my order?")

    assert derived.expected_intent == "order_status"
    assert derived.order_id is None
    assert derived.order_id_missing is True
    assert derived.category == "recovery"
    assert derived.required_tools == ["get_order"]
    assert derived.required_tool_arguments == {}
    assert derived.expected_contains == ["order number"]


def test_derive_case_missing_information_fault_marks_order_id_missing() -> None:
    derived = derive_case("Where is my order 1234?", "missing_information")

    # The pre-fault truth still comes from the input itself...
    assert derived.order_id == "1234"
    # ...but the declared fault flips the no-tool condition and category.
    assert derived.order_id_missing is True
    assert derived.category == "recovery"


# -----------------------------
# End-to-end chat evaluation (section 2.4)
# -----------------------------


def test_evaluate_chat_normal_message_scores_all_deterministic_metrics() -> None:
    payload = evaluate_chat("Where is my order 1234?")

    assert payload["kind"] == "chat"
    assert payload["passed"] is True
    assert payload["score"] == 1.0
    assert [metric["key"] for metric in payload["metrics"]] == PANEL_ORDER
    assert len(payload["metrics"]) == 8

    by_key = _metrics_by_key(payload)
    for key in (
        "groundedness",
        "intent_accuracy",
        "tool_selection",
        "tool_arguments",
        "task_completion",
        "latency",
    ):
        assert by_key[key]["status"] == "passed", key
        assert by_key[key]["passed"] is True

    quality = by_key["response_quality"]
    assert quality["status"] == "unavailable"
    assert quality["value"] is None
    assert quality["passed"] is None
    assert quality["scores"] == []
    assert quality["reason"] is not None
    assert "EVAL_JUDGE_API_KEY" in quality["reason"]

    reliability = by_key["reliability"]
    assert reliability["status"] == "na"
    assert reliability["value"] is None
    assert reliability["scores"] == []

    assert payload["judge"]["available"] is False
    assert payload["failures"] == []


def test_wrong_arguments_fault_fails_tool_arguments() -> None:
    payload = evaluate_chat("Where is my order 1234?", "wrong_arguments")
    by_key = _metrics_by_key(payload)

    tool_arguments = by_key["tool_arguments"]
    assert tool_arguments["status"] == "failed"
    failing = next(score for score in tool_arguments["scores"] if not score["passed"])
    assert failing["name"] == "tool_arguments"
    assert failing["metadata"]["expected"] == {"order_id": "1234"}
    assert failing["metadata"]["actual"] == {"order_id": "12340"}
    assert "Expected {'order_id': '1234'}" in failing["explanation"]
    assert "'order_id': '12340'" in failing["explanation"]

    assert payload["passed"] is False
    assert "tool_arguments" in [failure["name"] for failure in payload["failures"]]
    # The corrupted id echoes back as "12340", which still *contains* the
    # user's own "1234", so the substring-based completion criteria pass --
    # pinning the actual (documented) contains semantics here.
    assert by_key["task_completion"]["status"] == "passed"


def test_wrong_intent_fault_fails_intent_accuracy_and_tool_selection() -> None:
    payload = evaluate_chat("Where is my order 1234?", "wrong_intent")
    by_key = _metrics_by_key(payload)

    assert by_key["intent_accuracy"]["status"] == "failed"
    assert by_key["tool_selection"]["status"] == "failed"
    assert payload["passed"] is False
    failure_names = {failure["name"] for failure in payload["failures"]}
    assert {"intent_accuracy", "tool_selection"} <= failure_names


def test_hallucinated_response_fault_fails_groundedness() -> None:
    payload = evaluate_chat("Where is my order 1234?", "hallucinated_response")
    by_key = _metrics_by_key(payload)

    groundedness = by_key["groundedness"]
    assert groundedness["status"] == "failed"
    explanation = groundedness["explanation"]
    assert explanation is not None
    assert "unsupported claim 'delivered'" in explanation
    assert "unsupported claim 'tomorrow'" in explanation
    assert payload["passed"] is False
    assert [failure["name"] for failure in payload["failures"]] == ["groundedness"]


def test_unknown_intent_message_end_to_end() -> None:
    payload = evaluate_chat("Tell me something interesting.")
    by_key = _metrics_by_key(payload)

    assert payload["passed"] is True
    # No tool was executed for an unknown intent.
    assert by_key["reliability"]["status"] == "passed"
    assert by_key["intent_accuracy"]["status"] == "passed"
    assert by_key["tool_selection"]["status"] == "passed"
    assert by_key["task_completion"]["status"] == "passed"
    assert by_key["groundedness"]["status"] == "passed"
    # ...so there is nothing about tool arguments to check.
    assert by_key["tool_arguments"]["status"] == "na"
    assert by_key["tool_arguments"]["value"] is None
    assert by_key["tool_arguments"]["scores"] == []


@pytest.mark.parametrize(
    ("message", "fault"),
    [
        ("Where is my order 1234?", "none"),
        ("Where is my order 1234?", "wrong_arguments"),
        ("Where is my order 1234?", "wrong_intent"),
        ("Where is my order 1234?", "hallucinated_response"),
        ("Where is my order 1234?", "missing_information"),
        ("Tell me something interesting.", "none"),
        ("Where is my order?", "none"),
    ],
)
def test_panel_always_emits_the_eight_metrics_in_fixed_order(message: str, fault: str) -> None:
    payload = evaluate_chat(message, fault)
    metrics = payload["metrics"]

    assert [metric["key"] for metric in metrics] == PANEL_ORDER
    for metric in metrics:
        if metric["status"] in ("na", "unavailable"):
            assert metric["value"] is None, metric["key"]
            assert metric["passed"] is None, metric["key"]
            assert metric["scores"] == [], metric["key"]
        else:
            assert metric["status"] in ("passed", "failed"), metric["key"]
            assert metric["value"] is not None, metric["key"]
            assert metric["scores"], metric["key"]


# -----------------------------
# Trace shape (section 3)
# -----------------------------


def test_chat_trace_shape_for_known_intent() -> None:
    message = "Where is my order 1234?"
    derived = derive_case(message)
    result = execute_chat(message)
    trace = build_chat_trace(message, result, "none", derived)

    stages = [span.attributes.get("stage") for span in trace.spans]
    assert stages == ["user_input", "intent", "arguments", "tool", "response"]
    assert [span.tool_name for span in trace.spans] == [None, None, None, "get_order", None]

    # Only the tool span ever carries tool_args/tool_result.
    for span in trace.spans:
        carries_tool_keys = "tool_args" in span.attributes or "tool_result" in span.attributes
        assert carries_tool_keys == (span.attributes.get("stage") == "tool")

    assert trace.metadata["intent"] == "order_status"
    assert trace.metadata["fault"] == "none"
    assert trace.metadata["source"] == "chat"
    assert trace.metadata["message"] == message
    assert trace.metadata["order_id"] == "1234"
    assert trace.trace_id.startswith("trace-chat-")
    assert trace.estimated_cost_usd is None


def test_chat_trace_omits_tool_span_for_unknown_intent() -> None:
    message = "Tell me something interesting."
    derived = derive_case(message)
    result = execute_chat(message)
    trace = build_chat_trace(message, result, "none", derived)

    stages = [span.attributes.get("stage") for span in trace.spans]
    assert stages == ["user_input", "intent", "arguments", "response"]
    assert all(span.tool_name is None for span in trace.spans)
    assert trace.metadata["intent"] == "unknown"
    assert trace.metadata["source"] == "chat"


def test_latency_metric_carries_budget_and_baseline_scores() -> None:
    payload = evaluate_chat("Where is my order 1234?")
    latency = _metrics_by_key(payload)["latency"]

    assert latency["status"] == "passed"
    assert [score["name"] for score in latency["scores"]] == [
        "latency_threshold",
        "trajectory_efficiency",
    ]
    assert all(score["passed"] for score in latency["scores"])


# -----------------------------
# Baseline and scenario regressions
# -----------------------------


def test_baseline_suite_still_scores_ten_of_ten() -> None:
    suite = build_test_suite()
    samples = run_agent_and_create_samples(suite)
    report = evaluate_suite(suite, samples, registry=build_registry())

    assert report.summary.total_cases == 10
    assert report.summary.passed_cases == 10
    assert report.summary.pass_rate == 1.0
    assert report.summary.average_score == 1.0


def test_scenario_normal_order_status_passes() -> None:
    payload = evaluate_scenario(_preset("normal-order-status"))

    assert payload["passed"] is True
    assert all(metric["status"] != "failed" for metric in payload["metrics"])


def test_scenario_hallucinated_response_fails_groundedness() -> None:
    payload = evaluate_scenario(_preset("hallucinated-response"))

    assert payload["passed"] is False
    groundedness = next(m for m in payload["metrics"] if m["key"] == "groundedness")
    assert groundedness["status"] == "failed"


def test_scenario_unknown_intent_passes_reliability() -> None:
    payload = evaluate_scenario(_preset("unknown-intent"))

    assert payload["passed"] is True
    reliability = next(m for m in payload["metrics"] if m["key"] == "reliability")
    assert reliability["status"] == "passed"


# -----------------------------
# Groundedness generalization
# -----------------------------


def test_groundedness_finds_evidence_on_a_non_first_span() -> None:
    case = TestCase(
        id="chat",
        name="chat",
        expected_contains=["1234"],
        metadata={"category": "chat"},
    )
    trace = EvalTrace(
        trace_id="trace-multi-span",
        spans=[
            EvalSpan(tool_name=None, attributes={"stage": "user_input", "text": "hi"}),
            EvalSpan(tool_name=None, attributes={"stage": "intent", "intent": "order_status"}),
            EvalSpan(
                tool_name="get_order",
                attributes={
                    "stage": "tool",
                    "tool_args": {"order_id": "1234"},
                    "tool_result": {"order_id": "1234", "status": "shipped"},
                },
            ),
        ],
    )
    sample = EvaluationSample(case_id="chat", output="Your order 1234 is shipped.", trace=trace)
    context = EvaluationContext(
        case=case, sample=sample, config=EvaluatorConfig(name="groundedness")
    )

    scores = groundedness_evaluator(context)

    assert scores[0].passed is True
    assert scores[0].metadata["tool_result"] == {"order_id": "1234", "status": "shipped"}
    assert scores[0].explanation == "All factual values from tool_result found in response"


def test_groundedness_without_spans_falls_back_to_category_path() -> None:
    empty_trace = EvalTrace(trace_id="trace-empty", spans=[])
    sample = EvaluationSample(case_id="chat", output="Sure, one moment.", trace=empty_trace)
    config = EvaluatorConfig(name="groundedness")

    recovery_case = TestCase(
        id="chat",
        name="chat",
        expected_contains=["order number"],
        metadata={"category": "recovery"},
    )
    recovery_scores = groundedness_evaluator(
        EvaluationContext(case=recovery_case, sample=sample, config=config)
    )
    assert recovery_scores[0].passed is False
    assert recovery_scores[0].explanation == "Missing 'order number' fallback"
    assert recovery_scores[0].metadata["tool_result"] is None

    chat_case = TestCase(
        id="chat",
        name="chat",
        expected_contains=["anything"],
        metadata={"category": "chat"},
    )
    chat_scores = groundedness_evaluator(
        EvaluationContext(case=chat_case, sample=sample, config=config)
    )
    assert chat_scores[0].passed is True
    assert chat_scores[0].explanation == "No tool_result expected for this category"
    assert chat_scores[0].metadata["tool_result"] is None


# -----------------------------
# run_live_suite-compatible target
# -----------------------------


def test_chat_target_returns_a_run_live_suite_sample() -> None:
    case = TestCase(id="target-case", name="target-case", expected_contains=["1234"])

    payload = chat_target("Where is my order 1234?", case)

    assert set(payload) == {"output", "trace"}
    assert isinstance(payload["output"], str)
    sample = EvaluationSample(case_id=case.id, output=payload["output"], trace=payload["trace"])
    assert sample.trace.metadata["source"] == "chat"
    assert [span.tool_name for span in sample.trace.spans] == ["get_order"]
    assert sample.trace.estimated_cost_usd is None
