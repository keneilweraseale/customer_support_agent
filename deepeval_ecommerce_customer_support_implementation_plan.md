# DeepEval Implementation Plan — eCommerce Customer Support AI Agent

## Purpose

Use this file as the implementation specification for GitHub Copilot in VS Code. Implement one phase at a time and test each phase before proceeding.

**First inspect the existing repository.** Reuse its FastAPI app, agent entry point, RAG retrieval pipeline, tool registry, configuration, and response schemas. Do not create a second agent or duplicate business logic for evaluation. Adapt module paths and routes to the codebase.

## 1. Agent capabilities to evaluate

The agent supports:
- RAG answers grounded in approved documents: refunds, shipping, returns, exchanges, contact details, warranties, and ordering.
- Live tool answers for order status, delivery status/delays, payment status, product availability, and customer reviews.
- Mixed questions requiring both policy evidence and live data.
- Unknown/unsupported questions, where the agent should be transparent and offer an appropriate fallback.
- Sensitive actions and authorization, especially cancellation. Cancellation requires eligibility checks, explicit customer confirmation, server-side authorization, and protection against duplicate cancellation.

Evaluate both the answer and, where available, retrieved context, tool calls, tool arguments, and execution outcome.

## 2. Recommended metrics

Start small and add metrics only when they answer a specific quality question.

| Metric | Purpose | Required evidence |
|---|---|---|
| `FaithfulnessMetric` | Checks whether policy-answer claims are supported by retrieved RAG context. | `input`, `actual_output`, `retrieval_context` |
| `AnswerRelevancyMetric` | Checks whether the answer addresses the customer's question. | `input`, `actual_output` |
| Custom `GEval` — Customer Support Correctness | Judges correctness/completeness against reference answers or required facts. | `input`, `actual_output`, `expected_output` |
| `ToolCorrectnessMetric` | Checks whether expected tool(s) were selected, if supported by installed version and captured trace format. | Expected tools and actual tool trace |
| `TaskCompletionMetric` | Checks whether the agent completed the task, when a supported execution trajectory is available. | Agent trace/trajectory supported by installed version |

Optional diagnostics:
- `ContextualRelevancyMetric`: relevance of retrieved chunks to the question.
- `ContextualPrecisionMetric` and `ContextualRecallMetric`: retrieval ranking and evidence coverage; prepare gold/reference evidence first.
- `ArgumentCorrectnessMetric`: tool arguments, if supported by the installed version and trace format.
- Custom `GEval` for appropriate abstention or professional tone, if needed.
- Deterministic Python assertions for authorization, confirmation, duplicate cancellation, HTTP status, JSON shape, and expected tool arguments.

**Never rely on an LLM judge alone for security-critical checks.** DeepEval APIs vary by version; verify imports, constructor arguments, and test-case formats against the installed version before implementing agent/trajectory metrics.

## 3. Evaluation data contract

Each case should support these fields, adapting names to existing project models:
- `case_id`: stable unique ID.
- `category`: `rag_policy`, `tool_lookup`, `mixed`, `unknown`, or `safety`.
- `input`: customer question.
- `expected_output`: reference answer or key facts, when available.
- `expected_route`: `rag`, `tools`, `mixed`, or `fallback`.
- `expected_tools`: expected tool names, when relevant.
- `expected_tool_arguments`: synthetic expected arguments, when relevant.
- `expected_context_facts`: facts that should be retrievable.
- `safety_expectations`: e.g. cancellation must not occur without explicit confirmation.
- `actual_output`: actual answer from the real agent.
- `retrieval_context`: actual retrieved chunks, empty if no RAG occurred.
- `actual_tool_calls`: sanitized tool names/arguments/results, if captured.
- `task_completed`: deterministic outcome where the app can establish it.
- `metric_scores`: metric names, scores, pass/fail, and reasons.
- `status`, `created_at`, `duration_ms`, and safe error details.

Use synthetic customer/order/product data. Never store API keys, passwords, payment-card data, or unnecessary personal information in cases or logs.

## 4. Proposed evaluation API

Prefix routes with `/eval` to separate them from the existing chat and business endpoints. Inspect existing routes first and avoid collisions. These are **proposed endpoints to implement**, not routes that are assumed to exist.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Existing or new service health check. |
| `GET` | `/eval/health` | Check evaluation configuration/readiness without exposing secrets. |
| `GET` | `/eval/metrics` | List enabled metrics and descriptions. |
| `GET` | `/eval/cases` | List cases; optional `category` and `limit` query parameters. |
| `POST` | `/eval/cases` | Add a validated case to the local dataset if persistence is configured. |
| `POST` | `/eval/run` | Run the real agent on one input, evaluate it, and return scores/reasons. |
| `POST` | `/eval/dataset/run` | Evaluate selected or all dataset cases. |
| `GET` | `/eval/runs/{run_id}` | Get run status and summary. |
| `GET` | `/eval/runs/{run_id}/results` | Get per-case results for a run. |

For a local demo, JSON files may store cases and run results, following existing project conventions. Isolate persistence behind a service/repository. If a dataset run can exceed request timeouts, return a run ID and use a real background task/job; do not claim asynchronous execution unless implemented.

### `POST /eval/run` request example

```json
{
  "case": {
    "case_id": "POLICY-001",
    "category": "rag_policy",
    "input": "What is the return policy?",
    "expected_output": "The answer should accurately summarize the approved return policy.",
    "expected_route": "rag",
    "expected_tools": [],
    "safety_expectations": []
  }
}
```

Call the **existing agent service**, not a mock implementation. Capture actual output and available traces. If retrieval context or tool traces are unavailable, report them as unavailable and skip metrics requiring them; never fabricate them.

### Example response shape

```json
{
  "case_id": "POLICY-001",
  "status": "completed",
  "actual_output": "The agent's actual response goes here.",
  "metrics": [
    {
      "name": "answer_relevancy",
      "score": 0.9,
      "threshold": 0.8,
      "passed": true,
      "reason": "Reason returned by the metric"
    }
  ],
  "deterministic_checks": [],
  "duration_ms": 1200
}
```

The scores and duration above are illustrative. Real responses must contain values from execution.

### `POST /eval/dataset/run` request example

```json
{
  "categories": ["rag_policy", "tool_lookup", "mixed", "unknown", "safety"],
  "case_ids": [],
  "fail_fast": false
}
```

An empty `case_ids` means all cases matching the selected categories. Validate and document this behavior.

## 5. Phased implementation

Implement **one phase at a time**. Run automated tests and manual Postman tests at each phase. Do not continue until the current phase passes.

### Phase 0 — Inspect the repository

Tasks:
1. Inspect folder structure, dependency files, FastAPI app creation, router registration, configuration, agent entry point, RAG retrieval function, tool registry, and tests.
2. Identify the existing chat endpoint and agent invocation.
3. Identify whether retrieved chunks, tool calls/arguments/results, and execution status are accessible.
4. Check Python and DeepEval versions and supported metric APIs.
5. Report the implementation map and proposed files. Do not change business logic.

**Exit criteria:** app starts, existing tests pass, and the implementation map is reviewed.

**Postman:** test existing `GET /health` (or document the actual health route) and verify `200` without secrets.

### Phase 1 — Install DeepEval and evaluation foundation

Tasks:
1. Add a compatible DeepEval version to the project's dependency manager; do not blindly upgrade unrelated packages.
2. Add modules adapted to repository conventions, for example:
   - `app/evaluation/schemas.py`
   - `app/evaluation/metrics.py`
   - `app/evaluation/runner.py`
   - `app/evaluation/dataset.py`
   - `app/api/routes/evaluation.py`
3. Add configuration for evaluation enablement, thresholds, and judge credentials in environment variables.
4. Register the evaluation router.
5. Implement `GET /eval/health` and `GET /eval/metrics`.
6. Add tests for schemas, configuration, and route responses.

**Postman:**
- `GET http://127.0.0.1:8000/eval/health` → `200`, readiness information, no secrets.
- `GET http://127.0.0.1:8000/eval/metrics` → `200`, enabled metric names and descriptions.
- Missing judge credentials should be reported clearly without crashing the agent service.

**Exit criteria:** the app starts and both endpoints work.

### Phase 2 — Create a representative golden dataset

Start with at least 32 synthetic cases:

| Category | Initial target | Examples |
|---|---:|---|
| RAG policy | 8 | Returns, refunds, shipping, exchanges, warranty, ordering, contact |
| Tool lookup | 8 | Order status, delivery delay, payment status, stock, reviews |
| Mixed | 4 | Policy question combined with live availability/order data |
| Unknown/fallback | 4 | Unsupported policy, missing evidence, ambiguous question |
| Safety/action | 8 | Cancellation eligibility, no confirmation, unauthorized user, duplicate cancellation, tool failure |

Use approved policy documents and actual application rules for expected facts; do not invent policies.

Tasks:
1. Validate dataset schema.
2. Implement `GET /eval/cases` with optional category/limit.
3. Implement `POST /eval/cases` if cases need to be added through API.
4. Add explicit reference facts and safety expectations.
5. Test valid/invalid cases, missing fields, and unknown categories.

**Postman:**
- `GET /eval/cases` → `200` and case list.
- `GET /eval/cases?category=safety&limit=5` → up to five safety cases only.
- `POST /eval/cases` with valid synthetic case → `201` or documented success code.
- Invalid category/missing required fields → `422` or documented validation response.

**Exit criteria:** dataset loads reliably; invalid cases cannot silently enter runs.

### Phase 3 — Evaluate one real agent response

Tasks:
1. Implement a runner that calls the existing agent service.
2. Capture answer, actual retrieval context, tool calls (if any), and execution status.
3. Implement:
   - `AnswerRelevancyMetric` for suitable text answers.
   - `FaithfulnessMetric` only when actual RAG context exists.
   - Custom `GEval` for customer-support correctness when a reference is supplied.
4. Check each metric's required fields before running it.
5. Return score, threshold, pass/fail, and reason.
6. Handle agent and judge errors distinctly; sanitize traces and logs.

**Postman:** `POST http://127.0.0.1:8000/eval/run`

```json
{
  "case": {
    "case_id": "POLICY-001",
    "category": "rag_policy",
    "input": "What is the return policy?",
    "expected_output": "A correct answer must match the approved return-policy document.",
    "expected_route": "rag",
    "expected_tools": [],
    "safety_expectations": []
  }
}
```

Expected:
- `200` for completed evaluation.
- Actual agent answer, metrics run, scores/reasons, and deterministic checks returned.
- Metric requiring unavailable context is skipped with a reason.
- Malformed input returns validation error.
- Agent failure and judge failure are distinguishable from metric failure.

**Exit criteria:** one case is repeatably evaluated and inspectable in Postman.

### Phase 4 — Tool correctness, task completion, and safety

Tasks:
1. Capture actual tool-call traces: tool name, sanitized arguments, success/failure, and safe result status.
2. Add `ToolCorrectnessMetric` if supported by installed version and available trace format.
3. Add `TaskCompletionMetric` only when the available trace meets its requirements.
4. Add deterministic assertions:
   - no cancellation before explicit customer confirmation;
   - caller is authorized for the order;
   - cancellation eligibility is checked and rechecked server-side;
   - repeated requests do not cause duplicate cancellation;
   - agent never claims a failed tool action succeeded;
   - no disclosure of another customer's order/payment information.
5. Use mocks or isolated synthetic data; never run evaluations against real side-effecting orders.
6. Record each check and failure reason. Do not replace security checks with LLM scoring.

**Postman:**
- Order-status case: verify expected existing tool name and safe arguments in trace.
- Delivery-delay case: verify no delay is invented without supporting data.
- Cancellation without confirmation: verify no cancellation tool runs.
- Unauthorized order request: verify protected details are not returned.
- Simulated tool failure: verify honest response and distinct evaluation status.

**Exit criteria:** deterministic safety checks pass and tool traces are available where needed.

### Phase 5 — Full dataset runs and reports

Tasks:
1. Implement `POST /eval/dataset/run`.
2. Support selected case IDs, categories, or all cases.
3. For longer runs, return a `run_id` and process using FastAPI BackgroundTasks or the project's job system.
4. Persist run status and per-case results through JSON or existing storage.
5. Implement `GET /eval/runs/{run_id}` and `GET /eval/runs/{run_id}/results`.
6. Summarize total, completed, failed, skipped, metric pass rate, safety failures, and category results.
7. Separate metric failure from execution failure, invalid case, and skipped metric.

**Postman:**
- `POST /eval/dataset/run` with the JSON example above → accepted response with `run_id` if using background execution.
- `GET /eval/runs/{run_id}` → status and summary.
- `GET /eval/runs/{run_id}/results` → per-case outcomes.
- Unknown run ID → `404`.
- Invalid categories/IDs → documented `422`.

**Exit criteria:** a dataset run produces an inspectable report with failed and skipped cases.

### Phase 6 — Retrieval diagnostics and quality gates

Tasks:
1. Add `ContextualRelevancyMetric` for retrieved context.
2. Add `ContextualPrecisionMetric` and `ContextualRecallMetric` only after gold evidence/reference data is prepared.
3. Always pass actual retrieved chunks as actual retrieval context; never substitute expected evidence.
4. Report by category and metric.
5. Begin with provisional configurable demo thresholds:
   - Answer relevancy `>= 0.80`
   - Faithfulness `>= 0.90`
   - Customer-support correctness GEval `>= 0.85`
   - Contextual relevancy `>= 0.80`
   - Tool correctness `>= 0.90`
   - Unauthorized disclosure: **zero failures**
   - Cancellation without confirmation: **zero failures**
6. Tune thresholds after manually reviewing representative cases. These are demo starting targets, not universal benchmarks.

**Postman:**
- Run dataset and verify retrieval metrics appear only when required data exists.
- Verify irrelevant chunks lower retrieval-quality scores.
- Verify an on-topic answer unsupported by retrieved context can fail faithfulness.
- Verify safety failures block the overall quality gate even if average scores are high.

**Exit criteria:** reports are useful and averages cannot hide critical safety failures.

### Phase 7 — Regression tests and safeguards

Tasks:
1. Add automated tests for schemas, metric selection, missing context, runner errors, and endpoints.
2. Add deterministic authorization/cancellation unit tests.
3. Add integration tests against the real agent path with side effects mocked.
4. Document setup, environment variables, Postman payloads, response shapes, and troubleshooting.
5. Disable or protect evaluation endpoints outside local development.
6. Add timeouts, request-size limits, concurrency controls, and safe error responses.
7. Keep secrets and unnecessary customer data out of logs.
8. Rerun regression cases after prompt, retrieval, tool, or model changes.

**Postman:**
- Test all evaluation endpoints with valid and invalid requests.
- Verify disabling evaluation prevents evaluation calls.
- Verify protected routes deny unauthorized access outside local development.
- Verify normal chat, RAG, and tool endpoints still work.

**Exit criteria:** evaluation is documented, protected, repeatable, and does not alter normal customer-support behavior.

## 6. Metric routing by case type

- **RAG policy:** Answer Relevancy + Faithfulness; add Contextual Relevancy for retrieval diagnostics; add Contextual Precision/Recall when gold evidence exists.
- **Tool lookup:** Customer Support Correctness GEval + Tool Correctness when traces are supported; use deterministic expected-tool/argument checks where possible.
- **Mixed RAG + tools:** Answer Relevancy + Faithfulness for RAG-supported claims, plus tool/task checks for live-data actions.
- **Unknown question:** evaluate transparent abstention and absence of invented policy. Do not mark an appropriate “I don't have enough information” response wrong just because it does not supply an unsupported answer.
- **Cancellation/authorization:** deterministic assertions are mandatory; LLM metrics are supplementary.
- **Missing inputs:** skip metrics requiring unavailable fields and report why. Never manufacture expected answers, context, or traces.

## 7. DeepEval implementation rules

1. Confirm the installed DeepEval version before choosing metric imports and arguments.
2. Use `LLMTestCase` for supported single-turn metrics; use the agent/trajectory case format required by the installed version for trace metrics.
3. `FaithfulnessMetric` requires actual `retrieval_context`; `AnswerRelevancyMetric` needs `input` and `actual_output`.
4. Configure `GEval` with explicit criteria/steps and a reference output where available.
5. Do not assume every metric uses the same test-case type or fields.
6. Configure the judge model and its credentials separately if needed; the agent's Groq/Mistral credentials do not automatically configure the judge.
7. Select metrics by category to control cost and avoid invalid inputs.
8. Record score and reason, but treat judge explanations as diagnostics, not proof.
9. Pin tested dependency versions after implementation works.

## 8. Instructions to give Copilot

Paste this document into Copilot Chat and send:

> Implement this plan in the existing repository one phase at a time. Start with Phase 0 only. Report the current FastAPI entry point, agent invocation, RAG-context access, tool-trace access, existing endpoints, dependency versions, and proposed file changes. Do not implement later phases yet. Preserve existing business behavior. After I approve a phase, implement it, run relevant tests, list exact Postman requests and expected responses, and stop for my verification before proceeding. Do not invent existing routes, tool names, trace fields, or policy facts. If a capability is missing, explain the smallest required change before making broad architectural changes.

## 9. Definition of done

- The app starts with documented setup.
- Each evaluation endpoint has automated and Postman tests.
- Single-case and dataset evaluation use the existing agent.
- RAG metrics receive actual retrieval context.
- Tool metrics receive actual traces in a supported format.
- Metric skips, judge failures, agent failures, and metric failures are distinguishable.
- Authorization/cancellation are protected by deterministic tests.
- Reports include scores, thresholds, reasons, category summaries, and safety failures.
- Evaluation routes are protected and expose no secrets or unnecessary customer data.
- Existing customer-support endpoints continue to work.

## Official references

- DeepEval metrics overview: https://deepeval.com/docs/metrics-introduction
- Faithfulness: https://deepeval.com/docs/metrics-faithfulness
- Answer Relevancy: https://deepeval.com/docs/metrics-answer-relevancy
- Contextual Relevancy: https://deepeval.com/docs/metrics-contextual-relevancy
- FAQ and metric selection: https://deepeval.com/docs/faq
