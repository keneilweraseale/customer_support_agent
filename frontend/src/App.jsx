import { useState } from "react";

import {
  confirmCancellation as sendCancellationConfirmation,
  sendChatMessage,
  verifyDemoCustomer,
} from "./api.js";
import ChatComposer from "./components/ChatComposer.jsx";
import ChatHeader from "./components/ChatHeader.jsx";
import MessageList from "./components/MessageList.jsx";

const welcomeMessage = {
  id: "welcome",
  role: "assistant",
  text: "Hello! How can I help you today? Please don’t share passwords or full payment-card details.",
};

function createConversationId() {
  return globalThis.crypto?.randomUUID?.() ?? `demo-${Date.now()}`;
}

function createMessageId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function routeStatus(route) {
  return {
    rag: "Policy information retrieved",
    order_tool: "Order information retrieved",
    delivery_tool: "Delivery information retrieved",
    payment_tool: "Payment information retrieved",
    product_tool: "Product information retrieved",
    review_tool: "Review information retrieved",
    rag_and_tool: "Policy and product information retrieved",
    cancellation_check: "Cancellation eligibility checked",
    clarification: "More information needed",
  }[route] ?? "Support information retrieved";
}

export default function App() {
  const [conversationId, setConversationId] = useState(createConversationId);
  const [messages, setMessages] = useState([welcomeMessage]);
  const [draft, setDraft] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [authorizationToken, setAuthorizationToken] = useState("");
  const [verificationMessage, setVerificationMessage] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  async function verifyCustomer() {
    if (!customerId.trim() || isVerifying || isLoading) return;
    setIsVerifying(true);
    setAuthorizationToken("");
    setVerificationMessage("");
    try {
      const result = await verifyDemoCustomer(customerId.trim());
      setAuthorizationToken(result.authorization_token);
      setVerificationMessage(
        "Demo token issued for this browser session; this is not real identity verification.",
      );
    } catch (error) {
      setVerificationMessage(error.message);
    } finally {
      setIsVerifying(false);
    }
  }

  async function submitMessage(text = draft) {
    const messageText = text.trim();
    if (!messageText || isLoading) return;

    setDraft("");
    setIsLoading(true);
    const userMessageId = createMessageId();
    const replyId = createMessageId();
    setMessages((current) => [
      ...current,
      { id: userMessageId, role: "user", text: messageText },
      {
        id: replyId,
        role: "assistant",
        text: "",
        pending: true,
      },
    ]);

    try {
      const response = await sendChatMessage({
        message: messageText,
        conversationId,
        authorizationToken,
      });
      setConversationId(response.conversation_id);
      setMessages((current) =>
        current.map((message) =>
          message.id === replyId
            ? {
                ...message,
                text: response.answer,
                pending: false,
                status: routeStatus(response.route),
                sources: response.sources ?? [],
                actions: (response.actions ?? []).map((action) =>
                  action.type === "confirm_cancellation"
                    ? { ...action, idempotency_key: createMessageId() }
                    : action,
                ),
                needsConfirmation: response.needs_confirmation === true,
                showCancellationPreview: response.needs_confirmation === true,
              }
            : message,
        ),
      );
    } catch (error) {
      if (error.status === 401) {
        setAuthorizationToken("");
        setVerificationMessage(error.message);
      }
      setMessages((current) =>
        current.map((message) =>
          message.id === replyId
            ? {
                ...message,
                text: error.message,
                pending: false,
                error: true,
                retryText: messageText,
              }
            : message,
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }

  function startNewChat() {
    setConversationId(createConversationId());
    setMessages([welcomeMessage]);
    setDraft("");
    setCustomerId("");
    setAuthorizationToken("");
    setVerificationMessage("");
  }

  async function confirmCancellation(
    messageId,
    orderId,
    confirmationToken,
    idempotencyKey,
  ) {
    if (!authorizationToken || isLoading) return;
    setIsLoading(true);
    try {
      await sendCancellationConfirmation({
        orderId,
        authorizationToken,
        confirmationToken,
        idempotencyKey,
      });
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? {
                ...message,
                text: `Order ${orderId} was cancelled successfully.`,
                status: "Cancellation confirmed",
                showCancellationPreview: false,
              }
            : message,
        ),
      );
    } catch (error) {
      if (error.status === 401) {
        setAuthorizationToken("");
        setVerificationMessage(error.message);
      }
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? {
                ...message,
                text: error.retryable
                  ? "I couldn't confirm the result. You can safely retry this confirmation."
                  : error.message,
                status: error.retryable
                  ? "Cancellation confirmation can be retried"
                  : "Cancellation was not completed",
                showCancellationPreview: error.retryable,
              }
            : message,
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }

  function dismissCancellationPreview() {
    setMessages((current) =>
      current.map((message) =>
        message.showCancellationPreview
          ? { ...message, showCancellationPreview: false }
          : message,
      ),
    );
  }

  return (
    <>
      <style>{responsiveStyles}</style>
      <main style={styles.page}>
        <section aria-label="Customer support chat" style={styles.panel}>
          <ChatHeader disabled={isLoading} onNewChat={startNewChat} />
          <MessageList
            isLoading={isLoading}
            messages={messages.filter((message) => !message.pending)}
            onKeepOrder={dismissCancellationPreview}
            onConfirmCancellation={confirmCancellation}
            onQuickAction={(action) => submitMessage(action)}
            onRetry={(text) => submitMessage(text)}
          />
          <footer style={styles.footer}>
            <label htmlFor="demo-customer-id" style={styles.customerLabel}>
              Demo customer ID (for order lookups; not identity verification)
            </label>
            <input
              autoComplete="off"
              id="demo-customer-id"
              onChange={(event) => {
                setCustomerId(event.target.value);
                setAuthorizationToken("");
                setVerificationMessage("");
              }}
              placeholder="Optional, e.g. CUS-DEMO-001"
              style={styles.customerInput}
              value={customerId}
            />
            <div style={styles.verificationRow}>
              <button
                disabled={!customerId.trim() || isVerifying || isLoading}
                onClick={verifyCustomer}
                style={styles.verifyButton}
                type="button"
              >
                {isVerifying ? "Verifying…" : authorizationToken ? "Verified" : "Verify demo ID"}
              </button>
                      {verificationMessage && (
                        <span
                          role="status"
                          style={{
                            ...styles.verificationStatus,
                            color: authorizationToken ? "#0F766E" : "#B91C1C",
                          }}
                        >
                          {verificationMessage}
                        </span>
              )}
            </div>
            <p style={styles.demoWarning}>
              Demo only: these fictional IDs are not proof of real identity. Never use real customer records.
            </p>
            <ChatComposer
              disabled={isLoading}
              onChange={setDraft}
              onSubmit={() => submitMessage()}
              value={draft}
            />
            <p style={styles.privacy}>
              For your safety, don’t share passwords or full payment-card details.
            </p>
          </footer>
        </section>
      </main>
    </>
  );
}

const styles = {
  page: {
    alignItems: "center",
    background: "#F5F7FA",
    boxSizing: "border-box",
    display: "flex",
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    justifyContent: "center",
    minHeight: "100vh",
    padding: 24,
  },
  panel: {
    background: "#FFFFFF",
    border: "1px solid #E2E8F0",
    borderRadius: 20,
    boxShadow: "0 14px 45px rgba(15, 23, 42, 0.08)",
    display: "flex",
    flexDirection: "column",
    height: "min(820px, calc(100vh - 48px))",
    maxWidth: 980,
    overflow: "hidden",
    width: "100%",
  },
  footer: { borderTop: "1px solid #E2E8F0", padding: "16px 22px 13px" },
  customerLabel: { color: "#475569", display: "block", fontSize: 12, marginBottom: 5 },
  customerInput: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 8,
    color: "#1F2937",
    font: "inherit",
    fontSize: 13,
    marginBottom: 10,
    maxWidth: 300,
    outlineColor: "#1D4ED8",
    padding: "8px 10px",
    width: "100%",
  },
  verificationRow: { alignItems: "center", display: "flex", flexWrap: "wrap", gap: 10 },
  verifyButton: {
    background: "#1D4ED8",
    border: 0,
    borderRadius: 8,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    fontWeight: 600,
    padding: "8px 12px",
  },
  verificationStatus: { color: "#0F766E", fontSize: 12 },
  demoWarning: { color: "#92400E", fontSize: 11, margin: "7px 0 10px" },
  privacy: { color: "#64748B", fontSize: 12, margin: "10px 2px 0" },
};

const responsiveStyles = `
  * { box-sizing: border-box; }
  body { margin: 0; min-width: 320px; }
  button:focus-visible, textarea:focus-visible {
    outline: 3px solid #60A5FA !important;
    outline-offset: 2px;
  }
  button:disabled { cursor: not-allowed !important; opacity: 0.65; }
  @media (max-width: 600px) {
    main { padding: 0 !important; }
    main > section { border-radius: 0 !important; height: 100dvh !important; }
    header { padding: 16px !important; }
    footer { padding: 12px 14px !important; }
  }
`;
