function NavigationIcon({ name }) {
  const sharedProps = {
    "aria-hidden": "true",
    fill: "none",
    height: 20,
    stroke: "currentColor",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    strokeWidth: 1.7,
    viewBox: "0 0 24 24",
    width: 20,
  };

  if (name === "report") {
    return (
      <svg {...sharedProps}>
        <path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9Z" />
        <path d="m4.5 7.8 7.5 4.3 7.5-4.3M12 12v8.5M12 7v2.5" />
      </svg>
    );
  }

  if (name === "new-chat") {
    return (
      <svg {...sharedProps}>
        <path d="M12 20H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3" />
        <path d="M8 9h6M8 13h3M19 14v7M15.5 17.5h7" />
      </svg>
    );
  }

  if (name === "tickets") {
    return (
      <svg {...sharedProps}>
        <path d="M7 4h10a2 2 0 0 1 2 2v14H5V6a2 2 0 0 1 2-2Z" />
        <path d="M9 4.5V3h6v1.5M8.5 9h7M8.5 13h7M8.5 17h4" />
      </svg>
    );
  }

  if (name === "sign-out") {
    return (
      <svg {...sharedProps}>
        <path d="M10 17l5-5-5-5M15 12H3" />
        <path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6" />
      </svg>
    );
  }

  return (
    <svg {...sharedProps}>
      <path d="M4 10.5a8 8 0 0 1 16 0c0 4.5-3.6 8.5-8 8.5a8.6 8.6 0 0 1-3.2-.6L4 20l1.5-4.2A9.2 9.2 0 0 1 4 10.5Z" />
      <path d="M8.5 11h.01M12 11h.01M15.5 11h.01" strokeWidth="2.5" />
    </svg>
  );
}

export default function ChatHeader({
  authenticated,
  disabled,
  isDamageReportOpen,
  isTicketTrackingOpen,
  onLogout,
  onNewChat,
  onDamageReport,
  onTickets,
  onClose,
  open,
}) {
  return (
    <aside className={`sidebar${open ? " sidebar-open" : ""}`} id="primary-sidebar">
      <div className="sidebar-inner">
        <div className="sidebar-brand">
          <span className="sidebar-brand-icon">
            <NavigationIcon name="brand" />
          </span>
          <span className="sidebar-brand-copy">
            <strong>Customer Support</strong>
            <span>Here to help, every step</span>
          </span>
        </div>

        <div className="sidebar-section-label">WORKSPACE</div>
        {authenticated ? (
          <nav aria-label="Main navigation" className="sidebar-navigation">
            <button
              aria-current={isTicketTrackingOpen ? "page" : undefined}
              className={`sidebar-action${isTicketTrackingOpen ? " sidebar-action-active" : ""}`}
              disabled={disabled}
              onClick={() => {
                onTickets();
                onClose();
              }}
              type="button"
            >
              <NavigationIcon name="tickets" />
              <span>My Support Tickets</span>
            </button>
            <button
              aria-current={isDamageReportOpen ? "page" : undefined}
              className={`sidebar-action${isDamageReportOpen ? " sidebar-action-active" : ""}`}
              disabled={disabled}
              onClick={() => {
                onDamageReport();
                onClose();
              }}
              type="button"
            >
              <NavigationIcon name="report" />
              <span>Report damaged item</span>
            </button>
            <button
              className={`sidebar-action${!isDamageReportOpen && !isTicketTrackingOpen ? " sidebar-action-active" : ""}`}
              disabled={disabled}
              onClick={() => {
                onNewChat();
                onClose();
              }}
              type="button"
            >
              <NavigationIcon name="new-chat" />
              <span>New chat</span>
            </button>
          </nav>
        ) : (
          <p className="sidebar-description">
            Secure, personalized help for your orders and deliveries.
          </p>
        )}

        <div className="sidebar-bottom">
          {authenticated ? (
            <button
              className="sidebar-action sidebar-sign-out"
              onClick={() => {
                onLogout();
                onClose();
              }}
              type="button"
            >
              <NavigationIcon name="sign-out" />
              <span>Sign out</span>
            </button>
          ) : (
            <div className="sidebar-secure-note">
              <span aria-hidden="true" className="sidebar-secure-dot" />
              Your support session is secure
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
