const state = {
  token: null,
  user: null,
  meetingId: null,
  status: null,
  transcript: null,
  summary: null,
  summaryLangTouched: false,
  proofread: null,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);
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

async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form !== undefined) body = form;

  const res = await fetch(path, { method, headers, body });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && state.token) { logoutLocal("登入已失效，請重新登入"); }
  if (!res.ok) {
    const d = data.detail;
    const msg = (d && d.message) || (Array.isArray(d) ? "輸入格式不正確" : null) || `錯誤 ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function showError(el, msg) { el.textContent = msg; el.hidden = !msg; }

function showAuth(which, message) {
  const register = which === "register";
  $("loginForm").hidden = register;
  $("registerForm").hidden = !register;
  showError($("loginError"), register ? "" : (message || ""));
  showError($("registerError"), "");
}

function accountOk(name) { return /^[A-Za-z0-9_]{3,32}$/.test(name); }
function passwordOk(password) {
  return password.length >= 12 && password.length <= 200 && /[A-Za-z]/.test(password) && /[0-9]/.test(password);
}

async function enterRoom(data, form) {
  state.token = data.access_token;
  state.user = data.user;
  form.reset();
  showAuth("login");
  if (window.Entrance) await Entrance.close(state.user.username);
  showApp();
  if (window.Entrance) Entrance.open();
}

$("showRegister").addEventListener("click", () => showAuth("register"));
$("showLogin").addEventListener("click", () => showAuth("login"));

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  showError($("loginError"), "");
  try {
    const data = await api("/api/v1/auth/login", {
      method: "POST", json: { username: f.get("username"), password: f.get("password") },
    });
    await enterRoom(data, e.target);
  } catch (err) { showError($("loginError"), err.message); }
});

$("registerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const username = String(f.get("username") || "").trim();
  const password = String(f.get("password") || "");
  const again = String(f.get("password2") || "");
  showError($("registerError"), "");
  if (!accountOk(username)) {
    showError($("registerError"), "帳號只允許 3 到 32 碼的英數字或底線");
    return;
  }
  if (!passwordOk(password)) {
    showError($("registerError"), "密碼至少 12 碼，而且要同時含英文字母和數字");
    return;
  }
  if (password !== again) {
    showError($("registerError"), "兩次輸入的密碼不相同");
    return;
  }
  try {
    const data = await api("/api/v1/auth/register", {
      method: "POST", json: { username, password },
    });
    await enterRoom(data, e.target);
  } catch (err) { showError($("registerError"), err.message); }
});

$("logoutBtn").addEventListener("click", async () => {
  try { await api("/api/v1/auth/logout", { method: "POST" }); } catch (_) {  }
  logoutLocal();
});

function logoutLocal(message) {
  stopPolling();
  if (window.assistant) window.assistant.onLogout();
  Object.assign(state, { token: null, user: null, meetingId: null, status: null, transcript: null, summary: null, proofread: null });
  $("appView").hidden = true;
  $("userBox").hidden = true;
  $("loginView").hidden = false;
  document.body.classList.add("login-mode");
  if (window.Entrance) Entrance.greet();
  showAuth("login", message || "");
}

function showApp() {
  document.body.classList.remove("login-mode");
  $("loginView").hidden = true;
  $("appView").hidden = false;
  $("userBox").hidden = false;
  $("userName").textContent = state.user.username;
  if (window.Entrance) Entrance.greet(state.user.username);
  resetMeeting();
  if (typeof loadGlossary === "function") loadGlossary();
  if (window.assistant) window.assistant.onLogin();
  if (window.MeetUI) MeetUI.loadInfo();
}

function resetMeeting() {
  stopPolling();
  if (window.assistant) window.assistant.onStatus(null);
  Object.assign(state, { meetingId: null, status: null, transcript: null, summary: null, proofread: null, summaryLangTouched: false });
  $("uploadForm").reset();
  $("uploadForm").elements.date.value = new Date().toLocaleDateString("sv-SE");
  setSource("audio");
  setAsrLanguage("zh");
  if (window.MeetUI) MeetUI.onStatus("new");
  $("uploadCard").hidden = false;
  for (const id of ["progressCard", "transcriptCard", "summaryCard"]) $(id).hidden = true;
  showError($("uploadError"), "");
}
$("newMeetingBtn").addEventListener("click", resetMeeting);

function setSource(source) {
  const form = $("uploadForm");
  form.querySelector(`input[name=source][value=${source}]`).checked = true;
  const isAudio = source === "audio";
  $("audioField").hidden = !isAudio;
  $("asrLangField").hidden = !isAudio;
  $("transcriptField").hidden = isAudio;
  form.elements.audio.required = isAudio;
  form.elements.transcript.required = !isAudio;
}
for (const r of document.querySelectorAll("input[name=source]")) {
  r.addEventListener("change", () => setSource(r.value));
}

const ASR_LANG_INFO = {
  zh:  { label: "中文", model: "Breeze-ASR-25" },
  nan: { label: "台語", model: "Breeze-ASR-26" },
  hak: { label: "客語", model: "whisper-large-v3-taiwanese-hakka" },
  en:  { label: "英文", model: "Qwen3-ASR-1.7B" },
};
function setAsrLanguage(lang) {
  const form = $("uploadForm");
  const input = form.querySelector(`input[name=asr_language][value=${lang}]`) || form.querySelector("input[name=asr_language]");
  input.checked = true;
  const info = ASR_LANG_INFO[input.value];
  $("dialectField").hidden = input.value !== "hak";
  $("asrLangHint").textContent = `辨識時只啟動 ${info.model}，辨識完就關閉，不占記憶體`;
}
for (const r of document.querySelectorAll("input[name=asr_language]")) {
  r.addEventListener("change", () => setAsrLanguage(r.value));
}

$("uploadForm").addEventListener("submit", async (e) => {
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
  $("uploadBtn").disabled = true;
  $("uploadBtn").textContent = "上傳中…";
  try {
    const data = await api("/api/v1/meetings", { method: "POST", form });
    state.meetingId = data.meeting_id;
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
    $("uploadBtn").disabled = false;
    $("uploadBtn").textContent = "開始整理";
  }
});

async function openMeeting(meetingId, segmentId) {
  if (!meetingId) return;
  stopPolling();
  Object.assign(state, { meetingId, status: null, transcript: null, summary: null, proofread: null, summaryLangTouched: false });
  for (const id of ["transcriptCard", "summaryCard"]) $(id).hidden = true;
  let st;
  try { st = await api(`/api/v1/meetings/${meetingId}/status`); }
  catch (err) { showError($("jobError"), `開啟會議失敗：${err.message}`); return; }
  $("meetingTitle").textContent = st.meeting_name;
  $("stepTranscribing").textContent = st.source_type === "transcript" ? "自動分段" : "語音辨識";
  $("uploadCard").hidden = true;
  $("progressCard").hidden = false;
  renderStatus(st);
  await loadTranscript();
  if (st.status === "completed") await loadSummary();
  if (["uploaded", "transcribing", "proofreading", "summarizing"].includes(st.status)) startPolling();
  if (segmentId) setTimeout(() => jumpTo(segmentId), 250);
  else $("progressCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(checkStatus, 2000);
  checkStatus();
}
function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function checkStatus() {
  if (!state.meetingId) return;
  let data;
  try {
    data = await api(`/api/v1/meetings/${state.meetingId}/status`);
  } catch (err) {
    $("statusText").textContent = `查詢進度失敗：${err.message}（會自動重試）`;
    return;
  }
  const changed = data.status !== state.status;
  renderStatus(data);

  const failedStage = data.status === "failed" && data.error ? data.error.stage : null;
  const hasTranscript = ["proofreading", "reviewing", "transcribed", "summarizing", "completed"].includes(data.status)
    || ["proofreading", "summarizing"].includes(failedStage);
  if (hasTranscript && (!state.transcript || (changed && data.status !== "summarizing"))) await loadTranscript();
  if (data.status === "completed" && (changed || $("summaryCard").hidden)) await loadSummary();
  if (["reviewing", "transcribed", "completed", "failed"].includes(data.status)) stopPolling();
}

function renderStatus({ status, error }) {
  state.status = status;
  state.failedStage = status === "failed" && error ? error.stage : null;
  const failedStage = state.failedStage;
  const current = failedStage || (status === "transcribed" ? "summarizing" : status);
  const working = ["uploaded", "transcribing", "proofreading", "reviewing", "summarizing"].includes(status);
  const idx = STEP_ORDER.indexOf(current);
  for (const li of $("steps").children) {
    const i = STEP_ORDER.indexOf(li.dataset.step);
    li.className = "";
    if (failedStage && li.dataset.step === failedStage) li.className = "failed";
    else if (i < idx || status === "completed") li.className = "done";
    else if (i === idx && working) li.className = status === "reviewing" ? "active user" : "active";
  }
  $("statusText").textContent = STATUS_TEXT[status] || status;
  showError($("jobError"), status === "failed" && error ? error.message : "");

  const canSummarize = ["transcribed", "completed"].includes(status)
    || (status === "failed" && failedStage === "summarizing");
  $("summarizeBtn").hidden = !(canSummarize || status === "summarizing");
  $("summarizeBtn").disabled = !canSummarize;
  $("summarizeBtn").textContent = status === "completed" ? "重新產生重點"
    : status === "summarizing" ? "產生中…" : "產生重點";
  $("summaryLangWrap").hidden = $("summarizeBtn").hidden;
  $("summaryLang").disabled = !canSummarize;
  $("confirmBtn").hidden = status !== "reviewing";
  if (window.assistant) window.assistant.onStatus(status);
  if (window.MeetUI) MeetUI.onStatus(status, failedStage);
  updateReviewUI();
}

async function loadTranscript() {
  try {
    const [t, p] = await Promise.all([
      api(`/api/v1/meetings/${state.meetingId}/transcript`),
      api(`/api/v1/meetings/${state.meetingId}/proofread`),
    ]);
    state.transcript = t;
    state.proofread = p;
  } catch (err) { showError($("jobError"), `讀取逐字稿失敗：${err.message}`); return; }
  syncSummaryLang();
  review.index = -1;
  renderTranscript();
  updateReviewUI();
  if (state.status === "reviewing") gotoTypo(nextPending(-1), false);
  $("transcriptCard").hidden = false;
}

function renderTranscript() {
  if (typeof hideSelBar === "function") hideSelBar();
  const list = $("transcriptList");
  const keep = list.scrollTop;
  const editable = state.status === "reviewing";
  const bySeg = {};
  for (const t of suggestions()) (bySeg[t.segment_id] = bySeg[t.segment_id] || []).push(t);
  list.replaceChildren();
  for (const seg of state.transcript.segments) {
    const li = el("li", editable ? "editable" : null);
    li.id = `seg-${seg.segment_id}`;
    const range = seg.start_ms == null ? "—" : `${fmtMs(seg.start_ms)}–${fmtMs(seg.end_ms)}`;
    const time = el("span", "time", range);
    time.append(el("span", "sid", seg.segment_id));
    li.append(time, segmentText(seg, bySeg[seg.segment_id] || []));
    if (editable) {
      const b = el("button", "seg-edit-btn", "✎");
      b.type = "button";
      b.title = "直接修改這一段";
      b.addEventListener("click", () => openSegmentEditor(li, seg));
      li.append(b);
    }
    list.append(li);
  }
  list.scrollTop = keep;
  $("segmentCount").textContent = `（${state.transcript.segment_count} 段）`;
  markCurrent();
}

function segmentText(seg, items) {
  const span = el("span", "seg-text");
  const text = seg.text;
  const marks = [];
  for (const t of items) {
    const shown = t.status === "pending" ? t.wrong
      : (t.status === "accepted" || t.status === "edited") ? (t.applied ?? t.suggestion) : null;
    if (shown && text.substr(t.offset, shown.length) === shown) marks.push({ t, shown });
  }
  marks.sort((a, b) => a.t.offset - b.t.offset);
  let pos = 0;
  for (const { t, shown } of marks) {
    if (t.offset < pos) continue;
    span.append(document.createTextNode(text.slice(pos, t.offset)));
    const m = el("mark", t.status === "pending" ? "typo" : "typo fixed", shown);
    m.dataset.id = t.id;
    m.title = t.status === "pending" ? `疑似錯字，建議改成「${t.suggestion}」（點一下處理）` : `已修改，原本是「${t.wrong}」`;
    m.addEventListener("click", () => gotoTypo(suggestions().indexOf(t)));
    span.append(m);
    pos = t.offset + shown.length;
  }
  span.append(document.createTextNode(text.slice(pos)));
  if (seg.original_text != null) {
    const tag = el("span", "seg-tag", "已修改");
    tag.title = `原本：${seg.original_text}`;
    span.append(tag);
  }
  return span;
}

function openSegmentEditor(li, seg) {
  const box = el("div", "seg-editor");
  const ta = el("textarea");
  ta.value = seg.text;
  ta.rows = Math.max(2, Math.ceil(seg.text.length / 40));
  const bar = el("div", "rp-actions");
  const save = el("button", "btn primary small", "儲存");
  const cancel = el("button", "btn ghost small", "取消");
  save.type = cancel.type = "button";
  bar.append(save, cancel);
  box.append(ta, bar);
  li.children[1].replaceWith(box);
  li.querySelector(".seg-edit-btn").hidden = true;
  ta.focus();
  cancel.addEventListener("click", renderTranscript);
  save.addEventListener("click", async () => {
    if (ta.value.trim() === seg.text) { renderTranscript(); return; }
    save.disabled = true;
    try {
      const out = await api(`/api/v1/meetings/${state.meetingId}/transcript/segments/${seg.segment_id}`,
        { method: "PUT", json: { text: ta.value } });
      applyEditResult(out);
    } catch (err) { showError($("rpError"), err.message); save.disabled = false; }
  });
}

function fmtMs(ms) {
  if (ms == null) return "?";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

$("downloadJsonBtn").addEventListener("click", () => {
  if (!state.transcript) return;
  const out = { ...state.transcript, proofread: state.proofread };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `transcript-${state.meetingId}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
});

const review = { index: -1, editing: false };
const STATUS_LABEL = { pending: "待處理", accepted: "已套用", edited: "已自己改", ignored: "保留原文", outdated: "段落已手動修改" };

function suggestions() { return (state.proofread && state.proofread.suggestions) || []; }
function nextPending(from) {
  const list = suggestions();
  for (let k = 1; k <= list.length; k++) {
    const i = (from + k + list.length) % list.length;
    if (list[i].status === "pending") return i;
  }
  return -1;
}

function updateReviewUI() {
  const reviewing = state.status === "reviewing";
  const p = state.proofread;
  $("reviewPanel").hidden = !reviewing || !p;
  $("reproofBtn").hidden = !((reviewing && p && p.problems.length) || state.failedStage === "proofreading");
  if (!reviewing || !p) return;
  const c = p.counts;
  const handled = c.total - c.pending;
  const stats = $("rpStats");
  stats.replaceChildren();
  if (p.language) stats.append(el("span", "lang-tag", p.language === "en" ? "英文會議・依前後文校對英文" : "中文會議・校對同音錯字"));
  if (!p.enabled) stats.append("AI 錯字校對沒有開啟（TYPO_CHECK=false）。");
  else if (!c.total) stats.append("AI 沒有找到疑似錯字。");
  else {
    stats.append("AI 找到 ", el("b", null, `${c.total}`), " 處疑似錯字　已處理 ", el("b", null, `${handled}`),
      ` 處（套用 ${c.accepted}、自己改 ${c.edited}、保留原文 ${c.ignored}${c.outdated ? `、失效 ${c.outdated}` : ""}）`);
    const bar = el("div", "rp-bar");
    const fill = el("span");
    fill.style.width = `${Math.round((handled / c.total) * 100)}%`;
    bar.append(fill);
    stats.append(bar);
  }
  $("typoNav").hidden = !c.total;
  $("acceptAllBtn").hidden = !c.pending;
  $("acceptAllBtn").textContent = `全部套用（${c.pending}）`;
  $("confirmBtn").textContent = c.pending ? `確認逐字稿（${c.pending} 處未處理）` : "確認逐字稿";
  const probs = $("rpProblems");
  probs.replaceChildren(...p.problems.map((x) => el("li", null, x)));
  probs.hidden = !p.problems.length;
  renderReviewItem();
  if (typeof renderTermCandidates === "function") renderTermCandidates();
}

function renderReviewItem() {
  const box = $("rpItem");
  const list = suggestions();
  const t = list[review.index];
  $("typoCount").textContent = t ? `${review.index + 1} / ${list.length}` : `共 ${list.length} 處`;
  box.replaceChildren();
  box.hidden = !list.length;
  if (!list.length) return;
  if (!t) {
    box.append(el("p", "rp-done", state.proofread.counts.pending
      ? "按 ‹ › 或點逐字稿上的波浪線，一處一處處理。"
      : "全部處理完了。確認逐字稿沒問題，就按右上角「確認逐字稿」。"));
    return;
  }
  const seg = state.transcript.segments.find((x) => x.segment_id === t.segment_id);
  const where = el("div", "rp-where");
  where.append(`${t.segment_id}${seg && seg.start_ms != null ? "　" + fmtMs(seg.start_ms) : ""}`,
    el("span", `rp-badge ${t.status}`, STATUS_LABEL[t.status] || t.status));
  box.append(where);

  if (seg) {
    const pending = t.status === "pending";
    const now = pending ? t.wrong : (t.applied ?? (t.status === "ignored" ? t.wrong : t.suggestion));
    const at = seg.text.substr(t.offset, now.length) === now ? t.offset : seg.text.indexOf(now);
    if (at >= 0) {
      const before = seg.text.slice(Math.max(0, at - 14), at);
      const after = seg.text.slice(at + now.length, at + now.length + 14);
      const pre = (at > 14 ? "…" : "") + before;
      const post = after + (at + now.length + 14 < seg.text.length ? "…" : "");
      const line = (label, mid, cls) => {
        const p = el("p", "rp-line");
        p.append(el("span", "lbl", label), pre, el("span", cls, mid), post);
        return p;
      };
      if (t.status === "accepted" || t.status === "edited") {
        box.append(line("原文", t.wrong, "rp-wrong"), line("改成", now, "rp-right"));
      } else {
        box.append(line("原文", t.wrong, pending ? "rp-wrong" : null), line("建議", t.suggestion, "rp-right"));
      }
    }
  }

  const bar = el("div", "rp-actions");
  const btn = (text, cls, fn) => {
    const b = el("button", `btn ${cls} small`, text);
    b.type = "button";
    b.addEventListener("click", fn);
    bar.append(b);
    return b;
  };
  if (t.status === "pending") {
    btn(`套用「${t.suggestion}」`, "primary", () => decide("accept", [t.id]));
    btn("自己改", "ghost", () => {
      bar.replaceChildren();
      const input = el("input");
      input.value = t.suggestion;
      input.setAttribute("aria-label", "改成");
      bar.append(input);
      btn("確定", "primary", () => input.value.trim() && decide("accept", [t.id], input.value.trim()));
      btn("取消", "ghost", renderReviewItem);
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) decide("accept", [t.id], input.value.trim()); });
      input.focus();
      input.select();
    });
    btn("保留原文", "ghost", () => decide("ignore", [t.id]));
  } else if (t.status !== "outdated") {
    btn("復原", "ghost", () => decide("undo", [t.id]));
  }
  box.append(bar);
}

function gotoTypo(i, scroll = true) {
  const list = suggestions();
  if (!list.length) { review.index = -1; renderReviewItem(); return; }
  review.index = i < 0 ? -1 : (i + list.length) % list.length;
  renderReviewItem();
  markCurrent(scroll);
}
function markCurrent(scroll = false) {
  document.querySelectorAll("#transcriptList mark.current").forEach((m) => m.classList.remove("current"));
  const t = suggestions()[review.index];
  if (!t) return;
  const m = document.querySelector(`#transcriptList mark[data-id="${t.id}"]`);
  const target = m || document.getElementById(`seg-${t.segment_id}`);
  if (m) m.classList.add("current");
  if (scroll && target) {
    const list = $("transcriptList");
    const offset = target.getBoundingClientRect().top - list.getBoundingClientRect().top;
    list.scrollTo({ top: list.scrollTop + offset - list.clientHeight / 2, behavior: "smooth" });
  }
}
$("typoPrev").addEventListener("click", () => gotoTypo(review.index <= 0 ? suggestions().length - 1 : review.index - 1));
$("typoNext").addEventListener("click", () => gotoTypo(review.index + 1));

async function decide(action, ids, replacement) {
  showError($("rpError"), "");
  const body = { action };
  if (ids) body.ids = ids;
  if (replacement != null) body.replacement = replacement;
  try {
    const out = await api(`/api/v1/meetings/${state.meetingId}/proofread/decisions`, { method: "POST", json: body });
    const from = review.index;
    applyEditResult(out, false);
    gotoTypo(action === "undo" ? from : nextPending(from));
  } catch (err) { showError($("rpError"), err.message); }
}

function applyEditResult(out, keepPosition = true) {
  state.transcript = out.transcript;
  state.proofread = out.proofread;
  renderTranscript();
  updateReviewUI();
  if (keepPosition) markCurrent();
}

$("acceptAllBtn").addEventListener("click", async () => {
  const n = state.proofread ? state.proofread.counts.pending : 0;
  if (!n || !window.confirm(`把還沒處理的 ${n} 處全部改成 AI 建議的字？（之後還可以一處一處復原）`)) return;
  await decide("accept", null);
});

$("confirmBtn").addEventListener("click", async () => {
  const n = state.proofread ? state.proofread.counts.pending : 0;
  if (n && !window.confirm(`還有 ${n} 處疑似錯字沒處理，確認後這些地方會保留原文。確定要確認逐字稿嗎？`)) return;
  $("confirmBtn").disabled = true;
  try {
    const data = await api(`/api/v1/meetings/${state.meetingId}/transcript/confirm`, { method: "POST" });
    review.index = -1;
    renderStatus({ status: data.status, error: null });
    await loadTranscript();
  } catch (err) { showError($("rpError"), err.message); }
  finally { $("confirmBtn").disabled = false; }
});

$("reproofBtn").addEventListener("click", async () => {
  try {
    const data = await api(`/api/v1/meetings/${state.meetingId}/proofread`, { method: "POST" });
    renderStatus({ status: data.status, error: null });
    startPolling();
  } catch (err) { showError($("jobError"), err.message); }
});

function transcriptLang() {
  if (state.proofread && state.proofread.language) return state.proofread.language;
  const text = ((state.transcript && state.transcript.segments) || []).map((s) => s.text || "").join(" ");
  const lat = (text.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).length;
  const cjk = (text.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  return lat + cjk && lat / (lat + cjk) >= 0.6 ? "en" : "zh";
}
function syncSummaryLang() {
  if (state.summaryLangTouched) return;
  const done = state.summary && state.summary.summary && state.summary.summary.language;
  $("summaryLang").value = done || transcriptLang();
}
$("summaryLang").addEventListener("change", () => { state.summaryLangTouched = true; });

$("summarizeBtn").addEventListener("click", async () => {
  $("summarizeBtn").disabled = true;
  try {
    const data = await api(`/api/v1/meetings/${state.meetingId}/summary`,
      { method: "POST", json: { language: $("summaryLang").value } });
    renderStatus({ status: data.status, error: null });
    startPolling();
  } catch (err) {
    showError($("jobError"), err.message);
    $("summarizeBtn").disabled = false;
  }
});

const COLORS = { report: "#8a7e72", discussion: "#c9a273", decision: "#5e7a5a", action: "#2b2420" };
const NEXT_LABEL = { confirmed: "已確認", tentative: "暫定", not_mentioned: "未提及" };

async function loadSummary() {
  let data;
  try { data = await api(`/api/v1/meetings/${state.meetingId}/summary`); }
  catch (err) { showError($("jobError"), `讀取重點失敗：${err.message}`); return; }
  state.summary = data;
  syncSummaryLang();
  renderSnapshot(data);
  $("summaryCard").hidden = false;
}

function segmentTimes() {
  const map = {};
  let duration = 0;
  for (const seg of (state.transcript && state.transcript.segments) || []) {
    if (seg.start_ms != null) map[seg.segment_id] = seg.start_ms;
    if (seg.end_ms != null) duration = Math.max(duration, seg.end_ms);
  }
  return { map, duration };
}
function firstTime(item, times) {
  for (const ev of item.evidence || []) if (times.map[ev.segment_id] != null) return { ms: times.map[ev.segment_id], sid: ev.segment_id };
  return null;
}

function renderSnapshot(data) {
  const sm = data.summary;
  const mc = sm.meeting_content;
  const dtm = sm.meeting_datetime;
  const times = segmentTimes();
  const segCount = state.transcript ? state.transcript.segment_count : null;

  $("snapTitle").textContent = sm.meeting_name || "會議重點";
  const metaParts = [fmtDate(dtm)];
  if (times.duration) metaParts.push(`${Math.round(times.duration / 60000) || 1} 分鐘`);
  if (segCount) metaParts.push(`逐字稿 ${segCount} 段`);
  $("snapMeta").textContent = metaParts.filter(Boolean).join("　·　");
  $("snapHeadlineText").textContent = sm.headline || "（這次沒有產生一句話總結）";

  const nm = mc.next_meeting || { status: "not_mentioned" };
  const nmText = nm.status === "not_mentioned" ? "未提及" : [nm.date ? fmtMD(nm.date) : nm.date_text, nm.time].filter(Boolean).join(" ") || "時間未定";
  $("snapKpis").replaceChildren(
    kpi("決議", String(mc.decisions.length), "decision"),
    kpi("待辦", String(mc.action_items.length), "action"),
    kpi("需要確認", String(sm.review_notes.length), sm.review_notes.length ? "warn" : "ok"),
    kpi("下次會議", nmText, "next", nm.status === "not_mentioned" ? null : NEXT_LABEL[nm.status]),
  );

  const body = $("snapBody");
  body.replaceChildren(
    decisionsBlock(mc.decisions, times),
    actionsBlock(mc.action_items),
    times.duration ? timelineBlock(mc, times) : null,
    moreGroup(
    detailsBlock("討論內容", mc.discussions, "方案比較、不同意見", (d) => [
      el("div", "d-head", d.topic || "（未命名議題）"), d.summary ? el("div", "d-body", d.summary) : null,
      bulletsOf(d.key_points), evidence(d.evidence),
    ]),
    detailsBlock("報告事項", mc.reports, "進度與數據", (r) => [
      el("div", "d-head", r.topic || "（未命名）"), r.summary ? el("div", "d-body", r.summary) : null, evidence(r.evidence),
    ]),
    reviewBlock(sm.review_notes),
    ),
  );

  const when = data.updated_at ? new Date(data.updated_at).toLocaleString("zh-TW", { hour12: false }) : "";
  $("snapFoot").textContent = `由 ${data.model_name || "LLM"} 在本地端整理　·　產生時間 ${when}　·　點時間可回到逐字稿原文確認`;
}

function kpi(label, value, kind, sub) {
  const box = el("div", `kpi kpi-${kind}`);
  box.append(el("div", "kpi-label", label), el("div", value.length > 4 ? "kpi-value small" : "kpi-value", value));
  if (sub) box.append(el("div", "kpi-sub", sub));
  return box;
}

function blockTitle(text, kind) {
  const h = el("h3", `block-title t-${kind}`, text);
  return h;
}

function timeButton(t) {
  const b = el("button", "time-btn", `▶ ${fmtMs(t.ms)}`);
  b.type = "button";
  b.title = "跳到逐字稿這一段";
  b.setAttribute("aria-label", `跳到逐字稿 ${fmtMs(t.ms)}`);
  b.addEventListener("click", () => jumpTo(t.sid));
  return b;
}

function decisionsBlock(decisions, times) {
  const s = el("div", "block");
  s.append(blockTitle("決議", "decision"));
  if (!decisions.length) { s.append(el("p", "empty", "這場會議沒有明確的決議。")); return s; }
  for (const d of decisions) {
    const row = el("div", "decision");
    const text = el("div", "decision-text");
    text.append(el("div", "decision-summary", d.summary || "（未填）"));
    const q = (d.evidence || [])[0];
    if (q) text.append(el("div", "decision-quote", `依據：「${q.quote}」`));
    row.append(text);
    const t = firstTime(d, times);
    if (t) row.append(timeButton(t));
    s.append(row);
  }
  return s;
}

function actionsBlock(items) {
  const s = el("div", "block");
  s.append(blockTitle("誰要做什麼", "action"));
  if (!items.length) { s.append(el("p", "empty", "沒有明確的待辦事項。")); return s; }
  for (const a of items) {
    const row = el("div", "action");
    const who = a.assignees.length ? a.assignees.join("、") : null;
    const avatar = el("span", who ? "avatar" : "avatar missing", who ? who.slice(-1) : "?");
    const whoBox = el("div", "action-who");
    whoBox.append(avatar, el("span", who ? null : "missing", who || "未指定"));
    const due = a.due_date ? `${fmtMD(a.due_date)}${a.due_text ? `（${a.due_text}）` : ""}` : a.due_text;
    row.append(whoBox, el("div", "action-task", a.task || "（未填）"), el("div", due ? "action-due" : "action-due missing", due || "沒有期限"));
    s.append(row);
  }
  return s;
}

function timelineBlock(mc, times) {
  const s = el("div", "block");
  const head = el("div", "timeline-head");
  head.append(blockTitle("會議時間軸", "plain"));
  const legend = el("div", "legend");
  for (const [k, label] of [["report", "報告"], ["discussion", "討論"], ["decision", "決議"], ["action", "待辦"]]) {
    const i = el("span", null, label);
    const dot = el("i"); dot.style.background = COLORS[k];
    i.prepend(dot); legend.append(i);
  }
  head.append(legend);
  const track = el("div", "track");
  track.append(el("div", "track-line"));
  const add = (items, kind, labelOf) => {
    for (const it of items) {
      const t = firstTime(it, times);
      if (!t) continue;
      const b = el("button", "mark");
      b.type = "button";
      b.style.left = `${(t.ms / times.duration) * 100}%`;
      b.style.background = COLORS[kind];
      const label = `${labelOf(it)}　${fmtMs(t.ms)}`;
      b.title = label;
      b.setAttribute("aria-label", label);
      b.addEventListener("click", () => jumpTo(t.sid));
      track.append(b);
    }
  };
  add(mc.reports, "report", (r) => `報告：${r.topic || r.summary || ""}`);
  add(mc.discussions, "discussion", (d) => `討論：${d.topic || ""}`);
  add(mc.decisions, "decision", (d) => `決議：${d.summary || ""}`);
  add(mc.action_items, "action", (a) => `待辦：${a.task || ""}`);
  const ticks = el("div", "ticks");
  for (let i = 0; i <= 4; i++) ticks.append(el("span", null, fmtMs((times.duration * i) / 4)));
  s.append(head, track, ticks);
  return s;
}

function moreGroup(...blocks) {
  const g = el("div", "more-group");
  g.append(...blocks);
  return g;
}

function reviewBlock(notes) {
  const d = el("details", "more");
  if (notes.length) d.open = true;
  const sum = el("summary");
  sum.append(el("span", "more-title", "需要確認"), el("span", "more-count", `${notes.length} 項`), el("span", "more-hint", "AI 不確定的地方"));
  d.append(sum);
  const box = el("div", "more-body");
  if (!notes.length) box.append(el("p", "empty", "無"));
  for (const n of notes) {
    const card = el("div", "more-item");
    card.append(el("div", "d-head", n.reason || ""));
    if (n.field) card.append(el("div", "d-body muted", `位置：${n.field}`));
    box.append(card);
  }
  d.append(box);
  return d;
}

function detailsBlock(title, items, hint, render, open = false) {
  const d = el("details", "more");
  if (open) d.open = true;
  const sum = el("summary");
  sum.append(el("span", "more-title", title), el("span", "more-count", `${items.length} 項`), el("span", "more-hint", hint));
  d.append(sum);
  const box = el("div", "more-body");
  if (!items.length) box.append(el("p", "empty", "無"));
  for (const it of items) {
    const card = el("div", "more-item");
    for (const part of render(it)) if (part) card.append(part);
    box.append(card);
  }
  d.append(box);
  return d;
}

function bulletsOf(items) {
  if (!items || !items.length) return null;
  const ul = el("ul");
  for (const i of items) ul.append(el("li", null, i));
  return ul;
}

function fmtMD(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const w = "日一二三四五六"[new Date(y, m - 1, d).getDay()];
  return `${m}/${d}（${w}）`;
}
function fmtDate(dtm) {
  if (!dtm || !dtm.date) return "";
  const [y, m, d] = dtm.date.split("-").map(Number);
  const w = "日一二三四五六"[new Date(y, m - 1, d).getDay()];
  const t = [dtm.start_time, dtm.end_time].filter(Boolean).map((x) => x.slice(0, 5)).join("–");
  return `${y}/${m}/${d}（${w}）${t ? " " + t : ""}`;
}

function el(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
}
function evidence(list) {
  if (!list || !list.length) return null;
  const box = el("div", "evidence");
  for (const ev of list) {
    const b = el("button", null, `${ev.segment_id}「${ev.quote}」`);
    b.type = "button";
    b.title = "跳到逐字稿原文";
    b.addEventListener("click", () => jumpTo(ev.segment_id));
    box.append(b);
  }
  return box;
}

function safeName(s) { return (s || "會議").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40); }
function stamp(iso) {
  const d = iso ? new Date(iso) : new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}
function downloadBlob(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

$("downloadSummaryBtn").addEventListener("click", async () => {
  const data = state.summary;
  if (!data) return;
  let llm = null;
  try { llm = await api("/api/v1/health"); } catch (_) {  }
  const sm = data.summary;
  const out = {
    exported_at: new Date().toISOString(),
    meeting: { id: data.meeting_id, name: sm.meeting_name, datetime: sm.meeting_datetime },
    generated_at: data.updated_at,
    model_name: data.model_name,
    llm_settings_at_export: llm ? { temperature: llm.llm_temperature, seed: llm.llm_seed, num_ctx: llm.llm_num_ctx, think: llm.llm_think } : null,
    transcript_segment_count: state.transcript ? state.transcript.segment_count : null,
    headline: sm.headline,
    meeting_content: sm.meeting_content,
    review_notes: sm.review_notes,
    transcript_proofread: state.proofread ? state.proofread.counts : null,
  };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  downloadBlob(blob, `重點_${safeName(sm.meeting_name)}_${stamp(data.updated_at)}.json`);
});

const FONT = '"Noto Sans TC", "Noto Sans CJK TC", "PingFang TC", "Microsoft JhengHei", "Heiti TC", sans-serif';

const NO_LINE_START = "，。、！？：；」』）》〉…,.!?:;)";
function wrapLines(ctx, text, maxWidth) {
  const lines = [];
  let line = "";
  for (const ch of String(text)) {
    const tooWide = ctx.measureText(line + ch).width > maxWidth;
    if (tooWide && line && !NO_LINE_START.includes(ch)) { lines.push(line); line = ch; }
    else line += ch;
  }
  if (line) lines.push(line);
  return lines;
}
function drawText(ctx, text, x, y, maxWidth, lineHeight, maxLines = 99) {
  let lines = wrapLines(ctx, text, maxWidth);
  if (lines.length > maxLines) { lines = lines.slice(0, maxLines); lines[maxLines - 1] = lines[maxLines - 1].slice(0, -1) + "…"; }
  lines.forEach((l, i) => ctx.fillText(l, x, y + i * lineHeight));
  return y + lines.length * lineHeight;
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function buildFlow(mc, times) {
  const norm = (t) => (t || "").replace(/[\s與跟和及、]/g, "");
  const topics = mc.discussions.map((d, i) => ({ d, t: firstTime(d, times), order: i, reports: [], decisions: [] }));
  topics.sort((a, b) => (a.t && b.t ? a.t.ms - b.t.ms : a.order - b.order));
  for (const r of mc.reports) {
    let target = topics.find((x) => norm(x.d.topic) && norm(x.d.topic) === norm(r.topic));
    const rt = firstTime(r, times);
    if (!target && rt) {
      let best = Infinity;
      for (const x of topics) if (x.t && Math.abs(x.t.ms - rt.ms) < best) { best = Math.abs(x.t.ms - rt.ms); target = x; }
    }
    if (target) target.reports.push(r);
  }
  const byId = Object.fromEntries(topics.map((x) => [x.d.id, x]));
  const loose = [];
  for (const dec of mc.decisions) {
    const target = (dec.related_ids || []).map((id) => byId[id]).find(Boolean);
    (target ? target.decisions : loose).push(dec);
  }
  const usedReports = new Set(topics.flatMap((x) => x.reports));
  const looseReports = mc.reports.filter((r) => !usedReports.has(r));
  return { topics, loose, looseReports };
}

function drawShareImage(data) {
  const W = 1024, S = 2, P = 36, CW = W - P * 2;
  const MAX_TOPICS = 9, MAX_ACTIONS = 6;
  const c = document.createElement("canvas");
  c.width = W * S; c.height = 3200 * S;
  const ctx = c.getContext("2d");
  ctx.scale(S, S);
  ctx.textBaseline = "middle";
  const sm = data.summary, mc = sm.meeting_content;
  const flow = buildFlow(mc, segmentTimes());
  const C = { bg: "#fbf8f2", dark: "#2b2420", mid: "#5e7a5a", soft: "#f3e9da", row: "#f6efe3",
              ink: "#2b2420", muted: "#5f544a", line: "#e6daca", warn: "#c04a33", white: "#ffffff" };
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, 3200);

  const font = (w, px) => { ctx.font = `${w} ${px}px ${FONT}`; };
  const ell = (text, w) => {
    let t = String(text || "");
    if (ctx.measureText(t).width <= w) return t;
    while (t && ctx.measureText(t + "…").width > w) t = t.slice(0, -1);
    return t + "…";
  };
  const clamp = (text, w, max) => {
    const ls = wrapLines(ctx, String(text || ""), w);
    if (ls.length <= max) return ls;
    const out = ls.slice(0, max);
    out[max - 1] = ell(ls.slice(max - 1).join(""), w);
    return out;
  };
  const fitLine = (text, w, weight, px, minPx) => {
    let size = px;
    font(weight, size);
    while (ctx.measureText(text).width > w && size > minPx) font(weight, --size);
    return ell(text, w);
  };
  const brief = (text) => {
    let t = String(text || "").trim();
    const m = t.match(/^[^，。：:]{1,12}[：:]\s*/);
    if (m && t.length - m[0].length >= 6) t = t.slice(m[0].length);
    const first = t.split(/(?<=[。；！？])/)[0];
    return first.replace(/[。；]$/, "");
  };
  const center = (text, y) => ctx.fillText(text, (W - ctx.measureText(text).width) / 2, y);
  const disc = (x, y, r, color) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); };

  const icon = {
    bulb(x, y) {
      ctx.strokeStyle = C.white; ctx.fillStyle = C.white; ctx.lineWidth = 3; ctx.lineCap = "round";
      ctx.beginPath(); ctx.arc(x, y - 6, 15, Math.PI * 0.8, Math.PI * 2.2); ctx.lineTo(x + 7, y + 14); ctx.lineTo(x - 7, y + 14); ctx.closePath(); ctx.fill();
      ctx.fillRect(x - 7, y + 17, 14, 4); ctx.fillRect(x - 5, y + 23, 10, 3);
      for (const a of [-150, -110, -70, -30]) {
        const r = (a * Math.PI) / 180;
        ctx.beginPath(); ctx.moveTo(x + Math.cos(r) * 22, y - 6 + Math.sin(r) * 22); ctx.lineTo(x + Math.cos(r) * 29, y - 6 + Math.sin(r) * 29); ctx.stroke();
      }
    },
    doc(x, y) {
      ctx.fillStyle = C.white; roundRect(ctx, x - 11, y - 14, 22, 28, 4); ctx.fill();
      ctx.fillStyle = C.dark; for (const dy of [-6, 0, 6]) ctx.fillRect(x - 6, y + dy - 1, 12, 2.5);
    },
    target(x, y) {
      ctx.strokeStyle = C.white; ctx.lineWidth = 3;
      for (const r of [14, 8]) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); }
      disc(x, y, 3, C.white);
    },
    calendar(x, y) {
      ctx.fillStyle = C.white; roundRect(ctx, x - 17, y - 14, 34, 30, 5); ctx.fill();
      ctx.fillStyle = C.dark; ctx.fillRect(x - 17, y - 6, 34, 3);
      for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) ctx.fillRect(x - 11 + i * 9, y + 1 + j * 7, 5, 4);
      ctx.fillStyle = C.white; ctx.fillRect(x - 10, y - 19, 3, 8); ctx.fillRect(x + 7, y - 19, 3, 8);
    },
  };

  let y = P + 10;
  const title = `${sm.meeting_name || "會議"}｜重點摘要`;
  ctx.fillStyle = C.dark;
  let size = 46;
  font(900, size);
  while (ctx.measureText(title).width > CW && size > 34) font(900, --size);
  for (const l of clamp(title, CW, 2)) { center(l, y + size / 2); y += size + 10; }
  ctx.fillStyle = C.muted; font(500, 22);
  center(fmtDate(sm.meeting_datetime), y + 12);
  y += 46;

  font(700, 25);
  const hl = clamp(sm.headline || "（這次沒有產生一句話總結）", CW - 190, 3);
  const coreH = Math.max(130, 42 + 44 + hl.length * 38 + 22);
  ctx.fillStyle = C.soft; roundRect(ctx, P, y, CW, coreH, 22); ctx.fill();
  disc(P + 70, y + coreH / 2, 46, C.dark); icon.bulb(P + 70, y + coreH / 2);
  ctx.fillStyle = C.dark; ctx.fillRect(P + 140, y + 26, 3, coreH - 52);
  font(900, 32); ctx.fillText("核心結論：", P + 162, y + 46);
  font(700, 25); ctx.fillStyle = C.ink;
  hl.forEach((l, i) => ctx.fillText(l, P + 162, y + 88 + i * 38));
  y += coreH + 30;

  const ribbon = (label, draw) => {
    const h = 54, w = 300;
    ctx.fillStyle = C.dark;
    ctx.beginPath(); ctx.moveTo(P + h / 2, y); ctx.lineTo(P + w, y); ctx.lineTo(P + w - 18, y + h); ctx.lineTo(P + h / 2, y + h);
    ctx.arc(P + h / 2, y + h / 2, h / 2, Math.PI / 2, Math.PI * 1.5); ctx.fill();
    disc(P + h / 2, y + h / 2, h / 2 - 4, C.mid); draw(P + h / 2, y + h / 2);
    ctx.fillStyle = C.white; font(900, 28); ctx.fillText(label, P + h + 16, y + h / 2 + 1);
    ctx.strokeStyle = C.dark; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(P + w + 8, y + h / 2); ctx.lineTo(W - P, y + h / 2); ctx.stroke();
    y += h + 16;
  };

  const rows = flow.topics.map((tp) => ({
    label: tp.d.topic || "議題",
    text: brief(tp.decisions.length ? tp.decisions[0].summary : (tp.d.summary || (tp.d.key_points || [])[0] || "")),
  }));
  for (const dec of flow.loose) rows.push({ label: "其他決議", text: brief(dec.summary) });
  if (!rows.length) for (const r of mc.reports) rows.push({ label: r.topic || "報告", text: brief(r.summary) });
  ribbon("議題與決議", icon.doc);
  const shownRows = rows.slice(0, MAX_TOPICS);
  const RH = 56, NUM_W = 64, LABEL_X = P + NUM_W + 20, SEP_X = P + 270, TEXT_X = SEP_X + 22;
  if (!shownRows.length) { ctx.fillStyle = C.muted; font(500, 22); ctx.fillText("這場會議沒有整理出議題", P + 10, y + 20); y += 50; }
  shownRows.forEach((r, i) => {
    const mid = y + RH / 2;
    ctx.fillStyle = C.row; roundRect(ctx, P, y, CW, RH, 10); ctx.fill();
    ctx.fillStyle = C.soft; roundRect(ctx, P, y, NUM_W, RH, 10); ctx.fill();
    ctx.fillStyle = C.dark; font(900, 24);
    const n = String(i + 1); ctx.fillText(n, P + (NUM_W - ctx.measureText(n).width) / 2, mid + 1);
    const label = fitLine(r.label, SEP_X - LABEL_X - 14, 900, 23, 18);
    ctx.fillStyle = C.ink; ctx.fillText(label, LABEL_X, mid + 1);
    ctx.fillStyle = C.line; ctx.fillRect(SEP_X, y + 14, 2, RH - 28);
    const text = fitLine(r.text, W - P - TEXT_X - 18, 500, 21, 18);
    ctx.fillStyle = C.ink; ctx.fillText(text, TEXT_X, mid + 1);
    y += RH + 8;
  });
  if (rows.length > MAX_TOPICS) { ctx.fillStyle = C.muted; font(500, 19); ctx.fillText(`另有 ${rows.length - MAX_TOPICS} 個議題，請見網頁上的會議內容`, P + 6, y + 10); y += 30; }
  y += 22;

  ribbon("待辦與期限", icon.target);
  const acts = mc.action_items.slice(0, MAX_ACTIONS);
  const WHO_W = 220, DUE_W = 150, TASK_W = CW - WHO_W - DUE_W, HEAD_H = 48, LH = 29;
  const cells = acts.map((a) => {
    font(500, 20); const who = clamp(a.assignees.length ? a.assignees.join("、") : "未指定", WHO_W - 36, 2);
    font(500, 20); const task = clamp(a.task || "", TASK_W - 36, 2);
    const due = a.due_date ? fmtMD(a.due_date) : (a.due_text || "未定期限");
    return { a, who, task, due, h: Math.max(who.length, task.length) * LH + 26 };
  });
  const tableH = HEAD_H + (cells.length ? cells.reduce((s2, k) => s2 + k.h, 0) : 56);
  ctx.fillStyle = C.white; roundRect(ctx, P, y, CW, tableH, 12); ctx.fill();
  ctx.save(); roundRect(ctx, P, y, CW, tableH, 12); ctx.clip();
  ctx.fillStyle = C.soft; ctx.fillRect(P, y, CW, HEAD_H);
  ctx.restore();
  ctx.fillStyle = C.ink; font(900, 21);
  const headMid = y + HEAD_H / 2 + 1;
  const colCenter = (text, x, w, yy) => ctx.fillText(text, x + (w - ctx.measureText(text).width) / 2, yy);
  colCenter("負責", P, WHO_W, headMid); colCenter("待辦事項", P + WHO_W, TASK_W, headMid); colCenter("期限", P + WHO_W + TASK_W, DUE_W, headMid);
  let ty = y + HEAD_H;
  ctx.fillStyle = C.line;
  if (!cells.length) { ctx.fillStyle = C.muted; font(500, 20); colCenter("沒有明確的待辦", P, CW, ty + 28); }
  for (const k of cells) {
    ctx.fillStyle = C.line; ctx.fillRect(P, ty, CW, 1.5);
    const mid = ty + k.h / 2;
    font(500, 20);
    ctx.fillStyle = k.a.assignees.length ? C.ink : C.warn;
    k.who.forEach((l, i) => ctx.fillText(l, P + 22, mid + (i - (k.who.length - 1) / 2) * LH));
    ctx.fillStyle = C.ink;
    k.task.forEach((l, i) => ctx.fillText(l, P + WHO_W + 18, mid + (i - (k.task.length - 1) / 2) * LH));
    ctx.fillStyle = (k.a.due_date || k.a.due_text) ? C.ink : C.muted;
    colCenter(ell(k.due, DUE_W - 20), P + WHO_W + TASK_W, DUE_W, mid);
    ty += k.h;
  }
  ctx.fillStyle = C.line;
  ctx.fillRect(P + WHO_W, y, 1.5, tableH); ctx.fillRect(P + WHO_W + TASK_W, y, 1.5, tableH);
  ctx.strokeStyle = C.dark; ctx.lineWidth = 1.5; roundRect(ctx, P, y, CW, tableH, 12); ctx.stroke();
  y += tableH + 12;
  const notes = [];
  if (mc.action_items.length > MAX_ACTIONS) notes.push(`另有 ${mc.action_items.length - MAX_ACTIONS} 項待辦`);
  if (sm.review_notes.length) notes.push(`${sm.review_notes.length} 項需要確認`);
  ctx.fillStyle = notes.length ? C.warn : C.muted; font(500, 18);
  ctx.fillText(notes.length ? `${notes.join("、")}，請見網頁上的會議內容。` : "完整討論內容與原文依據，請見網頁上的會議內容。", P + 6, y + 10);
  y += 44;

  const nm = mc.next_meeting || {};
  const nmText = nm.status && nm.status !== "not_mentioned"
    ? `${[nm.date ? fmtMD(nm.date) : nm.date_text, nm.time].filter(Boolean).join(" ") || "時間未定"}${nm.status === "tentative" ? "（暫定）" : ""}`
    : "尚未排定";
  const NH = 104;
  ctx.fillStyle = C.soft; roundRect(ctx, P, y, CW, NH, 22); ctx.fill();
  disc(P + 66, y + NH / 2, 38, C.dark); icon.calendar(P + 66, y + NH / 2 + 2);
  ctx.fillStyle = C.dark; ctx.fillRect(P + 124, y + 24, 3, NH - 48);
  font(900, 34); ctx.fillText(ell(`下次會議：${nmText}`, CW - 180), P + 148, y + NH / 2 + 1);
  y += NH + 22;

  ctx.fillStyle = C.muted; font(400, 16);
  center(`覓聲 MeetSum · 本地端整理${data.model_name ? " · " + data.model_name : ""}`, y + 6);
  y += 22 + P / 2;

  const out = document.createElement("canvas");
  out.width = W * S; out.height = Math.ceil(y * S);
  out.getContext("2d").drawImage(c, 0, 0);
  return out;
}

$("saveImageBtn").addEventListener("click", () => {
  if (!state.summary) return;
  const canvas = drawShareImage(state.summary);
  canvas.toBlob((blob) => {
    if (blob) downloadBlob(blob, `會議快照_${safeName(state.summary.summary.meeting_name)}_${stamp(state.summary.updated_at)}.png`);
  }, "image/png");
});

function jumpTo(segmentId) {
  const li = document.getElementById(`seg-${segmentId}`);
  if (!li) return;
  li.scrollIntoView({ behavior: "smooth", block: "center" });
  li.classList.add("highlight");
  setTimeout(() => li.classList.remove("highlight"), 1800);
}
