"""Voice Agent Evaluation using Agentic Evals Framework.

This script integrates the existing voice agent and dataset with the
agentic-evals framework for structured evaluation.
"""

from dataset import VOICE_TEST_CASES
from evaluators import build_registry
from voice_agents import run_agent

from agentic_evals import (
    EvalSpan,
    EvalTrace,
    EvaluationReport,
    EvaluationSample,
    EvaluatorConfig,
    TestCase,
    TestSuite,
    evaluate_suite,
)

# -----------------------------
# Custom Evaluators
# -----------------------------

MAX_LATENCY_MS = 5000.0

CAT_BY_ID = {tc["id"]: tc["category"] for tc in VOICE_TEST_CASES}


# Evaluators moved to evaluators.py (single source of truth).
registry = build_registry()


# -----------------------------
# Build TestSuite from VOICE_TEST_CASES
# -----------------------------


def build_test_suite() -> TestSuite:
    """Convert VOICE_TEST_CASES into a TestSuite."""
    cases: list[TestCase] = []

    for tc in VOICE_TEST_CASES:
        evaluators: list[EvaluatorConfig] = []
        if "expected_transcript" in tc:
            evaluators.append(EvaluatorConfig(name="transcript_accuracy"))
        if "expected_intent" in tc:
            evaluators.append(EvaluatorConfig(name="intent_accuracy"))
        # Groundedness evaluator runs on ALL test cases
        evaluators.append(EvaluatorConfig(name="groundedness"))

        test_case = TestCase(
            id=tc["id"],
            name=tc["id"],
            input=tc["audio"],
            expected_contains=tc.get("expected_response_contains", []),
            required_tools=[tc["expected_tool"]] if "expected_tool" in tc else [],
            required_tool_arguments={tc["expected_tool"]: list(tc["expected_arguments"].keys())}
            if "expected_arguments" in tc
            else {},
            max_latency_ms=MAX_LATENCY_MS,
            evaluators=evaluators,
            metadata={
                "expected_transcript": tc.get("expected_transcript"),
                "expected_intent": tc.get("expected_intent"),
                "category": tc["category"],
            },
            tags=[tc["category"]],
        )
        cases.append(test_case)

    return TestSuite(
        name="voice-agent-evals",
        version="1.0",
        description="Voice agent evaluation suite for STT, intent, tool use, and task completion",
        cases=cases,
    )


# -----------------------------
# Run agent and create EvaluationSamples
# -----------------------------


def run_agent_and_create_samples(suite: TestSuite) -> list[EvaluationSample]:
    """Run the voice agent for each test case and create EvaluationSamples."""
    samples: list[EvaluationSample] = []

    for case in suite.cases:
        result = run_agent(case.input)

        spans = (
            [
                EvalSpan(
                    tool_name=result.tool_name,
                    attributes={"tool_args": result.tool_args, "tool_result": result.tool_result},
                )
            ]
            if result.tool_name
            else []
        )

        trace = EvalTrace(
            trace_id=f"trace-{case.id}",
            spans=spans,
            total_latency_ms=result.latency_ms,
            metadata={
                "transcript": result.transcript,
                "intent": result.intent,
                "recovered": result.recovered,
            },
        )

        sample = EvaluationSample(
            case_id=case.id,
            output=result.response,
            trace=trace,
        )
        samples.append(sample)

    return samples


# -----------------------------
# Print scorecard
# -----------------------------


def print_scorecard(report: EvaluationReport) -> None:
    """Print a readable scorecard with per-metric pass rates."""
    print("\n" + "=" * 70)
    print("VOICE AGENT EVALUATION SCORECARD")
    print("=" * 70)

    for case_eval in report.cases:
        status = "PASS" if case_eval.passed else "FAIL"
        category = CAT_BY_ID.get(case_eval.case_id, "unknown")

        print(f"{case_eval.case_id:20} {category:18} {status:5} {case_eval.latency_ms:.2f} ms")

        for score in case_eval.scores:
            if not score.passed and score.required:
                print(f"  -> {score.name}: {score.explanation}")

    print("=" * 70)

    print("\nMETRIC PASS RATES:")
    print("-" * 70)

    metric_scores: dict[str, list[float]] = {}
    metric_passed: dict[str, int] = {}
    metric_total: dict[str, int] = {}

    for case_eval in report.cases:
        for score in case_eval.scores:
            name = score.name
            if name not in metric_scores:
                metric_scores[name] = []
                metric_passed[name] = 0
                metric_total[name] = 0
            metric_scores[name].append(score.value)
            metric_total[name] += 1
            if score.passed:
                metric_passed[name] += 1

    for name in sorted(metric_scores.keys()):
        avg_score = sum(metric_scores[name]) / len(metric_scores[name])
        pass_rate = (metric_passed[name] / metric_total[name]) * 100
        print(
            f"  {name:30}  avg={avg_score:.3f}  "
            f"pass={metric_passed[name]}/{metric_total[name]} ({pass_rate:.1f}%)"
        )

    print("-" * 70)
    print("=" * 70)


# -----------------------------
# Main
# -----------------------------


def main() -> int:
    """Run the evaluation and return exit code."""
    print("Building test suite...")
    suite = build_test_suite()
    print(f"Created suite '{suite.name}' with {len(suite.cases)} test cases")

    print("Running voice agent...")
    samples = run_agent_and_create_samples(suite)
    print(f"Generated {len(samples)} evaluation samples")

    print("Evaluating with agentic-evals framework...")
    report = evaluate_suite(suite, samples, registry=registry)

    print_scorecard(report)

    return 0 if report.summary.passed_cases == report.summary.total_cases else 1


if __name__ == "__main__":
    exit(main())
