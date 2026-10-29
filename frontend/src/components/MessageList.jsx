
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
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, isLoading]);

  return (
    <div aria-label="Conversation" style={styles.scroller}>
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
                (action) =>
                  action.type === "support_ticket" ||
                  action.type === "support_ticket_message"
              ) && (
                <SupportTicketActions
                  action={message.actions.find(
                    (item) =>
                      item.type === "support_ticket" ||
                      item.type === "support_ticket_message"
                  )}
                  disabled={isLoading}
                  messageId={message.id}
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
                key={action}
                onClick={() => onQuickAction(action)}
                style={styles.chip}
                type="button"
              >
                {action}
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
              <span style={styles.loadingDot} />
              Checking that for you…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function SupportTicketActions({ action, disabled, messageId, onSend }) {
  const [formOpen, setFormOpen] = useState(
    action.type === "support_ticket_message",
  );
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);

  async function submitMessage(event) {
    event.preventDefault();
    const text = message.trim();
    if (!text || sending || disabled) return;
    setSending(true);
    setError("");
    try {
      await onSend(action.ticket_id, text);
      setSent(true);
      setMessage("");
      setFormOpen(false);
    } catch (sendError) {
      setError(sendError.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <section
      aria-label="Support ticket"
      style={styles.supportActions}
    >
      <strong>Support ticket: {action.ticket_id}</strong>
      <p style={{ margin: "8px 0 0" }}>
        {sent
          ? "Your additional message was sent to support."
          : "Your request has been saved as a ticket. Add details below to email the team."}
      </p>
      {formOpen ? (
        <form onSubmit={submitMessage} style={styles.ticketForm}>
          <label htmlFor={`ticket-message-${messageId}`}>
            What would you like the support team to know?
          </label>
          <textarea
            disabled={disabled || sending}
            id={`ticket-message-${messageId}`}
            onChange={(event) => setMessage(event.target.value)}
            maxLength={2000}
            required
            rows={4}
            style={styles.ticketTextarea}
            value={message}
          />
          {error && (
            <p role="alert" style={styles.ticketError}>
              {error}
            </p>
          )}
          <button
            disabled={disabled || sending || !message.trim()}
            style={styles.ticketButton}
            type="submit"
          >
            {sending ? "Sending…" : "Send to support"}
          </button>
        </form>
      ) : (
        <button
          disabled={disabled}
          onClick={() => setFormOpen(true)}
          style={styles.ticketLink}
          type="button"
        >
          {sent ? "Send another message" : "Add details to this ticket"}
        </button>
      )}
    </section>
  );
}

const quickActions = [
  "Check an order",
  "Delivery issue",
  "Payment issue",
  "Returns & refunds",
  "Product availability",
  "Contact support",
];

const styles = {
  scroller: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    padding: "24px 20px",
  },

  list: {
    margin: "0 auto",
    maxWidth: 760,
  },

  row: {
    display: "flex",
    margin: "14px 0",
  },

  bubble: {
    borderRadius: 18,
    fontSize: 15,
    lineHeight: 1.6,
    maxWidth: "min(88%, 600px)",
    overflowWrap: "anywhere",
    padding: "13px 16px",
    whiteSpace: "pre-wrap",
  },

  userBubble: {
    background: "#1D4ED8",
    borderBottomRightRadius: 5,
    color: "#FFFFFF",
  },

  assistantBubble: {
    background: "#FFFFFF",
    border: "1px solid #E2E8F0",
    borderBottomLeftRadius: 5,
    color: "#1F2937",
  },

  status: {
    color: "#0F766E",
    fontSize: 12,
    fontWeight: 600,
    marginTop: 8,
  },

  sources: {
    borderTop: "1px solid #E2E8F0",
    color: "#475569",
    fontSize: 12,
    marginTop: 10,
    paddingTop: 8,
  },

  retry: {
    background: "transparent",
    border: 0,
    color: "#1D4ED8",
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
    borderTop: "1px solid #E2E8F0",
    color: "#334155",
    fontSize: 13,
    marginTop: 12,
    paddingTop: 10,
  },

  ticketForm: {
    display: "grid",
    gap: 8,
    marginTop: 12,
  },

  ticketTextarea: {
    border: "1px solid #CBD5E1",
    borderRadius: 8,
    color: "#1F2937",
    font: "inherit",
    fontSize: 13,
    padding: 9,
    resize: "vertical",
  },

  ticketButton: {
    background: "#1D4ED8",
    border: 0,
    borderRadius: 7,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    fontWeight: 600,
    justifySelf: "start",
    padding: "8px 12px",
  },

  ticketLink: {
    background: "transparent",
    border: 0,
    color: "#1D4ED8",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    fontWeight: 600,
    marginTop: 8,
    padding: 0,
  },

  ticketError: {
    color: "#B91C1C",
    fontSize: 12,
    margin: 0,
  },

  quickActions: {
    display: "flex",
    flexWrap: "wrap",
    gap: 9,
    margin: "18px 0 24px",
  },

  chip: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 999,
    color: "#334155",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    padding: "9px 13px",
  },

  loadingDot: {
    background: "#0F766E",
    borderRadius: "50%",
    display: "inline-block",
    height: 8,
    marginRight: 8,
    width: 8,
  },
};
