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
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
  return data;
}

export const api = {
  me: () => request("GET", "/api/v1/me"),
  graph: () => request("GET", "/api/v1/graph"),
  addHost: (name) => request("POST", "/api/v1/hosts", { name }),
  rotateToken: (pk) => request("POST", `/api/v1/hosts/${pk}/rotate-token`, {}),
  csrfToken,
};
