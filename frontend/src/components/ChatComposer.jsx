export default function ChatComposer({ value, onChange, onSubmit, disabled }) {
  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }} style={styles.form}>
      <label htmlFor="chat-message" style={styles.srOnly}>Type your question</label>
      <textarea
        autoComplete="off"
        disabled={disabled}
        id="chat-message"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type your question…"
        rows={1}
        style={styles.input}
        value={value}
      />
      <button disabled={disabled || !value.trim()} style={styles.send} type="submit">
        Send <span aria-hidden="true">➤</span>
      </button>
    </form>
  );
}

const styles = {
  form: { alignItems: "flex-end", display: "flex", gap: 10 },
  input: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 12,
    color: "#1F2937",
    flex: 1,
    font: "inherit",
    fontSize: 15,
    lineHeight: 1.5,
    maxHeight: 130,
    minHeight: 46,
    outlineColor: "#1D4ED8",
    padding: "11px 13px",
    resize: "vertical",
  },
  send: {
    background: "#1D4ED8",
    border: 0,
    borderRadius: 12,
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 700,
    minHeight: 46,
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
