from dataclasses import dataclass
from typing import Any

# -----------------------------
# Mock tools
# -----------------------------

ORDERS: dict[str, dict[str, Any]] = {
    "1234": {
        "status": "shipped",
        "eta": "September 28",
    },
    "5678": {
        "status": "processing",
        "eta": "October 2",
    },
    "9999": {
        "status": "delivered",
        "eta": None,
    },
}


def get_order(order_id: str) -> dict[str, Any]:
    """Look up an order."""
    if order_id not in ORDERS:
        return {
            "found": False,
            "order_id": order_id,
        }

    return {
        "found": True,
        "order_id": order_id,
        **ORDERS[order_id],
    }


def cancel_order(order_id: str) -> dict[str, Any]:
    """Cancel an order."""
    if order_id not in ORDERS:
        return {
            "success": False,
            "reason": "Order not found",
        }

    if ORDERS[order_id]["status"] == "delivered":
        return {
            "success": False,
            "reason": "Delivered orders cannot be cancelled",
        }

    return {
        "success": True,
        "order_id": order_id,
    }


def refund_order(order_id: str) -> dict[str, Any]:
    """Request a refund."""
    if order_id not in ORDERS:
        return {
            "success": False,
            "reason": "Order not found",
        }

    return {
        "success": True,
        "order_id": order_id,
        "refund_status": "initiated",
    }


# -----------------------------
# Simulated STT
# -----------------------------


def transcribe(audio_text: str) -> str:
    """
    Simulates speech-to-text.

    In the evaluation dataset we can deliberately provide
    imperfect transcriptions to test STT robustness.
    """
    return audio_text


# -----------------------------
# Voice Agent
# -----------------------------


@dataclass
class AgentResult:
    transcript: str
    intent: str
    tool_name: str | None
    tool_args: dict[str, Any]
    tool_result: dict[str, Any] | None
    response: str
    latency_ms: float
    recovered: bool = True
    fault: str = "none"


def detect_intent(text: str) -> str:
    text_lower = text.lower()

    if any(word in text_lower for word in ["where", "status", "track", "tracking"]):
        return "order_status"

    if any(word in text_lower for word in ["cancel", "stop"]):
        return "cancel_order"

    if any(word in text_lower for word in ["refund", "money back", "return"]):
        return "refund_order"

    return "unknown"


def extract_order_id(text: str) -> str | None:
    words = text.replace("#", " ").split()

    for word in words:
        cleaned = "".join(char for char in word if char.isdigit())

        if cleaned:
            return cleaned

    return None


# -----------------------------
# Fault injection
# -----------------------------

# Deterministic fault modes accepted by run_agent(). Each mode perturbs one
# stage of the pipeline so a scenario can attribute the failure to a metric.
# "none" (default) and "normal" both keep the original baseline behavior.
FAULTS = {
    "none": "Unchanged baseline behavior.",
    "normal": "Alias for 'none'; unchanged baseline behavior.",
    "wrong_intent": "Intent label swapped after detection "
    "(order_status <-> cancel_order, refund_order -> order_status).",
    "wrong_tool": "Intent kept, but a rotated tool runs with the same arguments.",
    "wrong_arguments": "Extracted order id corrupted ('1234' -> '12340').",
    "hallucinated_response": "Order-status response claims delivered/tomorrow "
    "regardless of the tool output.",
    "unsupported_claim": "Grounded response gets an appended ' It will arrive tomorrow.' claim.",
    "tool_failure": "Tool returns an error payload instead of a real result.",
    "missing_information": "Order-id extraction forced to fail after extraction.",
    "slow_response": "250 ms sleep inside the timed section (~250 ms latency).",
}

# wrong_tool keeps the intent but rotates the executed tool one step:
# order_status intent -> cancel_order, cancel_order intent -> refund_order,
# refund_order intent -> get_order.
WRONG_TOOL_FOR_INTENT = {
    "order_status": "cancel_order",
    "cancel_order": "refund_order",
    "refund_order": "get_order",
}


def run_agent(audio_text: str, fault: str = "none") -> AgentResult:
    """
    Runs the complete simulated voice-agent pipeline:

    Caller → STT → Agent → Tool → Response

    `fault` selects a deterministic fault mode (see FAULTS above); the
    default "none" preserves the original baseline behavior exactly.
    """

    import time

    start = time.perf_counter()

    # STT
    transcript = transcribe(audio_text)

    # Intent detection
    intent = detect_intent(transcript)

    # Fault: force an incorrect intent label (tool selection follows it).
    if fault == "wrong_intent":
        if intent == "order_status":
            intent = "cancel_order"
        elif intent == "cancel_order" or intent == "refund_order":
            intent = "order_status"

    # Extract arguments
    order_id = extract_order_id(transcript)

    # Fault: corrupt the order id used in the tool call and the response.
    if fault == "wrong_arguments":
        order_id = f"{order_id}0" if order_id else "0"

    # Fault: simulate an extraction failure (agent must ask for the id).
    if fault == "missing_information":
        order_id = None

    tool_name = None
    tool_args = {}
    tool_result = None
    recovered = True

    # Tool selection
    if intent == "order_status":
        tool_name = "get_order"

    elif intent == "cancel_order":
        tool_name = "cancel_order"

    elif intent == "refund_order":
        tool_name = "refund_order"

    # Fault: keep the intent but execute a different tool with the same args.
    if fault == "wrong_tool" and intent in WRONG_TOOL_FOR_INTENT:
        tool_name = WRONG_TOOL_FOR_INTENT[intent]

    # Tool execution (dispatched on the tool that actually runs)
    if tool_name:
        tool_args = {"order_id": order_id}

        if order_id:
            if tool_name == "get_order":
                tool_result = get_order(order_id)
            elif tool_name == "cancel_order":
                tool_result = cancel_order(order_id)
            elif tool_name == "refund_order":
                tool_result = refund_order(order_id)

    # Fault: tool returns an error payload instead of a real result.
    if fault == "tool_failure" and tool_name:
        tool_result = {
            "found": False,
            "success": False,
            "order_id": order_id,
            "reason": "Order service unavailable",
        }

    # Response generation (branches on the tool that actually ran, so every
    # fault/input combination stays KeyError-safe)
    if intent == "unknown":
        response = "Sorry, I didn't understand your request."

    elif not order_id:
        response = "Could you please provide your order number?"
        recovered = True

    elif tool_result is None:
        response = "I'm sorry, I couldn't complete that request."

    elif tool_name == "get_order":
        if not tool_result.get("found", True):
            response = f"I couldn't find order {order_id}."
        else:
            status = tool_result.get("status", "")
            eta = tool_result.get("eta")

            if eta:
                response = (
                    f"Your order {order_id} is {status}. The estimated delivery date is {eta}."
                )
            else:
                response = f"Your order {order_id} has been {status}."

    elif tool_name == "cancel_order":
        if tool_result.get("success"):
            response = f"Order {order_id} has been cancelled successfully."
        else:
            response = (
                f"I couldn't cancel order {order_id}: {tool_result.get('reason', 'unknown error')}."
            )

    elif tool_name == "refund_order":
        if tool_result.get("success"):
            response = f"The refund for order {order_id} has been initiated."
        else:
            response = (
                f"I couldn't process the refund: {tool_result.get('reason', 'unknown error')}."
            )

    else:
        response = "I'm sorry, I couldn't complete that request."

    # Fault: tool failure overrides the response with an outage message.
    # Wording embeds the exact reason string so groundedness can match it.
    if fault == "tool_failure" and tool_name:
        if order_id:
            response = f"I couldn't check order {order_id}: order service unavailable."
        else:
            response = "order service unavailable."

    # Fault: hallucinate a delivery promise on top of a found order.
    if (
        fault == "hallucinated_response"
        and intent == "order_status"
        and tool_result
        and tool_result.get("found")
    ):
        response = f"Your order {order_id} has been delivered and will arrive tomorrow."

    # Fault: append an unsupported claim to an otherwise grounded response.
    if (
        fault == "unsupported_claim"
        and intent == "order_status"
        and tool_result
        and tool_result.get("found")
    ):
        response = response + " It will arrive tomorrow."

    # Fault: inject a real delay inside the timed section.
    if fault == "slow_response":
        time.sleep(0.25)

    latency_ms = (time.perf_counter() - start) * 1000

    return AgentResult(
        transcript=transcript,
        intent=intent,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
        response=response,
        latency_ms=latency_ms,
        recovered=recovered,
        fault=fault,
    )


if __name__ == "__main__":
    result = run_agent("Where is my order 1234?")

    print("Transcript:", result.transcript)
    print("Intent:", result.intent)
    print("Tool:", result.tool_name)
    print("Arguments:", result.tool_args)
    print("Tool result:", result.tool_result)
    print("Response:", result.response)
    print("Latency:", round(result.latency_ms, 2), "ms")
