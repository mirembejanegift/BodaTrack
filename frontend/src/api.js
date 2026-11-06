/** Small fetch wrapper around the /api endpoints.
 *
 * Authentication is Django session-based: the sessionid cookie is sent
 * automatically on same-origin requests, and every write includes the
 * X-CSRFToken header read from the csrftoken cookie.
 */

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/** Ask the backend to set the CSRF cookie before any write. */
export async function ensureCsrfToken() {
  if (readCookie("csrftoken")) return readCookie("csrftoken");
  await fetch("/api/auth/csrf/", { credentials: "same-origin" });
  return readCookie("csrftoken");
}

async function request(path, { method = "GET", body, params } = {}) {
  const headers = {};
  let url = `/api${path}`;
  if (params && Object.keys(params).length) {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
    ).toString();
    if (query) url += `?${query}`;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") {
    const token = await ensureCsrfToken();
    if (token) headers["X-CSRFToken"] = token;
  }
  const response = await fetch(url, {
    method,
    headers,
    credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = new Error(detailOf(data, response.status));
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function detailOf(data, statusCode) {
  if (!data) return statusCode === 403 ? "You are not allowed to perform this action." : "Request failed.";
  if (typeof data.detail === "string") return data.detail;
  // DRF field errors look like {"reference": ["Required"]}
  const parts = [];
  for (const [field, messages] of Object.entries(data)) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    parts.push(field === "non_field_errors" ? text : `${field}: ${text}`);
  }
  return parts.join(" · ") || "Request failed.";
}

const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body) => request(path, { method: "POST", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
};

export default api;
