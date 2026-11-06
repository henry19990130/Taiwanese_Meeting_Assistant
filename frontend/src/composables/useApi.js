import { session } from "../state.js";

let on401 = () => {};

export function bindSession(_getToken, unauthorized) {
  on401 = unauthorized;
}

export async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  if (form !== undefined) body = form;

  const res = await fetch(path, { method, headers, body, credentials: "same-origin" });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && session.entered) on401();
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
