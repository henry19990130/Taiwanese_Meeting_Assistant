<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { formatTranscriptDate, transcriptTitle } from "../composables/useTranscriptFilters";
import MarkdownBody from "./MarkdownBody.vue";

const props = defineProps({
  record: { type: Object, default: null },
  busy: { type: Boolean, default: false },
});

const emit = defineEmits(["close", "title-change", "add-tag", "tags-change", "save-summary", "delete-summary", "regenerate"]);
const dialogEl = ref(null);
const titleInput = ref(null);
const summaryInput = ref(null);
const editingTitle = ref(false);
const editingSummary = ref(false);
const titleDraft = ref("");
const summaryDraft = ref("");
const titleError = ref("");
const summaryError = ref("");
const view = ref("summary");
const historyAction = ref("edit");
const historyIndex = ref(0);

const historyVersions = computed(() => {
  const versions = (props.record && props.record.summary_log && props.record.summary_log.versions) || [];
  return versions.filter((item) => item.action === historyAction.value);
});

const selectedHistory = computed(() => historyVersions.value[historyIndex.value] || null);

watch(
  () => props.record,
  async (record) => {
    await nextTick();
    const el = dialogEl.value;
    if (!el) {
      return;
    }
    if (record) {
      if (!el.open) {
        el.showModal();
      }
      return;
    }
    resetDrafts();
    if (el.open) {
      el.close();
    }
  },
);

watch(
  () => props.record && props.record.id,
  () => {
    resetDrafts();
  },
);

function resetDrafts() {
  editingTitle.value = false;
  editingSummary.value = false;
  titleDraft.value = "";
  summaryDraft.value = "";
  titleError.value = "";
  summaryError.value = "";
  view.value = "summary";
  historyAction.value = "edit";
  historyIndex.value = 0;
}

async function startEditTitle() {
  titleDraft.value = transcriptTitle(props.record);
  titleError.value = "";
  editingTitle.value = true;
  await nextTick();
  titleInput.value?.focus();
  titleInput.value?.select();
}

function cancelEditTitle() {
  editingTitle.value = false;
  titleError.value = "";
}

function saveTitle() {
  const title = titleDraft.value.trim();
  if (!title) {
    titleError.value = "標題不能是空白";
    return;
  }
  emit("title-change", title);
  editingTitle.value = false;
  titleError.value = "";
}

function removeTag(tag) {
  emit(
    "tags-change",
    (props.record.tags || []).filter((value) => value !== tag),
  );
}

function showTranscript() {
  editingSummary.value = false;
  view.value = view.value === "transcript" ? "summary" : "transcript";
}

function historyTitle(action) {
  if (action === "regenerate") {
    return "重新生成紀錄";
  }
  if (action === "delete") {
    return "刪除紀錄";
  }
  return "編輯紀錄";
}

function historyLabel(action) {
  if (action === "regenerate") {
    return "重新編輯";
  }
  if (action === "delete") {
    return "已刪除";
  }
  return "已編輯";
}

function showHistory(action) {
  editingSummary.value = false;
  historyAction.value = action;
  historyIndex.value = 0;
  view.value = "history";
}

async function startEditSummary() {
  summaryDraft.value = props.record.summary || "";
  summaryError.value = "";
  view.value = "summary";
  editingSummary.value = true;
  await nextTick();
  summaryInput.value?.focus();
}

function cancelEditSummary() {
  editingSummary.value = false;
  summaryError.value = "";
}

function saveSummary() {
  const summary = summaryDraft.value.trim();
  if (!summary) {
    summaryError.value = "會議紀錄不能是空白";
    return;
  }
  emit("save-summary", summary);
  editingSummary.value = false;
  summaryError.value = "";
}
</script>

<template>
  <dialog
    ref="dialogEl"
    class="summary-dialog"
    @close="emit('close')"
  >
    <div class="section-head">
      <div v-if="record" class="summary-title-row">
        <form v-if="editingTitle" class="summary-title-form" @submit.prevent="saveTitle">
          <input
            ref="titleInput"
            v-model="titleDraft"
            type="text"
            maxlength="80"
            aria-label="會議標題"
            @keydown.esc.prevent="cancelEditTitle"
          >
        </form>
        <h2 v-else>{{ transcriptTitle(record) }}</h2>
        <button
          type="button"
          class="icon-btn ghost"
          :aria-label="editingTitle ? '儲存標題' : '編輯標題'"
          @click="editingTitle ? saveTitle() : startEditTitle()"
        >
          <svg v-if="editingTitle" class="icon" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M5 12.5 10 17.5 19 7.5" />
          </svg>
          <svg v-else class="icon" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M13.4 5.6 18.4 10.6M4 20l1.3-6.3L16.2 2.8a2.1 2.1 0 0 1 3 3L8.3 16.7 4 20Z" />
          </svg>
        </button>
      </div>
      <h2 v-else>會議記錄摘要</h2>
      <div class="summary-head-tools">
        <button v-if="record" type="button" class="ghost compact" @click="showTranscript">
          {{ view === "transcript" ? "會議摘要" : "逐字稿原稿" }}
        </button>
        <button type="button" class="ghost compact" @click="emit('close')">關閉</button>
      </div>
    </div>
    <p v-if="titleError" class="error tag-add-error">{{ titleError }}</p>
    <p v-if="!record" class="empty">讀取中。</p>
    <template v-else>
      <div class="summary-tag-row">
        <svg class="icon tag-icon" viewBox="0 0 24 24" aria-hidden="true">
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
        <div class="tag-chip-row">
          <span v-for="tag in record.tags || []" :key="tag" class="tag-chip">
            {{ tag }}
            <button type="button" class="tag-remove" :aria-label="`移除標籤 ${tag}`" @click="removeTag(tag)">×</button>
          </span>
          <button
            v-if="(record.tags || []).length < 8"
            type="button"
            class="tag-chip summary-add-tag"
            @click="emit('add-tag')"
          >
            新增標籤
          </button>
        </div>
      </div>
      <p class="history-date">
        <svg class="icon calendar-icon" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="15.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
          <path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" d="M8 3.5v4M16 3.5v4M3.5 10h17" />
        </svg>
        {{ formatTranscriptDate(record.created_at) }}
      </p>
      <hr class="summary-dialog-rule">
      <div v-if="view === 'summary' && !editingSummary" class="summary-log-row">
        <div class="summary-log-links">
          <button
            v-if="record.summary_log && record.summary_log.edited"
            type="button"
            class="summary-log-link"
            @click="showHistory('edit')"
          >
            已編輯
          </button>
          <button
            v-if="record.summary_log && record.summary_log.regenerated"
            type="button"
            class="summary-log-link"
            @click="showHistory('regenerate')"
          >
            重新編輯
          </button>
          <button
            v-if="record.summary_log && record.summary_log.deleted"
            type="button"
            class="summary-log-link"
            @click="showHistory('delete')"
          >
            已刪除
          </button>
        </div>
        <div class="summary-log-actions">
          <button type="button" class="ghost compact" @click="startEditSummary">修改紀錄</button>
          <button
            v-if="(record.summary || '').trim()"
            type="button"
            class="danger compact"
            @click="emit('delete-summary')"
          >
            刪除摘要
          </button>
        </div>
      </div>
      <form v-if="editingSummary" class="summary-editor" @submit.prevent="saveSummary">
        <textarea
          ref="summaryInput"
          v-model="summaryDraft"
          aria-label="會議紀錄"
          @keydown.esc.prevent="cancelEditSummary"
        ></textarea>
        <p v-if="summaryError" class="error tag-add-error">{{ summaryError }}</p>
        <div class="summary-editor-actions">
          <button type="submit" class="compact">儲存</button>
          <button type="button" class="ghost compact" @click="cancelEditSummary">取消</button>
        </div>
      </form>
      <template v-else-if="view === 'transcript'">
        <div class="summary-view-bar">
          <p class="hint">逐字稿原稿</p>
        </div>
        <p class="summary-source">{{ record.text || "（沒有逐字稿）" }}</p>
      </template>
      <template v-else-if="view === 'history'">
        <div class="summary-view-bar">
          <p class="hint">{{ historyTitle(historyAction) }}</p>
          <button type="button" class="ghost compact" @click="view = 'summary'">回到會議摘要</button>
        </div>
        <div v-if="historyVersions.length" class="summary-version-list">
          <button
            v-for="(item, index) in historyVersions"
            :key="`${item.action}-${item.at}-${index}`"
            type="button"
            class="tag-chip"
            :aria-pressed="index === historyIndex"
            @click="historyIndex = index"
          >
            {{ historyLabel(item.action) }} {{ formatTranscriptDate(item.at) }}
          </button>
        </div>
        <MarkdownBody :source="selectedHistory ? selectedHistory.summary : ''" empty="（這版沒有留下摘要）" />
      </template>
      <MarkdownBody v-else :source="record.summary || ''" />
      <div v-if="view !== 'transcript' && !editingSummary" class="summary-regenerate">
        <button type="button" :disabled="busy" @click="emit('regenerate')">
          {{ busy ? "正在重新生成…" : "重新生成摘要" }}
        </button>
      </div>
    </template>
  </dialog>
</template>
