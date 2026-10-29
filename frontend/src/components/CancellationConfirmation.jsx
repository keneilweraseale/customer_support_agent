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
    background: "linear-gradient(145deg, #fffaf0, #fffdf8)",
    border: "1px solid #f1dfb8",
    borderRadius: 15,
    display: "flex",
    gap: 11,
    marginTop: 12,
    maxWidth: 460,
    padding: 15,
  },
  icon: {
    alignItems: "center",
    background: "#f8e9c8",
    borderRadius: 9,
    color: "#95651f",
    display: "flex",
    flex: "0 0 23px",
    fontSize: 13,
    fontWeight: 700,
    height: 23,
    justifyContent: "center",
  },
  content: { minWidth: 0 },
  title: { color: "#72521e", fontSize: 13, margin: "2px 0 6px" },
  message: { color: "#7d6948", fontSize: 12, lineHeight: 1.6, margin: 0 },
  label: {
    color: "#72521e",
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
    border: "1px solid #eadbbd",
    borderRadius: 9,
    padding: "9px 10px",
    width: 320,
  },
  actions: { display: "flex", flexWrap: "wrap", gap: 7, marginTop: 14 },
  confirm: {
    background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))",
    border: 0,
    borderRadius: 9,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 12,
    fontWeight: 600,
    padding: "9px 11px",
  },
  keep: {
    background: "rgba(255,255,255,.82)",
    border: "1px solid #e8d8b7",
    borderRadius: 9,
    color: "#735c32",
    cursor: "pointer",
    font: "inherit",
    fontSize: 12,
    fontWeight: 600,
    padding: "9px 11px",
  },
};
