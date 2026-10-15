import { reactive } from "vue";
import { fetchMe, login as apiLogin, logout as apiLogout, register as apiRegister } from "../api/auth";

const state = reactive({
  user: null,
  ready: false,
});

export function useAuth() {
  async function refresh() {
    try {
      state.user = await fetchMe();
    } catch {
      state.user = null;
    }
    state.ready = true;
    return state.user;
  }

  async function login(username, password) {
    state.user = await apiLogin(username, password);
    return state.user;
  }

  async function register(username, password) {
    state.user = await apiRegister(username, password);
    return state.user;
  }

  async function logout() {
    try {
      await apiLogout();
    } finally {
      state.user = null;
    }
  }

  return { state, refresh, login, register, logout };
}
