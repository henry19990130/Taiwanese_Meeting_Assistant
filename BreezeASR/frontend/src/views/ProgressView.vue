<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { fetchJob } from "../api/jobs";
import AppTopbar from "../components/AppTopbar.vue";
import TranscriptCard from "../components/TranscriptCard.vue";
import { useAuth } from "../composables/useAuth";

const route = useRoute();
const router = useRouter();
const { state } = useAuth();

const jobId = String(route.query.job || "");
const filename = ref("");
const message = ref(jobId ? "正在讀取進度。" : "缺少工作編號。");
const percent = ref(0);
const error = ref(jobId ? "" : "請從首頁重新上傳音檔。");
const record = ref(null);
const backLabel = ref("回首頁");
let timer = 0;

async function pollJob() {
  try {
    const payload = await fetchJob(jobId);
    filename.value = payload.filename || "";
    message.value = payload.message || "";
    percent.value = Number(payload.percent) || 0;
    if (payload.status === "done") {
      stopPolling();
      record.value = payload.transcript || null;
      backLabel.value = "回首頁看紀錄";
      return;
    }
    if (payload.status === "failed") {
      stopPolling();
      error.value = payload.error || "辨識失敗";
    }
  } catch (exc) {
    stopPolling();
    if (exc.status === 401) {
      await router.push("/login");
      return;
    }
    message.value = "讀不到辨識進度。";
    error.value = exc.message || "辨識失敗";
  }
}

function stopPolling() {
  if (timer) {
    window.clearInterval(timer);
    timer = 0;
  }
}

onMounted(() => {
  if (!jobId) {
    return;
  }
  pollJob();
  timer = window.setInterval(pollJob, 800);
});

onUnmounted(stopPolling);
</script>

<template>
  <div class="app-shell">
    <AppTopbar :user="state.user" />
    <div class="stack">
      <header class="page-header">
        <p class="eyebrow">辨識進行中</p>
        <h1>語音辨識進度</h1>
        <p id="job-filename" class="lead">{{ filename }}</p>
      </header>

      <section class="card">
        <div id="job-progress" class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percent">
          <div id="job-bar" class="progress-bar" :style="{ width: `${percent}%` }"></div>
        </div>
        <p id="job-percent" class="percent">{{ percent }}%</p>
        <p id="job-message" role="status">{{ message }}</p>
        <p v-if="error" id="job-error" class="error">{{ error }}</p>
        <RouterLink id="back-home" class="text-link" to="/">{{ backLabel }}</RouterLink>
      </section>

      <TranscriptCard v-if="record" :record="record" variant="summary" />
    </div>
  </div>
</template>
