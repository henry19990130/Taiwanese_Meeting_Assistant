<script setup>
import { onMounted } from "vue";
import { mountSummary } from "../lib/summaryView.js";

onMounted(mountSummary);
</script>

<template>
  <section class="card snapshot" id="summaryCard" hidden>
    <div class="snap-head">
      <div class="snap-title">
        <div class="snap-meta" id="snapMeta"></div>
        <h2 id="snapTitle">會議重點</h2>
      </div>
      <div class="actions">
        <button class="btn ghost small" id="saveImageBtn" type="button">存成圖片</button>
        <button class="btn ghost small" id="deckBtn" type="button" title="開啟列印視窗，目的地選「另存為 PDF」">下載簡報 PDF</button>
        <button class="btn primary small" id="downloadSummaryBtn" type="button">下載重點</button>
      </div>
    </div>
    <div class="headline" id="snapHeadline">
      <span class="headline-label">一句話總結</span>
      <p id="snapHeadlineText"></p>
    </div>
    <div class="kpis" id="snapKpis"></div>
    <div id="snapBody"></div>
    <p class="snap-foot" id="snapFoot"></p>
  </section>
</template>
