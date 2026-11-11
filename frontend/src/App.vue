<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { session } from "./state.js";
import { displayName, logout, restoreSession, setAuthHooks } from "./composables/useAuth.js";
import { afterEnter, haltMeeting } from "./composables/useMeeting.js";
import { loadInfo } from "./composables/useDesk.js";
import LoginView from "./components/LoginView.vue";
import UploadCard from "./components/UploadCard.vue";
import ProgressCard from "./components/ProgressCard.vue";
import SummaryCard from "./components/SummaryCard.vue";
import TranscriptCard from "./components/TranscriptCard.vue";
import GlossaryDialog from "./components/GlossaryDialog.vue";
import AssistantWidget from "./components/AssistantWidget.vue";
import EntranceOverlay from "./components/EntranceOverlay.vue";

const entranceRef = ref(null);
const assistantRef = ref(null);
const userLabel = computed(() => displayName());
const userTitle = computed(() => (session.user ? `帳號：${session.user.username}` : ""));

setAuthHooks({
  beforeShow: (name) => entranceRef.value?.close(name),
  afterShow: async () => {
    await nextTick();
    afterEnter();
    loadInfo();
    entranceRef.value?.greet(displayName());
    assistantRef.value?.onLogin();
    await entranceRef.value?.open();
  },
  onLogout: () => {
    haltMeeting();
    assistantRef.value?.onLogout();
    entranceRef.value?.greet();
  },
});

watch(() => session.entered, (on) => {
  document.body.classList.toggle("login-mode", !on);
}, { immediate: true });

onMounted(() => {
  restoreSession();
});
</script>

<template>
  <svg width="0" height="0" style="position:absolute" aria-hidden="true">
    <symbol id="ms-mark" viewBox="0 0 48 48">
      <g fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="4">
        <path d="M8 19V10a2 2 0 0 1 2-2h9" stroke="#2B2420"/>
        <path d="M40 29v9a2 2 0 0 1-2 2h-9" stroke="#5E7A5A"/>
      </g>
      <g fill="#2B2420">
        <rect x="15" y="20" width="4" height="8" rx="2"/>
        <rect x="22" y="14" width="4" height="20" rx="2"/>
        <rect x="29" y="18" width="4" height="12" rx="2"/>
      </g>
    </symbol>
  </svg>

  <header class="topbar">
    <div class="brand">
      <svg class="brand-mark" width="32" height="32" role="img" aria-label="覓聲"><use href="#ms-mark"/></svg>
      <span class="brand-name">覓聲</span>
    </div>
    <ol class="flow" id="flowSteps" aria-label="流程">
      <li data-flow="upload"><span>01</span>上傳</li>
      <li data-flow="listen"><span>02</span>聆聽</li>
      <li data-flow="proof"><span>03</span>校對</li>
      <li data-flow="summary"><span>04</span>重點</li>
    </ol>
    <div class="user" id="userBox" :hidden="!session.entered">
      <span id="userName" :title="userTitle">{{ userLabel }}</span>
      <button class="btn ghost small" id="logoutBtn" type="button" @click="logout">登出</button>
    </div>
  </header>

  <main>
    <LoginView />
    <div id="appView" :hidden="!session.entered">
      <UploadCard />
      <ProgressCard />
      <SummaryCard />
      <TranscriptCard />
    </div>
  </main>

  <AssistantWidget ref="assistantRef" />
  <GlossaryDialog />

  <Teleport to="body">
    <div id="printDeck" v-once aria-hidden="true"></div>
  </Teleport>

  <EntranceOverlay ref="entranceRef" />
</template>
