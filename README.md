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
  vectors, traceable metadata, and persistence through the configured JSON or
  MongoDB repository. PDFs must contain
  extractable text; scanned/image-only PDFs are not OCR-processed.
- **Phase 5:** Policy chat uses approved/current chunks, vector and BM25
  retrieval combined by reciprocal rank fusion, and Groq answers grounded in
  retrieved evidence with source metadata. MongoDB storage uses Atlas Vector
  Search; JSON storage uses the existing in-process cosine search. Reciprocal
  rank fusion uses
  `1 / (60 + rank)` for each vector/BM25 result list. If query vectors cannot
  be created or stored vectors are missing/incompatible, BM25 can still retrieve
  evidence.
- **Phase 6:** Deterministic chat routing selects approved-policy RAG, order,
  delivery, payment, product, review, and cancellation-eligibility tools.
  Mixed warranty/product questions combine policy sources with current product
  data. Order-related requests require a signed-in customer session and order
  reference; cancellation checks eligibility before asking for confirmation.
  Delivery, policy, and support-contact tasks can be answered together. The
  local `Policies.pdf` currently conflicts with its registry approval flag, so
  it is marked unapproved and is excluded from retrieval until an authorized
  reviewer resolves that conflict.
- **Phase 7:** Authenticated conversations retain at most 12 recent turns and
  the last order reference, scoped to the verified customer. Memory expires
  after 30 minutes of inactivity by default, redacts common secret/payment
  formats, resolves follow-up references, and can recap recent exchanges when
  asked. The browser keeps the conversation ID in tab-scoped session storage so
  server-side history in the selected storage backend remains reachable after a
  page reload; `memory_enabled` can disable short-term storage and retrieval.
  The chat response reports short-term use and whether cancellation history was
  created, never the stored turns. Cancellation requests collect an
  optional reason, require explicit confirmation, and persist eligibility and
  final outcomes (`cancelled`, `declined`, `ineligible`, or `withdrawn`) in the
  selected repository (`data/cancellation_history.json` with JSON storage).
  Demo cancellation history expires after
  365 days by default. These retention values are configurable through
  `JsonRepository` when JSON storage is selected; confirm business retention
  requirements before production.
- **Multi-part requests and escalation context:** Combined order, delivery, and
  payment questions check each requested data source independently; policy
  questions in the same message are answered from eligible evidence or
  explicitly reported as unverified. A refund-status request checks the
  authenticated order’s payment record; only a record marked `refunded` confirms
  that state, otherwise a separate refund record is unavailable and the issue
  is offered to support. Repeated-delivery complaints receive an
  acknowledgment before the latest available status or the required order
  clarification. Address changes are not performed by the demo agent; it
  reports that limitation and offers escalation rather than claiming the
  change succeeded. When an
  authenticated customer asks about “the other one,” short-term context
  identifies the previous lookup type and the order search selects another
  order only when exactly one safe match exists. Escalation tickets keep a
  redacted issue summary, related order reference when known, and up to 12
  recent conversation turns in the selected repository
  (`data/support_tickets.json` with JSON storage).
- **Human support escalation:** When policy evidence is missing, the model
  marks an answer as unverifiable, or answer generation fails, chat creates an
  open ticket in the selected repository (`data/support_tickets.json` with JSON
  storage) and shows an in-app message form.
  The local ticket alone does not notify a human: the signed-in customer must
  submit the form to send details to the configured support email. The UI and
  response explain this distinction. Sensitive patterns are redacted before
  the message is emailed. The sender is the company SMTP account and the
  verified customer account email is included as `Reply-To`, so support can
  reply to the customer without allowing sender spoofing. Configure
  `SUPPORT_EMAIL`, `SMTP_HOST`, and
  `SMTP_PORT` in `.env`; configure `SMTP_USERNAME` and `SMTP_PASSWORD` when
  authentication is required. `SMTP_USE_TLS` defaults to `true`;
  `SMTP_USE_SSL=true` enables implicit TLS instead. `SMTP_FROM_EMAIL` can
  override the sender address. Email delivery must be configured for the customer
  follow-up form to send messages successfully. Support staff sign in separately at
  `POST /api/auth/support-agent/login`; customer tokens cannot read staff details
  or update tickets. Staff can transition a ticket with
  `PATCH /api/admin/tickets/{ticket_id}/status`, providing a status and
  audit note. Moving a ticket to `waiting_for_customer` or `resolved` also
  requires a customer-facing message. The staff dashboard is available at
  `/admin/dashboard`. Customers can check their own ticket's
  status and latest public update at `GET /api/support/tickets/{ticket_id}/status`;
  this response does not include staff notes or conversation details. Accounts
  are provisioned with
  `python -m app.services.support_agent_accounts --staff-id STAFF-001 --email agent@example.com`.
  Support-agent password hashes are stored in the git-ignored JSON file
  `data/support_agents.json`.
- **Customer ticket tracking:** The authenticated sidebar includes **My Support
  Tickets**, with search by ticket ID/subject, status filters and counts, and a
  detail timeline. Customer access is checked in the API using the bearer token;
  list and detail responses contain only tickets whose `customer_id` matches
  the signed-in customer. Legacy tickets without an owner are not exposed.
  `GET /api/tickets` lists a customer's tickets and
  `GET /api/tickets/{ticket_id}` returns customer-visible messages, status
  transitions, and the latest public update without staff notes or customer
  identifiers. `POST /api/support/tickets/{ticket_id}/message` reuses the
  support-email flow and persists the customer message on that same ticket.
  Support-agent replies, category, priority, assignment, update timestamps,
  internal notes, and audit history are stored alongside the original record.
  Internal notes are only returned by staff endpoints. Statuses stored in JSON are
  `open`, `investigating`, `waiting_for_customer`, `escalated`, `resolved`, and
  `closed`; the UI presents customer-friendly labels. Chat questions such as
  “What is the status of ticket SUP-...?” use the same owned records and do not
  infer ticket state.
- **Conversational scope and issue handling:** Harmless car-buying questions
  receive brief general selection guidance while the assistant explains its
  e-commerce support focus; other unrelated questions are politely declined.
  Delivery complaints without an order number can search only the verified
  customer's own orders. Cancelled-order charge/refund complaints
  check both order and payment records, then create a support ticket when human
  investigation is needed. The assistant does not claim that a refund was
  issued or that a human was contacted; tickets are local demo records and the
  signed-in customer can send further details directly to support by email.
  Tickets remain in JSON; staff use the separate ticket dashboard to assign and
  process them. Status updates are audit-recorded, require a note, and use explicit
  allowed transitions; JSON file locking is process-local, so multi-worker
  production deployments still need shared durable storage.

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

## MongoDB Atlas storage and policy Vector Search

The application can use MongoDB Atlas for its operational records and policy
chunks. Set the following values in your local, git-ignored `.env` file; use
your own Atlas connection string and the exact database name you created:

```dotenv
STORAGE_BACKEND=mongodb
MONGODB_URI=mongodb+srv://<database-user>:<encoded-password>@<cluster-host>/?retryWrites=true&w=majority
MONGODB_DATABASE=<your-database-name>
MONGODB_VECTOR_INDEX=policy_vector_index
```

In Atlas, add your development IP address to the project's network access list
and create a database user with read/write access to this database. Keep the
URI private and never commit it. The default `STORAGE_BACKEND=json` preserves
the current behavior; selecting `mongodb` does not silently fall back to JSON
if Atlas is unavailable.

Install dependencies, then import the current JSON data once:

```powershell
python -m pip install -r requirements.txt
python -m app.storage.migrate_json_to_mongodb
```

The migration inserts records without overwriting existing ones. It is safe to
rerun when every matching record is unchanged; conflicting existing records
stop the migration and are not overwritten. It also imports damage-report
images. The application stores customer accounts in `customers` and additionally
creates `policychunks`, `cancellationhistory`, and `damagereports` as needed.
Evaluation cases and evaluation-run reports remain local JSON files.

Before enabling policy-vector retrieval, create an Atlas Vector Search index
named `policy_vector_index` on the `policychunks` collection. In Atlas Data
Explorer, choose **Create Search Index**, select **Vector Search**, and use
this definition:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    {"type": "filter", "path": "embedding_model"},
    {"type": "filter", "path": "metadata.approved"},
    {"type": "filter", "path": "metadata.updated_at"}
  ]
}
```

Wait until the index status is **Ready**. Then run ingestion to re-chunk
approved local policy sources and save their Mistral embeddings in MongoDB:

```powershell
python -m app.rag.ingestion
```

Ingestion requires `MISTRAL_API_KEY`; semantic chunking uses Groq when
`GROQ_API_KEY` and `GROQ_MODEL` are configured and otherwise uses the existing
deterministic chunker. Start the API with `uvicorn app.main:app --reload` and
ask a policy question through the chat UI. Atlas Vector Search supplies the
vector-ranked candidates; the existing BM25 retrieval and reciprocal-rank
fusion remain in use. The search index must be ready before policy chat can use
MongoDB vector retrieval. Policy sources can be stored under `data/` or in
`app/policies/`; set each document's `source` field to the corresponding
repository-relative path. Only their metadata, chunks, and embeddings are
stored in MongoDB.

## Ticket Tracking Setup and API

Start the backend and frontend using the existing setup commands below. The
frontend runs through Vite and calls the API at the configured Vite proxy/API
origin; use the same origin and backend configuration as the chatbot.

```powershell
# Backend, from the repository root (after installing requirements.txt)
uvicorn app.main:app --reload

# Frontend, in another terminal
cd frontend
npm install
npm run dev
```

Provision a customer account for a fictional seeded customer, then sign in
through the UI or `POST /api/auth/login`:

```powershell
python -m app.services.customer_accounts --customer-id CUS-DEMO-002 --email customer@example.com
```

Use the returned `authorization_token` as `Authorization: Bearer <token>` for
the ticket list and details. Representative customer-owned ticket data in
`data/support_tickets.json` follows this shape (timestamps and identifiers are
illustrative):

```json
{
  "ticket_id": "SUP-0738300D0849",
  "conversation_id": "demo-conversation-1001",
  "customer_message": "My delivery has not arrived.",
  "customer_id": "CUS-DEMO-002",
  "order_id": "ORD-1002",
  "issue_summary": "Delayed delivery",
  "conversation_context": [
    {"role": "user", "text": "My delivery has not arrived.", "created_at": "2026-10-28T08:30:00Z"},
    {"role": "assistant", "text": "I have opened a support request.", "created_at": "2026-10-28T08:30:00Z"}
  ],
  "status": "waiting_for_customer",
  "status_history": [
    {"previous_status": "open", "status": "waiting_for_customer", "changed_by": "STAFF-001", "changed_at": "2026-10-28T09:00:00Z", "note": "Internal audit note"}
  ],
  "customer_update": {
    "status": "waiting_for_customer",
    "message": "Please confirm the delivery address.",
    "created_at": "2026-10-28T09:00:00Z"
  },
  "created_at": "2026-10-28T08:30:00Z"
}
```

Customer API endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/tickets` | List only the authenticated customer's tickets |
| `GET` | `/api/tickets/{ticket_id}` | Read one owned ticket's public details and timeline |
| `POST` | `/api/support/tickets/{ticket_id}/message` | Send a reply through configured support email |
| `POST` | `/api/chat` | Ask a ticket status/update question using the same records |

The ticket endpoints require a customer bearer token. A missing or foreign
ticket returns `404`; missing/expired authentication returns `401`; temporary
storage or email failures return `503`. The Postman collection includes
**My support tickets**, **Ticket details**, **Reply to support ticket**, and
**Ticket status via chat** requests. Run **Customer login** first so the
collection's `authorizationToken` variable is populated. Replies require the
same email configuration as the existing support form.

## Product Owner Dashboard

Open `http://127.0.0.1:5173/admin/dashboard` for the separate internal ticket
workspace; the customer chatbot remains at `/`. The admin page signs in through
the existing support-agent authentication service at
`POST /api/auth/support-agent/login`. Customer tokens are rejected by every
`/api/admin/*` endpoint, and the customer APIs continue to filter by the
authenticated `customer_id`. There are no hard-coded demo staff credentials.
Provision a staff account and enter the password interactively:

```powershell
python -m app.services.support_agent_accounts --staff-id STAFF-001 --email agent@example.com
```

Support-agent accounts have the `support_agent` role and are stored in the
git-ignored `data/support_agents.json`. Customer accounts have the `customer`
role and use the existing `/api/auth/login` flow.

The dashboard and customer ticket page both use the same records in
`data/support_tickets.json`. Status, assignment, priority, and messages are
saved to that record; customer ticket lists/details and admin counts poll every
15 seconds, with a detail refresh after each successful mutation. A response
is only shown as successful after the backend confirms persistence. Staff notes
are stored separately and are omitted from customer response models. Status
changes store previous/new status, staff ID, timestamp, and the internal audit
note. Assignment, priority, reply, and note actions also have staff audit
events. Customer follow-up messages remain emailed to configured support and
are now persisted to the same ticket timeline.

The UI labels map to the existing persisted status values:

| Dashboard label | Stored value |
|---|---|
| Open | `open` |
| In Progress | `investigating` (legacy `escalated` is included) |
| Pending Customer | `waiting_for_customer` |
| Resolved | `resolved` |
| Closed | `closed` |

The existing transition rules remain enforced by the backend. `resolved` can
be reopened to `open` or moved to `closed`; `closed` is terminal. Moving to
`waiting_for_customer` or `resolved` requires a customer-visible message.
Resolving and closing require confirmation in the dashboard.

Admin API endpoints (all require `Authorization: Bearer <support-agent-token>`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/support-agent/login` | Issue a role-scoped staff token |
| `GET` | `/api/admin/dashboard/stats` | Live counts by ticket status |
| `GET` | `/api/admin/tickets` | Search/filter/sort/paginate tickets (`search`, `status`, `priority`, `category`, `assigned_to`, `sort_by`, `sort_order`, `page`, `page_size`) |
| `GET` | `/api/admin/tickets/{ticket_id}` | Staff detail, public conversation, status and staff audit history, private notes |
| `GET` | `/api/admin/agents` | Agent IDs and work emails for assignment |
| `GET` | `/api/admin/categories` | Categories for complete filtering choices |
| `PATCH` | `/api/admin/tickets/{ticket_id}/status` | Change status with `status`, `note`, optional `customer_message` |
| `PATCH` | `/api/admin/tickets/{ticket_id}/priority` | Set `low`, `medium`, `high`, or `critical` |
| `PATCH` | `/api/admin/tickets/{ticket_id}/assign` | Set `assigned_to` to a staff ID or `null` |
| `POST` | `/api/admin/tickets/{ticket_id}/reply` | Add a customer-visible support reply |
| `POST` | `/api/admin/tickets/{ticket_id}/notes` | Add a staff-only internal note |

Example request and response for a status change:

```http
PATCH /api/admin/tickets/SUP-0738300D0849/status
Authorization: Bearer <support-agent-token>
Content-Type: application/json

{"status":"investigating","note":"Reviewing carrier scan history."}
```

```json
{
  "ticket_id": "SUP-0738300D0849",
  "status": "investigating",
  "priority": "medium",
  "assigned_to": null,
  "updated_at": "2026-10-30T08:30:00Z"
}
```

For a customer-visible response, send
`POST /api/admin/tickets/{ticket_id}/reply` with
`{"message":"We are checking the carrier scan history."}`. The customer then
receives it in `GET /api/tickets/{ticket_id}` as an assistant/support message.
`POST /api/admin/tickets/{ticket_id}/notes` accepts `{"note":"Check internal
carrier escalation log."}`; that note is never included in customer endpoints.
`GET /api/admin/tickets` returns `{ "tickets": [...], "total": 1, "page": 1,
"page_size": 20 }`. The Postman collection includes support-agent login,
admin stats/list, status, priority, assignment, reply, and internal-note
requests. Set `staffEmail` and `staffPassword` in a private Postman environment;
the login request stores `staffAuthorizationToken` for the admin requests.

This JSON demo repository uses process-local locking. For multiple backend
workers or production deployment, replace it with a shared transactional store
and durable shared sessions before relying on cross-worker synchronization.

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

Only documents marked `"approved": true` in the selected repository are
loaded. The JSON backend reads its registry from
`data/policy_documents.json`; after migration, MongoDB reads `policydocuments`.
Phase 4 accepts Markdown (`.md`), plain text (`.txt`), and PDFs (`.pdf`) within
the local `data/` directory. PDF extraction reads embedded text only; scanned
or image-only PDFs require OCR before ingestion. The sample policy documents
are fictional test materials, not actual company policies. Successful
ingestion replaces each document's existing chunks in the selected repository
(the default is `data/policy_chunks.json`); it does not duplicate chunks on
repeated runs.

## Live Picture damage reporting

Signed-in customers can use **Report damaged item** in the chat header or
**Report Damaged Item** in the first quick-action list to open Live Picture.
The customer must open the device camera, capture a new photo, review or retake
it, and confirm the photo before entering an order reference and submitting.
There is no image picker, file upload control, gallery fallback, or paste
workflow. The browser camera is accessed with `getUserMedia()` and stopped when
closed, after capture, or when the component unmounts. Camera access generally
requires HTTPS, except on localhost; the user must grant camera permission.

The React workflow is implemented in
`frontend/src/components/DamageReport.jsx` and uses the existing JSON API helper
in `frontend/src/api.js`. The FastAPI route is implemented in
`app/api/damage_reports.py` at `POST /api/damage-reports`. It uses the existing
demo authorization token and the signed-in customer's order ownership. Pass a
unique `Idempotency-Key` header (16–64 letters, digits, underscores, or hyphens)
to prevent retry duplicates.

Request fields:

```json
{
  "authorization_token": "<current signed-in session token>",
  "order_id": "ORD-1001",
  "image_data": "data:image/jpeg;base64,<base64-encoded camera capture>",
  "description": "The corner of the box is crushed."
}
```

`description` is optional (up to 1,000 characters). `image_data` must contain a
JPEG or PNG camera capture no larger than 5 MiB. Example successful response:

```json
{
  "report_id": "c1f3a5b7-1234-4567-89ab-cdef01234567",
  "order_id": "ORD-1001",
  "created": true,
  "message": "Your damage report was submitted for review.",
  "created_at": "2026-10-29T08:30:00Z"
}
```

An identical retry returns the original report identifier with `"created":
false`. Reusing the idempotency key for different report contents returns
`409`; expired/invalid sessions return `401`; an unknown or another customer's
order returns `404`; invalid image data returns `422` or `415`; oversized
images return `413`; and persistence failures return `503`. With JSON storage,
reports and private image bytes are persisted separately in
`data/damage_reports.json` and `data/damage_report_images/`; MongoDB stores them
in the `damagereports` collection. There is no public image-serving endpoint.
This demonstration storage is not a substitute for production
encrypted/private object storage, retention policies, or backups. Submission
records the report only; it does not approve a claim, refund, or replacement.

Run backend tests from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_damage_reports.py
```

Run the frontend build from `frontend`:

```powershell
npm run build
```

For manual camera verification, start the FastAPI app and Vite frontend, sign
in with a configured demo account, open Live Picture on a device with a camera,
grant the browser permission, take a photo, and verify that retake, confirmation,
submission, and the report reference work. Also test denied permission and a
device without camera hardware; both should show a helpful message without
offering image selection. For a physical device, serve the frontend and API
over HTTPS and configure them to share the same origin or suitable proxy.
