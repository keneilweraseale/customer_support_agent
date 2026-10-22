# Customer Support AI Agent: Requirements Document

## 1. Project Overview

The goal is to build an AI-powered customer support agent that helps customers get answers quickly, check their orders, resolve common issues, and understand company policies.

The agent will use:

- **RAG (Retrieval-Augmented Generation)** to answer questions from approved company documents, FAQs, and policies.
- **Tools through MCP and/or LangChain** to retrieve current information from systems such as order management, delivery, payments, and inventory.
- **Both RAG and tools** when a question needs general product information and current data, or when customer reviews need to be retrieved from a review source.

## 2. Customer Needs and System Requirements

### 2.1 Functional Requirements

Functional requirements describe **what the system must do**.

| ID | Requirement | Type | Expected Result |
|---|---|---|---|
| FR-01 | Check order status | Tool | Show the current status of a customer's order. |
| FR-02 | Identify delivery delays | Tool | Show available delivery updates and report a delay when supported by the data. |
| FR-03 | Cancel an order | Tool | Check whether cancellation is allowed and cancel only after customer confirmation. |
| FR-04 | Check payment issues | Tool | Retrieve payment status and explain any available error information. |
| FR-05 | Check product availability | Tool | Show current stock information from the inventory source. |
| FR-06 | Explain refund policies | RAG | Answer questions using approved refund policies. |
| FR-07 | Explain shipping costs | RAG | Explain shipping charges using approved documents. |
| FR-08 | Explain exchanges | RAG | Explain exchange rules and conditions. |
| FR-09 | Explain returns | RAG | Provide return instructions from approved documents. |
| FR-10 | Provide contact information | RAG | Retrieve the company's approved contact details. |
| FR-11 | Explain warranties | RAG | Answer warranty questions using approved policies. |
| FR-12 | Explain how to order | RAG | Guide customers through the ordering process. |
| FR-13 | Answer product questions | RAG + Tools | Retrieve descriptions from documents and current prices or stock from connected systems, where available. |
| FR-14 | Answer review questions | RAG + Tools | Retrieve available customer reviews and, if supported, current review data from a review source. |
| FR-15 | Handle unknown questions | RAG + Agent | Admit when information is unavailable and direct the customer to human support when appropriate. |
| FR-16 | Protect customer accounts | Tools + Agent | Verify the customer's identity or authorization before showing private order information or making account changes. |

### 2.2 Non-Functional Requirements

Non-functional requirements describe **how well and how safely the system must operate**.

| ID | Requirement | What It Means |
|---|---|---|
| NFR-01 | Accuracy | Answers must be supported by retrieved documents or tool results. |
| NFR-02 | Security | Protect private customer information and restrict unauthorized actions. |
| NFR-03 | Performance | Return answers within an agreed response-time target. |
| NFR-04 | Reliability | Handle unavailable APIs and failed tool calls without crashing. |
| NFR-05 | Transparency | Tell customers when information is unavailable or cannot be verified. |
| NFR-06 | Usability | Use simple, clear English and make the conversation easy to follow. |
| NFR-07 | Maintainability | Allow policies, documents, and tools to be updated without rebuilding the entire agent. |
| NFR-08 | Testability | Provide test cases to check whether the agent answers correctly and uses the right tools. |
| NFR-09 | Privacy | Avoid exposing sensitive information in responses, logs, or error messages. |
| NFR-10 | Scalability | Design the system so additional tools and customer needs can be added later. |



