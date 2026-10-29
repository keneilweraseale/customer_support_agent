
import { useEffect, useRef, useState } from "react";
import CancellationConfirmation from "./CancellationConfirmation.jsx";

export default function MessageList({
  messages,
  onRetry,
  onQuickAction,
  onConfirmCancellation,
  onCancellationDecision,
  onSupportTicketMessage,
  isLoading,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    const motionPreference = globalThis.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    );
    bottomRef.current?.scrollIntoView({
      behavior: motionPreference?.matches ? "auto" : "smooth",
      block: "end",
    });
  }, [messages, isLoading]);

  return (
    <div aria-label="Conversation" className="chat-scroller" style={styles.scroller}>
      <div
        aria-live="polite"
        aria-relevant="additions text"
        role="log"
        style={styles.list}
      >
        {messages.map((message) => (
          <div
            key={message.id}
            style={{
              ...styles.row,
              justifyContent:
                message.role === "user" ? "flex-end" : "flex-start",
              animation: "rise-in 280ms ease both",
            }}
          >
            <div
              style={{
                ...styles.bubble,
                ...(message.role === "user"
                  ? styles.userBubble
                  : styles.assistantBubble),
              }}
            >
              {message.text}

              {message.actions?.some(
                (action) => action.type === "support_ticket"
              ) && (
                <SupportTicketActions
                  action={message.actions.find(
                    (item) => item.type === "support_ticket"
                  )}
                  onSend={onSupportTicketMessage}
                />
              )}

              {message.error && (
                <button
                  onClick={() => onRetry(message.retryText)}
                  style={styles.retry}
                  type="button"
                >
                  Retry
                </button>
              )}

              {message.showCancellationPreview && (
                <CancellationConfirmation
                  onDecision={(
                    orderId,
                    confirmationToken,
                    outcome,
                    reasonCode,
                    reasonText
                  ) =>
                    onCancellationDecision(
                      message.id,
                      orderId,
                      confirmationToken,
                      outcome,
                      reasonCode,
                      reasonText,
                      message.actions?.[0]?.idempotency_key
                    )
                  }
                  onConfirm={(
                    orderId,
                    confirmationToken,
                    reasonCode,
                    reasonText
                  ) =>
                    onConfirmCancellation(
                      orderId,
                      confirmationToken,
                      message.actions?.[0]?.idempotency_key,
                      reasonCode,
                      reasonText
                    )
                  }
                  messageId={message.id}
                  orderId={message.actions?.[0]?.order_id}
                  confirmationToken={
                    message.actions?.[0]?.confirmation_token
                  }
                  disabled={isLoading}
                />
              )}

              {message.role === "assistant" && message.status && (
                <div style={styles.status}>{message.status}</div>
              )}

              {message.role === "assistant" &&
                message.sources?.length > 0 && (
                  <div style={styles.sources}>
                    <strong>Sources:</strong>{" "}
                    {message.sources
                      .map((source) => source.title)
                      .join(", ")}
                  </div>
                )}
            </div>
          </div>
        ))}

        {messages.length === 1 && (
          <div aria-label="Quick actions" style={styles.quickActions}>
            {quickActions.map((action) => (
              <button
                key={action.label}
                onClick={() => onQuickAction(action.prompt)}
                style={styles.chip}
                type="button"
              >
                {action.label}
              </button>
            ))}
          </div>
        )}

        {isLoading && (
          <div
            aria-label="Checking that for you"
            role="status"
            style={styles.row}
          >
            <div
              style={{
                ...styles.bubble,
                ...styles.assistantBubble,
              }}
            >
              <span aria-hidden="true" style={styles.loadingDots}>
                <i style={styles.loadingDot} />
                <i style={{ ...styles.loadingDot, animationDelay: "120ms" }} />
                <i style={{ ...styles.loadingDot, animationDelay: "240ms" }} />
              </span>
              I’m checking that for you…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function SupportTicketActions({ action, onSend }) {
  const [message, setMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  async function submitMessage(event) {
    event.preventDefault();
    const text = message.trim();
    if (!text || isSending) return;

    setIsSending(true);
    setError("");
    try {
      await onSend(action.ticket_id, text);
      setMessage("");
      setSent(true);
    } catch (sendError) {
      setError(sendError.message);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section aria-label="Contact human support" style={styles.supportActions}>
      <strong>Ticket {action.ticket_id}</strong>
      <p style={styles.supportDescription}>
        A ticket does not notify an agent yet. Send your message below to reach our support team.
      </p>
      <form className="ticket-message-form" onSubmit={submitMessage}>
        <label htmlFor={`ticket-message-${action.ticket_id}`}>
          Send more details
        </label>
        <textarea
          disabled={isSending}
          id={`ticket-message-${action.ticket_id}`}
          maxLength={2000}
          onChange={(event) => {
            setMessage(event.target.value);
            setSent(false);
          }}
          placeholder="Describe what you still need help with"
          value={message}
        />
        {error && (
          <p className="ticket-message-error" role="alert">
            {error}
          </p>
        )}
        {sent && (
          <p className="ticket-message-success" role="status">
            Your message was sent to support.
          </p>
        )}
        <button
          className="ticket-message-submit"
          disabled={!message.trim() || isSending}
          type="submit"
        >
          {isSending ? "Sending…" : "Send to support"}
        </button>
      </form>
    </section>
  );
}

const quickActions = [
  { label: "Track an order", prompt: "I need to track an order" },
  { label: "Delivery help", prompt: "I have a delivery issue" },
  { label: "Payment issue", prompt: "I have a payment issue" },
  { label: "Find a product", prompt: "I need help finding a product" },
  { label: "Returns & refunds", prompt: "What is your returns and refunds policy?" },
  { label: "Warranty", prompt: "What is your warranty policy?" },
  { label: "Report Damaged Item", prompt: "Report Damaged Item" },
  { label: "Contact support", prompt: "I want to contact support" },
];

const styles = {
  scroller: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    padding: "27px 28px",
    scrollBehavior: "smooth",
  },

  list: {
    margin: "0 auto",
    maxWidth: 720,
  },

  row: {
    display: "flex",
    margin: "17px 0",
  },

  bubble: {
    borderRadius: 19,
    fontSize: 14,
    lineHeight: 1.7,
    maxWidth: "min(88%, 620px)",
    overflowWrap: "anywhere",
    padding: "14px 17px",
    whiteSpace: "pre-wrap",
  },

  userBubble: {
    background: "linear-gradient(145deg, var(--color-primary), var(--color-primary-dark))",
    borderBottomRightRadius: 6,
    color: "#FFFFFF",
    boxShadow: "0 6px 16px rgba(22, 139, 126, .13)",
  },

  assistantBubble: {
    background: "#fff",
    border: "1px solid #e8efef",
    borderBottomLeftRadius: 6,
    boxShadow: "0 4px 14px rgba(30, 65, 68, .035)",
    color: "var(--color-text)",
  },

  status: {
    color: "var(--color-primary)",
    fontSize: 11,
    fontWeight: 600,
    marginTop: 10,
  },

  sources: {
    borderTop: "1px solid #edf2f2",
    color: "#77888a",
    fontSize: 11,
    marginTop: 12,
    paddingTop: 10,
  },

  retry: {
    background: "transparent",
    border: 0,
    color: "var(--color-primary-dark)",
    cursor: "pointer",
    display: "block",
    font: "inherit",
    fontSize: 13,
    fontWeight: 700,
    marginTop: 8,
    padding: 0,
    textDecoration: "underline",
  },

  supportActions: {
    borderTop: "1px solid #edf2f2",
    color: "#476164",
    fontSize: 13,
    marginTop: 12,
    paddingTop: 10,
  },

  quickActions: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    margin: "20px 0 26px",
  },

  chip: {
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderRadius: 12,
    color: "#496164",
    cursor: "pointer",
    font: "inherit",
    fontSize: 12,
    fontWeight: 600,
    padding: "10px 13px",
    boxShadow: "0 3px 9px rgba(30,65,68,.025)",
  },

  loadingDots: {
    display: "inline-flex",
    gap: 3,
    marginRight: 9,
    verticalAlign: "middle",
  },
  loadingDot: {
    background: "var(--color-primary)",
    borderRadius: "50%",
    display: "inline-block",
    height: 6,
    width: 6,
    animation: "soft-pulse 1.1s ease-in-out infinite",
  },
};
