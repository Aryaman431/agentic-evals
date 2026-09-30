"""Centralized evaluators for the voice-agent evaluation project.

Single source of truth for the custom evaluator functions and the
EvaluatorRegistry used by run_evals.py (baseline suite) and
scenario_runner.py (scenario lab).
"""

import json
from collections.abc import Callable
from typing import Any

from agentic_evals import (
    BusinessRuleEvaluator,
    EvaluationContext,
    EvaluatorRegistry,
    Score,
    default_registry,
)

# -----------------------------
# Groundedness claim vocabulary
# -----------------------------

# Factual claim terms the response must be able to trace to tool evidence.
CLAIM_TERMS = {
    "shipped",
    "delivered",
    "processing",
    "cancelled",
    "canceled",
    "refunded",
    "refund",
    "initiated",
    "returned",
    "tomorrow",
    "today",
    "yesterday",
}

# Claim terms allowed without literal evidence, but only when the tool
# itself reported success (e.g. "cancelled" is implied by a successful cancel).
ALLOWED_EXTRA = {"cancelled", "canceled", "initiated", "refund", "refunded"}


# -----------------------------
# Accuracy evaluator factory
# -----------------------------


def make_accuracy_evaluator(
    case_field: str, trace_field: str, score_name: str
) -> Callable[[EvaluationContext], list[Score]]:
    """Factory returning an evaluator that checks case.metadata[case_field]
    against sample.trace.metadata[trace_field]."""

    def evaluator(context: EvaluationContext) -> list[Score]:
        case = context.case
        sample = context.sample
        expected = case.metadata.get(case_field)
        if expected is None:
            return []
        actual = sample.trace.metadata.get(trace_field, "")
        passed = actual == expected
        match_str = "matches" if passed else "mismatches"
        return [
            Score(
                name=score_name,
                value=1.0 if passed else 0.0,
                passed=passed,
                required=True,
                explanation=(
                    f"{case_field.replace('expected_', '').capitalize()} {match_str} expected."
                ),
                evaluator_type="business_rule",
                metadata={"expected": expected, "actual": actual},
            )
        ]

    return evaluator


# -----------------------------
# Groundedness
# -----------------------------


def groundedness_evaluator(context: EvaluationContext) -> list[Score]:
    case = context.case
    sample = context.sample
    response = (sample.output or "").lower()
    category = case.metadata.get("category", "")

    tool_result: dict[str, Any] | None = None
    if sample.trace and sample.trace.spans:
        tool_result = sample.trace.spans[0].attributes.get("tool_result")

    # No tool_result - check fallback text
    if tool_result is None:
        fallback_checks = {
            "recovery": ("order number", "Missing 'order number' fallback"),
            "reliability": ("didn't understand", "Missing 'didn't understand' fallback"),
        }
        if category in fallback_checks:
            needle, msg = fallback_checks[category]
            passed = needle in response
            explanation = f"Response contains '{needle}' fallback" if passed else msg
        else:
            passed, explanation = True, "No tool_result expected for this category"
        return [
            Score(
                name="groundedness",
                value=1.0 if passed else 0.0,
                passed=passed,
                required=True,
                explanation=explanation,
                evaluator_type="business_rule",
                metadata={"tool_result": None, "category": category},
            )
        ]

    # Has tool_result - data-driven checks
    checks: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("order_id", lambda tr: str(tr.get("order_id", ""))),
        ("status", lambda tr: str(tr.get("status", ""))),
        ("eta", lambda tr: str(tr.get("eta", ""))),
        ("refund_status", lambda tr: str(tr.get("refund_status", "")).lower()),
    ]

    missing: list[str] = []
    for key, extractor in checks:
        val = extractor(tool_result)
        if val and val.lower() not in response:
            missing.append(f"{key}='{val}'")

    # Success handling
    success = tool_result.get("success")
    if success is not None:
        if success:
            if not any(w in response for w in ("success", "cancelled", "initiated")):
                missing.append("success (expected 'success', 'cancelled', or 'initiated')")
        else:
            reason = tool_result.get("reason")
            if reason and str(reason).lower() not in response:
                missing.append(f"reason='{reason}'")

    # Unsupported-claim precision check: any claim vocabulary in the response
    # that the tool never evidenced must be flagged (evidence path only).
    evidence = json.dumps(tool_result, sort_keys=True).lower()
    allowed_extra = ALLOWED_EXTRA if tool_result.get("success") is True else set()
    for term in sorted(CLAIM_TERMS):
        if term in response and term not in evidence and term not in allowed_extra:
            missing.append(f"unsupported claim '{term}' not found in tool result")

    passed = len(missing) == 0
    explanation = (
        "All factual values from tool_result found in response"
        if passed
        else f"Missing: {', '.join(missing)}"
    )

    return [
        Score(
            name="groundedness",
            value=1.0 if passed else 0.0,
            passed=passed,
            required=True,
            explanation=explanation,
            evaluator_type="business_rule",
            metadata={"tool_result": tool_result, "missing": missing},
        )
    ]


# -----------------------------
# Tool arguments
# -----------------------------


def tool_arguments_evaluator(context: EvaluationContext) -> list[Score]:
    """Compare recorded tool arguments against case.metadata["expected_arguments"] (value-level)."""
    case = context.case
    sample = context.sample
    expected = case.metadata.get("expected_arguments")
    if not expected:
        return []

    expected_tool = case.metadata.get("expected_tool")
    span = None
    if sample.trace:
        for candidate in sample.trace.spans:
            if expected_tool is None:
                if isinstance(candidate.attributes.get("tool_args"), dict):
                    span = candidate
                    break
            elif candidate.tool_name == expected_tool:
                span = candidate
                break

    actual = {}
    if span is not None:
        args = span.attributes.get("tool_args")
        if isinstance(args, dict):
            actual = args

    passed = all(str(actual.get(key)) == str(value) for key, value in expected.items())
    explanation = (
        "Tool arguments match expected."
        if passed
        else f"Expected {expected} but tool received {actual}."
    )
    return [
        Score(
            name="tool_arguments",
            value=1.0 if passed else 0.0,
            passed=passed,
            required=True,
            explanation=explanation,
            evaluator_type="business_rule",
            metadata={"expected": expected, "actual": actual},
        )
    ]


# -----------------------------
# Reliability
# -----------------------------


def reliability_evaluator(context: EvaluationContext) -> list[Score]:
    """No-tool guarantees for unknown intents and missing order ids."""
    case = context.case
    sample = context.sample
    unknown_intent = case.metadata.get("expected_intent") == "unknown"
    order_id_missing = bool(case.metadata.get("order_id_missing"))

    spans = sample.trace.spans if sample.trace else []
    executed_spans = [s for s in spans if s.attributes.get("tool_result") is not None]
    executed_names = sorted({s.tool_name or "unknown tool" for s in executed_spans})
    executed = bool(executed_spans)

    if unknown_intent:
        passed = not executed
        explanation = (
            "No tool invoked for unknown intent."
            if passed
            else f"Agent invoked tool despite unknown intent: {', '.join(executed_names)}"
        )
    elif order_id_missing:
        passed = not executed
        explanation = (
            "No tool invoked without required order id."
            if passed
            else f"Agent invoked {', '.join(executed_names)} with missing order id"
        )
    else:
        passed = True
        explanation = "No reliability condition applies to this scenario."

    return [
        Score(
            name="reliability",
            value=1.0 if passed else 0.0,
            passed=passed,
            required=True,
            explanation=explanation,
            evaluator_type="business_rule",
            metadata={
                "unknown_intent": unknown_intent,
                "order_id_missing": order_id_missing,
                "executed": executed,
            },
        )
    ]


# -----------------------------
# Registry
# -----------------------------


def build_registry() -> EvaluatorRegistry:
    """Fresh registry: 16 built-in scorers plus the custom evaluators."""
    registry = default_registry()
    registry.register(
        BusinessRuleEvaluator(
            "transcript_accuracy",
            make_accuracy_evaluator("expected_transcript", "transcript", "transcript_accuracy"),
        )
    )
    registry.register(
        BusinessRuleEvaluator(
            "intent_accuracy",
            make_accuracy_evaluator("expected_intent", "intent", "intent_accuracy"),
        )
    )
    registry.register(BusinessRuleEvaluator("groundedness", groundedness_evaluator))
    registry.register(BusinessRuleEvaluator("tool_arguments", tool_arguments_evaluator))
    registry.register(BusinessRuleEvaluator("reliability", reliability_evaluator))
    return registry
