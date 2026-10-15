<script setup>
import { formatTranscriptDate, transcriptTitle } from "../composables/useTranscriptFilters";

const props = defineProps({
  item: { type: Object, required: true },
});

const emit = defineEmits(["open", "delete", "tags-change"]);

function removeTag(tag) {
  emit(
    "tags-change",
    (props.item.tags || []).filter((value) => value !== tag),
  );
}
</script>

<template>
  <li class="history-row">
    <div class="history-main">
      <button type="button" class="open" @click="emit('open')">
        <span class="history-name">{{ transcriptTitle(item) }}</span>
        <span class="history-date">
          <svg class="icon calendar-icon" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3.5" y="5" width="17" height="15.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
            <path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" d="M8 3.5v4M16 3.5v4M3.5 10h17" />
          </svg>
          {{ formatTranscriptDate(item.created_at) }}
        </span>
        <span v-if="(item.tags || []).length" class="tag-chip-row" @click.stop>
          <span v-for="tag in item.tags" :key="tag" class="tag-chip">
            {{ tag }}
            <button type="button" class="tag-remove" :aria-label="`移除標籤 ${tag}`" @click.stop="removeTag(tag)">×</button>
          </span>
        </span>
      </button>
    </div>
    <div class="history-actions">
      <button type="button" class="danger compact" @click="emit('delete')">刪除</button>
    </div>
  </li>
</template>
