<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuth } from "../composables/useAuth";

const props = defineProps({
  user: { type: Object, required: true },
});

const router = useRouter();
const { logout } = useAuth();
const open = ref(false);

const letter = computed(() => {
  const first = Array.from(String(props.user.username || "").trim())[0];
  return first ? first.toLocaleUpperCase("zh-Hant") : "?";
});

function close() {
  open.value = false;
}

function toggle(event) {
  event.stopPropagation();
  open.value = !open.value;
}

async function onLogout() {
  await logout();
  close();
  await router.push("/login");
}

function onDocumentClick(event) {
  if (!event.target.closest(".account-menu")) {
    close();
  }
}

function onEscape(event) {
  if (event.key === "Escape") {
    close();
  }
}

onMounted(() => {
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onEscape);
});

onUnmounted(() => {
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("keydown", onEscape);
});
</script>

<template>
  <div id="account-menu" class="account-menu">
    <button
      id="account-avatar"
      type="button"
      class="avatar"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="`帳號 ${user.username}`"
      @click="toggle"
    >
      <span id="avatar-letter">{{ letter }}</span>
    </button>
    <div v-show="open" id="account-dropdown" class="account-dropdown" role="menu">
      <p id="account-name" class="account-name">{{ user.username }}</p>
      <button type="button" class="menu-item" data-action="profile" role="menuitem" @click="close">個人資料</button>
      <button type="button" class="menu-item" data-action="settings" role="menuitem" @click="close">設定</button>
      <button type="button" class="menu-item logout-item" data-action="logout" role="menuitem" @click="onLogout">登出</button>
    </div>
  </div>
</template>
