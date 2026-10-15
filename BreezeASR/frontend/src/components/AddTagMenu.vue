<script setup>
import { ref, watch } from "vue";
import { transcriptTitle } from "../composables/useTranscriptFilters";
import FilterMenu from "./FilterMenu.vue";

const props = defineProps({
  items: { type: Array, default: () => [] },
  selectedId: { type: String, default: "" },
});

const emit = defineEmits(["add"]);
const transcriptId = ref(props.selectedId);
const draft = ref("");
const tagError = ref("");

watch(
  () => [props.selectedId, props.items],
  () => {
    if (props.selectedId && props.items.some((item) => item.id === props.selectedId)) {
      transcriptId.value = props.selectedId;
      return;
    }
    if (!props.items.some((item) => item.id === transcriptId.value)) {
      transcriptId.value = props.items[0]?.id || "";
    }
  },
  { immediate: true },
);

function submit(close) {
  const tag = draft.value.trim();
  const item = props.items.find((entry) => entry.id === transcriptId.value);
  if (!item) {
    tagError.value = "請先選一筆逐字稿。";
    return;
  }
  if (!tag) {
    tagError.value = "請輸入標籤名稱。";
    return;
  }
  const current = item.tags || [];
  if (current.some((value) => value.toLocaleLowerCase("zh-Hant") === tag.toLocaleLowerCase("zh-Hant"))) {
    tagError.value = "這個標籤已經在這筆逐字稿上。";
    return;
  }
  emit("add", { item, tag });
  draft.value = "";
  tagError.value = "";
  close();
}
</script>

<template>
  <FilterMenu label="新增標籤" icon-only>
    <template #toggle>
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L3 13V4h9l8.59 8.59a2 2 0 0 1 0 2.82Z"
        />
        <circle cx="7.5" cy="7.5" r="1.15" fill="currentColor" />
      </svg>
    </template>
    <template #panel="{ close }">
      <form v-if="items.length" @submit.prevent="submit(close)">
        <label for="add-tag-transcript">逐字稿</label>
        <select id="add-tag-transcript" v-model="transcriptId">
          <option v-for="item in items" :key="item.id" :value="item.id">
            {{ transcriptTitle(item) }}
          </option>
        </select>
        <label for="add-tag-input">標籤名稱</label>
        <input
          id="add-tag-input"
          v-model="draft"
          type="text"
          maxlength="20"
          placeholder="標籤名稱"
          autocomplete="off"
        >
        <p v-if="tagError" class="error tag-add-error">{{ tagError }}</p>
        <div class="filter-menu-actions">
          <button type="submit" class="compact">加入</button>
          <button type="button" class="ghost compact" @click="close">取消</button>
        </div>
      </form>
      <p v-else class="hint">還沒有逐字稿可以加標籤。</p>
    </template>
  </FilterMenu>
</template>
