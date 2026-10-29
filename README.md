# Customer Support AI Agent

This repository implements the customer-support agent described in
[the architecture](./customer_support_ai_agent_architecture.md) and
[the requirements](./customer_support_ai_agent_requirements.md).

## Implemented phases

- **Phase 1:** FastAPI application, `GET /health`, a consistent JSON error
  format, and a Postman collection containing the API contract examples.
- **Phase 2:** Fictional JSON datasets, validated JSON repository operations,
  LangChain tools for customer/order/product/review lookups, and a separate
  cancellation eligibility and confirmation flow.
- **Phase 3:** Responsive React/Vite chat UI connected to `POST /api/chat`.
  The endpoint returns grounded policy answers from Phase 5.
- **Phase 4:** Approved Markdown/text/PDF policy ingestion with source-preserving
  Groq semantic chunking (deterministic fallback), Mistral `mistral-embed`
  vectors, traceable metadata, and JSON persistence. PDFs must contain
  extractable text; scanned/image-only PDFs are not OCR-processed.
- **Phase 5:** Policy chat uses approved/current chunks, cosine and BM25
  retrieval combined by reciprocal rank fusion, and Groq answers grounded in
  retrieved evidence with source metadata. Reciprocal rank fusion uses
  `1 / (60 + rank)` for each vector/BM25 result list. If query vectors cannot
  be created or stored vectors are missing/incompatible, BM25 can still retrieve
  evidence.
- **Phase 6:** Deterministic chat routing handles clear common requests, with
  Groq intent classification augmenting supported routes to interpret informal,
  misspelled, or context-dependent messages. It can identify multiple requested
  tasks in one message and combine their authorized order, delivery, payment,
  product, review, or policy results in one response. The classifier returns
  only validated intents;
  server-side routes still enforce authorization, business rules, and tool
  access. It can use recent redacted conversation turns to interpret follow-ups.
  `GROQ_INTENT_MODEL` optionally selects a dedicated model and defaults to
  `GROQ_MODEL`. If the classifier is unavailable, deterministic routing remains
  in place. The latest message and limited conversation context may be sent to
  Groq for classification; known payment-card formats, credentials, email
  addresses, and order/product/customer references are redacted first, but
  other personal details may still be present. Mixed warranty/product questions
  combine policy sources with current product data. Order-related requests
  require a signed-in customer session; cancellation checks eligibility before
  asking for confirmation.
- **Phase 7:** Authenticated conversations retain up to 200 turns and the first
  user message, scoped to the verified customer. Memory expires after 30 minutes
  of inactivity by default, redacts common secret/payment formats, and retrieves
  a small amount of relevant older context alongside recent turns. The web app
  restores the active conversation after a page reload; customers can ask the
  assistant to recall earlier messages. This is retrieval-based memory, not
  automatic model training. `memory_enabled` can disable short-term storage and
  retrieval. The chat response reports short-term use and whether cancellation
  history was created, never the stored turns. Cancellation requests collect an
  optional reason, require explicit confirmation, and persist eligibility and
  final outcomes (`cancelled`, `declined`, `ineligible`, or `withdrawn`) in
  `data/cancellation_history.json`. Demo cancellation history expires after
  365 days by default. These retention values are configurable through
  `JsonRepository`; confirm business retention requirements before production.
- **Human support escalation:** When policy evidence is missing, the model
  marks an answer as unverifiable, or answer generation fails, chat creates an
  open ticket in `data/support_tickets.json` and shows an in-app message form.
  The signed-in customer can add details to the ticket later in the same
  conversation or from its ticket card, then send them to the configured
  support email without opening another app. Sensitive patterns are redacted
  before the message is emailed. The sender is the company SMTP account and the
  verified customer account email is included as `Reply-To`, so support can
  reply to the customer without allowing sender spoofing. Configure
  `SUPPORT_EMAIL`, `SMTP_HOST`, and
  `SMTP_PORT` in `.env`; configure `SMTP_USERNAME` and `SMTP_PASSWORD` when
  authentication is required. `SMTP_USE_TLS` defaults to `true`;
  `SMTP_USE_SSL=true` enables implicit TLS instead. `SMTP_FROM_EMAIL` can
  override the sender address. Email delivery must be configured for the form
  to send messages successfully.
- **Conversational scope and issue handling:** General questions outside
  store/e-commerce support are politely declined rather than answered with
  generic advice. Delivery complaints without an order number can search only
  the verified customer's own orders. Cancelled-order charge/refund complaints
  check both order and payment records, then create a support ticket when human
  investigation is needed. The assistant does not claim that a refund was
  issued or that a human was contacted; tickets are local demo records and the
  signed-in customer can send further details directly to support by email.

Phase 2 tools are available through chat routing but are not separate HTTP
endpoints apart from cancellation confirmation. Customers sign in with their
email and password before using the chat UI. Accounts are provisioned by an
administrator and map one email address to one customer ID; passwords are
stored as salted scrypt hashes in the git-ignored
`data/customer_accounts.json` file. Sessions expire after 15 minutes and are
held in process memory, so configure durable shared sessions and an appropriate
password/account lifecycle before production use.

The records in `data/` are fictional test data. They are not real customer,
payment, product, delivery, or review records.
Demo order and product prices use South African rand (ZAR).

## DeepEval evaluation API (Implementation Phases 1–7)

The evaluation foundation exposes these endpoints:

- `GET /eval/health` — readiness and judge configuration status; never returns credentials.
- `GET /eval/metrics` — metric names, descriptions, enablement, and configured thresholds.
- `GET /eval/cases` — list the validated local cases; optional `category` accepts
  `rag_policy`, `tool_lookup`, `mixed`, `unknown`, or `safety`; optional `limit`
  must be between 1 and 100. The response's `total` is the number of matches
  before applying `limit`.
- `POST /eval/cases` — append a validated case to the local JSON dataset; returns
  `201`, rejects invalid cases with `422`, and duplicate case IDs with `409`.
- `POST /eval/run` — run one validated case through the same `ChatOrchestrator`
  instance as `POST /api/chat`, then return the actual answer, route, retrieved
  chunk text (when RAG returns it), sanitized tool-call names/arguments/status,
  metric outcomes, and duration. The evaluation runner only issues temporary
  demo authorization for a seeded customer ID explicitly present in
  `expected_tool_arguments`; it does not return that token. Do not use this demo
  path with real customer data.
- `POST /eval/dataset/run` — select all cases by default, or filter by `categories`
  and/or `case_ids`; `fail_fast` marks remaining cases skipped after the first
  failed case. Returns `202` with a `run_id` while a FastAPI background task
  evaluates the selected synthetic cases sequentially.
- `GET /eval/runs/{run_id}` — retrieve persisted run status, summary, and cases.
- `GET /eval/runs/{run_id}/results` — retrieve persisted per-case results.

An empty category and ID filter means all dataset cases. When both are supplied,
they are combined using intersection. Unknown IDs and filters selecting no cases
return `422`; unknown run IDs return `404`. Run records are stored atomically in
`data/evaluation_runs.json`. A `completed` run may still contain failed cases;
the report separates case execution/metric/safety outcomes and includes counts,
metric pass rate, safety failures, and category summaries. Metrics with score
statuses `passed` or `failed` contribute to pass rate; skipped and error metrics
are counted separately. LLM-judge API costs apply when credentials are set.

Phase 6 provisional demo thresholds can be configured individually through
`DEEPEVAL_ANSWER_RELEVANCY_THRESHOLD` (0.80),
`DEEPEVAL_FAITHFULNESS_THRESHOLD` (0.90),
`DEEPEVAL_CORRECTNESS_THRESHOLD` (0.85),
`DEEPEVAL_CONTEXTUAL_RELEVANCY_THRESHOLD` (0.80), and
`DEEPEVAL_TOOL_CORRECTNESS_THRESHOLD` (0.90). `DEEPEVAL_THRESHOLD` remains a
backward-compatible global fallback when an individual setting is not supplied.
Review and tune these starting values against representative runs; they are not
universal benchmarks. Dataset summaries include a fail-closed
`quality_gate_passed`: it is false if any case fails or is skipped, any metric
fails or errors, no metric scores are available, or a cancellation-without-
confirmation or unauthorized-order-disclosure check fails. A high average score
cannot override a failed safety check.

Single-case results also contain deterministic checks for the expected route,
expected tool selection/arguments, no cancellation during evaluation without a
separate customer confirmation, no success claim after an unavailable tool,
and cross-customer order disclosure for cases with a seeded synthetic
order/customer pair. Tool arguments redact `customer_id`; tool results are
represented only by safe status labels. A tool call mismatch is supplementary
to the deterministic exact name/argument checks.

`tool_correctness` uses the installed DeepEval `ToolCorrectnessMetric` with the
captured safe trace. `task_completion` is explicitly disabled/skipped because
the current orchestrator does not expose the trajectory format required by
DeepEval's `TaskCompletionMetric`. During evaluation, cancellation eligibility
uses a read-only preview adapter: it does not issue confirmation tokens, append
cancellation events, or execute the cancellation tool. Production chat retains
its existing cancellation flow.

The single-case runner evaluates answer relevancy for non-empty answers,
faithfulness and contextual relevancy only when the agent returned real
retrieval context, and customer-support correctness only when `expected_output`
is provided. Precision and recall remain unavailable until the dataset has gold
evidence and ranking labels. Metrics requiring unavailable inputs are marked
`skipped`. Without judge credentials,
the agent still runs and metrics are skipped with an explicit reason. Judge
metric errors are reported as `judge_error`; agent exceptions are reported as
`agent_error` with exception details omitted. `DEEPEVAL_ENABLED=false` returns
`disabled` without invoking the agent; `busy` means a configured in-process
evaluation slot was unavailable and the agent was not invoked. Phase 3 currently supports the OpenAI
judge provider via `DEEPEVAL_PROVIDER=openai`, `DEEPEVAL_MODEL`, and
`DEEPEVAL_JUDGE_API_KEY` (or `OPENAI_API_KEY`).

Outside `local`, `development`, and `test`, evaluation routes fail closed: if
`DEEPEVAL_API_TOKEN` is unset, they respond as not found; if configured, callers
must send `Authorization: Bearer <token>`. Keep this token private and configure
it through the deployment environment, not source control or Postman exports.
Evaluation request bodies are limited by `DEEPEVAL_MAX_REQUEST_BODY_BYTES`
(default 131072, maximum configurable 1048576). Judge requests have a configured
HTTP timeout via `DEEPEVAL_JUDGE_TIMEOUT_SECONDS` (default 30 seconds, accepted
range 1–300). In-process evaluation concurrency is bounded by
`DEEPEVAL_MAX_CONCURRENT_EVALUATIONS` (default 2, range 1–8); when at capacity,
single-case calls return a `busy` status without invoking the agent, while a
dataset run records the affected case as skipped. Use a reverse proxy/server
request timeout and durable job queue for deployments where FastAPI
BackgroundTasks cannot meet reliability requirements.

The seeded synthetic dataset is in `data/evaluation_cases.json` (32 cases: 8
policy, 8 tool lookup, 4 mixed, 4 unknown/fallback, and 8 safety). The policy
cases intentionally capture the observed conflict between the policy PDF's
controlled-draft cover and its `approved: true` registry flag; they do not
assert those policy terms as verified. Cases use only fictional local records.
Case creation writes to this JSON file, so use a unique `case_id` when adding
cases.

Import `postman/customer_support_evaluation.postman_collection.json` into
Postman to test all implemented evaluation endpoints, including a product lookup
through the real agent path, read-only cancellation preview, cross-customer order
privacy, and representative valid, invalid, filtered, and duplicate-case
requests, dataset-run acceptance, run summary, and per-case reports. After the
dataset-run request, use its saved `runId` for the report requests. Start the API locally and keep `baseUrl` set to
`http://127.0.0.1:8000`. LLM judge metrics make external API calls and may incur
provider charges when judge credentials are configured.

## Requirements

- Python 3.10 or later
- Windows PowerShell (commands below use the Windows virtual-environment path)

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Open
`http://127.0.0.1:8000/docs` for the interactive API documentation.

In a second PowerShell window, start the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open the local URL printed by Vite. Its development server proxies `/api` and
`/health` requests to the FastAPI server on port 8000.

`GET /health` returns:

```json
{"status":"ok"}
```

API errors use this shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found",
    "request_id": "server-generated-uuid"
  }
}
```

Unexpected server errors are logged by the application and return a generic
message without exposing a traceback.

## Test

### Run the tests and open the Allure dashboard

1. Install the Python test dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

2. Run the tests to generate Allure results. Run the full suite:

```powershell
python -m pytest --alluredir=allure-results
```

Or run just the authorization tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_authorization.py --alluredir=allure-results
```

3. Install the Allure command-line tool if it is not already installed. It
requires Java and npm:

```powershell
npm install --global allure-commandline
```

4. Start the dashboard:

```powershell
allure serve allure-results
```

This opens the generated report in your browser. Run the tests again whenever
you want to refresh the results.

### Use the Phase 2 tools in Python

The tools are LangChain `StructuredTool` objects; for example:

```python
from app.agent.tools import get_order_status_tool

result = get_order_status_tool.invoke(
    {"order_id": "ORD-1001", "customer_id": "CUS-DEMO-001"}
)
```

The cancellation eligibility tool issues a short-lived, single-use,
server-side confirmation token. The API only executes cancellation after a
separate confirmation request, using both the demo authorization token and the
eligibility token. The confirmation token expires after five minutes and is
bound to the customer, order, and order version.

## Postman

Import `postman/customer_support_agent.postman_collection.json` into Postman.
Set `baseUrl` to `http://127.0.0.1:8000`. The health, login, chat,
and cancellation confirmation requests are implemented; remaining requests
document endpoints planned for later phases.
There are no default login accounts or shared credentials. A fresh checkout
has no allowed email/password pairs; logins work only after an administrator
provisions an account for a seeded customer. Create one from the repository
root, replacing the example email if needed:

```powershell
python -m app.services.customer_accounts --customer-id CUS-DEMO-001 --email customer@example.com
```

This creates the `customer@example.com` login for customer `CUS-DEMO-001`.
Enter a password of at least 12 characters when prompted, then enter it again
to confirm. The password is not included in the command line and is not stored
in plaintext. Create one account per customer. Then call
`POST /api/auth/login` with the account email and password; copy the returned
`authorization_token` into chat and cancellation requests. Do not send customer
IDs from the browser. Order and cancellation handlers resolve the customer ID
only from that session and check that each requested order belongs to that
customer. Sessions expire after 15 minutes and are process-local.

For cancellation, send a chat message such as `Cancel order ORD-1001` with the
authorization token. If eligible, the response includes a separate
single-use `confirmation_token`. The chat UI asks for an optional reason before
the final decision. Confirm via `POST /api/orders/ORD-1001/cancel` with both
tokens and a unique `Idempotency-Key`; choose **Keep order** or **Withdraw
request** to record a non-cancellation outcome. Reuse the key only when
retrying the same cancellation request. The server rechecks the order owner,
eligibility, token expiry, and order version before making the change.
The demo's idempotency state is also process-local; production needs durable
transactional handling across service instances.
The chat UI sends this separate request only after **Confirm cancellation** is
pressed.

## Environment variables

Copy `.env.example` to `.env` as a configuration template, then set
`MISTRAL_API_KEY` before policy ingestion. The application and policy-ingestion
command load `.env` from the repository root; `.env.example` is never loaded.
Set `GROQ_API_KEY` to enable semantic chunking; if it is unavailable
or the configured `GROQ_MODEL` is not set, ingestion warns and uses
deterministic chunks instead. The selected Groq model must be enabled for your
account. Policy answers in chat require `GROQ_API_KEY`, `GROQ_MODEL`, and
`MISTRAL_API_KEY`. By default, every generated policy answer is checked against
the retrieved approved evidence using `GROQ_VERIFIER_MODEL` (defaults to
`openai/gpt-oss-20b`). An unsupported answer or verifier failure is replaced by
a safe escalation response rather than shown as fact. This adds a second model
request per policy answer, but model-based verification cannot guarantee that
all hallucinations are detected. Model requests have a 15-second timeout.
Never commit `.env` or place credentials in source code.

Chat requests are screened locally for attempts to retrieve credentials,
hidden instructions, or private customer information. To enable OpenAI's
Moderation API for user messages, set `OPENAI_MODERATION_API_KEY` (or
`OPENAI_API_KEY`) and optionally `OPENAI_MODERATION_MODEL` in `.env`. The
default model is `omni-moderation-latest`. User messages are redacted for
common credentials and demo order/customer references before being sent for
moderation. When a configured moderation request fails, chat fails closed with
HTTP 503 rather than passing the message to the agent. The local sensitive
information checks remain active when no OpenAI key is configured. The
Moderation API screens for its supported safety categories; the local checks
are what block credential and private-data disclosure requests.

Run policy ingestion from the project root after configuring the key:

```powershell
.\.venv\Scripts\python.exe -m app.rag.ingestion
```

Only documents marked `"approved": true` in `data/policy_documents.json` are
loaded. Phase 4 accepts Markdown (`.md`), plain text (`.txt`), and PDFs (`.pdf`)
within the `data/` directory. PDF extraction reads embedded text only; scanned
or image-only PDFs require OCR before ingestion. The sample policy documents
are fictional test materials, not actual company policies. Successful
ingestion replaces each document's existing chunks in
`data/policy_chunks.json`; it does not duplicate chunks on repeated runs.
