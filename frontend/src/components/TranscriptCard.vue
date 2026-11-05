<script setup>
import { onMounted } from "vue";
import { mountTranscript } from "../lib/transcriptView.js";

onMounted(mountTranscript);
</script>

<template>
  <section class="card" id="transcriptCard" hidden>
    <div class="card-head">
      <h2>逐字稿 <span class="muted" id="segmentCount"></span></h2>
      <div class="actions">
        <button class="btn ghost small" id="downloadJsonBtn" type="button">下載 JSON</button>
        <button class="btn ghost small" id="reproofBtn" type="button" hidden>重新校對</button>
        <button class="btn primary" id="confirmBtn" type="button" hidden>確認逐字稿</button>
        <label class="sum-lang" id="summaryLangWrap" hidden title="產生的重點要用哪種語言">
          重點語言
          <select id="summaryLang">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </label>
        <button class="btn primary" id="summarizeBtn" type="button" hidden>產生重點</button>
      </div>
    </div>

    <div class="review-panel" id="reviewPanel" hidden>
      <div class="rp-top">
        <div class="rp-stats" id="rpStats"></div>
        <div class="rp-tools">
          <span class="typo-nav" id="typoNav">
            <button class="btn ghost small" id="typoPrev" type="button" aria-label="上一處">‹</button>
            <span id="typoCount"></span>
            <button class="btn ghost small" id="typoNext" type="button" aria-label="下一處">›</button>
          </span>
          <button class="btn ghost small" id="acceptAllBtn" type="button">全部套用</button>
          <button class="btn ghost small" id="rpGlossaryBtn" type="button">詞彙庫</button>
        </div>
      </div>
      <div class="rp-item" id="rpItem"></div>
      <ul class="rp-problems" id="rpProblems" hidden></ul>
      <div class="rp-terms" id="rpTerms" hidden>
        <div class="rp-terms-head">把你改過的詞加入詞彙庫，下次 AI 校對就會參考：</div>
        <div class="rp-terms-list" id="rpTermsList"></div>
        <button class="btn ghost small" id="rpTermsAdd" type="button">加入勾選的詞</button>
      </div>
      <p class="rp-hint">AI 沒抓到的錯字（例如專有名詞）：<b>用滑鼠選取逐字稿裡的文字</b>就能修改，可以只改那一處或全部取代；也可以點每段右邊的「✎」改整段。處理完按右上角「確認逐字稿」，才能產生重點。</p>
      <p class="rp-msg" id="rpMsg" hidden></p>
      <p class="error" id="rpError" hidden></p>
    </div>

    <ul class="transcript" id="transcriptList"></ul>
  </section>

  <Teleport to="body">
    <div class="sel-bar" id="selBar" hidden>
      <div class="sel-row">
        <span class="sel-from" id="selFrom"></span><span class="muted">改成</span>
        <input id="selInput" maxlength="200" aria-label="改成">
      </div>
      <div class="sel-row">
        <button class="btn primary small" id="selOne" type="button">只改這裡</button>
        <button class="btn ghost small" id="selAll" type="button">全部取代</button>
        <label class="sel-check"><input type="checkbox" id="selAddTerm"> 改後的詞加入詞彙庫</label>
      </div>
      <div class="sel-row sel-sub">
        <button class="linkish" id="selTermOnly" type="button">這個詞本身是對的，只加入詞彙庫</button>
        <button class="linkish" id="selClose" type="button">取消</button>
      </div>
    </div>
  </Teleport>
</template>
