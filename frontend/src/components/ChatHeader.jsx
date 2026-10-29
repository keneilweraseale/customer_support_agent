export default function ChatHeader({
  authenticated,
  disabled,
  onLogout,
  onNewChat,
  onDamageReport,
}) {
  return (
    <header style={styles.header}>
      <div style={styles.brand}>
        <div aria-hidden="true" style={styles.icon}>S</div>
        <div>
          <h1 style={styles.title}>Customer Support</h1>
          <p style={styles.subtitle}>Here to help with your order and more</p>
        </div>
      </div>
      {authenticated && (
        <div style={styles.actions}>
          <button disabled={disabled} onClick={onDamageReport} style={styles.newChat} type="button">
            Report damaged item
          </button>
          <button disabled={disabled} onClick={onNewChat} style={styles.newChat} type="button">
            <span aria-hidden="true">＋</span> New chat
          </button>
          <button disabled={disabled} onClick={onLogout} style={styles.newChat} type="button">
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}

const styles = {
  header: {
    alignItems: "center",
    borderBottom: "1px solid #E2E8F0",
    display: "flex",
    justifyContent: "space-between",
    padding: "20px 24px",
  },
  actions: { alignItems: "center", display: "flex", gap: 8 },
  brand: { alignItems: "center", display: "flex", gap: 12 },
  icon: {
    alignItems: "center",
    background: "#1D4ED8",
    borderRadius: 14,
    color: "#FFFFFF",
    display: "flex",
    fontSize: 18,
    fontWeight: 700,
    height: 42,
    justifyContent: "center",
    width: 42,
  },
  title: { color: "#1F2937", fontSize: 18, margin: 0 },
  subtitle: { color: "#64748B", fontSize: 13, margin: "4px 0 0" },
  newChat: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    borderRadius: 10,
    color: "#334155",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 600,
    padding: "9px 13px",
  },
};
