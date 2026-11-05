<script setup>
import { onMounted } from "vue";
import { mountProgress } from "../composables/useMeeting.js";

onMounted(mountProgress);
</script>

<template>
  <section class="card listen" id="progressCard" hidden>
    <div class="card-head">
      <div class="listen-title">
        <span class="eyebrow mono" id="meetingTitle">處理進度</span>
        <h2 id="listenTitle">正在聽…</h2>
      </div>
      <div class="listen-right">
        <span class="elapsed" id="elapsed" aria-live="off">00:00</span>
        <button class="btn ghost small" id="newMeetingBtn" type="button">＋ 新的會議</button>
      </div>
    </div>
    <div class="wave" id="waveBox" aria-hidden="true"><canvas id="waveCanvas"></canvas><span class="wave-scan"></span></div>
    <ol class="steps" id="steps">
      <li data-step="uploaded">已上傳</li>
      <li data-step="transcribing" id="stepTranscribing">語音辨識</li>
      <li data-step="proofreading">AI 校對錯字</li>
      <li data-step="reviewing">確認逐字稿</li>
      <li data-step="summarizing">產生重點</li>
      <li data-step="completed">完成</li>
    </ol>
    <p class="status-text" id="statusText"></p>
    <p class="error" id="jobError" hidden></p>
  </section>
</template>
