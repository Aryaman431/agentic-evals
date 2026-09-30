# Voice Agent Evaluation with Agentic Evals

## Overview

This project demonstrates how **Agentic Evals** can be used to evaluate a simulated voice-based customer support agent.

The evaluation focuses on:

* Speech-to-text (STT) accuracy
* Intent detection
* Tool selection
* Tool argument handling
* Task completion
* Response quality
* Reliability and recovery
* Latency

The voice system is simulated locally so that the evaluation workflow can be tested without requiring real speech recognition, text-to-speech, or external APIs.

---

## Problem

Voice customer-support agents must do more than generate a response. They need to correctly understand the user's request, select the appropriate tool, provide the correct information, and recover gracefully when information is missing.

This project evaluates these behaviors using a structured test dataset and the **Agentic Evals** evaluation framework.

---

## Architecture

```text
User Voice Input
       |
       v
   Transcription
       |
       v
  Intent Detection
       |
       v
  Order ID Extraction
       |
       v
    Tool Selection
       |
       +------> get_order()
       |
       +------> cancel_order()
       |
       +------> refund_order()
       |
       v
  Agent Response
       |
       v
 Agentic Evals
       |
       +------> Accuracy
       +------> Tool Usage
       +------> Response Checks
       +------> Latency
       +------> Reliability
```

The interactive layer wraps the same pipeline in a platform flow:

```text
Dashboard → Scenario → Evaluation API → Python Voice Agent → Agentic Evals → Evaluation Trace → Metrics → Dashboard
```

---

## Project Structure

```text
voice-agent-evals/
│
├── voice_agents.py
├── dataset.py
├── run_evals.py
├── evaluators.py
├── scenarios.py
├── scenario_runner.py
├── server.py
├── config.js
├── index.html
└── README.md
```

### Files

**`voice_agents.py`**

Contains the simulated voice customer-support agent, including:

* Transcription
* Intent detection
* Order ID extraction
* Order lookup
* Order cancellation
* Refund processing
* Response generation

**`dataset.py`**

Contains the evaluation dataset with test cases covering STT, intent, tools, task completion, recovery, and reliability.

**`run_evals.py`**

Connects the voice agent and dataset to the Agentic Evals framework and generates the evaluation report.

**`evaluators.py`**

Centralized evaluators (accuracy, groundedness including the unsupported-claim precision check, tool-argument value comparison, reliability) plus `build_registry()`, which combines the Agentic Evals `default_registry()` built-ins with the custom business rules; `run_evals.py` imports from it.

**`scenarios.py`**

Scenario model, the 10 preset scenarios, the fault-mode catalog, and the in-memory scenario store.

**`scenario_runner.py`**

Converts a Scenario into a 1-case Agentic Evals `TestSuite`, runs the agent with fault injection, evaluates it, and serializes metrics, failures, and trace to JSON.

**`server.py`**

FastAPI evaluation API (default `http://localhost:8001`).

**`config.js`**

Frontend API base URL. Override order: `?api=` query param > `localStorage('evalApiBase')` > default `http://localhost:8001`.

**`index.html`**

Evaluation dashboard, including the Scenario Lab.

---

## Evaluation Dataset

The dataset contains **10 test cases**:

| Test Case         | Category        | Purpose                       |
| ----------------- | --------------- | ----------------------------- |
| `stt-basic`       | STT             | Basic transcription           |
| `stt-accent`      | STT             | Transcription variation       |
| `intent-status`   | Intent          | Detect order-status requests  |
| `intent-cancel`   | Intent          | Detect cancellation requests  |
| `intent-refund`   | Intent          | Detect refund requests        |
| `tool-selection`  | Tool            | Verify correct tool selection |
| `tool-arguments`  | Tool Arguments  | Verify tool argument handling |
| `task-completion` | Task Completion | Verify useful final response  |
| `missing-order`   | Recovery        | Handle missing order number   |
| `unknown-intent`  | Reliability     | Handle unsupported requests   |

---

## Agentic Evals Integration

The project uses the Agentic Evals framework to convert the test cases into structured evaluation objects.

The workflow is:

```text
Test Dataset
     |
     v
TestSuite
     |
     v
Run Voice Agent
     |
     v
EvaluationSample
     |
     v
EvalTrace + EvalSpan
     |
     v
Agentic Evals Evaluators
     |
     v
Evaluation Report
```

Each evaluation sample contains:

* Agent output
* Transcript
* Detected intent
* Tool calls
* Tool arguments
* Tool results
* Latency
* Trace information

---

## Evaluation Metrics

The current evaluation includes the following metrics.

### 1. Transcript Accuracy

Checks whether the simulated transcript matches the expected transcript.

### 2. Intent Accuracy

Checks whether the agent correctly identifies the user's intent.

Examples:

```text
order status  -> order_status
cancel order  -> cancel_order
refund        -> refund_order
```

### 3. Required Tool

Checks whether the expected tool was selected.

For example:

```text
"Where is my order 1234?"
        ↓
     get_order
```

### 4. Tool Arguments

Checks whether the expected tool argument structure is supplied.

Example:

```text
get_order(order_id="1234")
```

### 5. Response Content

Checks whether the final response contains expected information such as:

```text
1234
shipped
September 28
```

### 6. Latency

Checks whether the agent completes the test case within the configured latency threshold.

### 7. Recovery and Reliability

Tests cases where the user does not provide enough information or makes an unsupported request.

Examples:

```text
"Where is my order?"
```

The agent asks for the order number.

```text
"Tell me something interesting."
```

The agent handles the unknown intent instead of incorrectly calling an order tool.

---

## Results

The current evaluation run produced:

```text
Total test cases: 10
Passed:           10
Failed:            0
Pass rate:       100%
```

Metric results:

```text
Intent accuracy          4/4     100%
Transcript accuracy      2/2     100%
Latency threshold       10/10    100%
Required tool            2/2     100%
Tool arguments           1/1     100%
Response checks          5/5     100%
```

The simulated local agent produced very low execution latency because it does not use real external speech or AI services.

Therefore, the local latency result should **not** be interpreted as production voice-agent latency.

---

## Evaluation API

The FastAPI backend (`server.py`) exposes the following endpoints.

| Method | Endpoint             | Description                                                                                                              |
| ------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/health`            | Service health check                                                                                                     |
| GET    | `/scenarios`         | List all stored scenarios                                                                                                |
| POST   | `/scenarios`         | Create a new scenario                                                                                                    |
| PUT    | `/scenarios/{id}`    | Update an existing scenario                                                                                              |
| DELETE | `/scenarios/{id}`    | Delete a scenario                                                                                                        |
| POST   | `/evaluate`          | Evaluate a scenario. Body: `scenario_id` or a full scenario config. Returns `run_id`, `passed`, `score`, `metrics[]`, `failures[]`, `agent_result`, `trace` |
| GET    | `/runs`              | Session run history                                                                                                      |
| GET    | `/stats`             | Aggregated statistics over runs (total, passed, failed, average score, latest run)                                       |

### Session run history

Runs are stored in memory on the API process and are reset whenever the server restarts. There is no database in this phase.

---

## Scenario Lab

The Scenario Lab section of the dashboard runs a selected scenario through the full pipeline: **Evaluation API → Python Voice Agent → Agentic Evals → Evaluation Trace → Metrics → Dashboard**.

Results are computed live by the real pipeline — nothing is faked client-side.

### Preset scenarios

The 10 preset scenarios ship with `scenarios.py`:

| Scenario               | Exercises                                                              | Detecting evaluator (injected fault)   |
| ---------------------- | ---------------------------------------------------------------------- | -------------------------------------- |
| Normal Order Status    | Standard order-status request handled correctly (baseline)             | —                                      |
| Wrong Tool Selection   | Agent executes a different tool than the intent requires               | Tool Selection                         |
| Wrong Tool Arguments   | Order id corrupted before the tool call                                | Tool Arguments                         |
| Hallucinated Response  | Response claims delivery status the tool never reported                | Groundedness                           |
| Unsupported Claim      | Correct response with an appended unsupported "tomorrow" claim         | Groundedness (precision check)         |
| Missing Order ID       | User omits the order id; agent must ask instead of guessing            | —                                      |
| Unknown Order          | Valid request for an order that does not exist                         | —                                      |
| Tool Failure           | Tool returns an error payload; the task cannot complete                | Response Quality                       |
| Slow Response          | Real 250 ms delay injected against a 100 ms latency budget             | Latency                                |
| Unknown Intent         | Out-of-scope request; agent must decline without calling a tool        | —                                      |

### Evaluation rules

The 8 rules and the evaluator that actually computes them:

| Rule                 | Evaluator source                                                                       |
| -------------------- | -------------------------------------------------------------------------------------- |
| Transcript Accuracy  | Custom `transcript_accuracy` in `evaluators.py` (expected vs. traced transcript)        |
| Intent Accuracy      | Custom `intent_accuracy` in `evaluators.py` (expected vs. traced intent)                |
| Tool Selection       | Agentic Evals built-in `required_tool` score (case `required_tools`)                    |
| Tool Arguments       | Custom `tool_arguments` in `evaluators.py` (value-level argument comparison)            |
| Response Quality     | Agentic Evals built-in `contains` score (expected response criteria)                    |
| Groundedness         | Custom `groundedness` in `evaluators.py`, incl. unsupported-claim precision check       |
| Reliability          | Custom `reliability` in `evaluators.py` (no-tool guarantees)                            |
| Latency              | Agentic Evals built-in `latency_threshold` score (scenario latency budget)              |

`build_registry()` combines the Agentic Evals `default_registry()` built-ins with these custom business rules; both the CLI baseline (`run_evals.py`) and the Scenario Lab (`scenario_runner.py`) evaluate against it.

### Fault injection

| Fault mode             | Agent behavior                       | Detecting evaluator           |
| ---------------------- | ------------------------------------ | ----------------------------- |
| `normal`               | Baseline                             | —                             |
| `wrong_intent`         | Forced intent label                  | Intent Accuracy              |
| `wrong_tool`           | Different tool executed              | Tool Selection               |
| `wrong_arguments`      | Corrupted order id                   | Tool Arguments               |
| `hallucinated_response`| Invented delivery claim              | Groundedness                  |
| `unsupported_claim`    | Appended "tomorrow" claim            | Groundedness (precision check)|
| `tool_failure`         | Error payload                        | Response Quality              |
| `missing_information`  | Extraction failure                   | Reliability                   |
| `slow_response`        | Real 250 ms delay vs 100 ms budget   | Latency                       |

---

## Limitations

This project intentionally uses a deterministic simulated voice environment.

Current limitations include:

* No real microphone input
* No real speech-to-text service
* No text-to-speech system
* Small synthetic evaluation dataset
* Deterministic intent detection
* Local simulated tools
* Local execution latency
* No real network failures
* No production-scale traces

These limitations make the project reproducible while demonstrating the evaluation workflow.

---

## Future Improvements

The evaluation could be extended with:

* Real STT providers
* Real TTS providers
* Larger voice datasets
* Background-noise testing
* Accent and pronunciation testing
* Silence and interruption handling
* Tool failures and retries
* More complex multi-turn conversations
* LLM-based groundedness evaluation
* Production trace evaluation
* Cost and token usage evaluation

---

## Running the Project

### Install

From the repository root (where `pyproject.toml` lives), install the package in
editable mode with the `voice` extra:

```bash
python -m pip install -e ".[voice]"
```

This also installs the dashboard backend dependencies (`fastapi>=0.115` and
`uvicorn>=0.30`) that `server.py` uses to serve the Evaluation API, so run it
before starting the API.

From the `voice-agent-evals` directory:

### Run the agent

```bash
python voice_agents.py
```

### Check the dataset

```bash
python dataset.py
```

### Run the complete evaluation

```bash
python run_evals.py
```

The final command generates a structured evaluation scorecard using the Agentic Evals framework. The CLI baseline is unchanged and still passes **10/10** test cases.

### Start the evaluation API

```bash
python server.py
```

Or equivalently:

```bash
uvicorn server:app --port 8001
```

Configuration is read from environment variables (no secrets involved):

| Variable           | Default             | Purpose                                             |
| ------------------ | ------------------- | --------------------------------------------------- |
| `EVAL_API_HOST`    | `127.0.0.1`         | Host the API binds to                               |
| `EVAL_API_PORT`    | `8001`              | Port the API listens on                             |
| `EVAL_CORS_ORIGINS`| `*`                 | Allowed CORS origins (comma-separated)              |

### Open the dashboard

With the API running, open `index.html` in a browser (or serve it statically, e.g. the existing preview on port 8000). The Scenario Lab calls the evaluation API to run scenarios live.

---

## Deployment Notes

* **Frontend:** deploy `index.html` on Vercel and point `config.js` `apiBase` (or the `?api=` query param / `localStorage('evalApiBase')` override) at your deployed API URL.
* **Backend:** deploy `server.py` anywhere Python runs.
* Never put API keys in `index.html` or `config.js`; use environment variables for backend configuration.

---

## Conclusion

This project demonstrates a complete evaluation workflow for an agentic voice-support system:

```text
Dataset
   ↓
Agent
   ↓
Trace
   ↓
Evaluators
   ↓
Metrics
   ↓
Evaluation Report
```

The main goal is to show how agent behavior can be evaluated systematically instead of judging responses manually.
