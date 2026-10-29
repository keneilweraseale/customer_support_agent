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
