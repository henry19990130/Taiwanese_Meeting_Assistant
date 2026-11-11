import { session } from "../state.js";

let on401 = () => {};
let refreshing = null;

export function bindSession(_getToken, unauthorized) {
  on401 = unauthorized;
}

function canRefresh(path) {
  return !path.startsWith("/api/v1/auth/login")
    && !path.startsWith("/api/v1/auth/register")
    && !path.startsWith("/api/v1/auth/refresh")
    && !path.startsWith("/api/v1/auth/logout");
}

export function refreshAccess({ force = false } = {}) {
  if (session.token && !force) return Promise.resolve(true);
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
    }).then(async (res) => {
      if (!res.ok) return false;
      const data = await res.json().catch(() => ({}));
      if (!data.access_token) return false;
      session.token = data.access_token;
      if (data.user) session.user = data.user;
      return true;
    }).catch(() => false).finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

export async function api(path, { method = "GET", json, form } = {}, retried = false) {
  const headers = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  if (form !== undefined) body = form;

  const res = await fetch(path, { method, headers, body, credentials: "same-origin" });
  if (res.status === 401 && !retried && canRefresh(path)) {
    const renewed = await refreshAccess({ force: true });
    if (renewed) return api(path, { method, json, form }, true);
    if (session.entered) on401();
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = (d && d.message) || (Array.isArray(d) ? "輸入格式不正確" : null) || `錯誤 ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

bindSession(null, () => {
  import("./useAuth.js").then((m) => m.logoutLocal("登入已失效，請重新登入"));
});
