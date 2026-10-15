<script setup>
import { ref, watch } from "vue";
import FilterMenu from "./FilterMenu.vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue"]);
const draft = ref(props.modelValue);

watch(
  () => props.modelValue,
  (value) => {
    draft.value = value;
  },
);

function apply(close) {
  emit("update:modelValue", draft.value.trim());
  close();
}

function clear(close) {
  draft.value = "";
  emit("update:modelValue", "");
  close();
}
</script>

<template>
  <FilterMenu :active="Boolean(modelValue)" label="搜尋檔名" icon-only>
    <template #toggle>
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="10.5" cy="10.5" r="6.2" fill="none" stroke="currentColor" stroke-width="1.8" />
        <path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" d="m15.2 15.2 5 5" />
      </svg>
    </template>
    <template #panel="{ close }">
      <form @submit.prevent="apply(close)">
        <label for="name-search-input">文件名稱</label>
        <input
          id="name-search-input"
          v-model="draft"
          type="search"
          placeholder="搜尋文件名稱"
          autocomplete="off"
        >
        <div class="filter-menu-actions">
          <button type="submit" class="compact">搜尋</button>
          <button v-if="modelValue" type="button" class="ghost compact" @click="clear(close)">清除</button>
        </div>
      </form>
    </template>
  </FilterMenu>
</template>
