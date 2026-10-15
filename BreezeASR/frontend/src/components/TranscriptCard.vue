<script setup>
import MarkdownBody from "./MarkdownBody.vue";

const props = defineProps({
  record: { type: Object, required: true },
  closable: { type: Boolean, default: false },
  variant: { type: String, default: "transcript" },
});

defineEmits(["close"]);
</script>

<template>
  <section id="result" class="card">
    <div class="section-head">
      <h2>{{ variant === "summary" ? "會議摘要" : "逐字稿" }}</h2>
      <button v-if="closable" id="close-result" type="button" class="ghost compact" @click="$emit('close')">
        關閉記錄
      </button>
    </div>
    <MarkdownBody v-if="variant === 'summary'" :source="record.summary || ''" />
    <p v-else id="result-text">{{ record.text || "（沒有辨識到文字）" }}</p>
    <dl>
      <div>
        <dt>來源檔名</dt>
        <dd id="result-filename">{{ record.source_filename }}</dd>
      </div>
      <div>
        <dt>時間</dt>
        <dd id="result-time">{{ record.created_at }}</dd>
      </div>
      <div v-if="record.tags && record.tags.length">
        <dt>標籤</dt>
        <dd>
          <div class="tag-chip-row">
            <span v-for="tag in record.tags" :key="tag" class="tag-chip">{{ tag }}</span>
          </div>
        </dd>
      </div>
    </dl>
  </section>
</template>
