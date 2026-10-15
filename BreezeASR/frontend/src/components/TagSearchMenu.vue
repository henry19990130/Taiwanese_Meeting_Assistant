<script setup>
import { ref, watch } from "vue";
import FilterMenu from "./FilterMenu.vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  tags: { type: Array, default: () => [] },
});

const emit = defineEmits(["update:modelValue"]);
const query = ref("");

watch(
  () => props.modelValue,
  (value) => {
    if (!value) {
      query.value = "";
    }
  },
);

function applyTag(tag, close) {
  emit("update:modelValue", tag);
  close();
}

function submitSearch(close) {
  emit("update:modelValue", query.value.trim());
  close();
}

function clearTag(close) {
  query.value = "";
  emit("update:modelValue", "");
  close();
}
</script>

<template>
  <FilterMenu :active="Boolean(modelValue)" label="標籤搜尋">
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
      標籤搜尋
    </template>
    <template #panel="{ close }">
      <form @submit.prevent="submitSearch(close)">
        <label for="tag-search-input">標籤名稱</label>
        <input
          id="tag-search-input"
          v-model="query"
          type="search"
          maxlength="20"
          placeholder="輸入你下過的標籤"
          autocomplete="off"
        >
        <div class="filter-menu-actions">
          <button type="submit" class="compact">搜尋</button>
          <button v-if="modelValue" type="button" class="ghost compact" @click="clearTag(close)">清除</button>
        </div>
      </form>
      <p v-if="tags.length === 0" class="hint">還沒有標籤。用標題旁的標籤圖示新增。</p>
      <div v-else class="tag-chip-row">
        <button
          v-for="tag in tags"
          :key="tag"
          type="button"
          class="tag-chip"
          :aria-pressed="modelValue === tag"
          @click="applyTag(tag, close)"
        >
          {{ tag }}
        </button>
      </div>
    </template>
  </FilterMenu>
</template>
