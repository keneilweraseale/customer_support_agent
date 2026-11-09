export async function sendChatMessage({ message, conversationId, authorizationToken }) {
  const data = await postJson("/api/chat", {
    message,
    conversation_id: conversationId,
    memory_enabled: true,
    authorization_token: authorizationToken || null,
  });
  if (typeof data.answer !== "string" || typeof data.conversation_id !== "string") {
    throw new Error("We received an unexpected response. Please try again.");
  }

  return data;
}

export async function loadConversationHistory({ conversationId, authorizationToken }) {
  const data = await postJson("/api/chat/history", {
    conversation_id: conversationId,
    authorization_token: authorizationToken,
  });
  if (
    data.conversation_id !== conversationId
    || !Array.isArray(data.turns)
    || data.turns.some(
      (turn) =>
        !["user", "assistant"].includes(turn.role)
        || typeof turn.text !== "string",
    )
  ) {
    throw new Error("We received an unexpected conversation-history response.");
  }
  return data.turns;
}

export async function sendSupportTicketMessage({
  ticketId,
  message,
  authorizationToken,
}) {
  const data = await postJson(
    `/api/support/tickets/${encodeURIComponent(ticketId)}/message`,
    { message, authorization_token: authorizationToken },
  );
  if (data.sent !== true || data.ticket_id !== ticketId) {
    throw new Error("We could not confirm that your message was sent. Please try again.");
  }
  return data;
}

export async function getCustomerTickets(authorizationToken) {
  const data = await getJson("/api/tickets", authorizationToken);
  if (!Array.isArray(data.tickets)) {
    throw new Error("We received an unexpected ticket list. Please try again.");
  }
  return data.tickets;
}

export async function getCustomerTicket(ticketId, authorizationToken) {
  const data = await getJson(
    `/api/tickets/${encodeURIComponent(ticketId)}`,
    authorizationToken,
  );
  if (data.ticket_id !== ticketId || !Array.isArray(data.messages)) {
    throw new Error("We received unexpected ticket details. Please try again.");
  }
  return data;
}

export async function login(email, password) {
  let data;
  try {
    data = await postJson("/api/auth/login", { email, password });
  } catch (error) {
    if (error.status === 401) {
      throw new Error("Email or password is incorrect.");
    }
    throw error;
  }
  if (typeof data.authorization_token !== "string" || typeof data.expires_at !== "string") {
    throw new Error("We received an unexpected login response. Please try again.");
  }
  return data;
}

export async function loginSupportAgent(email, password) {
  const data = await postJson("/api/auth/support-agent/login", { email, password });
  if (
    typeof data.authorization_token !== "string"
    || typeof data.expires_at !== "string"
  ) {
    throw new Error("We received an unexpected login response. Please try again.");
  }
  return data;
}

export async function getAdminDashboardStats(authorizationToken) {
  return authorizedJson("/api/admin/dashboard/stats", authorizationToken);
}

export async function getAdminTickets(authorizationToken, filters = {}) {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value != null) parameters.set(key, value);
  }
  const suffix = parameters.size ? `?${parameters.toString()}` : "";
  const data = await authorizedJson(
    `/api/admin/tickets${suffix}`,
    authorizationToken,
  );
  if (!Array.isArray(data.tickets) || typeof data.total !== "number") {
    throw new Error("We received an unexpected ticket list.");
  }
  return data;
}

export async function getAdminTicket(ticketId, authorizationToken) {
  return authorizedJson(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}`,
    authorizationToken,
  );
}

export async function getAdminTicketAttachment(
  ticketId,
  attachmentId,
  authorizationToken,
) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    response = await fetch(
      `/api/admin/tickets/${encodeURIComponent(ticketId)}/attachments/${encodeURIComponent(attachmentId)}`,
      {
        headers: { Authorization: `Bearer ${authorizationToken}` },
        signal: controller.signal,
      },
    );
  } catch {
    const error = new Error(
      "We could not load the ticket attachment. Please try again.",
    );
    error.retryable = true;
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) throw await responseError(response);
  return response.blob();
}

export async function getSupportAgents(authorizationToken) {
  return authorizedJson("/api/admin/agents", authorizationToken);
}

export async function getAdminCategories(authorizationToken) {
  return authorizedJson("/api/admin/categories", authorizationToken);
}

export async function updateAdminTicketStatus(ticketId, body, authorizationToken) {
  return authorizedJson(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}/status`,
    authorizationToken,
    "PATCH",
    body,
  );
}

export async function updateAdminTicketPriority(ticketId, priority, authorizationToken) {
  return authorizedJson(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}/priority`,
    authorizationToken,
    "PATCH",
    { priority },
  );
}

export async function assignAdminTicket(ticketId, assignedTo, authorizationToken) {
  return authorizedJson(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}/assign`,
    authorizationToken,
    "PATCH",
    { assigned_to: assignedTo || null },
  );
}

export async function replyToAdminTicket(ticketId, message, authorizationToken) {
  return authorizedJson(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}/reply`,
    authorizationToken,
    "POST",
    { message },
  );
}

export async function addAdminTicketNote(ticketId, note, authorizationToken) {
  return authorizedJson(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}/notes`,
    authorizationToken,
    "POST",
    { note },
  );
}

export async function confirmCancellation({
  orderId,
  authorizationToken,
  confirmationToken,
  idempotencyKey,
  reasonCode,
  reasonText,
}) {
  const data = await postJson(
    `/api/orders/${encodeURIComponent(orderId)}/cancel`,
    {
      authorization_token: authorizationToken,
      confirmation_token: confirmationToken,
      reason_code: reasonCode,
      reason_text: reasonText || null,
    },
    { "Idempotency-Key": idempotencyKey },
  );
  if (data.cancelled !== true || data.order_id !== orderId) {
    throw new Error("Cancellation could not be confirmed. Please contact support.");
  }
  return data;
}

export async function recordCancellationDecision({
  orderId,
  authorizationToken,
  confirmationToken,
  idempotencyKey,
  outcome,
  reasonCode,
  reasonText,
}) {
  const data = await postJson(
    `/api/orders/${encodeURIComponent(orderId)}/cancel/decision`,
    {
      authorization_token: authorizationToken,
      confirmation_token: confirmationToken,
      outcome,
      reason_code: reasonCode,
      reason_text: reasonText || null,
    },
    { "Idempotency-Key": idempotencyKey },
  );
  if (data.recorded !== true || data.order_id !== orderId || data.outcome !== outcome) {
    throw new Error("We could not record your cancellation decision. Please try again.");
  }
  return data;
}

export async function submitDamageReport({
  authorizationToken,
  orderId,
  imageData,
  description,
  idempotencyKey,
}) {
  const data = await postJson(
    "/api/damage-reports",
    {
      authorization_token: authorizationToken,
      order_id: orderId,
      image_data: imageData,
      description: description || null,
    },
    { "Idempotency-Key": idempotencyKey },
  );
  if (
    typeof data.report_id !== "string" ||
    typeof data.ticket_id !== "string" ||
    data.order_id !== orderId ||
    typeof data.created !== "boolean" ||
    typeof data.message !== "string"
  ) {
    throw new Error("We could not confirm that your damage report was received.");
  }
  return data;
}

async function postJson(url, body, additionalHeaders = {}) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...additionalHeaders },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch {
    const error = new Error(
      "We could not reach support or the request timed out. Please try again.",
    );
    error.retryable = true;
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    throw await responseError(response);
  }
  try {
    return await response.json();
  } catch {
    throw new Error("We received an unexpected response. Please try again.");
  }
}

async function getJson(url, authorizationToken) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    response = await fetch(url, {
      headers: { Authorization: `Bearer ${authorizationToken}` },
      signal: controller.signal,
    });
  } catch {
    const error = new Error(
      "We could not reach support or the request timed out. Please try again.",
    );
    error.retryable = true;
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) throw await responseError(response);
  try {
    return await response.json();
  } catch {
    throw new Error("We received an unexpected response. Please try again.");
  }
}

async function authorizedJson(url, authorizationToken, method = "GET", body) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${authorizationToken}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
      signal: controller.signal,
    });
  } catch {
    const error = new Error(
      "We could not reach support or the request timed out. Please try again.",
    );
    error.retryable = true;
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) throw await responseError(response);
  try {
    return await response.json();
  } catch {
    throw new Error("We received an unexpected response. Please try again.");
  }
}

async function responseError(response) {
  if (response.status === 401) {
    const error = new Error("Your session has expired. Please sign in again.");
    error.status = 401;
    return error;
  }
  let message = "Support is temporarily unavailable. Please try again.";
  try {
    const data = await response.json();
    if (typeof data?.error?.message === "string") {
      message = data.error.message;
    }
  } catch {
    // Keep the generic message when the server response is not valid JSON.
  }
  const error = new Error(message);
  error.retryable = response.status === 503;
  error.status = response.status;
  return error;
}
