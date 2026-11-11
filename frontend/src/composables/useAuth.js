import { nextTick } from "vue";
import { session } from "../state.js";
import { api, refreshAccess } from "./useApi.js";
import { views } from "../views.js";

const hooks = {
  beforeShow: async () => {},
  afterShow: async () => {},
  onLogout: () => {},
};

export function setAuthHooks(next) {
  Object.assign(hooks, next);
}

export function displayName(user) {
  const u = user || session.user;
  return (u && (u.display_name || u.username)) || "";
}

export function accountOk(name) {
  return /^[A-Za-z0-9_]{3,32}$/.test(name);
}

export function passwordOk(password) {
  return password.length >= 12 && password.length <= 200 && /[A-Za-z]/.test(password) && /[0-9]/.test(password);
}

export async function restoreSession() {
  if (session.token) return;
  const ok = await refreshAccess();
  if (!ok) return;
  await hooks.beforeShow(displayName());
  session.entered = true;
  await hooks.afterShow();
}

export async function enterRoom(data, form) {
  session.token = data.access_token || null;
  session.user = data.user;
  form?.reset();
  await hooks.beforeShow(displayName());
  session.entered = true;
  await hooks.afterShow();
}

export function logoutLocal(message) {
  hooks.onLogout();
  session.token = null;
  session.user = null;
  session.entered = false;
  nextTick(() => views.showAuth("login", message || ""));
}

export async function logout() {
  try { await api("/api/v1/auth/logout", { method: "POST" }); } catch (_) { /* 本機登出仍要清掉畫面 */ }
  logoutLocal();
}
