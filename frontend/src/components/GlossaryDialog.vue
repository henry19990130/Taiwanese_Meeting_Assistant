<script setup>
import { onMounted } from "vue";
import { mountGlossary } from "../composables/useGlossary.js";

onMounted(mountGlossary);
</script>

<template>
  <dialog class="glossary-dialog" id="glossaryDialog">
    <div class="gd-head">
      <h2>專有名詞詞彙庫 <span class="muted" id="gdCount"></span></h2>
      <button class="btn ghost small" id="gdClose" type="button">關閉</button>
    </div>
    <p class="hint">AI 校對逐字稿時，會把發音相近的錯字建議改成這裡的寫法，這些詞本身也不會被改掉。每個帳號一份，最多 200 個詞。</p>
    <form class="gd-add" id="gdForm">
      <textarea id="gdInput" rows="2" placeholder="例如：Kubernetes、加權平均、佩珊（用換行或逗號分開，可一次加多個）"></textarea>
      <button class="btn primary small" type="submit">新增</button>
    </form>
    <p class="gd-msg" id="gdMsg" hidden></p>
    <input class="gd-filter" id="gdFilter" placeholder="搜尋詞彙" aria-label="搜尋詞彙">
    <ul class="gd-list" id="gdList"></ul>
  </dialog>
</template>
