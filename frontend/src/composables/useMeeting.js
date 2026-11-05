import { $, showError } from "../lib/dom.js";
import { api } from "./useApi.js";
import { meeting } from "../state.js";
import { views, actions } from "../views.js";
import { loadGlossary, openGlossary } from "./useGlossary.js";

const STEP_ORDER = ["uploaded", "transcribing", "proofreading", "reviewing", "summarizing", "completed"];
const STATUS_TEXT = {
  uploaded: "已上傳，等待處理…",
  transcribing: "正在辨識語音（會先載入這個語言的模型，辨識完就關閉）…",
  proofreading: "AI 正在校對逐字稿的錯字（約需幾分鐘）…",
  reviewing: "請確認逐字稿：AI 找到的疑似錯字可以逐處套用、自己改、保留原文，或一鍵全部套用。確認後才能產生重點。",
  transcribed: "逐字稿已確認，可以按「產生重點」。",
  summarizing: "正在用確認過的逐字稿產生會議重點（約需幾分鐘）…",
  completed: "已完成。",
  failed: "處理失敗。",
};
export const ASR_LANG_INFO = {
  zh: { label: "中文", model: "Breeze-ASR-25" },
  nan: { label: "台語", model: "Breeze-ASR-26" },
  hak: { label: "客語", model: "whisper-large-v3-taiwanese-hakka" },
  en: { label: "英文", model: "Qwen3-ASR-1.7B" },
};

let uploadBound = false;
let progressBound = false;

export function stopPolling() {
  if (meeting.pollTimer) clearInterval(meeting.pollTimer);
  meeting.pollTimer = null;
}

export function haltMeeting() {
  stopPolling();
  meeting.meetingId = null;
  meeting.status = null;
  meeting.failedStage = null;
  meeting.transcript = null;
  meeting.summary = null;
  meeting.proofread = null;
  meeting.summaryLangTouched = false;
}

export function setSource(source) {
  const form = $("uploadForm");
  if (!form) return;
  const radio = form.querySelector(`input[name=source][value=${source}]`);
  if (radio) radio.checked = true;
  const isAudio = source === "audio";
  $("audioField").hidden = !isAudio;
  $("asrLangField").hidden = !isAudio;
  $("transcriptField").hidden = isAudio;
  form.elements.audio.required = isAudio;
  form.elements.transcript.required = !isAudio;
}

export function setAsrLanguage(lang) {
  const form = $("uploadForm");
  if (!form) return;
  const input = form.querySelector(`input[name=asr_language][value=${lang}]`) || form.querySelector("input[name=asr_language]");
  if (!input) return;
  input.checked = true;
  const info = ASR_LANG_INFO[input.value] || ASR_LANG_INFO.zh;
  $("dialectField").hidden = input.value !== "hak";
  $("asrLangHint").textContent = `辨識時只啟動 ${info.model}，辨識完就關閉，不占記憶體`;
}

export function resetMeeting() {
  stopPolling();
  views.assistantStatus(null);
  haltMeeting();
  const form = $("uploadForm");
  if (form) {
    form.reset();
    form.elements.date.value = new Date().toLocaleDateString("sv-SE");
  }
  setSource("audio");
  setAsrLanguage("zh");
  views.deskStatus("new");
  const upload = $("uploadCard");
  if (upload) upload.hidden = false;
  for (const id of ["progressCard", "transcriptCard", "summaryCard"]) {
    const node = $(id);
    if (node) node.hidden = true;
  }
  showError($("uploadError"), "");
}

function transcriptLang() {
  if (meeting.proofread && meeting.proofread.language) return meeting.proofread.language;
  const text = ((meeting.transcript && meeting.transcript.segments) || []).map((s) => s.text || "").join(" ");
  const lat = (text.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).length;
  const cjk = (text.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  return lat + cjk && lat / (lat + cjk) >= 0.6 ? "en" : "zh";
}

function syncSummaryLang() {
  if (meeting.summaryLangTouched) return;
  const done = meeting.summary && meeting.summary.summary && meeting.summary.summary.language;
  const sel = $("summaryLang");
  if (sel) sel.value = done || transcriptLang();
}

export function renderStatus({ status, error }) {
  meeting.status = status;
  meeting.failedStage = status === "failed" && error ? error.stage : null;
  const failedStage = meeting.failedStage;
  const current = failedStage || (status === "transcribed" ? "summarizing" : status);
  const working = ["uploaded", "transcribing", "proofreading", "reviewing", "summarizing"].includes(status);
  const idx = STEP_ORDER.indexOf(current);
  const steps = $("steps");
  if (steps) {
    for (const li of steps.children) {
      const i = STEP_ORDER.indexOf(li.dataset.step);
      li.className = "";
      if (failedStage && li.dataset.step === failedStage) li.className = "failed";
      else if (i < idx || status === "completed") li.className = "done";
      else if (i === idx && working) li.className = status === "reviewing" ? "active user" : "active";
    }
  }
  const statusText = $("statusText");
  if (statusText) statusText.textContent = STATUS_TEXT[status] || status;
  showError($("jobError"), status === "failed" && error ? error.message : "");

  const canSummarize = ["transcribed", "completed"].includes(status)
    || (status === "failed" && failedStage === "summarizing");
  const summarizeBtn = $("summarizeBtn");
  if (summarizeBtn) {
    summarizeBtn.hidden = !(canSummarize || status === "summarizing");
    summarizeBtn.disabled = !canSummarize;
    summarizeBtn.textContent = status === "completed" ? "重新產生重點"
      : status === "summarizing" ? "產生中…" : "產生重點";
  }
  const wrap = $("summaryLangWrap");
  if (wrap && summarizeBtn) wrap.hidden = summarizeBtn.hidden;
  const lang = $("summaryLang");
  if (lang) lang.disabled = !canSummarize;
  const confirmBtn = $("confirmBtn");
  if (confirmBtn) confirmBtn.hidden = status !== "reviewing";
  views.assistantStatus(status);
  views.deskStatus(status, failedStage);
  views.updateReviewUI();
}

export async function loadTranscript() {
  try {
    const [t, p] = await Promise.all([
      api(`/api/v1/meetings/${meeting.meetingId}/transcript`),
      api(`/api/v1/meetings/${meeting.meetingId}/proofread`),
    ]);
    meeting.transcript = t;
    meeting.proofread = p;
  } catch (err) {
    showError($("jobError"), `讀取逐字稿失敗：${err.message}`);
    return;
  }
  syncSummaryLang();
  views.resetReview();
  views.renderTranscript();
  views.updateReviewUI();
  if (meeting.status === "reviewing") views.gotoTypo(views.nextPending(-1), false);
  const card = $("transcriptCard");
  if (card) card.hidden = false;
}

export async function loadSummary() {
  let data;
  try { data = await api(`/api/v1/meetings/${meeting.meetingId}/summary`); }
  catch (err) { showError($("jobError"), `讀取重點失敗：${err.message}`); return; }
  meeting.summary = data;
  syncSummaryLang();
  views.renderSnapshot(data);
  const card = $("summaryCard");
  if (card) card.hidden = false;
}

function startPolling() {
  stopPolling();
  meeting.pollTimer = setInterval(checkStatus, 2000);
  checkStatus();
}

async function checkStatus() {
  if (!meeting.meetingId) return;
  let data;
  try {
    data = await api(`/api/v1/meetings/${meeting.meetingId}/status`);
  } catch (err) {
    const statusText = $("statusText");
    if (statusText) statusText.textContent = `查詢進度失敗：${err.message}（會自動重試）`;
    return;
  }
  const changed = data.status !== meeting.status;
  renderStatus(data);
  const failedStage = data.status === "failed" && data.error ? data.error.stage : null;
  const hasTranscript = ["proofreading", "reviewing", "transcribed", "summarizing", "completed"].includes(data.status)
    || ["proofreading", "summarizing"].includes(failedStage);
  if (hasTranscript && (!meeting.transcript || (changed && data.status !== "summarizing"))) await loadTranscript();
  const summaryCard = $("summaryCard");
  if (data.status === "completed" && (changed || (summaryCard && summaryCard.hidden))) await loadSummary();
  if (["reviewing", "transcribed", "completed", "failed"].includes(data.status)) stopPolling();
}

export async function openMeeting(meetingId, segmentId) {
  if (!meetingId) return;
  stopPolling();
  meeting.meetingId = meetingId;
  meeting.status = null;
  meeting.transcript = null;
  meeting.summary = null;
  meeting.proofread = null;
  meeting.summaryLangTouched = false;
  meeting.failedStage = null;
  for (const id of ["transcriptCard", "summaryCard"]) {
    const node = $(id);
    if (node) node.hidden = true;
  }
  let st;
  try { st = await api(`/api/v1/meetings/${meetingId}/status`); }
  catch (err) { showError($("jobError"), `開啟會議失敗：${err.message}`); return; }
  const title = $("meetingTitle");
  if (title) title.textContent = st.meeting_name;
  const step = $("stepTranscribing");
  if (step) step.textContent = st.source_type === "transcript" ? "自動分段" : "語音辨識";
  $("uploadCard").hidden = true;
  $("progressCard").hidden = false;
  renderStatus(st);
  await loadTranscript();
  if (st.status === "completed") await loadSummary();
  if (["uploaded", "transcribing", "proofreading", "summarizing"].includes(st.status)) startPolling();
  if (segmentId) setTimeout(() => import("../lib/jump.js").then((m) => m.jumpTo(segmentId)), 250);
  else $("progressCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function submitUpload(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  for (const k of ["start_time", "end_time"]) if (!form.get(k)) form.delete(k);
  const source = form.get("source");
  form.delete("source");
  form.delete(source === "audio" ? "transcript" : "audio");
  const asrLang = form.get("asr_language");
  if (source !== "audio") { form.delete("asr_language"); form.delete("hakka_dialect"); }
  else if (asrLang !== "hak") form.delete("hakka_dialect");
  showError($("uploadError"), "");
  const btn = $("uploadBtn");
  btn.disabled = true;
  btn.textContent = "上傳中…";
  try {
    const data = await api("/api/v1/meetings", { method: "POST", form });
    meeting.meetingId = data.meeting_id;
    $("meetingTitle").textContent = data.meeting_name;
    $("stepTranscribing").textContent = data.source_type === "transcript" ? "自動分段"
      : `語音辨識（${(ASR_LANG_INFO[asrLang] || ASR_LANG_INFO.zh).label}）`;
    $("uploadCard").hidden = true;
    $("progressCard").hidden = false;
    renderStatus({ status: data.status, error: null });
    startPolling();
  } catch (err) {
    showError($("uploadError"), err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "開始整理";
  }
}

export async function confirmTranscript() {
  const n = meeting.proofread ? meeting.proofread.counts.pending : 0;
  if (n && !window.confirm(`還有 ${n} 處疑似錯字沒處理，確認後這些地方會保留原文。確定要確認逐字稿嗎？`)) return;
  const btn = $("confirmBtn");
  btn.disabled = true;
  try {
    const data = await api(`/api/v1/meetings/${meeting.meetingId}/transcript/confirm`, { method: "POST" });
    views.resetReview();
    renderStatus({ status: data.status, error: null });
    await loadTranscript();
  } catch (err) { showError($("rpError"), err.message); }
  finally { btn.disabled = false; }
}

export async function reproof() {
  try {
    const data = await api(`/api/v1/meetings/${meeting.meetingId}/proofread`, { method: "POST" });
    renderStatus({ status: data.status, error: null });
    startPolling();
  } catch (err) { showError($("jobError"), err.message); }
}

export async function summarize() {
  const btn = $("summarizeBtn");
  btn.disabled = true;
  try {
    const data = await api(`/api/v1/meetings/${meeting.meetingId}/summary`, {
      method: "POST", json: { language: $("summaryLang").value },
    });
    renderStatus({ status: data.status, error: null });
    startPolling();
  } catch (err) {
    showError($("jobError"), err.message);
    btn.disabled = false;
  }
}

export function mountUpload() {
  if (uploadBound) return;
  uploadBound = true;
  const form = $("uploadForm");
  form.addEventListener("submit", submitUpload);
  for (const r of form.querySelectorAll("input[name=source]")) {
    r.addEventListener("change", () => setSource(r.value));
  }
  for (const r of form.querySelectorAll("input[name=asr_language]")) {
    r.addEventListener("change", () => setAsrLanguage(r.value));
  }
  $("glossaryBtn").addEventListener("click", openGlossary);
}

export function mountProgress() {
  if (progressBound) return;
  progressBound = true;
  $("newMeetingBtn").addEventListener("click", resetMeeting);
}

export function afterEnter() {
  resetMeeting();
  loadGlossary();
}

actions.confirm = confirmTranscript;
actions.reproof = reproof;
actions.summarize = summarize;
actions.openMeeting = openMeeting;
