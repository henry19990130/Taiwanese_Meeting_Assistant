<script setup>
import { onMounted } from "vue";
import { mountDesk } from "../composables/useDesk.js";
import { mountUpload } from "../composables/useMeeting.js";

onMounted(() => {
  mountDesk();
  mountUpload();
});
</script>

<template>
  <section class="home-hero" id="homeHero">
    <h2 id="homeGreeting">早安</h2>
    <p>今天有哪一場會議，要好好聽懂？</p>
  </section>

  <section class="card" id="uploadCard">
    <div class="upload-grid">
      <form id="uploadForm">
        <div class="source" role="radiogroup" aria-label="資料來源">
          <label class="choice"><input type="radio" name="source" value="audio" checked> 錄音檔</label>
          <label class="choice"><input type="radio" name="source" value="transcript"> 已經有逐字稿</label>
        </div>
        <label class="dropzone" id="audioField">
          <svg class="dz-wave" width="120" height="40" viewBox="0 0 120 40" aria-hidden="true"><g fill="currentColor"><rect x="4" y="16" width="4" height="8" rx="2"/><rect x="12" y="10" width="4" height="20" rx="2"/><rect x="20" y="4" width="4" height="32" rx="2"/><rect x="28" y="12" width="4" height="16" rx="2"/><rect x="36" y="7" width="4" height="26" rx="2"/><rect x="44" y="14" width="4" height="12" rx="2"/><rect x="52" y="2" width="4" height="36" rx="2"/><rect x="60" y="9" width="4" height="22" rx="2"/><rect x="68" y="15" width="4" height="10" rx="2"/><rect x="76" y="6" width="4" height="28" rx="2"/><rect x="84" y="12" width="4" height="16" rx="2"/><rect x="92" y="17" width="4" height="6" rx="2"/><rect x="100" y="10" width="4" height="20" rx="2"/><rect x="108" y="15" width="4" height="10" rx="2"/></g></svg>
          <span class="dz-title">把錄音放到桌上</span>
          <span class="dz-hint">拖曳檔案到這裡，或點一下選擇 · m4a、mp3、wav、影片也可以<br>上傳後會自動切成一句一句，並標上每句的起訖時間</span>
          <span class="dz-file" id="audioChip" hidden></span>
          <input name="audio" type="file" accept="audio/*,video/*,.m4a,.mp3,.wav,.webm,.ogg,.flac" required aria-label="選擇會議錄音">
        </label>
        <div class="asr-lang" id="asrLangField">
          <div class="source" role="radiogroup" aria-label="會議語言">
            <span class="source-title">會議語言</span>
            <label class="choice"><input type="radio" name="asr_language" value="zh" checked> 中文</label>
            <label class="choice"><input type="radio" name="asr_language" value="nan"> 台語</label>
            <label class="choice"><input type="radio" name="asr_language" value="hak"> 客語</label>
            <label class="choice"><input type="radio" name="asr_language" value="en"> 英文</label>
            <label class="sum-lang" id="dialectField" hidden title="客語腔調">腔調
              <select name="hakka_dialect">
                <option value="sixian" selected>四縣</option>
                <option value="hailu">海陸</option>
                <option value="dapu">大埔</option>
                <option value="raoping">饒平</option>
                <option value="zhaoan">詔安</option>
                <option value="nansixian">南四縣</option>
              </select>
            </label>
          </div>
          <small class="hint" id="asrLangHint">只會啟動這個語言的辨識模型，辨識完就關閉，不占記憶體</small>
        </div>
        <label class="dropzone" id="transcriptField" hidden>
          <svg class="dz-wave" width="120" height="40" viewBox="0 0 120 40" aria-hidden="true"><g fill="currentColor"><rect x="14" y="6" width="92" height="4" rx="2"/><rect x="14" y="16" width="72" height="4" rx="2"/><rect x="14" y="26" width="84" height="4" rx="2"/><rect x="14" y="36" width="48" height="4" rx="2"/></g></svg>
          <span class="dz-title">把逐字稿放到桌上</span>
          <span class="dz-hint">支援 txt、srt、vtt、json<br>檔案裡有時間就沿用；沒有時間會依換行與句子自動分段</span>
          <span class="dz-file" id="transcriptChip" hidden></span>
          <input name="transcript" type="file" accept=".txt,.srt,.vtt,.json,text/plain,application/json" aria-label="選擇逐字稿檔">
        </label>
        <label>會議名稱<input class="line-input" name="meeting_name" required maxlength="255" placeholder="例如：系統開發週會"></label>
        <div class="row">
          <label>會議日期<input class="line-input mono" name="date" type="date" required></label>
          <label>開始時間<input class="line-input mono" name="start_time" type="time"></label>
          <label>結束時間<input class="line-input mono" name="end_time" type="time"></label>
        </div>
        <p class="error" id="uploadError" hidden></p>
        <div class="upload-actions">
          <div class="glossary-row">
            <button class="btn ghost small" type="button" id="glossaryBtn">專有名詞詞彙庫</button>
            <small class="hint">AI 校對時會參考這些詞的正確寫法</small>
          </div>
          <button class="btn primary pill-btn" type="submit" id="uploadBtn">開始整理</button>
        </div>
      </form>
      <aside class="desk-info">
        <span class="eyebrow">這台電腦上</span>
        <dl>
          <div><dt>語音辨識</dt><dd id="infoAsr">—</dd></div>
          <div><dt>摘要模型</dt><dd id="infoLlm">—</dd></div>
          <div><dt>資料位置</dt><dd>本機</dd></div>
        </dl>
        <p class="desk-quote">錄音、逐字稿和重點，<br>都不會離開這張桌子。</p>
      </aside>
    </div>
  </section>
</template>
