export default function ChatHeader({
  authenticated,
  disabled,
  onLogout,
  onNewChat,
  onDamageReport,
}) {
  return (
    <header className="chat-header" style={styles.header}>
      <div style={styles.brand}>
        <div aria-hidden="true" style={styles.icon}>
          <span>✦</span>
        </div>
        <div>
          <h1 style={styles.title}>Customer Support</h1>
          <p className="brand-subtitle" style={styles.subtitle}>Here to help with your order and more</p>
        </div>
      </div>
      {authenticated && (
        <div className="header-actions" style={styles.actions}>
          <button
            aria-label="Report a damaged item"
            className="header-action damage-report-action"
            disabled={disabled}
            onClick={onDamageReport}
            style={styles.damageReport}
            type="button"
          >
            <span aria-hidden="true">▣</span>
            <span>Report damaged item</span>
          </button>
          <button className="header-action" disabled={disabled} onClick={onNewChat} style={styles.newChat} type="button">
            <span aria-hidden="true">＋</span><span className="new-chat-label"> New chat</span>
          </button>
          <button className="header-action" disabled={disabled} onClick={onLogout} style={styles.newChat} type="button">
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
    background: "rgba(255,255,255,0.82)",
    borderBottom: "1px solid #e8efef",
    display: "flex",
    justifyContent: "space-between",
    padding: "19px 28px",
  },
  actions: { alignItems: "center", display: "flex", gap: 10 },
  damageReport: {
    alignItems: "center",
    background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))",
    border: 0,
    borderRadius: 11,
    color: "#FFFFFF",
    cursor: "pointer",
    display: "flex",
    font: "inherit",
    fontSize: 12,
    fontWeight: 700,
    gap: 7,
    padding: "10px 13px",
    whiteSpace: "nowrap",
  },
  brand: { alignItems: "center", display: "flex", gap: 13, minWidth: 0 },
  icon: {
    alignItems: "center",
    background: "linear-gradient(145deg, #1ba291, var(--color-primary-dark))",
    borderRadius: 15,
    color: "#FFFFFF",
    display: "flex",
    fontSize: 20,
    fontWeight: 700,
    height: 46,
    justifyContent: "center",
    boxShadow: "0 6px 15px rgba(22, 139, 126, .18)",
    width: 46,
    flex: "0 0 46px",
  },
  title: {   color: "var(--color-ink)", fontSize: 16, letterSpacing: "-0.025em", margin: 0 },
  subtitle: { color: "#829295", fontSize: 12, margin: "4px 0 0" },
  newChat: {
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    borderRadius: 11,
    color: "#476164",
    cursor: "pointer",
    font: "inherit",
    fontSize: 12,
    fontWeight: 600,
    padding: "10px 13px",
  },
};
