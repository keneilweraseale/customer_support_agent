import { useEffect, useState } from "react";

import {
  addAdminTicketNote,
  assignAdminTicket,
  getAdminCategories,
  getAdminDashboardStats,
  getAdminTicket,
  getAdminTickets,
  getSupportAgents,
  loginSupportAgent,
  replyToAdminTicket,
  updateAdminTicketPriority,
  updateAdminTicketStatus,
} from "../api.js";

const statusOptions = [
  ["open", "Open"],
  ["investigating", "In Progress"],
  ["waiting_for_customer", "Pending Customer"],
  ["resolved", "Resolved"],
  ["closed", "Closed"],
];
const priorityOptions = ["low", "medium", "high", "critical"];
const statusNames = Object.fromEntries(statusOptions);
const tokenKey = "support-agent-authorization-token";

function formatDate(value) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Not available"
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function StatusBadge({ status }) {
  const canonical = status === "escalated" ? "investigating" : status;
  return (
    <span className={`admin-status admin-status-${canonical}`}>
      {statusNames[canonical] ?? canonical.replaceAll("_", " ")}
    </span>
  );
}

function PriorityLabel({ priority }) {
  return (
    <span className={`admin-priority admin-priority-${priority}`}>
      <span aria-hidden="true" />
      {priority}
    </span>
  );
}

export default function AdminDashboard() {
  const [authorizationToken, setAuthorizationToken] = useState(
    () => globalThis.sessionStorage?.getItem(tokenKey) ?? "",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState(null);
  const [tickets, setTickets] = useState([]);
  const [agents, setAgents] = useState([]);
  const [categories, setCategories] = useState([]);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [currentView, setCurrentView] = useState("dashboard");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [assignedFilter, setAssignedFilter] = useState("");
  const [sortBy, setSortBy] = useState("updated_at");
  const [sortOrder, setSortOrder] = useState("desc");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [nextStatus, setNextStatus] = useState("open");
  const [statusNote, setStatusNote] = useState("");
  const [publicReply, setPublicReply] = useState("");
  const [replyDraft, setReplyDraft] = useState("");
  const [noteDraft, setNoteDraft] = useState("");

  async function signIn(event) {
    event.preventDefault();
    if (!email.trim() || !password || busy) return;
    setBusy(true);
    setLoginError("");
    try {
      const result = await loginSupportAgent(email.trim(), password);
      globalThis.sessionStorage?.setItem(tokenKey, result.authorization_token);
      setAuthorizationToken(result.authorization_token);
      setPassword("");
    } catch (error) {
      setLoginError(error.message);
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    globalThis.sessionStorage?.removeItem(tokenKey);
    setAuthorizationToken("");
    setStats(null);
    setTickets([]);
    setSelectedTicket(null);
  }

  useEffect(() => {
    if (!authorizationToken) return undefined;
    let active = true;
    const load = async (showLoading = false) => {
      if (showLoading) setIsLoadingData(true);
      try {
        const [nextStats, ticketResult, nextCategories] = await Promise.all([
          getAdminDashboardStats(authorizationToken),
          getAdminTickets(authorizationToken, {
            search,
            status: statusFilter,
            priority: priorityFilter,
            category: categoryFilter,
            assigned_to: assignedFilter,
            sort_by: sortBy,
            sort_order: sortOrder,
            page,
            page_size: 20,
          }),
          getAdminCategories(authorizationToken),
        ]);
        if (!active) return;
        setStats(nextStats);
        setTickets(ticketResult.tickets);
        setTotal(ticketResult.total);
        setCategories(nextCategories);
        setLoadError("");
        setIsLoadingData(false);
      } catch (error) {
        if (!active) return;
        setIsLoadingData(false);
        if (error.status === 401) signOut();
        else setLoadError(error.message);
      }
    };
    void load(true);
    const timer = globalThis.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      globalThis.clearInterval(timer);
    };
  }, [
    authorizationToken,
    search,
    statusFilter,
    priorityFilter,
    categoryFilter,
    assignedFilter,
    sortBy,
    sortOrder,
    page,
    refreshKey,
  ]);

  useEffect(() => {
    if (!authorizationToken) return undefined;
    let active = true;
    const load = async () => {
      try {
        const result = await getSupportAgents(authorizationToken);
        if (active) setAgents(result);
      } catch (error) {
        if (active && error.status === 401) signOut();
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [authorizationToken]);

  useEffect(() => {
    if (!authorizationToken || !selectedTicket?.ticket_id) return undefined;
    const ticketId = selectedTicket.ticket_id;
    let active = true;
    const load = async () => {
      try {
        const result = await getAdminTicket(ticketId, authorizationToken);
        if (active) setSelectedTicket(result);
      } catch (error) {
        if (active && error.status === 401) signOut();
        else if (active) setActionError(error.message);
      }
    };
    const timer = globalThis.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      globalThis.clearInterval(timer);
    };
  }, [authorizationToken, selectedTicket?.ticket_id, refreshKey]);

  useEffect(() => {
    setNextStatus(selectedTicket?.status ?? "open");
    setStatusNote("");
    setPublicReply("");
    setReplyDraft("");
    setNoteDraft("");
    setActionError("");
  }, [selectedTicket?.ticket_id]);

  async function openTicket(ticketId) {
    setActionError("");
    try {
      setSelectedTicket(await getAdminTicket(ticketId, authorizationToken));
    } catch (error) {
      if (error.status === 401) signOut();
      else setActionError(error.message);
    }
  }

  async function performAction(action, successMessage) {
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await action();
      setNotice(successMessage);
      setRefreshKey((value) => value + 1);
      if (selectedTicket) {
        setSelectedTicket(
          await getAdminTicket(selectedTicket.ticket_id, authorizationToken),
        );
      }
    } catch (error) {
      if (error.status === 401) signOut();
      else setActionError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveStatus(event) {
    event.preventDefault();
    if (!selectedTicket || busy) return;
    if (["resolved", "closed"].includes(nextStatus)) {
      const confirmed = globalThis.confirm(
        `Confirm changing ${selectedTicket.ticket_id} to ${statusNames[nextStatus]}?`,
      );
      if (!confirmed) return;
    }
    await performAction(
      () => updateAdminTicketStatus(
        selectedTicket.ticket_id,
        {
          status: nextStatus,
          note: statusNote.trim() || "Updated by support agent.",
          customer_message: publicReply.trim() || null,
        },
        authorizationToken,
      ),
      "Ticket status saved.",
    );
    setStatusNote("");
    setPublicReply("");
  }

  async function sendReply(event) {
    event.preventDefault();
    if (!selectedTicket || !replyDraft.trim() || busy) return;
    await performAction(
      () => replyToAdminTicket(
        selectedTicket.ticket_id,
        replyDraft.trim(),
        authorizationToken,
      ),
      "Customer reply sent.",
    );
    setReplyDraft("");
  }

  async function saveNote(event) {
    event.preventDefault();
    if (!selectedTicket || !noteDraft.trim() || busy) return;
    await performAction(
      () => addAdminTicketNote(
        selectedTicket.ticket_id,
        noteDraft.trim(),
        authorizationToken,
      ),
      "Internal note saved.",
    );
    setNoteDraft("");
  }

  function selectQueue(status) {
    setStatusFilter(status);
    setCurrentView(status ? "queue" : "all");
    setPage(1);
    setSelectedTicket(null);
  }

  if (!authorizationToken) {
    return (
      <main className="admin-login-shell">
        <section className="admin-login-panel">
          <a className="admin-login-back" href="/">Customer support</a>
          <div className="admin-login-mark" aria-hidden="true">CS</div>
          <p className="admin-kicker">INTERNAL WORKSPACE</p>
          <h1>Support operations</h1>
          <p className="admin-login-copy">Sign in with your support-agent account to manage customer tickets.</p>
          <form onSubmit={signIn}>
            <label htmlFor="admin-email">Work email</label>
            <input id="admin-email" autoComplete="username" onChange={(event) => setEmail(event.target.value)} type="email" value={email} required />
            <label htmlFor="admin-password">Password</label>
            <input id="admin-password" autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} type="password" value={password} required />
            {loginError && <p className="admin-error" role="alert">{loginError}</p>}
            <button className="admin-primary-button admin-login-submit" disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in to dashboard"}</button>
          </form>
        </section>
      </main>
    );
  }

  const pageCount = Math.max(1, Math.ceil(total / 20));
  const timeline = selectedTicket
    ? [
        ...selectedTicket.messages.map((message) => ({
          kind: message.author_role === "customer" ? "Customer" : "Support reply",
          text: message.text,
          at: message.created_at,
          private: false,
        })),
        ...selectedTicket.status_history.map((event) => ({
          kind: `Status changed to ${statusNames[event.status] ?? event.status}`,
          text: event.note,
          at: event.changed_at,
          private: false,
        })),
        ...selectedTicket.internal_notes.map((note) => ({
          kind: `Internal note · ${note.staff_id}`,
          text: note.text,
          at: note.created_at,
          private: true,
        })),
      ].sort((a, b) => new Date(a.at) - new Date(b.at))
    : [];

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <a className="admin-brand" href="/admin/dashboard">
          <span className="admin-brand-mark">CS</span>
          <span><strong>Support desk</strong><small>Operations</small></span>
        </a>
        <p className="admin-nav-label">WORKSPACE</p>
        <nav aria-label="Ticket queues" className="admin-nav">
          <button className={currentView === "dashboard" ? "active" : ""} onClick={() => { setCurrentView("dashboard"); setStatusFilter(""); setPage(1); setSelectedTicket(null); }} type="button"><span className="admin-nav-icon">▦</span>Dashboard</button>
          <button className={currentView === "all" ? "active" : ""} onClick={() => selectQueue("")} type="button"><span className="admin-nav-icon">▤</span>All Tickets</button>
          {statusOptions.map(([value, label]) => (
            <button className={statusFilter === value ? "active" : ""} key={value} onClick={() => selectQueue(value)} type="button">
              <span className={`admin-queue-dot admin-queue-${value}`} />{label}
              {stats && <span className="admin-nav-count">{stats[value] ?? (value === "investigating" ? stats.investigating : 0)}</span>}
            </button>
          ))}
        </nav>
        <div className="admin-sidebar-bottom">
          <div className="admin-agent-badge"><span>{(email || "Agent").slice(0, 1).toUpperCase()}</span><div><strong>{email || "Support agent"}</strong><small>Support team</small></div></div>
          <button className="admin-signout" onClick={signOut} type="button"><span aria-hidden="true">↪</span>Sign out</button>
        </div>
      </aside>

      <main className="admin-main">
        <header className="admin-topbar">
          <div><p className="admin-kicker">CUSTOMER CARE / OPERATIONS</p><h1>{statusFilter ? statusNames[statusFilter] ?? "Tickets" : currentView === "dashboard" ? "Dashboard" : "All Tickets"}</h1></div>
          <div className="admin-top-actions"><div className="admin-live"><span />Live updates · 15 sec</div><button className="admin-top-signout" onClick={signOut} type="button">Sign out</button></div>
        </header>

        {stats && currentView === "dashboard" && (
          <section aria-label="Ticket overview" className="admin-stats">
            {[["Total tickets", "total", "#2563eb"], ["Open", "open", "#d97706"], ["In progress", "investigating", "#2563eb"], ["Pending customer", "waiting_for_customer", "#7c3aed"], ["Resolved", "resolved", "#16805d"], ["Closed", "closed", "#64748b"]].map(([label, key, color]) => (
              <button className="admin-stat" key={key} onClick={() => selectQueue(key === "total" ? "" : key)} style={{ "--stat-accent": color }} type="button">
                <span>{label}</span><strong>{stats[key] ?? 0}</strong>
              </button>
            ))}
          </section>
        )}

        {currentView !== "dashboard" && <section aria-label="Ticket management" className="admin-queue">
          <div className="admin-queue-heading">
            <div><h2>{statusFilter ? `${statusNames[statusFilter]} tickets` : "All tickets"}</h2><p>{total} customer requests</p></div>
            <button aria-label="Refresh tickets" className="admin-refresh" onClick={() => setRefreshKey((value) => value + 1)} type="button">↻</button>
          </div>
          <div className="admin-filters">
            <label className="admin-search"><span aria-hidden="true">⌕</span><input aria-label="Search ticket ID, customer, or subject" onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Ticket ID, customer or subject" type="search" value={search} /></label>
            <select aria-label="Filter by status" onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} value={statusFilter}><option value="">All statuses</option>{statusOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
            <select aria-label="Filter by priority" onChange={(event) => { setPriorityFilter(event.target.value); setPage(1); }} value={priorityFilter}><option value="">All priorities</option>{priorityOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select>
            <select aria-label="Filter by category" onChange={(event) => { setCategoryFilter(event.target.value); setPage(1); }} value={categoryFilter}><option value="">All categories</option>{categories.map((value) => <option key={value} value={value}>{value}</option>)}</select>
            <select aria-label="Filter by assigned agent" onChange={(event) => { setAssignedFilter(event.target.value); setPage(1); }} value={assignedFilter}><option value="">All agents</option>{agents.map((agent) => <option key={agent.staff_id} value={agent.staff_id}>{agent.email}</option>)}</select>
            <select aria-label="Sort tickets" onChange={(event) => setSortBy(event.target.value)} value={sortBy}><option value="updated_at">Recently updated</option><option value="created_at">Created date</option><option value="priority">Priority</option></select>
          </div>
          {loadError && <div className="admin-error-banner" role="alert">{loadError}<button onClick={() => setRefreshKey((value) => value + 1)} type="button">Retry</button></div>}
          {notice && <p className="admin-notice" role="status">{notice}</p>}
          <div className="admin-table-wrap">
            <table className="admin-ticket-table">
              <thead><tr><th>Ticket</th><th>Customer</th><th>Subject</th><th>Category</th><th>Priority</th><th>Status</th><th>Assigned to</th><th>Created</th><th>Updated</th><th /></tr></thead>
              <tbody>
                {tickets.map((ticket) => (
                  <tr key={ticket.ticket_id} onClick={() => void openTicket(ticket.ticket_id)}>
                    <td><button className="admin-ticket-id" onClick={() => void openTicket(ticket.ticket_id)} type="button">{ticket.ticket_id}</button></td>
                    <td><span className="admin-customer">{ticket.customer_email || ticket.customer_id || "Unknown"}</span><small>{ticket.customer_id}</small></td>
                    <td className="admin-subject">{ticket.subject}</td><td>{ticket.category}</td><td><PriorityLabel priority={ticket.priority} /></td><td><StatusBadge status={ticket.status} /></td><td>{agents.find((agent) => agent.staff_id === ticket.assigned_to)?.email ?? ticket.assigned_to ?? "Unassigned"}</td><td>{formatDate(ticket.created_at)}</td><td>{formatDate(ticket.updated_at)}</td><td><button aria-label={`Manage ${ticket.ticket_id}`} className="admin-row-action" onClick={() => void openTicket(ticket.ticket_id)} type="button">Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {isLoadingData ? <div aria-live="polite" className="admin-loading" role="status"><span />Loading tickets…</div> : !tickets.length && !loadError && <div className="admin-empty"><span aria-hidden="true">▤</span><h3>No tickets found</h3><p>Try changing the filters or check again after a customer submits a request.</p></div>}
          </div>
          {total > 0 && <footer className="admin-pagination"><span>Page {page} of {pageCount}</span><div><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)} type="button">Previous</button><button disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)} type="button">Next</button></div></footer>}
        </section>}
      </main>

      {selectedTicket && (
        <div className="admin-detail-backdrop" onClick={(event) => { if (event.target === event.currentTarget) setSelectedTicket(null); }}>
          <aside aria-label={`Manage ticket ${selectedTicket.ticket_id}`} aria-modal="true" className="admin-detail-panel" role="dialog">
            <header className="admin-detail-header"><div><p className="admin-kicker">TICKET MANAGEMENT</p><h2>{selectedTicket.ticket_id}</h2></div><button aria-label="Close ticket details" className="admin-close" onClick={() => setSelectedTicket(null)} type="button">×</button></header>
            <div className="admin-detail-scroll">
              <div className="admin-detail-title"><StatusBadge status={selectedTicket.status} /><PriorityLabel priority={selectedTicket.priority} /><h3>{selectedTicket.subject}</h3><p>{selectedTicket.description}</p></div>
              <dl className="admin-ticket-meta"><div><dt>Customer</dt><dd>{selectedTicket.customer_email || selectedTicket.customer_id || "Unknown"}</dd></div><div><dt>Customer ID</dt><dd>{selectedTicket.customer_id || "Not available"}</dd></div><div><dt>Category</dt><dd>{selectedTicket.category}</dd></div><div><dt>Created</dt><dd>{formatDate(selectedTicket.created_at)}</dd></div><div><dt>Last updated</dt><dd>{formatDate(selectedTicket.updated_at)}</dd></div></dl>
              <div className="admin-action-grid">
                <label>Priority<select disabled={busy} onChange={(event) => void performAction(() => updateAdminTicketPriority(selectedTicket.ticket_id, event.target.value, authorizationToken), "Priority updated.")} value={selectedTicket.priority}>{priorityOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                <label>Assigned agent<select disabled={busy} onChange={(event) => void performAction(() => assignAdminTicket(selectedTicket.ticket_id, event.target.value, authorizationToken), "Assignment updated.")} value={selectedTicket.assigned_to ?? ""}><option value="">Unassigned</option>{agents.map((agent) => <option key={agent.staff_id} value={agent.staff_id}>{agent.email}</option>)}</select></label>
              </div>
              <form className="admin-status-form" onSubmit={saveStatus}><h3>Update status</h3><label>Status<select onChange={(event) => setNextStatus(event.target.value)} value={nextStatus}>{statusOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Internal change note<input maxLength={1000} onChange={(event) => setStatusNote(event.target.value)} placeholder="Reason for this status change" value={statusNote} /></label>{["waiting_for_customer", "resolved"].includes(nextStatus) && <label>Message to customer<textarea maxLength={1000} onChange={(event) => setPublicReply(event.target.value)} placeholder="This message appears in the customer's ticket" value={publicReply} /></label>}<button className="admin-primary-button" disabled={busy || nextStatus === selectedTicket.status || (["waiting_for_customer", "resolved"].includes(nextStatus) && !publicReply.trim())} type="submit">{busy ? "Saving…" : "Save status"}</button></form>
              <section className="admin-conversation"><div className="admin-section-title"><h3>Conversation & history</h3><span>{timeline.length} updates</span></div>{timeline.length ? <ol>{timeline.map((item, index) => <li className={item.private ? "private" : ""} key={`${item.at}-${index}`}><div className="admin-timeline-top"><strong>{item.kind}</strong><time>{formatDate(item.at)}</time></div><p>{item.text}</p></li>)}</ol> : <p className="admin-muted">No conversation updates yet.</p>}{selectedTicket.audit_history?.length > 0 && <div className="admin-audit-history"><h4>Staff audit</h4>{selectedTicket.audit_history.map((event, index) => <p key={`${event.created_at}-${index}`}><strong>{event.changed_by}</strong> · {event.description}<time>{formatDate(event.created_at)}</time></p>)}</div>}</section>
              <form className="admin-message-form" onSubmit={sendReply}><h3>Reply to customer</h3><textarea maxLength={2000} onChange={(event) => setReplyDraft(event.target.value)} placeholder="Write a customer-visible reply" value={replyDraft} /><button className="admin-primary-button" disabled={busy || !replyDraft.trim()} type="submit">Send reply</button></form>
              <form className="admin-note-form" onSubmit={saveNote}><h3>Internal note <span>Staff only</span></h3><textarea maxLength={2000} onChange={(event) => setNoteDraft(event.target.value)} placeholder="Add a private note for the support team" value={noteDraft} /><button className="admin-secondary-button" disabled={busy || !noteDraft.trim()} type="submit">Add internal note</button></form>
              {actionError && <p className="admin-error" role="alert">{actionError}</p>}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
