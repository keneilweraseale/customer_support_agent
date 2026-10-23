import { useState } from "react";

export default function CancellationConfirmation({
  onDecision,
  onConfirm,
  messageId,
  orderId,
  confirmationToken,
  disabled,
}) {
  const [reasonCode, setReasonCode] = useState("not_provided");
  const [reasonText, setReasonText] = useState("");

  return (
    <section aria-labelledby={`cancel-preview-title-${messageId}`} style={styles.card}>
      <div aria-hidden="true" style={styles.icon}>!</div>
      <div style={styles.content}>
        <h3 id={`cancel-preview-title-${messageId}`} style={styles.title}>
          Cancellation preview{orderId ? ` · ${orderId}` : ""}
        </h3>
        <p style={styles.message}>
          This order appears eligible. Select an optional reason before deciding.
          Nothing changes unless you confirm below.
        </p>
        <label htmlFor={`cancel-reason-${messageId}`} style={styles.label}>
          Cancellation reason
        </label>
        <select
          disabled={disabled}
          id={`cancel-reason-${messageId}`}
          onChange={(event) => setReasonCode(event.target.value)}
          style={styles.input}
          value={reasonCode}
        >
          <option value="not_provided">Prefer not to say</option>
          <option value="ordered_by_mistake">Ordered by mistake</option>
          <option value="delivery_too_late">Delivery is too late</option>
          <option value="found_better_price">Found a better price</option>
          <option value="changed_mind">Changed my mind</option>
          <option value="duplicate_order">Duplicate order</option>
          <option value="payment_problem">Payment problem</option>
          <option value="other">Other</option>
        </select>
        {reasonCode === "other" && (
          <label style={styles.label}>
            Brief explanation (optional)
            <textarea
              disabled={disabled}
              maxLength={280}
              onChange={(event) => setReasonText(event.target.value)}
              rows={2}
              style={styles.input}
              value={reasonText}
            />
          </label>
        )}
        <div style={styles.actions}>
          <button
            disabled={disabled || !orderId || !confirmationToken}
            onClick={() =>
              onConfirm(
                orderId,
                confirmationToken,
                reasonCode,
                reasonCode === "other" ? reasonText.trim() || null : null,
              )
            }
            style={styles.confirm}
            type="button"
          >
            Confirm cancellation
          </button>
          <button
            disabled={disabled}
            onClick={() =>
              onDecision(
                orderId,
                confirmationToken,
                "declined",
                reasonCode,
                reasonCode === "other" ? reasonText.trim() || null : null,
              )
            }
            style={styles.keep}
            type="button"
          >
            Keep order
          </button>
          <button
            disabled={disabled}
            onClick={() =>
              onDecision(
                orderId,
                confirmationToken,
                "withdrawn",
                reasonCode,
                reasonCode === "other" ? reasonText.trim() || null : null,
              )
            }
            style={styles.keep}
            type="button"
          >
            Withdraw request
          </button>
        </div>
      </div>
    </section>
  );
}

const styles = {
  card: {
    alignItems: "flex-start",
    background: "#FFFBEB",
    border: "1px solid #FCD34D",
    borderRadius: 14,
    display: "flex",
    gap: 12,
    marginTop: 12,
    maxWidth: 460,
    padding: 16,
  },
  icon: {
    alignItems: "center",
    background: "#FEF3C7",
    borderRadius: "50%",
    color: "#92400E",
    display: "flex",
    flex: "0 0 24px",
    fontWeight: 700,
    height: 24,
    justifyContent: "center",
  },
  content: { minWidth: 0 },
  title: { color: "#78350F", fontSize: 14, margin: "2px 0 6px" },
  message: { color: "#78350F", fontSize: 13, lineHeight: 1.5, margin: 0 },
  label: {
    color: "#78350F",
    display: "block",
    fontSize: 12,
    fontWeight: 600,
    marginTop: 10,
  },
  input: {
    boxSizing: "border-box",
    display: "block",
    font: "inherit",
    fontSize: 13,
    marginTop: 5,
    maxWidth: "100%",
    padding: 7,
    width: 320,
  },
  actions: { display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 },
  confirm: {
    background: "#1D4ED8",
    border: 0,
    borderRadius: 8,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    fontWeight: 600,
    padding: "9px 12px",
  },
  keep: {
    background: "#FFFFFF",
    border: "1px solid #D6A94F",
    borderRadius: 8,
    color: "#713F12",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    fontWeight: 600,
    padding: "9px 12px",
  },
};
