<script setup>
import { computed } from "vue";
import { renderMarkdown } from "../markdown/render.js";

const props = defineProps({
  source: { type: String, default: "" },
  empty: { type: String, default: "（沒有會議摘要）" },
});

const html = computed(() => renderMarkdown(props.source));
</script>

<template>
  <div v-if="html" class="summary-markdown" v-html="html"></div>
  <p v-else class="empty">{{ empty }}</p>
</template>
