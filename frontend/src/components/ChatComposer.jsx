export default function ChatComposer({ value, onChange, onSubmit, disabled }) {
  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <form className="chat-footer-form" onSubmit={(event) => { event.preventDefault(); onSubmit(); }} style={styles.form}>
      <label htmlFor="chat-message" style={styles.srOnly}>Type your question</label>
      <textarea
        autoComplete="off"
        aria-label="Type your question"
        autoFocus
        disabled={disabled}
        id="chat-message"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask us anything about your order…"
        rows={1}
        style={styles.input}
        value={value}
      />
      <button className="send-button" disabled={disabled || !value.trim()} style={styles.send} type="submit">
        Send <span aria-hidden="true">↗</span>
      </button>
    </form>
  );
}

const styles = {
  form: {
    alignItems: "flex-end",
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderRadius: 16,
    boxShadow: "var(--shadow-control)",
    display: "flex",
    gap: 10,
    padding: 6,
  },
  input: {
    background: "transparent",
    border: 0,
    borderRadius: 11,
    color: "var(--color-ink)",
    flex: 1,
    font: "inherit",
    fontSize: 14,
    lineHeight: 1.5,
    maxHeight: 130,
    minHeight: 44,
    outline: "none",
    padding: "11px 12px",
    resize: "none",
  },
  send: {
    alignItems: "center",
    background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))",
    border: 0,
    borderRadius: 11,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 13,
    fontWeight: 700,
    display: "flex",
    gap: 9,
    justifyContent: "center",
    minHeight: 44,
    padding: "0 17px",
  },
  srOnly: {
    clip: "rect(0, 0, 0, 0)",
    clipPath: "inset(50%)",
    height: 1,
    overflow: "hidden",
    position: "absolute",
    whiteSpace: "nowrap",
    width: 1,
  },
};
