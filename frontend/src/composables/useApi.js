import { session } from "../state.js";

let tokenOf = () => null;
let on401 = () => {};

export function bindSession(getToken, unauthorized) {
  tokenOf = getToken;
  on401 = unauthorized;
}

export async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  const token = tokenOf();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  if (form !== undefined) body = form;

  const res = await fetch(path, { method, headers, body });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && token) on401();
  if (!res.ok) {
    const d = data.detail;
    const msg = (d && d.message) || (Array.isArray(d) ? "輸入格式不正確" : null) || `錯誤 ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

bindSession(() => session.token, () => {
  import("./useAuth.js").then((m) => m.logoutLocal("登入已失效，請重新登入"));
});
