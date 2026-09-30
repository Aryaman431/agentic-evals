from typing import Any

VOICE_TEST_CASES: list[dict[str, Any]] = [
    {
        "id": "stt-basic",
        "category": "stt",
        "audio": "Where is my order 1234?",
        "expected_transcript": "Where is my order 1234?",
    },
    {
        "id": "stt-accent",
        "category": "stt",
        "audio": "Can you track order 5678?",
        "expected_transcript": "Can you track order 5678?",
    },
    {
        "id": "intent-status",
        "category": "intent",
        "audio": "Where is my order 1234?",
        "expected_intent": "order_status",
    },
    {
        "id": "intent-cancel",
        "category": "intent",
        "audio": "Please cancel order 5678.",
        "expected_intent": "cancel_order",
    },
    {
        "id": "intent-refund",
        "category": "intent",
        "audio": "I want a refund for order 1234.",
        "expected_intent": "refund_order",
    },
    {
        "id": "tool-selection",
        "category": "tool",
        "audio": "Where is my order 1234?",
        "expected_tool": "get_order",
    },
    {
        "id": "tool-arguments",
        "category": "tool_arguments",
        "audio": "Where is my order 1234?",
        "expected_tool": "get_order",
        "expected_arguments": {"order_id": "1234"},
    },
    {
        "id": "task-completion",
        "category": "task_completion",
        "audio": "Where is my order 1234?",
        "expected_response_contains": ["1234", "shipped", "September 28"],
    },
    {
        "id": "missing-order",
        "category": "recovery",
        "audio": "Where is my order?",
        "expected_response_contains": ["order number"],
    },
    {
        "id": "unknown-intent",
        "category": "reliability",
        "audio": "Tell me something interesting.",
        "expected_intent": "unknown",
        "expected_response_contains": ["didn't understand"],
    },
]


if __name__ == "__main__":
    print(f"Loaded {len(VOICE_TEST_CASES)} voice-agent test cases.")

    for case in VOICE_TEST_CASES:
        print(f"{case['id']:20} {case['category']:18} {case['audio']}")
