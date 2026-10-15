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
  emit("update:modelValue", draft.value);
  close();
}

function clear(close) {
  draft.value = "";
  emit("update:modelValue", "");
  close();
}
</script>

<template>
  <FilterMenu :active="Boolean(modelValue)" label="日曆搜尋">
    <template #toggle>
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3.5" y="5" width="17" height="15.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
        <path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" d="M8 3.5v4M16 3.5v4M3.5 10h17" />
      </svg>
      日曆搜尋
    </template>
    <template #panel="{ close }">
      <form @submit.prevent="apply(close)">
        <label for="date-search-input">日期</label>
        <input id="date-search-input" v-model="draft" type="date">
        <div class="filter-menu-actions">
          <button type="submit" class="compact">搜尋</button>
          <button v-if="modelValue" type="button" class="ghost compact" @click="clear(close)">清除</button>
        </div>
      </form>
    </template>
  </FilterMenu>
</template>
