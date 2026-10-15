<script setup>
import { computed, nextTick, ref, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  currentTags: { type: Array, default: () => [] },
  previousTags: { type: Array, default: () => [] },
  suggestedTags: { type: Array, default: () => [] },
  suggesting: { type: Boolean, default: false },
  suggestError: { type: String, default: "" },
});

const emit = defineEmits(["close", "add"]);
const dialogEl = ref(null);
const inputEl = ref(null);
const draft = ref("");
const error = ref("");

function unused(tags) {
  const used = new Set((props.currentTags || []).map((tag) => String(tag).toLocaleLowerCase("zh-Hant")));
  return (tags || []).filter((tag) => !used.has(String(tag).toLocaleLowerCase("zh-Hant")));
}

const suggested = computed(() => unused(props.suggestedTags));
const previous = computed(() => {
  const suggestedKeys = new Set(suggested.value.map((tag) => String(tag).toLocaleLowerCase("zh-Hant")));
  return unused(props.previousTags).filter((tag) => !suggestedKeys.has(String(tag).toLocaleLowerCase("zh-Hant")));
});
const atLimit = computed(() => (props.currentTags || []).length >= 8);

watch(
  () => props.open,
  async (open) => {
    await nextTick();
    const el = dialogEl.value;
    if (!el) {
      return;
    }
    if (open) {
      draft.value = "";
      error.value = "";
      if (!el.open) {
        el.showModal();
      }
      await nextTick();
      inputEl.value?.focus();
      return;
    }
    if (el.open) {
      el.close();
    }
  },
);

function submit(tag) {
  const value = String(tag || "").trim();
  if (atLimit.value) {
    error.value = "一筆紀錄最多 8 個標籤";
    return;
  }
  if (!value) {
    error.value = "請輸入標籤名稱";
    return;
  }
  const exists = (props.currentTags || []).some(
    (item) => item.toLocaleLowerCase("zh-Hant") === value.toLocaleLowerCase("zh-Hant"),
  );
  if (exists) {
    error.value = "這個標籤已經在這筆紀錄上";
    return;
  }
  emit("add", value);
  draft.value = "";
  error.value = "";
}

function onClose() {
  draft.value = "";
  error.value = "";
  emit("close");
}
</script>

<template>
  <dialog ref="dialogEl" class="add-tag-dialog" @close="onClose">
    <div class="section-head">
      <h2>新增標籤</h2>
      <button type="button" class="ghost compact" @click="onClose">關閉</button>
    </div>
    <form class="add-tag-dialog-form" @submit.prevent="submit(draft)">
      <label for="add-tag-name">標籤名稱</label>
      <input
        id="add-tag-name"
        ref="inputEl"
        v-model="draft"
        type="text"
        maxlength="20"
        placeholder="自己輸入，或從下方挑選"
        autocomplete="off"
      >
      <p v-if="error" class="error tag-add-error">{{ error }}</p>
      <div class="filter-menu-actions">
        <button type="submit" class="compact" :disabled="atLimit">加入</button>
        <button type="button" class="ghost compact" @click="onClose">取消</button>
      </div>
    </form>
    <section class="add-tag-group">
      <h3>建議標籤</h3>
      <p v-if="suggesting" class="hint">正在依這份內容推薦標籤。</p>
      <p v-else-if="suggestError" class="error">{{ suggestError }}</p>
      <div v-else-if="suggested.length" class="tag-chip-row">
        <button
          v-for="tag in suggested"
          :key="`suggest-${tag}`"
          type="button"
          class="tag-chip"
          :disabled="atLimit"
          @click="submit(tag)"
        >
          {{ tag }}
        </button>
      </div>
      <p v-else class="hint">這份內容沒有可推薦的標籤。</p>
    </section>
    <section class="add-tag-group">
      <h3>以往標籤</h3>
      <div v-if="previous.length" class="tag-chip-row">
        <button
          v-for="tag in previous"
          :key="`prev-${tag}`"
          type="button"
          class="tag-chip"
          :disabled="atLimit"
          @click="submit(tag)"
        >
          {{ tag }}
        </button>
      </div>
      <p v-else class="hint">還沒有其他用過的標籤。</p>
    </section>
  </dialog>
</template>
