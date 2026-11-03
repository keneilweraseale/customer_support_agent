# Customer Support Agent — Application Testing Guide

## 1. Purpose

This guide describes how to test the Customer Support Agent application using:

- **Postman** for manual API testing and response validation.
- **pytest** for automated backend testing.
- **Integration testing** to verify that the React frontend, FastAPI backend, storage layer, LangChain tools, RAG system, and ticket dashboards work together.

The testing objective is to verify that customers can access support, receive accurate responses, create and track tickets, and that authorized product owners and administrators can process tickets while status remains synchronized.

> **Important:** This guide is based on the repository structure included in this document. Some endpoint paths and request/response fields are examples. Confirm them against the routes and schemas in the running FastAPI application. Do not add duplicate endpoints simply to match this guide.

---

## 2. Testing Environment

### 2.1 Tools

| Tool | Purpose |
|---|---|
| FastAPI | Backend API |
| Postman | Manual API testing |
| pytest | Automated tests |
| pytest-cov | Test coverage |
| httpx / FastAPI TestClient | API tests without manually starting the server |
| JSON demo storage / MongoDB | Application data |
| React + Vite | Frontend |
| LangChain | Tool execution and routing |
| RAG | Retrieval and grounded answers |

### 2.2 Start the backend

From the repository root:

```bash
python -m uvicorn app.main:app --reload
```

Local API base URL:

```text
http://127.0.0.1:8000
```

Open the interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

Install test dependencies if they are not already installed:

```bash
python -m pip install pytest pytest-cov httpx
```

The repository also includes `requirements-dev.txt`. Prefer installing the project’s declared development dependencies when that file is maintained:

```bash
python -m pip install -r requirements-dev.txt
```

### 2.3 Start the frontend

From the frontend directory:

```bash
cd frontend
npm install
npm run dev
```

Use the URL printed by Vite. Confirm that the frontend is configured to call the local backend.

---

## 3. Repository Structure and Test Locations

The testing examples below use the repository structure supplied in this guide. Tests should be placed in the existing `tests/` directory rather than creating a separate testing project.

```text
customer_support_agent/
├── app/
│   ├── main.py
│   ├── agent/
│   │   ├── intent_classifier.py
│   │   ├── router.py
│   │   └── tools.py
│   ├── api/
│   │   ├── admin_tickets.py
│   │   ├── authorization.py
│   │   ├── chat.py
│   │   ├── damage_reports.py
│   │   ├── errors.py
│   │   ├── health.py
│   │   └── orders.py
│   ├── evaluation/
│   │   ├── config.py
│   │   ├── dataset.py
│   │   ├── middleware.py
│   │   ├── metrics.py
│   │   ├── router.py
│   │   ├── runs.py
│   │   ├── safety.py
│   │   └── schemas.py
│   ├── rag/
│   │   ├── generation.py
│   │   ├── ingestion.py
│   │   ├── providers.py
│   │   ├── retrieval.py
│   │   └── service.py
│   ├── services/
│   │   ├── cancellations.py
│   │   ├── conversation_memory.py
│   │   ├── customer_accounts.py
│   │   ├── demo_authorization.py
│   │   ├── moderation.py
│   │   ├── support_agent_accounts.py
│   │   ├── support_email.py
│   │   └── support_tickets.py
│   └── storage/
│       ├── factory.py
│       ├── json_store.py
│       ├── migrate_json_to_mongodb.py
│       ├── models.py
│       ├── mongodb.py
│       └── repository.py
├── data/
│   ├── policies/
│   ├── damage_report_images/
│   ├── cancellation_history.json
│   ├── support_tickets.json
│   └── support_agents.json
├── frontend/
│   └── src/
│       ├── App.jsx
│       ├── admin.css
│       ├── api.js
│       ├── main.jsx
│       ├── styles.css
│       └── components/
│           ├── AdminDashboard.jsx
│           ├── CancellationConfirmation.jsx
│           ├── ChatComposer.jsx
│           ├── ChatHeader.jsx
│           ├── DamageReport.jsx
│           ├── MessageList.jsx
│           └── TicketTracking.jsx
├── postman/
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_authorization.py
│   ├── test_damage_reports.py
│   ├── test_evaluation_phase1.py
│   ├── test_evaluation_phase2.py
│   ├── test_evaluation_phase3.py
│   ├── test_evaluation_phase4.py
│   ├── test_evaluation_phase5.py
│   ├── test_evaluation_phase6.py
│   ├── test_evaluation_phase7.py
│   ├── test_generation.py
│   ├── test_ingestion.py
│   ├── test_intent_classifier.py
│   ├── test_memory.py
│   ├── test_moderation.py
│   ├── test_mongodb.py
│   ├── test_provider_timeouts.py
│   ├── test_retrieval.py
│   ├── test_router.py
│   ├── test_support_email.py
│   └── test_tools.py
├── .env.example
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── customer_support_ai_agent_architecture.md
├── customer_support_ai_agent_requirements.md
└── testing.md
```

The tree above reflects the supplied structure. The test cases in this guide are recommendations; add them to the existing test modules or create a new `tests/test_*.py` file when needed. Do not assume that every example test or route already exists in the implementation.

### 3.1 Suggested mapping of test coverage to code

| Area | Main code location | Existing test files to review |
|---|---|---|
| API and health checks | `app/main.py`, `app/api/` | `test_api.py` |
| Authentication and authorization | `app/api/authorization.py`, `app/services/demo_authorization.py` | `test_authorization.py` |
| Intent routing and tools | `app/agent/` | `test_intent_classifier.py`, `test_router.py`, `test_tools.py` |
| RAG ingestion and retrieval | `app/rag/` | `test_ingestion.py`, `test_retrieval.py`, `test_generation.py` |
| Conversation memory | `app/services/conversation_memory.py` | `test_memory.py` |
| Moderation and safety | `app/services/moderation.py`, `app/evaluation/safety.py` | `test_moderation.py`, evaluation tests |
| Ticket workflows | `app/services/support_tickets.py`, relevant API modules | Add or extend ticket-focused tests |
| Damage reports | `app/api/damage_reports.py`, `frontend/src/components/DamageReport.jsx` | `test_damage_reports.py` |
| Storage | `app/storage/` | `test_mongodb.py` and API/service tests |
| Support email | `app/services/support_email.py` | `test_support_email.py` |
| Evaluation workflow | `app/evaluation/` | `test_evaluation_phase1.py` through `test_evaluation_phase7.py` |

---

## 4. Postman Manual API Testing

Create a Postman collection named **Customer Support Agent — API Tests**.

Create an environment with variables such as:

| Variable | Example |
|---|---|
| `base_url` | `http://127.0.0.1:8000` |
| `customer_id` | `CUS-DEMO-001` |
| `token` | Leave blank until a successful verification/login |
| `order_id` | `ORD-DEMO-001` |
| `ticket_id` | Leave blank until a ticket is created |
| `product_id` | `PROD-DEMO-001` |
| `admin_token` | Leave blank until admin login |
| `product_owner_token` | Leave blank until product-owner login |

Use `{{variable_name}}` in request URLs, headers, and bodies. Replace example routes and payloads with the actual API contract.

### 4.1 Customer verification / login

**Example request**

```http
POST {{base_url}}/api/auth/verify
Content-Type: application/json
```

```json
{
  "customer_id": "{{customer_id}}"
}
```

**Expected checks**

- A valid demo customer is accepted according to the implemented verification rules.
- The response confirms verification.
- If the application issues a token, it is returned only after successful verification.
- Sensitive information is not included in the response.

Example Postman tests (adjust the response property to match the actual schema):

```javascript
pm.test("Verification request completed successfully", function () {
    pm.expect([200, 201]).to.include(pm.response.code);
});

pm.test("Response is JSON", function () {
    pm.response.to.be.json;
});
```

For an invalid customer ID, missing ID, or empty ID, verify that the request is rejected and no valid session/token is issued. Assert the actual documented rejection status rather than assuming one.

### 4.2 Protected order access

Test the actual order endpoint shown in Swagger or the application router.

Checks:

- Request without authentication is denied if the endpoint is protected.
- An invalid token is denied.
- A customer cannot access another customer's order.
- An authorized customer receives only permitted order details.
- Sensitive payment data is not exposed.

### 4.3 Chat and order-related questions

Use the actual chat endpoint and request schema. An example message could be:

```json
{
  "customer_id": "CUS-DEMO-001",
  "message": "Can you check my order status?",
  "order_id": "ORD-DEMO-001"
}
```

Check that:

- The appropriate intent is selected.
- The relevant order tool is called when required.
- The response uses retrieved order data.
- Missing or unknown order data is handled clearly.
- The chatbot does not invent an order status or delivery date.

Repeat with a delivery-delay question and an invalid order ID.

### 4.4 Support ticket lifecycle

The repository includes ticket service code and ticket storage. Confirm the actual ticket endpoints in the API documentation before sending requests.

For ticket creation, validate:

- Required fields are checked.
- A unique ticket identifier is created.
- The ticket is associated with the correct customer.
- A valid initial status is assigned.
- The ticket is persisted.

For invalid ticket requests, test missing fields, empty descriptions, unsupported category/priority values, and unauthorized requests. Expected status codes must follow the actual API contract.

### 4.5 Customer ticket tracking

Test the actual customer-facing ticket list/detail endpoint.

Checks:

- The customer sees only tickets they are authorized to access.
- The current status is included.
- The returned status matches the stored ticket record.
- A customer cannot read another customer's ticket by changing the ticket ID.

### 4.6 Product-owner ticket processing

Use the actual product-owner API routes and role authorization. The paths below are conceptual test actions, not confirmed route names.

Checks:

- An authorized product owner can retrieve permitted tickets.
- A customer cannot access product-owner functions.
- A product owner cannot update a ticket outside their permitted scope.
- A status update is validated against allowed status values.
- The update is persisted and returned by the API.

### 4.7 Ticket status synchronization

1. Create a ticket as a customer.
2. Record its ticket ID.
3. Retrieve the ticket through the customer-facing API.
4. Retrieve the same ticket through the authorized product-owner view.
5. Update its status as the product owner.
6. Retrieve the ticket again through the customer-facing API.
7. Confirm that both views show the same status.
8. Repeat for another valid status transition.

**Expected result:** Both interfaces read the same ticket record from the backend. The frontend must not maintain an independent status value that can drift from the database.

### 4.8 RAG policy questions

Ask questions about supported policy topics, such as:

- Refund policy
- Shipping costs
- Exchange information
- Return instructions
- Warranty
- Contact information
- How to order

Check that:

- Relevant policy content is retrieved.
- The response is grounded in the retrieved material.
- Unsupported conditions are not invented.
- If the source material does not contain the answer, the chatbot says it cannot confirm the information.

### 4.9 Product information and payment issues

For product information, verify that the answer uses the relevant product source and does not invent product details.

For payment questions, verify that the response uses permitted payment/order information and does not expose sensitive payment data.

### 4.10 Damage report / live picture

The frontend includes `DamageReport.jsx`, and the backend includes `app/api/damage_reports.py`. Test the actual capture and report flow implemented in the application.

Checks:

- The customer can use the supported camera capture flow.
- The interface does not offer a file-upload control if the requirement is camera-only capture.
- Camera permission denial is handled with a clear message.
- The captured image is associated with the correct damage report/ticket.
- Invalid or missing report details are rejected safely.
- The image is not exposed to unrelated customers.
- The backend handles image size and content validation according to its rules.

### 4.11 API health

Use the actual health endpoint shown in Swagger. Confirm that it returns the documented healthy response and does not expose secrets, environment variables, or internal configuration.

---

## 5. pytest Automated Testing

### 5.1 Test client

The repository already includes `tests/conftest.py`. Review and reuse its fixtures before adding another test client. A basic FastAPI test client pattern is:

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
```

If the existing fixture configures temporary storage, dependency overrides, authentication, or test settings, preserve those behaviors. Avoid replacing it with a simpler fixture that removes existing test setup.

### 5.2 Authentication and authorization

The supplied tree has `tests/test_authorization.py`; use that file rather than creating a duplicate `test_auth.py` without a reason.

Cover:

- Valid demo customer verification.
- Invalid customer ID.
- Missing and empty customer ID.
- Missing or invalid credentials/token.
- Customer access to another customer's data.
- Customer access to admin/product-owner functions.
- Product-owner access limited to permitted tickets.
- Admin access restricted to authorized admin accounts.

Use separate fixtures or credentials for customer, product owner, and admin roles when the implementation supports role-based access.

### 5.3 API and order tests

Extend `tests/test_api.py` for API behavior, and use the existing tool/router tests for relevant agent behavior.

Example test pattern (replace the route and response keys with the real contract):

```python
def test_chat_endpoint_returns_response(client):
    response = client.post(
        "/api/chat",
        json={
            "customer_id": "CUS-DEMO-001",
            "message": "Check my order status",
            "order_id": "ORD-DEMO-001",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data
```

Test valid data, missing fields, malformed requests, unknown IDs, and graceful error handling. Avoid asserting exact LLM wording unless the model output is mocked.

### 5.4 Ticket tests

Add ticket lifecycle tests to an existing relevant test module or create a focused file such as `tests/test_support_tickets.py` if no current test module covers the workflow.

Recommended coverage:

- Create a ticket with valid input.
- Reject missing or invalid fields.
- Retrieve a ticket for its owner.
- Deny access to another customer's ticket.
- Update ticket status as an authorized product owner.
- Reject invalid status values.
- Verify status persistence after a fresh read.
- Verify that the customer-facing ticket read returns the updated status.

These tests require the application's actual ticket routes, service methods, and fixtures. The example below is a workflow outline, not a drop-in test until those contracts are confirmed:

```python
def test_ticket_status_is_visible_to_customer(
    client,
    customer_headers,
    product_owner_headers,
    ticket_payload,
):
    # Create the ticket using the real customer endpoint.
    create_response = client.post(
        "<actual customer ticket creation route>",
        headers=customer_headers,
        json=ticket_payload,
    )
    assert create_response.status_code in (200, 201)

    ticket_id = create_response.json()["ticket_id"]

    # Update it using the real authorized product-owner endpoint.
    update_response = client.patch(
        f"<actual product-owner ticket update route>/{ticket_id}",
        headers=product_owner_headers,
        json={"status": "In Progress"},
    )
    assert update_response.status_code == 200

    # Read the same record through the customer-facing endpoint.
    customer_response = client.get(
        f"<actual customer ticket detail route>/{ticket_id}",
        headers=customer_headers,
    )
    assert customer_response.status_code == 200
    assert customer_response.json()["status"] == "In Progress"
```

Replace placeholder route strings with actual routes before running this test. Use fixtures backed by isolated test data so tests do not modify real demo records.

### 5.5 RAG, routing, and memory tests

Use the existing test modules:

- `test_intent_classifier.py`
- `test_router.py`
- `test_tools.py`
- `test_ingestion.py`
- `test_retrieval.py`
- `test_generation.py`
- `test_memory.py`

Test intent classification separately from tool execution and final response generation. For RAG, use fixed policy documents and mock model/provider calls where possible. This makes tests repeatable and avoids failures caused by model wording or external provider availability.

### 5.6 Damage report tests

Use `tests/test_damage_reports.py`.

Cover:

- Valid damage report submission.
- Missing required report fields.
- Invalid image content or unsupported format.
- Oversized image handling.
- Camera/report flow error handling as exposed by the API.
- Correct association between report, customer, and ticket.
- Access restrictions when retrieving a report or image.

Test camera permission behavior in frontend/browser testing; backend pytest cannot grant or deny browser camera permissions.

### 5.7 Storage tests

Use `tests/test_mongodb.py` and the storage-related fixtures already available.

Test JSON and MongoDB behavior separately where both are supported. Use temporary/test collections or isolated JSON fixtures. Ensure tests clean up their own records and do not rely on execution order.

---

## 6. Integration Testing

Integration tests verify that the system components work together.

| Test ID | Components | Expected result |
|---|---|---|
| INT-001 | React + FastAPI | Frontend requests reach the backend and display the response |
| INT-002 | Verification + authorization | Valid demo customer receives permitted access |
| INT-003 | LangChain + order data | Correct order information is retrieved |
| INT-004 | RAG + retrieval | Relevant policy material is found |
| INT-005 | RAG + generation | Answer is grounded in retrieved content |
| INT-006 | Customer UI + ticket API | Customer can create and view a ticket |
| INT-007 | Ticket service + storage | Ticket persists and can be retrieved |
| INT-008 | Product-owner UI + ticket API | Authorized product owner can process permitted tickets |
| INT-009 | Ticket update + customer tracking | Customer sees the latest stored status |
| INT-010 | Damage capture + report API | Captured image is linked to the appropriate damage report |
| INT-011 | Admin UI + ticket service | Admin actions update the shared ticket record |
| INT-012 | Evaluation UI/API + evaluation service | Evaluation results are saved and displayed correctly |

---

## 7. Security Testing

The application handles customer and ticket information. Test the following controls:

| Test | Expected result |
|---|---|
| Access protected endpoint without credentials | Access denied |
| Use invalid or expired credentials | Access denied |
| Customer requests another customer's order/ticket | Access denied |
| Customer attempts product-owner/admin action | Access denied |
| Product owner updates a ticket outside their permitted scope | Access denied |
| Submit malformed JSON | Safe validation error |
| Submit invalid or oversized input | Rejected or safely limited |
| Submit injection-like input | Input handled safely; no unauthorized query/action |
| Request sensitive payment information | Sensitive information is not exposed |
| Retrieve damage image as an unauthorized user | Access denied |
| Inspect error responses | No secrets, tokens, or unnecessary internal details |

The demo customer verification feature should not be treated as production-grade authentication. Production deployment requires suitable authentication, authorization, and session management.

---

## 8. Running the Tests

Run the full test suite from the repository root:

```bash
python -m pytest
```

Run the existing authorization tests:

```bash
python -m pytest tests/test_authorization.py
```

Run damage report tests:

```bash
python -m pytest tests/test_damage_reports.py
```

Run tool and routing tests:

```bash
python -m pytest tests/test_tools.py tests/test_router.py tests/test_intent_classifier.py
```

Run RAG tests:

```bash
python -m pytest tests/test_ingestion.py tests/test_retrieval.py tests/test_generation.py
```

Run evaluation tests:

```bash
python -m pytest tests/test_evaluation_phase1.py tests/test_evaluation_phase2.py tests/test_evaluation_phase3.py tests/test_evaluation_phase4.py tests/test_evaluation_phase5.py tests/test_evaluation_phase6.py tests/test_evaluation_phase7.py
```

Run with coverage:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

Generate an HTML coverage report:

```bash
python -m pytest --cov=app --cov-report=html
```

The HTML report is normally written to:

```text
htmlcov/index.html
```

Only run test paths that exist in the repository. Ticket/admin-specific test filenames in this guide are suggestions for new coverage, not names confirmed in the supplied tree.

---

## 9. Test Results Template

Record test execution results:

| Test ID | Test description | Expected result | Actual result | Status |
|---|---|---|---|---|
| AUTH-001 | Valid customer verification | Verification succeeds | | |
| AUTH-002 | Invalid customer verification | Request rejected | | |
| AUTH-003 | Missing customer ID | Validation error | | |
| SEC-001 | Unauthorized endpoint access | Access denied | | |
| ORDER-001 | Order status request | Correct retrieved information | | |
| ORDER-002 | Delivery delay request | Accurate delivery information | | |
| TICKET-001 | Create ticket | Ticket is created and persisted | | |
| TICKET-002 | Retrieve customer ticket | Permitted ticket is returned | | |
| TICKET-003 | Update ticket status | Status is updated and persisted | | |
| TICKET-004 | Status synchronization | Customer and product owner see the same status | | |
| DAMAGE-001 | Camera damage report | Captured image is associated with report | | |
| RAG-001 | Refund policy question | Grounded answer or safe fallback | | |
| ADMIN-001 | Admin ticket view | Authorized admin sees permitted tickets | | |
| ADMIN-002 | Admin ticket assignment | Assignment is persisted and visible to owner | | |

Use these statuses:

- **PASS**
- **FAIL**
- **BLOCKED**
- **NOT TESTED**

---

## 10. Acceptance Criteria

The application is ready for a demonstration when:

1. Customer verification follows the implemented access rules.
2. Invalid verification attempts are rejected.
3. Protected APIs enforce authentication and authorization.
4. Customers can retrieve only their permitted order information.
5. Chat responses use retrieved data and do not invent order details.
6. Customers can create and track support tickets.
7. Authorized product owners can retrieve and process permitted tickets.
8. Ticket updates are persisted and visible in the customer-facing view.
9. Admin actions, where implemented, operate on the same ticket records.
10. Damage reports use the supported camera capture flow and associate the captured image with the correct report.
11. RAG answers are grounded in available policy documents or provide a safe fallback.
12. Invalid requests and provider failures are handled safely.
13. Critical automated tests pass.

**Final testing objective:** Verify the complete support workflow from customer access through ticket processing and resolution, with accurate responses, shared ticket status, and appropriate access controls.
