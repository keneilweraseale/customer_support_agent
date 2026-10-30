import { useEffect, useMemo, useState } from "react";

import { getCustomerTicket, getCustomerTickets } from "../api.js";

const statusLabels = {
  open: "Open",
  investigating: "In Progress",
  waiting_for_customer: "Pending Customer",
  escalated: "In Progress",
  resolved: "Resolved",
  closed: "Closed",
};

const filterOptions = [
  ["all", "All statuses"],
  ["open", "Open"],
  ["investigating", "In Progress"],
  ["waiting_for_customer", "Pending Customer"],
  ["resolved", "Resolved"],
  ["closed", "Closed"],
];

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

function statusLabel(status) {
  return statusLabels[status] ?? status.replaceAll("_", " ");
}

function StatusBadge({ status }) {
  return (
    <span className={`ticket-status ticket-status-${status}`}>
      <span aria-hidden="true" className="ticket-status-mark">
        {status === "resolved" || status === "closed" ? "✓" : status === "waiting_for_customer" ? "?" : "•"}
      </span>
      {statusLabel(status)}
    </span>
  );
}

export default function TicketTracking({
  authorizationToken,
  onBack,
  onSendMessage,
  onSessionExpired,
}) {
  const [tickets, setTickets] = useState([]);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [failedTicketId, setFailedTicketId] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reply, setReply] = useState("");
  const [replying, setReplying] = useState(false);
  const [replyError, setReplyError] = useState("");
  const [replySent, setReplySent] = useState(false);

  async function loadTickets() {
    setLoading(true);
    setError("");
    try {
      setTickets(await getCustomerTickets(authorizationToken));
    } catch (loadError) {
      if (loadError.status === 401) onSessionExpired(loadError.message);
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTickets();
    const timer = globalThis.setInterval(async () => {
      try {
        setTickets(await getCustomerTickets(authorizationToken));
        setError("");
      } catch (loadError) {
        if (loadError.status === 401) onSessionExpired(loadError.message);
        setError(loadError.message);
      }
    }, 15000);
    return () => globalThis.clearInterval(timer);
  }, [authorizationToken]);

  useEffect(() => {
    if (!selectedTicket) return undefined;
    const ticketId = selectedTicket.ticket_id;
    let active = true;
    const timer = globalThis.setInterval(async () => {
      try {
        const latest = await getCustomerTicket(ticketId, authorizationToken);
        if (active) setSelectedTicket(latest);
      } catch (detailError) {
        if (active && detailError.status === 401) {
          onSessionExpired(detailError.message);
        }
      }
    }, 15000);
    return () => {
      active = false;
      globalThis.clearInterval(timer);
    };
  }, [authorizationToken, selectedTicket?.ticket_id]);

  async function openTicket(ticketId) {
    setLoading(true);
    setError("");
    setFailedTicketId("");
    setReply("");
    setReplyError("");
    setReplySent(false);
    try {
      setSelectedTicket(await getCustomerTicket(ticketId, authorizationToken));
    } catch (detailError) {
      if (detailError.status === 401) onSessionExpired(detailError.message);
      setFailedTicketId(ticketId);
      setError(detailError.message);
    } finally {
      setLoading(false);
    }
  }

  const visibleTickets = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return tickets.filter((ticket) => {
      const matchesSearch = !term ||
        ticket.ticket_id.toLocaleLowerCase().includes(term) ||
        ticket.subject.toLocaleLowerCase().includes(term);
      const matchesStatus = statusFilter === "all" ||
        (statusFilter === "investigating" && ticket.status === "escalated") ||
        ticket.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [tickets, search, statusFilter]);

  async function submitReply(event) {
    event.preventDefault();
    if (!selectedTicket || !reply.trim() || replying) return;
    setReplying(true);
    setReplyError("");
    setReplySent(false);
    try {
      await onSendMessage(selectedTicket.ticket_id, reply.trim());
      setReply("");
      setSelectedTicket(
        await getCustomerTicket(selectedTicket.ticket_id, authorizationToken),
      );
      setReplySent(true);
    } catch (sendError) {
      setReplyError(sendError.message);
    } finally {
      setReplying(false);
    }
  }

  const statusCounts = tickets.reduce((counts, ticket) => {
    counts[ticket.status] = (counts[ticket.status] ?? 0) + 1;
    return counts;
  }, {});

  const timeline = selectedTicket
    ? [
        ...selectedTicket.messages.map((message) => ({
          kind: message.role === "user" ? "Customer message" : "Support response",
          text: message.text,
          at: message.created_at,
          role: message.role,
        })),
        ...selectedTicket.status_history.map((event) => ({
          kind: `Status changed to ${statusLabel(event.status)}`,
          text: "",
          at: event.changed_at,
          role: "event",
        })),
        ...(selectedTicket.customer_update && !selectedTicket.messages.some(
          (message) => message.text === selectedTicket.customer_update.message,
        )
          ? [{
              kind: "Support update",
              text: selectedTicket.customer_update.message,
              at: selectedTicket.customer_update.created_at,
              role: "event",
            }]
          : []),
      ].sort((first, second) => new Date(first.at) - new Date(second.at))
    : [];

  return (
    <section aria-labelledby="tickets-title" className="ticket-page">
      <header className="ticket-page-header">
        <div>
          {selectedTicket && (
            <button className="ticket-back-link" onClick={() => setSelectedTicket(null)} type="button">
              <span aria-hidden="true">←</span> All tickets
            </button>
          )}
          <p className="ticket-eyebrow">CUSTOMER SUPPORT</p>
          <h2 id="tickets-title">{selectedTicket ? selectedTicket.ticket_id : "My Support Tickets"}</h2>
          <p className="ticket-intro">
            {selectedTicket ? selectedTicket.subject : "View updates and follow the progress of your requests."}
          </p>
        </div>
        <button className="ticket-chat-button" onClick={onBack} type="button">Back to chat</button>
      </header>

      {selectedTicket ? (
        <div className="ticket-detail-layout">
          <article className="ticket-detail-main">
            <div className="ticket-detail-summary">
              <StatusBadge status={selectedTicket.status} />
              <p>{selectedTicket.description}</p>
              <dl className="ticket-meta-grid">
                <div><dt>Created</dt><dd>{formatDate(selectedTicket.created_at)}</dd></div>
                <div><dt>Last updated</dt><dd>{formatDate(selectedTicket.updated_at)}</dd></div>
              </dl>
            </div>
            <section aria-labelledby="ticket-timeline-title" className="ticket-timeline-section">
              <h3 id="ticket-timeline-title">Updates</h3>
              {timeline.length ? (
                <ol className="ticket-timeline">
                  {timeline.map((event, index) => (
                    <li className="ticket-timeline-event" key={`${event.at}-${index}`}>
                      <span aria-hidden="true" className={`ticket-timeline-marker ticket-timeline-${event.role}`} />
                      <div>
                        <div className="ticket-event-heading">
                          <strong>{event.kind}</strong>
                          <time dateTime={event.at}>{formatDate(event.at)}</time>
                        </div>
                        {event.text && <p>{event.text}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="ticket-muted">No updates have been recorded yet.</p>
              )}
            </section>
            <form className="ticket-reply-form" onSubmit={submitReply}>
              <label htmlFor="ticket-reply">Send more information to support</label>
              <textarea
                id="ticket-reply"
                maxLength={2000}
                onChange={(event) => setReply(event.target.value)}
                placeholder="Add details that may help with your request"
                value={reply}
              />
              {replyError && <p className="ticket-error" role="alert">{replyError}</p>}
              {replySent && <p className="ticket-success" role="status">Your message was sent to support.</p>}
              <button className="ticket-primary-button" disabled={!reply.trim() || replying} type="submit">
                {replying ? "Sending…" : "Send message"}
              </button>
            </form>
          </article>
          <aside className="ticket-detail-aside">
            <h3>Ticket information</h3>
            <dl>
              <div><dt>Ticket ID</dt><dd>{selectedTicket.ticket_id}</dd></div>
              <div><dt>Status</dt><dd><StatusBadge status={selectedTicket.status} /></dd></div>
              <div><dt>Created</dt><dd>{formatDate(selectedTicket.created_at)}</dd></div>
              <div><dt>Last updated</dt><dd>{formatDate(selectedTicket.updated_at)}</dd></div>
            </dl>
          </aside>
        </div>
      ) : (
        <>
          {tickets.length > 0 && (
            <div aria-label="Ticket counts by status" className="ticket-counts">
              <div><strong>{tickets.length}</strong><span>Total tickets</span></div>
              <div><strong>{statusCounts.open ?? 0}</strong><span>Open</span></div>
              <div><strong>{(statusCounts.investigating ?? 0) + (statusCounts.escalated ?? 0)}</strong><span>In progress</span></div>
              <div><strong>{statusCounts.waiting_for_customer ?? 0}</strong><span>Pending you</span></div>
              <div><strong>{statusCounts.resolved ?? 0}</strong><span>Resolved</span></div>
              <div><strong>{statusCounts.closed ?? 0}</strong><span>Closed</span></div>
            </div>
          )}
          <div className="ticket-controls">
            <label className="ticket-search">
              <span aria-hidden="true">⌕</span>
              <input
                aria-label="Search ticket ID or subject"
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by ticket ID or subject"
                type="search"
                value={search}
              />
            </label>
            <label className="ticket-filter-label" htmlFor="ticket-status-filter">Status</label>
            <select id="ticket-status-filter" onChange={(event) => setStatusFilter(event.target.value)} value={statusFilter}>
              {filterOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>

          {loading ? (
            <div aria-live="polite" className="ticket-loading"><span className="ticket-spinner" />Loading your tickets…</div>
          ) : error ? (
            <div className="ticket-empty-state" role="alert">
              <h3>We couldn’t load your tickets</h3>
              <p>{error}</p>
              <button
                className="ticket-primary-button"
                onClick={() => void (failedTicketId ? openTicket(failedTicketId) : loadTickets())}
                type="button"
              >Try again</button>
            </div>
          ) : tickets.length === 0 ? (
            <div className="ticket-empty-state">
              <span aria-hidden="true" className="ticket-empty-icon">▤</span>
              <h3>No support tickets yet</h3>
              <p>When you contact our support team, your requests and updates will appear here.</p>
              <button className="ticket-primary-button" onClick={onBack} type="button">Start a chat</button>
            </div>
          ) : visibleTickets.length === 0 ? (
            <div className="ticket-empty-state ticket-filter-empty">
              <h3>No matching tickets</h3>
              <p>Try a different search or status filter.</p>
            </div>
          ) : (
            <div aria-label="Your support tickets" className="ticket-list">
              {visibleTickets.map((ticket) => (
                <button className="ticket-card" key={ticket.ticket_id} onClick={() => void openTicket(ticket.ticket_id)} type="button">
                  <span className="ticket-card-top"><strong>{ticket.ticket_id}</strong><StatusBadge status={ticket.status} /></span>
                  <span className="ticket-card-subject">{ticket.subject}</span>
                  <span className="ticket-card-meta">
                    <span>Created {formatDate(ticket.created_at)}</span>
                    <span>Updated {formatDate(ticket.updated_at)}</span>
                  </span>
                  <span aria-hidden="true" className="ticket-card-chevron">›</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}