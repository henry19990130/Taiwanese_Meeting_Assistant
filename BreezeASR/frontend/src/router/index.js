import { createRouter, createWebHistory } from "vue-router";
import { useAuth } from "../composables/useAuth";
import HomeView from "../views/HomeView.vue";
import LoginView from "../views/LoginView.vue";
import ProgressView from "../views/ProgressView.vue";
import RegisterView from "../views/RegisterView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: HomeView,
      meta: { requiresAuth: true, title: "Breeze-ASR-26" },
    },
    {
      path: "/progress",
      component: ProgressView,
      meta: { requiresAuth: true, title: "辨識進度 · Breeze-ASR-26" },
    },
    {
      path: "/login",
      component: LoginView,
      meta: { guestOnly: true, layout: "auth", title: "登入 · Breeze-ASR-26" },
    },
    {
      path: "/register",
      component: RegisterView,
      meta: { guestOnly: true, layout: "auth", title: "建立帳號 · Breeze-ASR-26" },
    },
  ],
});

router.beforeEach(async (to) => {
  const { state, refresh } = useAuth();
  if (!state.ready) {
    await refresh();
  }
  if (to.meta.requiresAuth && !state.user) {
    return { path: "/login" };
  }
  if (to.meta.guestOnly && state.user) {
    return { path: "/" };
  }
  return true;
});

export default router;
