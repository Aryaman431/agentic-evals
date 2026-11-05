"""Run a Scenario through the voice agent and the agentic-evals framework."""

import json
from typing import Any

from evaluators import build_registry
from scenarios import RULE_LABELS, RULE_ORDER, Scenario
from voice_agents import AgentResult, extract_order_id, run_agent

from agentic_evals import (
    CaseEvaluation,
    EvalSpan,
    EvalTrace,
    EvaluationSample,
    EvaluatorConfig,
    Score,
    TestCase,
    TestSuite,
    evaluate_suite,
)

# -----------------------------
# Score name -> rule key mapping
# -----------------------------

# Custom evaluators whose score name equals the rule key.
_EVALUATOR_FOR_RULE = {
    "transcript_accuracy": "transcript_accuracy",
    "intent_accuracy": "intent_accuracy",
    "groundedness": "groundedness",
    "tool_arguments": "tool_arguments",
    "reliability": "reliability",
}


def score_to_rule(name: str) -> str | None:
    """Map a score name back to its rule key (None = unmapped)."""
    if name in _EVALUATOR_FOR_RULE:
        return name
    if name.startswith("required_tool:"):
        return "tool_selection"
    if name.startswith("contains:"):
        return "response_quality"
    if name == "latency_threshold":
        return "latency"
    return None


# -----------------------------
# Satisfiability / category
# -----------------------------


def _satisfiability(scenario: Scenario) -> tuple[list[str], dict[str, str]]:
    """Rules enabled in the scenario that can actually be evaluated."""
    order_id = extract_order_id(scenario.input)

    checks: dict[str, tuple[bool, str]] = {
        "transcript_accuracy": (
            scenario.expected_transcript is not None,
            "Scenario has no expected transcript.",
        ),
        "intent_accuracy": (
            scenario.expected_intent is not None,
            "Scenario has no expected intent.",
        ),
        "tool_selection": (
            scenario.expected_tool is not None,
            "Scenario has no expected tool.",
        ),
        "tool_arguments": (
            scenario.expected_tool is not None and scenario.expected_arguments is not None,
            "Scenario needs both an expected tool and expected arguments.",
        ),
        "response_quality": (
            bool(scenario.expected_response_criteria),
            "Scenario has no response criteria.",
        ),
        "groundedness": (
            order_id is not None
            or scenario.expected_intent == "unknown"
            or not scenario.expected_tool,
            "Scenario has no tool evidence or recovery condition to ground against.",
        ),
        "reliability": (
            order_id is None
            or scenario.expected_intent == "unknown"
            or scenario.fault == "missing_information",
            "No missing-information or unknown-intent condition in this scenario.",
        ),
        "latency": (
            bool(scenario.max_latency_ms and scenario.max_latency_ms > 0),
            "Scenario has no latency budget.",
        ),
    }

    enabled: list[str] = []
    skipped: dict[str, str] = {}
    for key in RULE_ORDER:
        if not scenario.rules.get(key):
            continue
        ok, reason = checks[key]
        if ok:
            enabled.append(key)
        else:
            skipped[key] = reason
    return enabled, skipped


def _category(scenario: Scenario) -> str:
    """Trace-metadata category driving the groundedness fallback path."""
    if scenario.expected_intent == "unknown":
        return "reliability"
    if extract_order_id(scenario.input) is None or scenario.fault == "missing_information":
        return "recovery"
    return "scenario"


# -----------------------------
# Case construction
# -----------------------------


def _build_case(scenario: Scenario, enabled: list[str]) -> TestCase:
    """Translate an evaluated scenario into a single agentic-evals TestCase."""
    evaluators = [
        EvaluatorConfig(name=_EVALUATOR_FOR_RULE[key])
        for key in enabled
        if key in _EVALUATOR_FOR_RULE
    ]
    expected_contains = scenario.expected_response_criteria if "response_quality" in enabled else []
    required_tools = (
        [scenario.expected_tool] if "tool_selection" in enabled and scenario.expected_tool else []
    )
    max_latency_ms = scenario.max_latency_ms if "latency" in enabled else None

    if not evaluators and not expected_contains and not required_tools and max_latency_ms is None:
        raise ValueError("scenario has no enabled, satisfiable evaluation rules")

    metadata = {
        "expected_transcript": scenario.expected_transcript,
        "expected_intent": scenario.expected_intent,
        "expected_tool": scenario.expected_tool,
        "expected_arguments": scenario.expected_arguments,
        "category": _category(scenario),
        "order_id_missing": (
            extract_order_id(scenario.input) is None or scenario.fault == "missing_information"
        ),
    }

    return TestCase(
        id="scenario",
        name=scenario.name,
        input=scenario.input,
        expected_contains=expected_contains,
        required_tools=required_tools,
        max_latency_ms=max_latency_ms,
        evaluators=evaluators,
        metadata=metadata,
    )


# -----------------------------
# Result serialization
# -----------------------------


def _metrics(
    case_eval: CaseEvaluation, enabled: list[str], skipped: dict[str, str]
) -> list[dict[str, Any]]:
    """Aggregate case scores into one entry per rule key, in display order."""
    by_rule: dict[str, list[Score]] = {}
    for score in case_eval.scores:
        key = score_to_rule(score.name)
        if key is not None:
            by_rule.setdefault(key, []).append(score)

    metrics: list[dict[str, Any]] = []
    for key in RULE_ORDER:
        label = RULE_LABELS[key]

        if key in skipped:
            metrics.append(
                {
                    "key": key,
                    "name": label,
                    "status": "skipped",
                    "reason": skipped[key],
                    "value": None,
                    "passed": None,
                    "explanation": None,
                }
            )
        elif key not in enabled:
            continue  # disabled rules are omitted entirely
        else:
            scores = by_rule.get(key, [])
            if not scores:
                metrics.append(
                    {
                        "key": key,
                        "name": label,
                        "status": "skipped",
                        "reason": "Evaluator produced no score.",
                        "value": None,
                        "passed": None,
                        "explanation": None,
                    }
                )
            else:
                values = [score.value for score in scores]
                passed = all(score.passed for score in scores)
                failing = next((score for score in scores if not score.passed), None)
                explanation = failing.explanation if failing else scores[0].explanation
                metrics.append(
                    {
                        "key": key,
                        "name": label,
                        "status": "passed" if passed else "failed",
                        "reason": None,
                        "value": sum(values) / len(values),
                        "passed": passed,
                        "explanation": explanation,
                    }
                )
    return metrics


def _step_status(metric: dict[str, Any] | None) -> str:
    """Step status derived from a metric ('ok' when absent, skipped, or N/A)."""
    if metric and metric.get("status") in ("passed", "failed"):
        return str(metric["status"])
    return "ok"


def _steps(
    scenario: Scenario,
    result: AgentResult,
    metrics: list[dict[str, Any]],
    passed: bool,
    score: float,
) -> list[dict[str, Any]]:
    """Pipeline steps built only from actual agent/evaluation data."""
    by_key = {metric["key"]: metric for metric in metrics}

    return [
        {
            "key": "input",
            "label": "INPUT",
            "title": "User input",
            "content": scenario.input,
            "status": "ok",
        },
        {
            "key": "transcript",
            "label": "TRANSCRIPT",
            "title": "Speech to text",
            "content": result.transcript,
            "status": "ok",
        },
        {
            "key": "intent",
            "label": "INTENT",
            "title": "Intent detection",
            "content": result.intent,
            "status": _step_status(by_key.get("intent_accuracy")),
            "detail": scenario.expected_intent,
        },
        {
            "key": "tool_call",
            "label": "TOOL CALL",
            "title": "Tool selection",
            "content": result.tool_name or "no tool called",
            "status": _step_status(by_key.get("tool_selection")),
        },
        {
            "key": "tool_args",
            "label": "TOOL ARGUMENTS",
            "title": "Tool arguments",
            "content": json.loads(json.dumps(result.tool_args)),
            "status": _step_status(by_key.get("tool_arguments")),
        },
        {
            "key": "tool_result",
            "label": "TOOL RESULT",
            "title": "Tool result",
            "content": result.tool_result,
            "status": "ok" if result.tool_result is not None else "not executed",
        },
        {
            "key": "response",
            "label": "RESPONSE",
            "title": "Agent response",
            "content": result.response,
            "status": "ok",
        },
        {
            "key": "evaluation",
            "label": "EVALUATION",
            "title": "Agentic Evals",
            "content": {"passed": passed, "score": score},
            "status": "passed" if passed else "failed",
            "detail": [{"name": metric["name"], "passed": metric["passed"]} for metric in metrics],
        },
    ]


# -----------------------------
# Public entry point
# -----------------------------


def evaluate_scenario(scenario: Scenario) -> dict[str, Any]:
    """Run one scenario through the agent and evaluators; returns a JSON-safe dict."""
    enabled, skipped = _satisfiability(scenario)

    try:
        case = _build_case(scenario, enabled)
    except ValueError as exc:
        raise ValueError(
            f"Could not build evaluation case for scenario '{scenario.id}': {exc}"
        ) from exc

    result = run_agent(scenario.input, fault=scenario.fault)

    spans = []
    if result.tool_name:
        spans = [
            EvalSpan(
                tool_name=result.tool_name,
                attributes={"tool_args": result.tool_args, "tool_result": result.tool_result},
            )
        ]

    trace = EvalTrace(
        trace_id=f"trace-scenario-{scenario.id}",
        spans=spans,
        total_latency_ms=result.latency_ms,
        metadata={
            "transcript": result.transcript,
            "intent": result.intent,
            "recovered": result.recovered,
            "fault": scenario.fault,
        },
    )

    sample = EvaluationSample(case_id="scenario", output=result.response, trace=trace)
    suite = TestSuite(
        name="scenario-lab",
        version="1.0",
        description=f"Single-scenario evaluation for {scenario.name}",
        cases=[case],
    )

    try:
        report = evaluate_suite(suite, [sample], registry=build_registry())
    except ValueError as exc:
        raise ValueError(f"Evaluation failed for scenario '{scenario.id}': {exc}") from exc

    case_eval = report.cases[0]
    metrics = _metrics(case_eval, enabled, skipped)
    failures = [
        {"name": metric["name"], "reason": metric["explanation"]}
        for metric in metrics
        if metric["status"] == "failed"
    ]
    passed = case_eval.passed
    score = report.summary.average_score

    return {
        "scenario": scenario.name,
        "scenario_id": scenario.id,
        "fault": scenario.fault,
        "passed": passed,
        "score": score,
        "pass_rate": report.summary.pass_rate,
        "latency_ms": case_eval.latency_ms,
        "metrics": metrics,
        "failures": failures,
        "agent_result": {
            "transcript": result.transcript,
            "intent": result.intent,
            "tool_name": result.tool_name,
            "tool_args": result.tool_args,
            "tool_result": result.tool_result,
            "response": result.response,
            "latency_ms": result.latency_ms,
            "recovered": result.recovered,
            "fault": result.fault,
        },
        "trace": {
            "trace_id": trace.trace_id,
            "total_latency_ms": trace.total_latency_ms,
            "metadata": trace.metadata,
            "spans": [
                {"tool_name": span.tool_name, "attributes": span.attributes} for span in trace.spans
            ],
            "steps": _steps(scenario, result, metrics, passed, score),
        },
        "report": report.model_dump(mode="json"),
    }
