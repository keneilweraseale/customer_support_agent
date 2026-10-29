import { useState } from "react";

import {
  confirmCancellation as sendCancellationConfirmation,
  recordCancellationDecision as sendCancellationDecision,
  login as sendLogin,
  sendChatMessage,
  sendSupportTicketMessage,
} from "./api.js";
import DamageReport from "./components/DamageReport.jsx";
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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authorizationToken, setAuthorizationToken] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isDamageReportOpen, setIsDamageReportOpen] = useState(false);

  async function signIn(event) {
    event.preventDefault();
    if (!email.trim() || !password || isSigningIn || isLoading) return;
    setIsSigningIn(true);
    setLoginMessage("");
    try {
      const result = await sendLogin(email.trim(), password);
      setAuthorizationToken(result.authorization_token);
      setPassword("");
    } catch (error) {
      setLoginMessage(error.message);
    } finally {
      setIsSigningIn(false);
    }
  }

  async function submitMessage(text = draft) {
    const messageText = text.trim();
    if (!messageText || !authorizationToken || isLoading) return;

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
                status: response.needs_human_support
                  ? "Escalated to human support"
                  : routeStatus(response.route),
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
        setLoginMessage(error.message);
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

  function handleQuickAction(action) {
    if (action === "Report Damaged Item") {
      setIsDamageReportOpen(true);
      return;
    }
    void submitMessage(action);
  }

  function startNewChat() {
    setIsDamageReportOpen(false);
    setConversationId(createConversationId());
    setMessages([welcomeMessage]);
    setDraft("");
    setLoginMessage("");
  }

  function signOut() {
    setIsDamageReportOpen(false);
    setAuthorizationToken("");
    setPassword("");
    setMessages([welcomeMessage]);
    setDraft("");
    setLoginMessage("");
    setConversationId(createConversationId());
  }

  async function confirmCancellation(
    messageId,
    orderId,
    confirmationToken,
    idempotencyKey,
    reasonCode,
    reasonText,
  ) {
    if (!authorizationToken || isLoading) return;
    setIsLoading(true);
    try {
      await sendCancellationConfirmation({
        orderId,
        authorizationToken,
        confirmationToken,
        idempotencyKey,
        reasonCode,
        reasonText,
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
        setLoginMessage(error.message);
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

  async function sendTicketMessage(ticketId, message) {
    if (!authorizationToken) {
      throw new Error("Your session has expired. Please sign in again.");
    }
    await sendSupportTicketMessage({
      ticketId,
      message,
      authorizationToken,
    });
  }

  async function recordCancellationDecision(
    messageId,
    orderId,
    confirmationToken,
    outcome,
    reasonCode,
    reasonText,
    idempotencyKey,
  ) {
    if (!authorizationToken || isLoading) return;
    setIsLoading(true);
    try {
      await sendCancellationDecision({
        orderId,
        authorizationToken,
        confirmationToken,
        idempotencyKey,
        outcome,
        reasonCode,
        reasonText,
      });
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? {
                ...message,
                text:
                  outcome === "declined"
                    ? `Cancellation declined. Order ${orderId} was not changed.`
                    : `Cancellation request withdrawn. Order ${orderId} was not changed.`,
                status: `Cancellation ${outcome}`,
                showCancellationPreview: false,
              }
            : message,
        ),
      );
    } catch (error) {
      if (error.status === 401) {
        setAuthorizationToken("");
        setLoginMessage(error.message);
      }
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? {
                ...message,
                text: error.message,
                status: "Cancellation decision was not recorded",
                showCancellationPreview: true,
              }
            : message,
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <>
      <style>{responsiveStyles}</style>
      <main style={styles.page}>
        <section aria-label="Customer support chat" style={styles.panel}>
          <ChatHeader
            authenticated={Boolean(authorizationToken)}
            disabled={isLoading}
            onDamageReport={() => setIsDamageReportOpen(true)}
            onLogout={signOut}
            onNewChat={startNewChat}
          />
          {!authorizationToken ? (
            <form onSubmit={signIn} style={styles.loginForm}>
              <h2 style={styles.loginTitle}>Sign in to customer support</h2>
              <p style={styles.loginDescription}>
                Sign in to ask about your orders, deliveries, payments, or cancellations.
              </p>
              <label htmlFor="customer-email" style={styles.loginLabel}>Email</label>
              <input
                autoComplete="username"
                id="customer-email"
                onChange={(event) => setEmail(event.target.value)}
                required
                style={styles.loginInput}
                type="email"
                value={email}
              />
              <label htmlFor="customer-password" style={styles.loginLabel}>Password</label>
              <input
                autoComplete="current-password"
                id="customer-password"
                onChange={(event) => setPassword(event.target.value)}
                required
                style={styles.loginInput}
                type="password"
                value={password}
              />
              <button
                disabled={!email.trim() || !password || isSigningIn}
                style={styles.loginButton}
                type="submit"
              >
                {isSigningIn ? "Signing in…" : "Sign in"}
              </button>
              {loginMessage && <p role="status" style={styles.loginError}>{loginMessage}</p>}
            </form>
          ) : (
            <>
              {isDamageReportOpen ? (
                <DamageReport
                  authorizationToken={authorizationToken}
                  onBack={() => setIsDamageReportOpen(false)}
                />
              ) : (
                <>
                  <MessageList
                    isLoading={isLoading}
                    messages={messages.filter((message) => !message.pending)}
                    onCancellationDecision={recordCancellationDecision}
                    onConfirmCancellation={confirmCancellation}
                    onQuickAction={handleQuickAction}
                    onRetry={(text) => submitMessage(text)}
                    onSupportTicketMessage={sendTicketMessage}
                  />
                  <footer style={styles.footer}>
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
                </>
              )}
            </>
          )}
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
  loginForm: {
    alignSelf: "center",
    display: "flex",
    flexDirection: "column",
    maxWidth: 420,
    padding: 28,
    width: "100%",
  },
  loginTitle: { color: "#1F2937", fontSize: 22, margin: "0 0 8px" },
  loginDescription: { color: "#64748B", fontSize: 14, lineHeight: 1.5, margin: "0 0 20px" },
  loginLabel: { color: "#475569", fontSize: 13, margin: "0 0 6px" },
  loginInput: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 8,
    color: "#1F2937",
    font: "inherit",
    fontSize: 14,
    marginBottom: 14,
    outlineColor: "#1D4ED8",
    padding: "10px 12px",
    width: "100%",
  },
  loginButton: {
    background: "#1D4ED8",
    border: 0,
    borderRadius: 8,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 600,
    marginTop: 4,
    padding: "10px 12px",
  },
  loginError: { color: "#B91C1C", fontSize: 13, margin: "14px 0 0" },
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
