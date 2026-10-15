<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { createJob } from "../api/jobs";
import { deleteTranscript, deleteTranscriptSummary, getTranscript, listTranscripts, regenerateTranscriptSummary, suggestTranscriptTags, updateTranscriptSummary, updateTranscriptTags, updateTranscriptTitle } from "../api/transcripts";
import AddTagDialog from "../components/AddTagDialog.vue";
import AddTagMenu from "../components/AddTagMenu.vue";
import AppTopbar from "../components/AppTopbar.vue";
import DateSearchMenu from "../components/DateSearchMenu.vue";
import HistoryRow from "../components/HistoryRow.vue";
import NameSearchMenu from "../components/NameSearchMenu.vue";
import SummaryDialog from "../components/SummaryDialog.vue";
import TagSearchMenu from "../components/TagSearchMenu.vue";
import { useAuth } from "../composables/useAuth";
import { useConfirm } from "../composables/useConfirm";
import { useTranscriptFilters } from "../composables/useTranscriptFilters";

const router = useRouter();
const { state } = useAuth();
const { askConfirm } = useConfirm();

const file = ref(null);
const status = ref("");
const submitting = ref(false);
const history = ref([]);
const historyError = ref("");
const openRecord = ref(null);
const addingTag = ref(false);
const suggestedTags = ref([]);
const suggesting = ref(false);
const suggestError = ref("");
const summaryBusy = ref(false);
let suggestToken = 0;
const {
  nameQuery,
  dateQuery,
  tagQuery,
  allTags,
  visible,
} = useTranscriptFilters(history);

function onFileChange(event) {
  file.value = event.target.files && event.target.files[0] ? event.target.files[0] : null;
}

function replaceRecord(record) {
  history.value = history.value.map((item) => {
    if (item.id !== record.id) {
      return item;
    }
    const next = { ...item, ...record };
    delete next.summary;
    delete next.summary_log;
    return next;
  });
  if (openRecord.value && openRecord.value.id === record.id) {
    openRecord.value = {
      ...openRecord.value,
      ...record,
      summary: record.summary ?? openRecord.value.summary,
    };
  }
}

async function loadHistory() {
  try {
    history.value = await listTranscripts();
    historyError.value = "";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    history.value = [];
    historyError.value = "讀不到會議紀錄。";
  }
}

async function onSubmit() {
  if (!file.value) {
    status.value = "請先選擇音檔。";
    return;
  }
  submitting.value = true;
  status.value = "正在建立辨識工作。";
  try {
    const job = await createJob(file.value);
    await router.push({ path: "/progress", query: { job: job.id } });
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "無法開始辨識";
    submitting.value = false;
  }
}

async function onDelete(item) {
  const confirmed = await askConfirm({
    title: "確定刪除這筆會議紀錄？",
    body: `${item.title || item.source_filename} 會從列表移除，刪除前的摘要會留在日誌。`,
    confirmLabel: "確定刪除",
  });
  if (!confirmed) {
    return;
  }
  try {
    await deleteTranscript(item.id);
    if (openRecord.value && openRecord.value.id === item.id) {
      openRecord.value = null;
      closeAddTag();
    }
    status.value = "已刪除逐字稿。";
    await loadHistory();
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "刪除失敗";
  }
}

function closeAddTag() {
  suggestToken += 1;
  addingTag.value = false;
  suggesting.value = false;
}

async function openAddTag() {
  const record = openRecord.value;
  if (!record) {
    return;
  }
  addingTag.value = true;
  suggestedTags.value = [];
  suggestError.value = "";
  suggesting.value = true;
  const token = ++suggestToken;
  try {
    const result = await suggestTranscriptTags(record.id);
    if (token !== suggestToken) {
      return;
    }
    suggestedTags.value = Array.isArray(result.tags) ? result.tags : [];
  } catch (error) {
    if (token !== suggestToken) {
      return;
    }
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    suggestError.value = error.message || "無法推薦標籤";
  } finally {
    if (token === suggestToken) {
      suggesting.value = false;
    }
  }
}

async function onOpen(item) {
  try {
    openRecord.value = await getTranscript(item.id);
    status.value = "";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "讀不到會議摘要";
  }
}

async function onTitleChange(item, title) {
  try {
    const record = await updateTranscriptTitle(item.id, title);
    replaceRecord(record);
    status.value = "已更新標題。";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "標題更新失敗";
  }
}

async function onSaveSummary(item, summary) {
  try {
    const record = await updateTranscriptSummary(item.id, summary);
    replaceRecord(record);
    status.value = "已更新會議紀錄。";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "會議紀錄更新失敗";
  }
}

async function onDeleteSummary(item) {
  const confirmed = await askConfirm({
    title: "確定刪除這份摘要？",
    body: "目前摘要會清掉，刪除前的內容會留在日誌。",
    confirmLabel: "確定刪除",
  });
  if (!confirmed) {
    return;
  }
  try {
    const record = await deleteTranscriptSummary(item.id);
    replaceRecord(record);
    status.value = "已刪除摘要。";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "摘要刪除失敗";
  }
}

async function onRegenerate(item) {
  summaryBusy.value = true;
  status.value = "正在重新生成摘要。";
  try {
    const record = await regenerateTranscriptSummary(item.id);
    replaceRecord(record);
    status.value = "已重新生成摘要。";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "重新生成失敗";
  } finally {
    summaryBusy.value = false;
  }
}

async function onTagsChange(item, tags) {
  try {
    const record = await updateTranscriptTags(item.id, tags);
    replaceRecord(record);
    status.value = "已更新標籤。";
  } catch (error) {
    if (error.status === 401) {
      await router.push("/login");
      return;
    }
    status.value = error.message || "標籤更新失敗";
  }
}

onMounted(loadHistory);
</script>

<template>
  <div class="app-shell">
    <AppTopbar :user="state.user">
      <DateSearchMenu v-model="dateQuery" />
      <TagSearchMenu v-model="tagQuery" :tags="allTags" />
    </AppTopbar>
    <div class="stack">
      <header class="page-header">
        <p class="eyebrow">本地語音辨識</p>
        <h1>Breeze-ASR-26</h1>
        <p class="lead">本服務提供本地語音辨識功能，請將音檔上傳進行辨識，辨識完成後可查看逐字稿，逐字稿只屬於目前登入的帳號。</p>
      </header>

      <form id="upload-form" class="card" @submit.prevent="onSubmit">
        <label for="audio-file">音檔</label>
        <input id="audio-file" name="file" type="file" accept=".wav,.mp3,.m4a,.flac,.ogg,.webm,.mp4,.aac,audio/*,video/mp4,video/webm" @change="onFileChange">
        <p class="hint">支援 wav、mp3、m4a、flac、ogg、webm、mp4、aac，上限 200 MB。</p>
        <button id="submit" type="submit" :disabled="submitting">開始辨識</button>
        <p id="status" role="status">{{ status }}</p>
      </form>

      <SummaryDialog
        :record="openRecord"
        :busy="summaryBusy"
        @close="openRecord = null; closeAddTag()"
        @title-change="onTitleChange(openRecord, $event)"
        @add-tag="openAddTag"
        @tags-change="onTagsChange(openRecord, $event)"
        @save-summary="onSaveSummary(openRecord, $event)"
        @delete-summary="onDeleteSummary(openRecord)"
        @regenerate="onRegenerate(openRecord)"
      />
      <AddTagDialog
        :open="addingTag"
        :current-tags="openRecord ? openRecord.tags : []"
        :previous-tags="allTags"
        :suggested-tags="suggestedTags"
        :suggesting="suggesting"
        :suggest-error="suggestError"
        @close="closeAddTag"
        @add="onTagsChange(openRecord, [...(openRecord.tags || []), $event])"
      />

      <section class="card">
        <div class="section-head history-head">
          <h2>會議記錄摘要</h2>
          <div class="history-head-actions">
            <AddTagMenu
              :items="visible"
              :selected-id="openRecord ? openRecord.id : ''"
              @add="onTagsChange($event.item, [...($event.item.tags || []), $event.tag])"
            />
            <NameSearchMenu v-model="nameQuery" />
          </div>
        </div>
        <div id="history">
          <p v-if="historyError" class="empty">{{ historyError }}</p>
          <p v-else-if="history.length === 0" class="empty">還沒有會議紀錄。</p>
          <p v-else-if="visible.length === 0" class="empty">沒有符合條件的會議紀錄。</p>
          <ul v-else>
            <HistoryRow
              v-for="item in visible"
              :key="item.id"
              :item="item"
              @open="onOpen(item)"
              @delete="onDelete(item)"
              @tags-change="onTagsChange(item, $event)"
            />
          </ul>
        </div>
      </section>
    </div>
  </div>
</template>
