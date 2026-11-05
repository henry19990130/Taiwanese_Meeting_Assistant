<script setup>
import { onMounted } from "vue";
import { mountAssistant } from "../assistant/mountAssistant.js";

let ctl = { onLogin() {}, onLogout() {} };
onMounted(() => { ctl = mountAssistant(); });
defineExpose({
  onLogin: () => ctl.onLogin(),
  onLogout: () => ctl.onLogout(),
});
</script>

<template>
  <div class="assistant" id="assistant" hidden>
    <section class="as-panel" id="asPanel" aria-label="會議小幫手" hidden>
      <header class="as-head">
        <div class="as-title">
          <strong>鉛筆小書記</strong>
          <small>只回答你的會議紀錄相關問題</small>
        </div>
        <button class="as-close" id="asClose" type="button" aria-label="收起小幫手">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 9l6 6 6-6"></path></svg>
        </button>
      </header>
      <div class="as-body" id="asBody" aria-live="polite"></div>
      <form class="as-form" id="asForm" autocomplete="off">
        <label class="sr-only" for="asInput">輸入問題</label>
        <input id="asInput" maxlength="300" placeholder="或直接輸入跟會議有關的問題">
        <button type="submit" id="asSend" aria-label="送出">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>
        </button>
      </form>
    </section>
    <div class="as-hint" id="asHint">有會議上的問題，可以問我！</div>
    <button class="as-launcher" id="asLauncher" type="button" aria-label="打開會議小幫手（鉛筆小書記）" aria-expanded="false" aria-controls="asPanel">
      <span class="ag" id="agent" aria-hidden="true">
        <span class="ag-shadow" id="agShadow"></span>
        <span class="ag-body" id="agBody">
          <img class="ag-pose on" data-pose="idle" src="/img/agent/idle.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="blink" src="/img/agent/blink.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="wave" src="/img/agent/wave.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="think" src="/img/agent/think.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="sleep" src="/img/agent/sleep.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="search" src="/img/agent/search.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="listen" src="/img/agent/listen.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="proofread" src="/img/agent/proofread.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="summary" src="/img/agent/summary.webp" alt="" draggable="false" decoding="async">
          <img class="ag-pose" data-pose="done" src="/img/agent/done.webp" alt="" draggable="false" decoding="async">
        </span>
      </span>
      <span class="as-badge" id="asBadge" hidden></span>
    </button>
  </div>
</template>
