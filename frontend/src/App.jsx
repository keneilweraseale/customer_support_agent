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
const conversationStorageKey = "customer-support-conversation-id";

function createConversationId() {
  return globalThis.crypto?.randomUUID?.() ?? `demo-${Date.now()}`;
}

function getConversationId() {
  return sessionStorage.getItem(conversationStorageKey) || createConversationId();
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
    conversation_memory: "Earlier conversation recalled",
  }[route] ?? "Support information retrieved";
}

export default function App() {
  const [conversationId, setConversationId] = useState(getConversationId);
  const [messages, setMessages] = useState([welcomeMessage]);
  const [draft, setDraft] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const [authorizationToken, setAuthorizationToken] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isDamageReportOpen, setIsDamageReportOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  async function signIn(event) {
    event.preventDefault();
    if (!email.trim() || !password || isSigningIn || isLoading) return;
    setIsSigningIn(true);
    setLoginMessage("");
    try {
      const result = await sendLogin(email.trim(), password);
      setAuthorizationToken(result.authorization_token);
      setPassword("");
      setIsPasswordVisible(false);
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
      sessionStorage.setItem(conversationStorageKey, response.conversation_id);
      setConversationId(response.conversation_id);
      setMessages((current) =>
        current.map((message) =>
          message.id === replyId
            ? {
                ...message,
                text: response.answer,
                pending: false,
                status: response.needs_human_support
                  ? "Support ticket created"
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
    const newConversationId = createConversationId();
    sessionStorage.setItem(conversationStorageKey, newConversationId);
    setConversationId(newConversationId);
    setMessages([welcomeMessage]);
    setDraft("");
    setLoginMessage("");
    setIsDamageReportOpen(false);
  }

  function signOut() {
    sessionStorage.removeItem(conversationStorageKey);
    setAuthorizationToken("");
    setPassword("");
    setMessages([welcomeMessage]);
    setDraft("");
    setLoginMessage("");
    setConversationId(createConversationId());
    setIsDamageReportOpen(false);
    setIsSidebarOpen(false);
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
    try {
      await sendSupportTicketMessage({
        ticketId,
        message,
        authorizationToken,
      });
    } catch (error) {
      if (error.status === 401) {
        setAuthorizationToken("");
        setLoginMessage(error.message);
      }
      throw error;
    }
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
    <div className={`app-shell${authorizationToken ? "" : " app-shell-public"}`}>
      {authorizationToken && (
        <>
          <ChatHeader
            authenticated
            disabled={isLoading}
            isDamageReportOpen={isDamageReportOpen}
            onDamageReport={() => setIsDamageReportOpen(true)}
            onLogout={signOut}
            onNewChat={startNewChat}
            onClose={() => setIsSidebarOpen(false)}
            open={isSidebarOpen}
          />
          {isSidebarOpen && (
            <button
              aria-label="Close navigation"
              className="sidebar-backdrop"
              onClick={() => setIsSidebarOpen(false)}
              type="button"
            />
          )}
        </>
      )}
      <main className={`workspace${authorizationToken ? "" : " workspace-public"}`}>
        {authorizationToken && (
          <header className="workspace-header">
            <div className="workspace-heading">
              <button
                aria-controls="primary-sidebar"
                aria-expanded={isSidebarOpen}
                aria-label={isSidebarOpen ? "Close navigation" : "Open navigation"}
                className="mobile-menu-toggle"
                onClick={() => setIsSidebarOpen((open) => !open)}
                type="button"
              >
                <svg
                  aria-hidden="true"
                  fill="none"
                  height="21"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeWidth="1.8"
                  viewBox="0 0 24 24"
                  width="21"
                >
                  {isSidebarOpen ? <path d="m6 6 12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
                </svg>
              </button>
              <div>
                <p className="workspace-eyebrow">SUPPORT WORKSPACE</p>
                <h1 className="workspace-title">
                  {isDamageReportOpen ? "Damage report" : "Customer support"}
                </h1>
                <p className="workspace-subtitle">
                  {isDamageReportOpen
                    ? "Tell us what happened and our team will review it."
                    : "Chat with us about orders, delivery, and more."}
                </p>
              </div>
            </div>
            <div className="availability-indicator">
              <span aria-hidden="true" />
              Secure support
            </div>
          </header>
        )}
        <section
          aria-label={
            isDamageReportOpen
              ? "Report a damaged item"
              : authorizationToken
                ? "Customer support chat"
                : "Sign in to customer support"
          }
          className={authorizationToken ? "chat-panel authenticated-panel" : "chat-panel sign-in-panel"}
          style={{
            ...styles.panel,
            ...(!authorizationToken ? styles.publicPanel : {}),
          }}
        >
          {!authorizationToken ? (
            <form className="login-form" onSubmit={signIn} style={styles.loginForm}>
              <div aria-hidden="true" style={styles.loginIllustration}>
                <span>✦</span>
              </div>
              <p style={styles.loginEyebrow}>PERSONALIZED SUPPORT</p>
              <h2 style={styles.loginTitle}>How can we help?</h2>
              <p style={styles.loginDescription}>
                Sign in to get help with orders, deliveries, payments, and more.
              </p>
              <label htmlFor="customer-email" style={styles.loginLabel}>Email</label>
              <input
                autoComplete="username"
                aria-describedby={loginMessage ? "login-error" : undefined}
                aria-invalid={loginMessage ? "true" : undefined}
                id="customer-email"
                onChange={(event) => {
                  setEmail(event.target.value);
                  setLoginMessage("");
                }}
                required
                style={styles.loginInput}
                type="email"
                value={email}
              />
              <label htmlFor="customer-password" style={styles.loginLabel}>Password</label>
              <div className="password-field">
                <input
                  autoComplete="current-password"
                  aria-describedby={loginMessage ? "login-error" : undefined}
                  aria-invalid={loginMessage ? "true" : undefined}
                  id="customer-password"
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setLoginMessage("");
                  }}
                  required
                  style={styles.loginInput}
                  type={isPasswordVisible ? "text" : "password"}
                  value={password}
                />
                <button
                  aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                  aria-pressed={isPasswordVisible}
                  className="password-toggle"
                  onClick={() => setIsPasswordVisible((visible) => !visible)}
                  type="button"
                >
                  {isPasswordVisible ? "Hide" : "Show"}
                </button>
              </div>
              <button
                aria-busy={isSigningIn}
                disabled={!email.trim() || !password || isSigningIn}
                style={styles.loginButton}
                type="submit"
              >
                {isSigningIn ? "Signing in…" : <>Sign in <span aria-hidden="true">→</span></>}
              </button>
              {loginMessage && <p aria-live="polite" id="login-error" role="alert" style={styles.loginError}>{loginMessage}</p>}
              <p style={styles.loginPrivacy}>🔒 Your account details stay private and secure.</p>
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
    </div>
  );
}

const styles = {
  panel: {
    background: "var(--color-surface)",
    border: 0,
    borderRadius: 0,
    boxShadow: "none",
    display: "flex",
    flex: "1 1 auto",
    flexDirection: "column",
    overflow: "hidden",
    minHeight: 0,
    width: "100%",
  },
  publicPanel: {
    height: "100dvh",
    minHeight: "100dvh",
  },
  footer: {
    background: "var(--color-surface)",
    borderTop: "1px solid var(--color-border)",
    padding: "18px 28px 16px",
  },
  loginForm: {
    alignSelf: "center",
    display: "flex",
    flex: "1 1 auto",
    flexDirection: "column",
    justifyContent: "center",
    maxWidth: 460,
    minHeight: 0,
    padding: "36px 32px 42px",
    width: "100%",
  },
  loginIllustration: {
    alignItems: "center",
    alignSelf: "center",
    background: "linear-gradient(145deg, #dff3ef, #eef7f5)",
    border: "1px solid #d5ebe6",
    borderRadius: 22,
    color: "var(--color-primary)",
    display: "flex",
    fontSize: 28,
    height: 66,
    justifyContent: "center",
    marginBottom: 22,
    width: 66,
  },
  loginEyebrow: {
    color: "var(--color-primary)",
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: "0.14em",
    margin: "0 0 9px",
    textAlign: "center",
  },
  loginTitle: { color: "var(--color-ink)", fontSize: 29, letterSpacing: "-0.04em", margin: "0 0 9px", textAlign: "center" },
  loginDescription: { color: "var(--color-muted)", fontSize: 14, lineHeight: 1.65, margin: "0 0 26px", textAlign: "center" },
  loginLabel: { color: "var(--color-text)", fontSize: 12, fontWeight: 700, margin: "0 0 7px" },
  loginInput: {
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderRadius: 12,
    color: "var(--color-ink)",
    font: "inherit",
    fontSize: 14,
    marginBottom: 18,
    padding: "13px 14px",
    width: "100%",
  },
  loginButton: {
    alignItems: "center",
    background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))",
    border: 0,
    borderRadius: 12,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 700,
    justifyContent: "center",
    marginTop: 6,
    padding: "14px 16px",
  },
  loginError: { color: "var(--color-danger)", fontSize: 13, margin: "14px 0 0" },
  loginPrivacy: { color: "#8a9a9c", fontSize: 11, margin: "22px 0 0", textAlign: "center" },
  privacy: { color: "#8a9a9c", fontSize: 11, margin: "10px 2px 0", textAlign: "center" },
};
