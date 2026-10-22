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
- **Phase 4:** Approved Markdown/text policy ingestion with source-preserving
  Groq semantic chunking (deterministic fallback), Mistral `mistral-embed`
  vectors, traceable metadata, and JSON persistence.
- **Phase 5:** Policy chat uses approved/current chunks, cosine and BM25
  retrieval combined by reciprocal rank fusion, and Groq answers grounded in
  retrieved evidence with source metadata. Reciprocal rank fusion uses
  `1 / (60 + rank)` for each vector/BM25 result list. If query vectors cannot
  be created or stored vectors are missing/incompatible, BM25 can still retrieve
  evidence.
- **Phase 6:** Deterministic chat routing selects approved-policy RAG, order,
  delivery, payment, product, review, and cancellation-eligibility tools.
  Mixed warranty/product questions combine policy sources with current product
  data. Order-related requests require a demo authorization token and order
  reference; cancellation checks eligibility before asking for confirmation.
- **Phase 7:** Seeded demo identities receive short-lived server-side tokens.
  Order lookups require a valid token; cancellation has a separate explicit
  confirmation endpoint and rechecks the single-use eligibility token before
  changing the demo order. Provider requests have bounded timeouts, and tests
  cover authorization, malformed requests, missing data, provider timeouts,
  tool failures, cancellation, and RAG evidence/fallback behavior.

Phase 2 tools are available through chat routing but are not separate HTTP
endpoints apart from cancellation confirmation. The demo verification endpoint
issues a token to anyone who supplies a known seeded customer ID. This is
intentionally a simulation for fictional local records, not authentication; do
not connect it to real customer data.

The records in `data/` are fictional test data. They are not real customer,
payment, product, delivery, or review records.

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

Install test dependencies and run the suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

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
Set `baseUrl` to `http://127.0.0.1:8000`. The health, demo verification, chat,
and cancellation confirmation requests are implemented; remaining requests
document endpoints planned for later phases.
To test order, delivery, payment, or cancellation chat routes, first call
`POST /api/demo/verify` with `{"customer_id":"CUS-DEMO-001"}` and copy its
`authorization_token` into the chat request. Tokens expire after 15 minutes and
are held in process memory. Anyone who knows a seeded demo ID can obtain a
token; this is not authentication and must not be used with real records.

For cancellation, send a chat message such as `Cancel order ORD-1001` with the
authorization token. If eligible, the response includes a separate
single-use `confirmation_token`. Only after explicit confirmation, send both
tokens to `POST /api/orders/ORD-1001/cancel` with a unique `Idempotency-Key`
header. Reuse that key only when retrying the same cancellation request. The
server rechecks the order owner, eligibility, token expiry, and order version
before making the change.
The demo's idempotency state is also process-local; production needs durable
transactional handling across service instances.
The chat UI sends this separate request only after **Confirm cancellation** is
pressed.

## Environment variables

Copy `.env.example` to `.env`, then set `MISTRAL_API_KEY` before policy
ingestion. Set `GROQ_API_KEY` to enable semantic chunking; if it is unavailable
or the configured `GROQ_MODEL` is not set, ingestion warns and uses
deterministic chunks instead. The selected Groq model must be enabled for your
account. Policy answers in chat require `GROQ_API_KEY`, `GROQ_MODEL`, and
`MISTRAL_API_KEY`. Model requests have a 15-second timeout. Never commit `.env`
or place credentials in source code.

Run policy ingestion from the project root after configuring the key:

```powershell
.\.venv\Scripts\python.exe -m app.rag.ingestion
```

Only documents marked `"approved": true` in `data/policy_documents.json` are
loaded. Phase 4 accepts Markdown (`.md`) and plain text (`.txt`) sources within
the `data/` directory. The sample policy documents are fictional test
materials, not actual company policies. Successful ingestion replaces each
document's existing chunks in `data/policy_chunks.json`; it does not duplicate
chunks on repeated runs.
