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
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isLoading]);

  return (
    <div aria-label="Conversation" style={styles.scroller}>
      <div aria-live="polite" aria-relevant="additions text" role="log" style={styles.list}>
        {messages.map((message) => (
          <div
            key={message.id}
            style={{
              ...styles.row,
              justifyContent: message.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            <div
              style={{
                ...styles.bubble,
                ...(message.role === "user" ? styles.userBubble : styles.assistantBubble),
              }}
            >
              {message.text}
              {message.actions?.find((action) => action.type === "support_ticket") && (
                <SupportTicketActions
                  action={message.actions.find((item) => item.type === "support_ticket")}
                  onSubmit={onSupportTicketMessage}
                />
              )}
              {message.error && (
                <button onClick={() => onRetry(message.retryText)} style={styles.retry} type="button">
                  Retry
                </button>
              )}
              {message.showCancellationPreview && (
                <CancellationConfirmation
                  onDecision={(orderId, confirmationToken, outcome, reasonCode, reasonText) =>
                    onCancellationDecision(
                      message.id,
                      orderId,
                      confirmationToken,
                      outcome,
                      reasonCode,
                      reasonText,
                      message.actions?.[0]?.idempotency_key,
                    )
                  }
                  onConfirm={(orderId, confirmationToken, reasonCode, reasonText) =>
                    onConfirmCancellation(
                      message.id,
                      orderId,
                      confirmationToken,
                      message.actions?.[0]?.idempotency_key,
                      reasonCode,
                      reasonText,
                    )
                  }
                  messageId={message.id}
                  orderId={message.actions?.[0]?.order_id}
                  confirmationToken={message.actions?.[0]?.confirmation_token}
                  disabled={isLoading}
                />
              )}
              {message.role === "assistant" && message.status && (
                <div style={styles.status}>{message.status}</div>
              )}
              {message.role === "assistant" && message.sources?.length > 0 && (
                <div style={styles.sources}>
                  <strong>Sources:</strong>{" "}
                  {message.sources.map((source) => source.title).join(", ")}
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
          <div aria-label="Checking that for you" role="status" style={styles.row}>
            <div style={{ ...styles.bubble, ...styles.assistantBubble }}>
              <span style={styles.loadingDot} /> Checking that for you…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
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

function SupportTicketActions({ action, onSubmit }) {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [isSending, setIsSending] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const messageText = message.trim();
    if (!messageText || isSending) return;
    setIsSending(true);
    setStatus("");
    try {
      await onSubmit(action.ticket_id, messageText);
      setMessage("");
      setStatus("Your message was sent to our support team.");
    } catch (error) {
      setStatus(error.message);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section aria-label="Contact human support" style={styles.supportActions}>
      <strong>Ticket {action.ticket_id}</strong>
      <p style={styles.supportDescription}>
        Tell us more about the problem and we’ll send it directly to our support team.
      </p>
      <form onSubmit={submit} style={styles.supportForm}>
        <label htmlFor={`support-message-${action.ticket_id}`} style={styles.supportLabel}>
          Your message
        </label>
        <textarea
          id={`support-message-${action.ticket_id}`}
          maxLength={2000}
          onChange={(event) => setMessage(event.target.value)}
          required
          rows={4}
          style={styles.supportInput}
          value={message}
        />
        <button
          disabled={!message.trim() || isSending}
          style={styles.supportButton}
          type="submit"
        >
          {isSending ? "Sending…" : "Send to support"}
        </button>
      </form>
      {status && <p aria-live="polite" role="status" style={styles.supportStatus}>{status}</p>}
    </section>
  );
}

const styles = {
  scroller: { flex: 1, minHeight: 0, overflowY: "auto", padding: "24px 20px" },
  list: { margin: "0 auto", maxWidth: 760 },
  row: { display: "flex", margin: "14px 0" },
  bubble: {
    borderRadius: 18,
    fontSize: 15,
    lineHeight: 1.6,
    maxWidth: "min(88%, 600px)",
    overflowWrap: "anywhere",
    padding: "13px 16px",
    whiteSpace: "pre-wrap",
  },
  userBubble: { background: "#1D4ED8", borderBottomRightRadius: 5, color: "#FFFFFF" },
  assistantBubble: {
    background: "#FFFFFF",
    border: "1px solid #E2E8F0",
    borderBottomLeftRadius: 5,
    color: "#1F2937",
  },
  status: { color: "#0F766E", fontSize: 12, fontWeight: 600, marginTop: 8 },
  sources: { borderTop: "1px solid #E2E8F0", color: "#475569", fontSize: 12, marginTop: 10, paddingTop: 8 },
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
  supportDescription: { color: "#64748B", lineHeight: 1.5, margin: "6px 0 10px" },
  supportForm: { display: "flex", flexDirection: "column", gap: 8 },
  supportLabel: { color: "#475569", fontWeight: 600 },
  supportInput: {
    border: "1px solid #CBD5E1",
    borderRadius: 8,
    boxSizing: "border-box",
    color: "#1F2937",
    font: "inherit",
    minHeight: 86,
    padding: "9px 10px",
    resize: "vertical",
    width: "100%",
  },
  supportButton: {
    alignSelf: "flex-start",
    background: "#1D4ED8",
    border: 0,
    borderRadius: 8,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontWeight: 600,
    padding: "9px 13px",
  },
  supportStatus: {
    color: "#0F766E",
    lineHeight: 1.5,
    margin: "9px 0 0",
  },
  quickActions: { display: "flex", flexWrap: "wrap", gap: 9, margin: "18px 0 24px" },
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
