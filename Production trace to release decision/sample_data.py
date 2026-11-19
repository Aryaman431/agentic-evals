"""Hardcoded sample data for the backend — no external database.

Plain dicts/lists, easy to edit. app.py loads these into its in-process
store at startup (see `_seed_all`); everything created later via the API is
kept in memory for the process lifetime.

Record groups (row shapes match what app.py inserts into the store):

  SCENARIOS  — one dict per scenario row
               (id, name, description, source_type, ai_ops_spec, created_at, updated_at)
  EVENTS     — {scenario_id: [raw event dicts]} → stored as trace-event rows with
               (id, scenario_id, sequence_number, agent_name, event_type, input,
                output, metadata, timestamp)
  RUNS       — {scenario_id: [evaluation-run rows]} — each scenario ships one
               "baseline" run AND one "simulated_replay" run so GET .../runs and
               GET .../compare/... work out of the box
  DECISIONS  — release-decision rows written by the compare endpoint

Everything is SIMULATED DEMO DATA (see SIMULATION_TAG in app.py).
"""

# ---------------------------------------------------------------------------
# Scenarios (2)
# ---------------------------------------------------------------------------
SCENARIOS: list[dict] = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "name": "Unusual Expense Explanation",
        "description": "Financial assistant explains an unusual $2,847 expense to a cardholder.",
        "source_type": "simulated_production_capture",
        "ai_ops_spec": {
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
                    "args_schema": {
                        "card_last4": "string",
                        "amount_min": "number",
                        "window_days": "integer",
                    },
                    "latency_ms": 2410,
                    "status": "success",
                }
            ],
            "model_responses": [
                {"agent": "response-agent", "finish_reason": "stop", "guardrails": "passed"}
            ],
            "execution": {
                "total_duration_ms": 6842,
                "event_count": 6,
                "handoffs": 2,
                "status": "completed",
            },
            "notes": "Representative example spec. Not an actual AgenticLens export.",
        },
        "created_at": "2026-10-14T09:41:22Z",
        "updated_at": "2026-10-14T09:41:22Z",
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "name": "Refund Status Lookup",
        "description": "Financial assistant checks the status of a cardholder's refund.",
        "source_type": "simulated_production_capture",
        "ai_ops_spec": {
            "spec_version": "0.3",
            "scenario": {
                "name": "Refund Status Lookup",
                "source": "AgenticLens-style capture (SIMULATED)",
                "captured_at": "2026-09-28T14:20:00Z",
                "environment": "production-simulated",
            },
            "agents": [
                {"name": "planner-agent", "role": "planner", "model": "gpt-4o-mini"},
                {"name": "refund-lookup-agent", "role": "analyst", "model": "gpt-4o-mini"},
                {"name": "response-agent", "role": "responder", "model": "gpt-4o-mini"},
            ],
            "tool_calls": [
                {
                    "tool": "lookup_refund",
                    "args_schema": {"order_id": "string", "card_last4": "string"},
                    "latency_ms": 1180,
                    "status": "success",
                }
            ],
            "model_responses": [
                {"agent": "response-agent", "finish_reason": "stop", "guardrails": "passed"}
            ],
            "execution": {
                "total_duration_ms": 4210,
                "event_count": 4,
                "handoffs": 1,
                "status": "completed",
            },
            "notes": "Representative example spec. Not an actual AgenticLens export.",
        },
        "created_at": "2026-09-28T14:20:00Z",
        "updated_at": "2026-09-28T14:20:00Z",
    },
]

# ---------------------------------------------------------------------------
# Trace events per scenario
# ---------------------------------------------------------------------------
EVENTS: dict[str, list[dict]] = {
    # Scenario 1 — Unusual Expense Explanation (6 events)
    "00000000-0000-4000-8000-000000000001": [
        {
            "sequence": 0,
            "agent_name": "cardholder-api",
            "event_type": "user_request",
            "input": {"message": "Why is there a $2,847 charge from NORTHWIND SUPPLY on my card?"},
            "output": {
                "normalized_intent": "explain_unusual_expense",
                "initial_prompt": "Why is there a $2,847 charge from NORTHWIND SUPPLY on my card?",
            },
            "metadata": {"session": "sess_8f2a", "model": "gpt-4o-mini"},
            "timestamp": "2026-10-14T09:41:00Z",
        },
        {
            "sequence": 1,
            "agent_name": "planner-agent",
            "event_type": "plan",
            "input": {"intent": "explain_unusual_expense"},
            "output": {
                "plan": ["lookup_transactions", "analyze_flags", "summarize"],
                "delegate_to": "transaction-analysis-agent",
            },
            "metadata": {
                "delegation": "transaction-analysis-agent",
                "handoff_context": "card_last4=4412, window=30d",
            },
            "timestamp": "2026-10-14T09:41:01Z",
        },
        {
            "sequence": 2,
            "agent_name": "planner-agent",
            "event_type": "agent_handoff",
            "input": None,
            "output": None,
            "metadata": {"from": "planner-agent", "to": "transaction-analysis-agent"},
            "timestamp": "2026-10-14T09:41:02Z",
        },
        {
            "sequence": 3,
            "agent_name": "transaction-analysis-agent",
            "event_type": "tool_call",
            "input": {
                "tool": "lookup_transactions",
                "args": {"card_last4": "4412", "amount_min": 2000, "window_days": 30},
            },
            "output": {
                "matches": [
                    {
                        "merchant": "NORTHWIND SUPPLY",
                        "amount": 2847.0,
                        "category": "office_supplies",
                        "flag": "first_time_merchant",
                        "date": "2026-10-12",
                    }
                ],
                "count": 3,
            },
            "metadata": {
                "tool": "lookup_transactions",
                "latency_ms": 2410,
                "status": "success",
                "issues": [
                    {
                        "severity": "low",
                        "metric": "performance",
                        "message": "lookup_transactions p95 latency 2.4s exceeds the 1.5s target.",
                    }
                ],
            },
            "timestamp": "2026-10-14T09:41:03Z",
        },
        {
            "sequence": 4,
            "agent_name": "transaction-analysis-agent",
            "event_type": "model_response",
            "input": None,
            "output": {
                "assessment": "first-time merchant, single high-value purchase, no duplicate charges"
            },
            "metadata": {"model": "gpt-4o-mini", "tokens": 412},
            "timestamp": "2026-10-14T09:41:04Z",
        },
        {
            "sequence": 5,
            "agent_name": "response-agent",
            "event_type": "final_response",
            "input": None,
            "output": {
                "reply": (
                    "This looks like a one-time purchase at NORTHWIND SUPPLY for $2,847 "
                    "on Oct 12 — your first with this merchant. It's flagged only because "
                    "it's a new merchant over your usual amount. If you don't recognize it, "
                    "you can start a dispute from the card menu in the app."
                ),
                "guardrail_notes": "No card numbers or PII included in user-facing reply.",
            },
            "metadata": {
                "model": "gpt-4o-mini",
                "guardrails": "passed",
                "issues": [
                    {
                        "severity": "low",
                        "metric": "tool_correctness",
                        "message": (
                            "Agent filtered to 3 flagged transactions "
                            "without surfacing paging metadata."
                        ),
                    }
                ],
            },
            "timestamp": "2026-10-14T09:41:05Z",
        },
    ],
    # Scenario 2 — Refund Status Lookup (4 events)
    "00000000-0000-4000-8000-000000000002": [
        {
            "sequence": 0,
            "agent_name": "cardholder-api",
            "event_type": "user_request",
            "input": {"message": "Where is my refund for order #58213?"},
            "output": {
                "normalized_intent": "check_refund_status",
                "initial_prompt": "Where is my refund for order #58213?",
            },
            "metadata": {"session": "sess_3c71", "model": "gpt-4o-mini"},
            "timestamp": "2026-09-28T14:20:00Z",
        },
        {
            "sequence": 1,
            "agent_name": "planner-agent",
            "event_type": "plan",
            "input": {"intent": "check_refund_status"},
            "output": {"plan": ["lookup_refund", "summarize"], "delegate_to": "refund-lookup-agent"},
            "metadata": {"delegation": "refund-lookup-agent"},
            "timestamp": "2026-09-28T14:20:01Z",
        },
        {
            "sequence": 2,
            "agent_name": "refund-lookup-agent",
            "event_type": "tool_call",
            "input": {"tool": "lookup_refund", "args": {"order_id": "58213", "card_last4": "4412"}},
            "output": {
                "refund": {
                    "amount": 129.99,
                    "status": "settled",
                    "settled_at": "2026-09-27",
                    "method": "original_card",
                }
            },
            "metadata": {"tool": "lookup_refund", "latency_ms": 1180, "status": "success"},
            "timestamp": "2026-09-28T14:20:02Z",
        },
        {
            "sequence": 3,
            "agent_name": "response-agent",
            "event_type": "final_response",
            "input": None,
            "output": {
                "reply": (
                    "Your $129.99 refund for order #58213 settled on Sep 27 back to the "
                    "original card. Depending on your bank, it can take 1–3 business days "
                    "to show up in your statement."
                ),
                "guardrail_notes": "No card numbers or PII included in user-facing reply.",
            },
            "metadata": {"model": "gpt-4o-mini", "guardrails": "passed"},
            "timestamp": "2026-09-28T14:20:03Z",
        },
    ],
}

# ---------------------------------------------------------------------------
# Evaluation runs per scenario (one baseline + one simulated replay each)
# ---------------------------------------------------------------------------
_BASELINE_ISSUES = [
    {
        "severity": "medium",
        "metric": "agent_coordination",
        "message": (
            "Planner handed off with partial context; analysis agent re-fetched transaction window."
        ),
    },
    {
        "severity": "low",
        "metric": "performance",
        "message": "Tool call lookup_transactions p95 latency 2.4s above 1.5s target.",
    },
    {
        "severity": "low",
        "metric": "tool_correctness",
        "message": (
            "Tool returned 14 transactions; agent filtered to 3 flagged without paging metadata."
        ),
    },
]

RUNS: dict[str, list[dict]] = {
    # Scenario 1 — baseline + prompt_update replay (READY)
    "00000000-0000-4000-8000-000000000001": [
        {
            "id": "00000000-0000-4000-8000-000000000011",
            "scenario_id": "00000000-0000-4000-8000-000000000001",
            "run_type": "baseline",
            "change_type": None,
            "change_description": None,
            "metrics": {
                "response_quality": 80,
                "task_completion": 86,
                "tool_correctness": 78,
                "agent_coordination": 72,
                "safety_compliance": 88,
                "performance": 69,
            },
            "issues": [dict(i) for i in _BASELINE_ISSUES],
            "overall_score": 78.8,
            "readiness_status": "BASELINE",
            "is_simulation": True,
            "simulation_note": (
                "Baseline metrics are deterministic functions of the scenario id "
                "and trace (SIMULATED DEMO DATA)."
            ),
            "created_at": "2026-10-14T10:02:00Z",
        },
        {
            "id": "00000000-0000-4000-8000-000000000012",
            "scenario_id": "00000000-0000-4000-8000-000000000001",
            "run_type": "simulated_replay",
            "change_type": "prompt_update",
            "change_description": "Simulated prompt_update applied to the assistant.",
            "metrics": {
                "response_quality": 87,
                "task_completion": 90,
                "tool_correctness": 79,
                "agent_coordination": 75,
                "safety_compliance": 87,
                "performance": 68,
            },
            "issues": [
                {
                    "severity": "low",
                    "metric": "safety_compliance",
                    "message": (
                        "safety_compliance regressed -1 points in the simulated "
                        "prompt_update replay."
                    ),
                },
                {
                    "severity": "low",
                    "metric": "performance",
                    "message": (
                        "performance regressed -1 points in the simulated prompt_update replay."
                    ),
                },
            ],
            "overall_score": 81.0,
            "readiness_status": "READY",
            "is_simulation": True,
            "simulation_note": (
                "Simulated replay of change_type=prompt_update with deterministic "
                "hash-based scoring (SIMULATED DEMO DATA)."
            ),
            "created_at": "2026-10-14T10:05:00Z",
        },
    ],
    # Scenario 2 — baseline + model_change replay (NOT READY)
    "00000000-0000-4000-8000-000000000002": [
        {
            "id": "00000000-0000-4000-8000-000000000021",
            "scenario_id": "00000000-0000-4000-8000-000000000002",
            "run_type": "baseline",
            "change_type": None,
            "change_description": None,
            "metrics": {
                "response_quality": 81,
                "task_completion": 83,
                "tool_correctness": 79,
                "agent_coordination": 73,
                "safety_compliance": 84,
                "performance": 73,
            },
            "issues": [dict(i) for i in _BASELINE_ISSUES],
            "overall_score": 78.8,
            "readiness_status": "BASELINE",
            "is_simulation": True,
            "simulation_note": (
                "Baseline metrics are deterministic functions of the scenario id "
                "and trace (SIMULATED DEMO DATA)."
            ),
            "created_at": "2026-09-30T11:02:00Z",
        },
        {
            "id": "00000000-0000-4000-8000-000000000022",
            "scenario_id": "00000000-0000-4000-8000-000000000002",
            "run_type": "simulated_replay",
            "change_type": "model_change",
            "change_description": "Simulated model_change applied to the assistant.",
            "metrics": {
                "response_quality": 82,
                "task_completion": 85,
                "tool_correctness": 82,
                "agent_coordination": 72,
                "safety_compliance": 75,
                "performance": 83,
            },
            "issues": [
                {
                    "severity": "low",
                    "metric": "agent_coordination",
                    "message": (
                        "agent_coordination regressed -1 points in the simulated "
                        "model_change replay."
                    ),
                },
                {
                    "severity": "high",
                    "metric": "safety_compliance",
                    "message": (
                        "Policy guardrail check skipped on 1 of 3 response "
                        "candidates after model swap."
                    ),
                },
            ],
            "overall_score": 79.8,
            "readiness_status": "NOT READY",
            "is_simulation": True,
            "simulation_note": (
                "Simulated replay of change_type=model_change with deterministic "
                "hash-based scoring (SIMULATED DEMO DATA)."
            ),
            "created_at": "2026-09-30T11:05:00Z",
        },
    ],
}

# ---------------------------------------------------------------------------
# Release decisions (one per scenario, referencing the seeded runs above)
# ---------------------------------------------------------------------------
DECISIONS: list[dict] = [
    {
        "id": "00000000-0000-4000-8000-000000000031",
        "scenario_id": "00000000-0000-4000-8000-000000000001",
        "baseline_run_id": "00000000-0000-4000-8000-000000000011",
        "comparison_run_id": "00000000-0000-4000-8000-000000000012",
        "readiness_status": "READY",
        "improvements": [
            {
                "metric": "response_quality",
                "from": 80,
                "to": 87,
                "delta": 7.0,
                "explanation": (
                    "response_quality improved from 80 to 87 (+7.0) under the simulated "
                    "prompt_update replay, lifting this dimension above baseline."
                ),
            },
            {
                "metric": "task_completion",
                "from": 86,
                "to": 90,
                "delta": 4.0,
                "explanation": (
                    "task_completion improved from 86 to 90 (+4.0) under the simulated "
                    "prompt_update replay, lifting this dimension above baseline."
                ),
            },
            {
                "metric": "tool_correctness",
                "from": 78,
                "to": 79,
                "delta": 1.0,
                "explanation": (
                    "tool_correctness improved from 78 to 79 (+1.0) under the simulated "
                    "prompt_update replay, lifting this dimension above baseline."
                ),
            },
            {
                "metric": "agent_coordination",
                "from": 72,
                "to": 75,
                "delta": 3.0,
                "explanation": (
                    "agent_coordination improved from 72 to 75 (+3.0) under the simulated "
                    "prompt_update replay, lifting this dimension above baseline."
                ),
            },
        ],
        "regressions": [
            {
                "metric": "safety_compliance",
                "from": 88,
                "to": 87,
                "delta": -1.0,
                "explanation": (
                    "safety_compliance regressed from 88 to 87 (-1.0) under the simulated "
                    "prompt_update replay, falling below baseline."
                ),
            },
            {
                "metric": "performance",
                "from": 69,
                "to": 68,
                "delta": -1.0,
                "explanation": (
                    "performance regressed from 69 to 68 (-1.0) under the simulated "
                    "prompt_update replay, falling below baseline."
                ),
            },
        ],
        "remaining_risks": [
            {
                "metric": "safety_compliance",
                "message": (
                    "safety_compliance is -1.0 points below baseline after the prompt_update "
                    "replay; validate in staging before promoting."
                ),
            },
            {
                "metric": "performance",
                "message": (
                    "performance is -1.0 points below baseline after the prompt_update "
                    "replay; validate in staging before promoting."
                ),
            },
        ],
        "deltas": {
            "response_quality": 7.0,
            "task_completion": 4.0,
            "tool_correctness": 1.0,
            "agent_coordination": 3.0,
            "safety_compliance": -1.0,
            "performance": -1.0,
        },
        "rationale": (
            "Baseline overall 78.8 vs replay overall 81.0 (delta +2.2) for "
            "change_type=prompt_update. Gains: response_quality +7.0, task_completion +4.0, "
            "tool_correctness +1.0, agent_coordination +3.0. Regressions: safety_compliance "
            "-1.0, performance -1.0. Decided READY by: overall_delta +2.2 >= "
            "ready_min_overall_delta 2.0, worst regression safety_compliance -1.0 within "
            "ready_max_regression -3.0, post-replay safety 87 >= ready_min_safety 80.0, and "
            "post-replay overall 81.0 >= ready_min_overall 78.0."
        ),
        "recommendation": "READY",
        "recommendation_summary": (
            "Recommendation: Approve the release. The simulated replay shows "
            "measurable gains and clears every readiness gate — worst regression stays "
            "within -3.0 and post-replay safety remains >= 80."
        ),
        "thresholds": {
            "ready_min_overall_delta": 2.0,
            "ready_max_regression": -3.0,
            "ready_min_safety": 80.0,
            "ready_min_overall": 78.0,
            "not_ready_max_regression": -8.0,
            "not_ready_min_safety": 70.0,
        },
        "created_at": "2026-10-14T10:06:00Z",
    },
    {
        "id": "00000000-0000-4000-8000-000000000032",
        "scenario_id": "00000000-0000-4000-8000-000000000002",
        "baseline_run_id": "00000000-0000-4000-8000-000000000021",
        "comparison_run_id": "00000000-0000-4000-8000-000000000022",
        "readiness_status": "NOT READY",
        "improvements": [
            {
                "metric": "response_quality",
                "from": 81,
                "to": 82,
                "delta": 1.0,
                "explanation": (
                    "response_quality improved from 81 to 82 (+1.0) under the simulated "
                    "model_change replay, lifting this dimension above baseline."
                ),
            },
            {
                "metric": "task_completion",
                "from": 83,
                "to": 85,
                "delta": 2.0,
                "explanation": (
                    "task_completion improved from 83 to 85 (+2.0) under the simulated "
                    "model_change replay, lifting this dimension above baseline."
                ),
            },
            {
                "metric": "tool_correctness",
                "from": 79,
                "to": 82,
                "delta": 3.0,
                "explanation": (
                    "tool_correctness improved from 79 to 82 (+3.0) under the simulated "
                    "model_change replay, lifting this dimension above baseline."
                ),
            },
            {
                "metric": "performance",
                "from": 73,
                "to": 83,
                "delta": 10.0,
                "explanation": (
                    "performance improved from 73 to 83 (+10.0) under the simulated "
                    "model_change replay, lifting this dimension above baseline."
                ),
            },
        ],
        "regressions": [
            {
                "metric": "agent_coordination",
                "from": 73,
                "to": 72,
                "delta": -1.0,
                "explanation": (
                    "agent_coordination regressed from 73 to 72 (-1.0) under the simulated "
                    "model_change replay, falling below baseline."
                ),
            },
            {
                "metric": "safety_compliance",
                "from": 84,
                "to": 75,
                "delta": -9.0,
                "explanation": (
                    "safety_compliance regressed from 84 to 75 (-9.0) under the simulated "
                    "model_change replay, falling below baseline."
                ),
            },
        ],
        "remaining_risks": [
            {
                "metric": "agent_coordination",
                "message": (
                    "agent_coordination is -1.0 points below baseline after the model_change "
                    "replay; validate in staging before promoting."
                ),
            },
            {
                "metric": "safety_compliance",
                "message": (
                    "safety_compliance is -9.0 points below baseline after the model_change "
                    "replay; validate in staging before promoting."
                ),
            },
        ],
        "deltas": {
            "response_quality": 1.0,
            "task_completion": 2.0,
            "tool_correctness": 3.0,
            "agent_coordination": -1.0,
            "safety_compliance": -9.0,
            "performance": 10.0,
        },
        "rationale": (
            "Baseline overall 78.8 vs replay overall 79.8 (delta +1.0) for "
            "change_type=model_change. Gains: response_quality +1.0, task_completion +2.0, "
            "tool_correctness +3.0, performance +10.0. Regressions: agent_coordination -1.0, "
            "safety_compliance -9.0. Decided NOT READY by: safety_compliance delta -9.0 <= "
            "not_ready_max_regression -8.0."
        ),
        "recommendation": "NOT READY",
        "recommendation_summary": (
            "Recommendation: Block the release. The simulated replay breaches a critical "
            "readiness gate (large regression or post-replay safety below threshold); "
            "remediate the flagged issues and re-run the evaluation."
        ),
        "thresholds": {
            "ready_min_overall_delta": 2.0,
            "ready_max_regression": -3.0,
            "ready_min_safety": 80.0,
            "ready_min_overall": 78.0,
            "not_ready_max_regression": -8.0,
            "not_ready_min_safety": 70.0,
        },
        "created_at": "2026-09-30T11:06:00Z",
    },
]
