function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function request(method, url, body) {
  const resp = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "X-CSRFToken": csrfToken() } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401 || resp.status === 403) {
    if (method === "GET") {
      window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
      throw new Error("Not signed in");
    }
  }
  const data = resp.status === 204 ? {} : await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
  return data;
}

async function upload(url, file) {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" }, body: form });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
  return data;
}

export const api = {
  me: () => request("GET", "/api/v1/me"),
  graph: () => request("GET", "/api/v1/graph"),
  addHost: (name) => request("POST", "/api/v1/hosts", { name }),
  rotateToken: (pk) => request("POST", `/api/v1/hosts/${pk}/rotate-token`, {}),
  hosts: () => request("GET", "/api/v1/hosts"),
  updateHost: (pk, changes) => request("PATCH", `/api/v1/hosts/${pk}`, changes),
  deleteHost: (pk) => request("DELETE", `/api/v1/hosts/${pk}`),
  users: () => request("GET", "/api/v1/users"),
  createUser: (body) => request("POST", "/api/v1/users", body),
  updateUser: (id, changes) => request("PATCH", `/api/v1/users/${id}`, changes),
  deleteUser: (id) => request("DELETE", `/api/v1/users/${id}`),
  resetPassword: (id, password) => request("POST", `/api/v1/users/${id}/reset-password`, password ? { password } : {}),
  changeMyPassword: (current_password, new_password) => request("POST", "/api/v1/me/password", { current_password, new_password }),
  // logs (admins)
  requestLogs: (hostPk, container, tail, since) => request("POST", `/api/v1/hosts/${hostPk}/logs`, { container, tail, ...(since ? { since } : {}) }),
  logResult: (id) => request("GET", `/api/v1/logs/${id}`),
  // appearance
  branding: () => request("GET", "/api/v1/branding"),
  updateBranding: (changes) => request("PATCH", "/api/v1/branding", changes),
  uploadBrandingImage: (kind, file) => upload(`/api/v1/branding/${kind}`, file),
  deleteBrandingImage: (kind) => request("DELETE", `/api/v1/branding/${kind}`),
  // reports
  reportSchedule: () => request("GET", "/api/v1/report/schedule"),
  updateReportSchedule: (changes) => request("PATCH", "/api/v1/report/schedule", changes),
  sendReport: (recipients) => request("POST", "/api/v1/report/send", recipients ? { recipients } : {}),
  audit: (action) => request("GET", `/api/v1/audit${action ? `?action=${encodeURIComponent(action)}` : ""}`),
  csrfToken,
};
