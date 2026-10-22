export async function sendChatMessage({ message, conversationId, authorizationToken }) {
  const data = await postJson("/api/chat", {
    message,
    conversation_id: conversationId,
    authorization_token: authorizationToken || null,
  });
  if (typeof data.answer !== "string" || typeof data.conversation_id !== "string") {
    throw new Error("We received an unexpected response. Please try again.");
  }

  return data;
}

export async function verifyDemoCustomer(customerId) {
  const data = await postJson("/api/demo/verify", { customer_id: customerId });
  if (typeof data.authorization_token !== "string" || typeof data.expires_at !== "string") {
    throw new Error("We received an unexpected verification response. Please try again.");
  }
  return data;
}

export async function confirmCancellation({
  orderId,
  authorizationToken,
  confirmationToken,
  idempotencyKey,
}) {
  const data = await postJson(
    `/api/orders/${encodeURIComponent(orderId)}/cancel`,
    {
      authorization_token: authorizationToken,
      confirmation_token: confirmationToken,
    },
    { "Idempotency-Key": idempotencyKey },
  );
  if (data.cancelled !== true || data.order_id !== orderId) {
    throw new Error("Cancellation could not be confirmed. Please contact support.");
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
    const error = new Error(
      "Demo verification is missing or expired. Verify your demo customer ID and try again.",
    );
    error.status = 401;
    return error;
  }
  const error = new Error("Support is temporarily unavailable. Please try again.");
  error.retryable = response.status === 503;
  error.status = response.status;
  return error;
}
