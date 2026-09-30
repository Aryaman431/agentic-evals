"""Scenario definitions and in-memory store for the scenario lab."""

import re
from typing import Any

from pydantic import BaseModel

# -----------------------------
# Scenario model
# -----------------------------


class Scenario(BaseModel):
    id: str
    name: str
    description: str = ""
    input: str
    expected_transcript: str | None = None
    expected_intent: str | None = None
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] | None = None
    expected_response_criteria: list[str] = []
    rules: dict[str, bool]
    fault: str = "none"
    max_latency_ms: float = 5000.0


# Rule keys in display order with their labels.
RULE_KEYS: list[tuple[str, str]] = [
    ("transcript_accuracy", "Transcript Accuracy"),
    ("intent_accuracy", "Intent Accuracy"),
    ("tool_selection", "Tool Selection"),
    ("tool_arguments", "Tool Arguments"),
    ("response_quality", "Response Quality"),
    ("groundedness", "Groundedness"),
    ("reliability", "Reliability"),
    ("latency", "Latency"),
]

RULE_LABELS: dict[str, str] = dict(RULE_KEYS)
RULE_ORDER: list[str] = [key for key, _ in RULE_KEYS]


# -----------------------------
# Fault modes
# -----------------------------

# (key, label, description, detected_by)
FAULT_MODES: list[tuple[str, str, str, str]] = [
    ("normal", "Normal", "Baseline agent behavior.", "\u2014"),
    (
        "wrong_intent",
        "Wrong Intent",
        "Intent classifier forced to an incorrect label.",
        "Intent Accuracy",
    ),
    (
        "wrong_tool",
        "Wrong Tool",
        "Agent executes a different tool than the intent requires.",
        "Tool Selection",
    ),
    (
        "wrong_arguments",
        "Wrong Arguments",
        "Order id corrupted before the tool call.",
        "Tool Arguments",
    ),
    (
        "hallucinated_response",
        "Hallucinated Response",
        "Response claims delivered/tomorrow while tool says shipped/September 28.",
        "Groundedness",
    ),
    (
        "unsupported_claim",
        "Unsupported Claim",
        "Correct response with an appended unsupported claim ('tomorrow').",
        "Groundedness",
    ),
    (
        "tool_failure",
        "Tool Failure",
        "Tool returns an error payload; task cannot complete.",
        "Response Quality",
    ),
    (
        "missing_information",
        "Missing Information",
        "Order-id extraction fails; agent must ask for the order number.",
        "Reliability / Response Quality",
    ),
    (
        "slow_response",
        "Slow Response",
        "Real 250 ms delay injected; scenario latency budget 100 ms.",
        "Latency",
    ),
]

# "none" is the runtime alias for "normal" (run_agent's default).
FAULT_KEYS: list[str] = ["none", *[key for key, *_ in FAULT_MODES]]
FAULT_LABELS: dict[str, str] = {key: label for key, label, *_ in FAULT_MODES}


# -----------------------------
# Preset scenarios
# -----------------------------


def _rules(**overrides: bool) -> dict[str, bool]:
    """All rules enabled except reliability, then apply per-scenario overrides."""
    rules = {key: True for key in RULE_ORDER}
    rules["reliability"] = False
    rules.update(overrides)
    return rules


PRESET_SCENARIOS: list[Scenario] = [
    Scenario(
        id="normal-order-status",
        name="Normal Order Status",
        description="Standard order-status request handled correctly.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="none",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="wrong-tool-selection",
        name="Wrong Tool Selection",
        description="Agent executes the wrong tool for an order-status request.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="wrong_tool",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="wrong-tool-arguments",
        name="Wrong Tool Arguments",
        description="Order id is corrupted before the tool call.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="wrong_arguments",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="hallucinated-response",
        name="Hallucinated Response",
        description="Response invents delivery status not present in tool output.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="hallucinated_response",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="unsupported-claim",
        name="Unsupported Claim",
        description="Response appends a delivery claim the tool never made.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="unsupported_claim",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="missing-order-id",
        name="Missing Order ID",
        description="User omits the order id; agent must ask instead of guessing.",
        input="Where is my order?",
        expected_transcript="Where is my order?",
        expected_intent="order_status",
        expected_response_criteria=["order number"],
        rules=_rules(tool_selection=False, tool_arguments=False, reliability=True),
        fault="none",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="unknown-order",
        name="Unknown Order",
        description="Valid request for an order that does not exist.",
        input="Where is my order 4242?",
        expected_transcript="Where is my order 4242?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "4242"},
        expected_response_criteria=["couldn't find", "4242"],
        rules=_rules(),
        fault="none",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="tool-failure",
        name="Tool Failure",
        description="Tool returns an error; completion criteria cannot be met.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="tool_failure",
        max_latency_ms=5000.0,
    ),
    Scenario(
        id="slow-response",
        name="Slow Response",
        description="Injected delay breaches the 100 ms latency budget.",
        input="Where is my order 1234?",
        expected_transcript="Where is my order 1234?",
        expected_intent="order_status",
        expected_tool="get_order",
        expected_arguments={"order_id": "1234"},
        expected_response_criteria=["shipped", "September 28"],
        rules=_rules(),
        fault="slow_response",
        max_latency_ms=100.0,
    ),
    Scenario(
        id="unknown-intent",
        name="Unknown Intent",
        description="Out-of-scope request; agent must decline without calling tools.",
        input="Tell me something interesting.",
        expected_transcript="Tell me something interesting.",
        expected_intent="unknown",
        expected_response_criteria=["didn't understand"],
        rules=_rules(tool_selection=False, tool_arguments=False, reliability=True),
        fault="none",
        max_latency_ms=5000.0,
    ),
]


# -----------------------------
# In-memory store
# -----------------------------

_SCENARIOS: dict[str, Scenario] = {scenario.id: scenario for scenario in PRESET_SCENARIOS}


def list_scenarios() -> list[Scenario]:
    """All stored scenarios in insertion order (presets first)."""
    return list(_SCENARIOS.values())


def get_scenario(scenario_id: str) -> Scenario | None:
    """Look up a scenario; returns None when it does not exist."""
    return _SCENARIOS.get(scenario_id)


def slugify(text: str) -> str:
    """Lowercase, dash-separated id derived from free text."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "scenario"


def validate_scenario(scenario: Scenario) -> None:
    """Reject unknown fault modes and rule keys."""
    if scenario.fault not in FAULT_KEYS:
        raise ValueError(
            f"Unknown fault mode: {scenario.fault!r}. Valid modes: {', '.join(FAULT_KEYS)}"
        )
    unknown = [key for key in scenario.rules if key not in RULE_LABELS]
    if unknown:
        raise ValueError(f"Unknown rule keys: {', '.join(unknown)}")


def create_scenario(data: dict[str, Any]) -> Scenario:
    """Create and store a scenario, generating a unique id from its name."""
    payload = dict(data)
    provided_id = payload.pop("id", None)
    if provided_id is not None and provided_id in _SCENARIOS:
        raise ValueError(f"Scenario '{provided_id}' already exists")
    if not str(payload.get("input") or "").strip():
        raise ValueError("scenario input is required")
    if not str(payload.get("name") or "").strip():
        raise ValueError("scenario name is required")
    if payload.get("rules") is None:
        payload["rules"] = {key: True for key in RULE_ORDER}

    base = slugify(payload["name"])
    scenario_id = base
    suffix = 2
    while scenario_id in _SCENARIOS:
        scenario_id = f"{base}-{suffix}"
        suffix += 1

    scenario = Scenario(id=scenario_id, **payload)
    validate_scenario(scenario)
    _SCENARIOS[scenario.id] = scenario
    return scenario


def update_scenario(scenario_id: str, data: dict[str, Any]) -> Scenario:
    """Merge the provided fields into an existing scenario."""
    current = _SCENARIOS.get(scenario_id)
    if current is None:
        raise KeyError(f"Scenario '{scenario_id}' not found")

    payload = dict(data)
    payload.pop("id", None)
    merged = current.model_dump()
    merged.update(payload)

    scenario = Scenario(**merged)
    validate_scenario(scenario)
    _SCENARIOS[scenario_id] = scenario
    return scenario


def delete_scenario(scenario_id: str) -> None:
    """Remove a scenario from the store (presets included)."""
    if scenario_id not in _SCENARIOS:
        raise KeyError(f"Scenario '{scenario_id}' not found")
    del _SCENARIOS[scenario_id]
