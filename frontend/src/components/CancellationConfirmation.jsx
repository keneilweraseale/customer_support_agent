export default function CancellationConfirmation({
  onKeepOrder,
  onConfirm,
  orderId,
  confirmationToken,
  disabled,
}) {
  return (
    <section aria-labelledby="cancel-preview-title" style={styles.card}>
      <div aria-hidden="true" style={styles.icon}>!</div>
      <div style={styles.content}>
        <h3 id="cancel-preview-title" style={styles.title}>
          Cancellation preview{orderId ? ` · ${orderId}` : ""}
        </h3>
        <p style={styles.message}>
          This order appears eligible. Nothing changes unless you confirm below.
        </p>
        <div style={styles.actions}>
          <button
            disabled={disabled || !orderId || !confirmationToken}
            onClick={() => onConfirm(orderId, confirmationToken)}
            style={styles.confirm}
            type="button"
          >
            Confirm cancellation
          </button>
          <button disabled={disabled} onClick={onKeepOrder} style={styles.keep} type="button">
            Keep order
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
