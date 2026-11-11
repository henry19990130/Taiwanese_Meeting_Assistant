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
  // 通知追蹤：避免重複發送同一會議的完成通知
  notifiedMeetings: new Set(),
  // ASR 模式：'cloud' (雲端) 或 'local' (本地)
  asrMode: 'cloud',
  // App 層級模式：'cloud' 或 'local'（本機模式免登入）
  appMode: 'cloud',
  localUser: null,
  localProfileName: '',
  // 本機模式的模型狀態
  localModels: null,
  // 本地 ASR 狀態
  localAsrJobId: null,
  localAsrProgress: 0,
  localAsrListener: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// 後端伺服器位址設定
// 優先順序：使用者設定 > 建置時注入的 __API_BASE_URL__ > 同源相對路徑
// ---------------------------------------------------------------------------
const SERVER_URL_KEY = "meetsum.server_url";
const DEFAULT_API_BASE =
  (typeof __API_BASE_URL__ !== "undefined" && __API_BASE_URL__) ? String(__API_BASE_URL__) : "";

// 正規化伺服器位址；回傳 null 表示格式錯誤，回傳 "" 表示使用同源相對路徑
function normalizeServerUrl(raw) {
  let url = String(raw ?? "").trim();
  if (!url) return "";
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(url)) url = `http://${url}`;
  let parsed;
  try { parsed = new URL(url); } catch (_) { return null; }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  return parsed.origin;
}

function getServerUrl() {
  let stored = null;
  try { stored = localStorage.getItem(SERVER_URL_KEY); } catch (_) { /* ignore */ }
  return normalizeServerUrl(stored ?? DEFAULT_API_BASE) ?? "";
}

function setServerUrl(raw) {
  const normalized = normalizeServerUrl(raw);
  if (normalized === null) return false;
  try {
    if (normalized) localStorage.setItem(SERVER_URL_KEY, normalized);
    else localStorage.removeItem(SERVER_URL_KEY);
  } catch (_) { /* ignore */ }
  updateServerLabels();
  return true;
}

function apiUrl(path) {
  const base = getServerUrl();
  return base ? `${base}${path}` : path;
}

async function testServer(raw) {
  const target = normalizeServerUrl(raw);
  if (target === null) throw new Error("網址格式不正確（例：http://localhost:8000）");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 6000);
  try {
    const res = await fetch(`${target}/api/v1/health`, { signal: controller.signal });
    if (!res.ok) throw new Error(`伺服器回應 ${res.status}`);
    return await res.json().catch(() => ({}));
  } catch (err) {
    if (err && err.name === "AbortError") throw new Error("連線逾時，請確認後端已啟動");
    throw new Error("無法連線，請確認網址與後端是否啟動");
  } finally {
    clearTimeout(timer);
  }
}

function updateServerLabels() {
  const url = getServerUrl();
  const text = url || "同源（由後端提供頁面）";
  const label = document.getElementById("serverLabel");
  if (label) label.textContent = text;
  const top = document.getElementById("serverBtnTop");
  if (top) top.title = `後端伺服器：${text}`;
}

function setServerMsg(msg, ok = false) {
  const el = $("serverMsg");
  if (!el) return;
  el.textContent = msg || "";
  el.hidden = !msg;
  el.style.color = ok ? "var(--accent)" : "var(--error)";
}

function openServerDialog() {
  const dialog = $("serverDialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    // 對話框不支援時的降級做法
    const next = window.prompt("後端伺服器位址（留空＝使用建置時預設）", getServerUrl());
    if (next !== null && !setServerUrl(next)) window.alert("網址格式不正確");
    return;
  }
  $("serverInput").value = getServerUrl();
  setServerMsg("");
  dialog.showModal();
}

async function handleServerTest() {
  setServerMsg("測試中…");
  try {
    const info = await testServer($("serverInput").value);
    const asr = info.asr_engine ? `ASR：${info.asr_engine}` : "";
    const llm = info.llm_model ? `LLM：${info.llm_model}` : "";
    const detail = [asr, llm].filter(Boolean).join("，");
    setServerMsg(`✅ 連線成功${detail ? `（${detail}）` : ""}`, true);
  } catch (err) {
    setServerMsg(`❌ ${err.message}`);
  }
}

function handleServerSave() {
  if (!setServerUrl($("serverInput").value)) {
    setServerMsg("網址格式不正確（例：http://localhost:8000）");
    return;
  }
  $("serverDialog").close();
}

// 綁定伺服器設定 UI（script 在 body 尾端，元素已存在）
if ($("serverDialog")) {
  $("serverBtn").addEventListener("click", openServerDialog);
  $("serverBtnTop").addEventListener("click", openServerDialog);
  $("serverClose").addEventListener("click", () => $("serverDialog").close());
  $("serverTest").addEventListener("click", handleServerTest);
  $("serverClear").addEventListener("click", () => {
    $("serverInput").value = DEFAULT_API_BASE;
    setServerMsg(DEFAULT_API_BASE ? "已帶入建置時的預設位址，按「儲存」生效" : "已清空，將使用同源相對路徑", true);
  });
  $("serverForm").addEventListener("submit", (e) => { e.preventDefault(); handleServerSave(); });
  updateServerLabels();
}

// 供其他模組（ui.js 等）與偵錯使用
window.MeetSumConfig = { getServerUrl, setServerUrl, apiUrl, testServer, DEFAULT_API_BASE };

// 這些模組原本是共用全域的 classic scripts，被打包成 ES modules 後
// module scope 不互通，明確掛到 window 供 deck.js / glossary.js / assistant.js 使用
window.$ = $;
window.state = state;
window.api = api;
window.showError = showError;

// Capacitor Bridge - 掛載到 window 供其他模組使用
import * as CapacitorBridge from './capacitor.js';
window.CapacitorBridge = CapacitorBridge;

// 常數：鑰匙串/Preferences 儲存鍵
const TOKEN_KEY = 'meetsum.auth_token';
const USER_KEY = 'meetsum.auth_user';

// ---------------------------------------------------------------------------
// 執行模式（本機 / 雲端）
//
// 本機模式：免登入，ASR 與摘要都在这台装置跑（原生 plugin），資料只存裝置。
// 雲端模式：Google 或帳密登入，連 Colab 後端；結果一樣寫回裝置。
// ---------------------------------------------------------------------------
const APP_MODE_KEY = 'meetsum.app_mode';
const LOCAL_PROFILE_KEY = 'meetsum.local_profile';
const DISCOVERY_CACHE_KEY = 'meetsum.discovery_cache';
const DISCOVERY_URL =
  (typeof __DISCOVERY_URL__ !== "undefined" && __DISCOVERY_URL__) ? String(__DISCOVERY_URL__) : "";

function isLocalMode() { return state.appMode === "local"; }

function applyMode(mode) {
  state.appMode = mode;
  const local = mode === "local";
  document.body.dataset.mode = mode;

  const cloudBtn = $("modeCloudBtn");
  const localBtn = $("modeLocalBtn");
  if (cloudBtn) { cloudBtn.classList.toggle("is-active", !local); cloudBtn.setAttribute("aria-pressed", String(!local)); }
  if (localBtn) { localBtn.classList.toggle("is-active", local); localBtn.setAttribute("aria-pressed", String(local)); }

  if ($("loginForm")) $("loginForm").hidden = local;
  if ($("localEntry")) $("localEntry").hidden = !local;

  const badge = $("modeBadge");
  if (badge) { badge.hidden = !local; badge.textContent = "本機"; }
  const serverBtn = $("serverBtnTop");
  if (serverBtn) serverBtn.hidden = local;

  const foot = $("loginModeLabel");
  if (foot) {
    foot.textContent = local
      ? "本機模式 · 模型與資料都在這台裝置"
      : "雲端模式 · 台語＋華語辨識";
  }
  setAsrMode(local ? "local" : "cloud");
}

async function persistMode(mode) {
  try { localStorage.setItem(APP_MODE_KEY, mode); } catch (_) { /* ignore */ }
  try { if (window.Store) await Store.kv.set(APP_MODE_KEY, mode); } catch (_) { /* ignore */ }
}

async function readStoredMode() {
  try {
    const v = window.Store ? await Store.kv.get(APP_MODE_KEY, null) : null;
    if (v) return v;
  } catch (_) { /* ignore */ }
  try { return localStorage.getItem(APP_MODE_KEY) || "cloud"; } catch (_) { return "cloud"; }
}

async function enterLocalMode({ restore = false } = {}) {
  let profile = {};
  try { if (window.Store) profile = (await Store.kv.get(LOCAL_PROFILE_KEY, null)) || {}; } catch (_) { /* ignore */ }
  state.token = null;
  state.localUser = {
    username: profile.username || "local",
    display_name: profile.display_name || "本機使用者",
    local: true,
  };
  state.user = state.localUser;
  await persistMode("local");
  applyMode("local");
  showApp();
  if (!restore) CapacitorBridge.hapticNotification('success').catch(() => {});
}

function exitToModeChoice(message = "") {
  stopPolling();
  if (window.assistant) window.assistant.onLogout();
  Object.assign(state, {
    token: null, user: null, meetingId: null, status: null,
    transcript: null, summary: null, proofread: null,
  });
  $("appView").hidden = true;
  $("userBox").hidden = true;
  $("loginView").hidden = false;
  document.body.classList.add("login-mode");
  applyMode("cloud");
  if (window.Entrance) Entrance.greet();
  showAuth("login", message || "");
}

async function switchMode() {
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  if (isLocalMode()) {
    await persistMode("cloud");
    exitToModeChoice();
    // 若裝置仍留有雲端登入狀態就直接還原，否則停在登入頁
    await loadStoredAuth();
  } else {
    await enterLocalMode();
  }
}

// ---------------------------------------------------------------------------
// 自動發現 Colab 後端（Cloudflare Worker 固定入口）
// 使用者手動設定的位址永遠優先，不會被覆蓋。
// ---------------------------------------------------------------------------
async function discoverServer() {
  if (!DISCOVERY_URL || getServerUrl()) return null;
  let cached = null;
  try { cached = JSON.parse(localStorage.getItem(DISCOVERY_CACHE_KEY) || "null"); } catch (_) { /* ignore */ }
  if (cached && cached.url && Date.now() - (cached.at || 0) < 5 * 60 * 1000) {
    setServerUrl(cached.url);
    return cached.url;
  }
  try {
    const res = await fetch(DISCOVERY_URL, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || (!data.url && !data.api_url)) return null;
    // 新版 Worker 直接代理後端，api_url 是固定網域（Google OAuth 才不用每次改設定）
    const target = data.api_url || data.url;
    setServerUrl(target);
    try { localStorage.setItem(DISCOVERY_CACHE_KEY, JSON.stringify({ url: target, at: Date.now() })); } catch (_) { /* ignore */ }
    return target;
  } catch (_) {
    return null;
  }
}

// 背景重試：Colab 可能比 App 晚啟動
async function discoverServerWithRetry({ attempts = 4, delay = 4000 } = {}) {
  for (let i = 0; i < attempts; i++) {
    const url = await discoverServer();
    if (url) return url;
    await new Promise((r) => setTimeout(r, delay));
  }
  return null;
}


// 初始化 Capacitor (在 DOM 準備好後)
document.addEventListener('DOMContentLoaded', async () => {
  try { if (window.Store) await Store.init(); } catch (err) { console.warn('[Store] 初始化失敗:', err); }
  try {
    await CapacitorBridge.initCapacitor();
  } catch (err) {
    console.warn('[Capacitor] 初始化失敗:', err);
  }
  setupModeControls();
  setupGoogleLogin();
  setupDeepLink();
  setupHistoryControls();
  // 與 initCapacitor 分開，避免初始化失敗連帶跳過登入狀態還原
  try {
    await loadStoredAuth();
  } catch (err) {
    console.warn('[Auth] 載入儲存的認證失敗:', err);
  }
  // 背景自動發現 Colab 後端（有設定固定入口且使用者未手動指定時）
  if (!isLocalMode()) discoverServerWithRetry({ attempts: 3, delay: 5000 }).catch(() => {});
});
const STEP_ORDER = ["uploaded", "transcribing", "proofreading", "reviewing", "summarizing", "completed"];

// 從安全儲存載入認證資訊
async function loadStoredAuth() {
  let mode = "cloud";
  try { mode = await readStoredMode(); } catch (_) { /* ignore */ }

  if (mode === "local") {
    try { await enterLocalMode({ restore: true }); return; }
    catch (err) { console.warn("[Auth] 還原本機模式失敗:", err); }
  }
  applyMode("cloud");

  try {
    const [token, userStr] = await Promise.all([
      CapacitorBridge.getSecure(TOKEN_KEY),
      CapacitorBridge.getSecure(USER_KEY),
    ]);
    if (token && userStr) {
      state.token = token;
      state.user = JSON.parse(userStr);
      // 驗證 token 是否仍有效
      try {
        await api("/api/v1/auth/me"); // 假設有此端點，或用其他方式驗證
        showApp();
        return;
      } catch (_) {
        // token 無效，清除並回到登入頁
        await clearStoredAuth();
      }
    }
  } catch (err) {
    console.warn('[Auth] 載入儲存的認證失敗:', err);
  }
  // 沒有有效 token，顯示登入頁
  if (window.Entrance) Entrance.greet();
}

async function saveAuth(token, user) {
  await Promise.all([
    CapacitorBridge.setSecure(TOKEN_KEY, token),
    CapacitorBridge.setSecure(USER_KEY, JSON.stringify(user)),
  ]);
}

async function clearStoredAuth() {
  await Promise.all([
    CapacitorBridge.removeSecure(TOKEN_KEY),
    CapacitorBridge.removeSecure(USER_KEY),
  ]);
  state.token = null;
  state.user = null;
}

// ---------------------------------------------------------------------------
// 模式 UI / Google 登入 / 深層連結
// ---------------------------------------------------------------------------
function setupModeControls() {
  const cloudBtn = $("modeCloudBtn");
  const localBtn = $("modeLocalBtn");
  if (cloudBtn) cloudBtn.addEventListener("click", async () => {
    CapacitorBridge.hapticSelection().catch(() => {});
    applyMode("cloud");
    showAuth("login");
    await persistMode("cloud");
  });
  if (localBtn) localBtn.addEventListener("click", async () => {
    CapacitorBridge.hapticSelection().catch(() => {});
    applyMode("local");
  });
  const enter = $("localEnterBtn");
  if (enter) enter.addEventListener("click", async () => {
    CapacitorBridge.hapticImpact('medium').catch(() => {});
    await enterLocalMode();
  });
  const models = $("localModelBtn");
  if (models) models.addEventListener("click", async () => {
    CapacitorBridge.hapticImpact('light').catch(() => {});
    if (!isLocalMode()) await enterLocalMode();
    if (typeof showLocalModelManager === "function") showLocalModelManager();
  });
  const switchBtn = $("switchModeBtn");
  if (switchBtn) switchBtn.addEventListener("click", switchMode);
  applyMode(state.appMode);
}

function setupGoogleLogin() {
  const btn = $("googleLoginBtn");
  if (btn) btn.addEventListener("click", startGoogleLogin);
}

async function startGoogleLogin() {
  const btn = $("googleLoginBtn");
  showError($("loginError"), "");
  if (btn) btn.disabled = true;
  try {
    if (!getServerUrl()) await discoverServer();
    const data = await api("/api/v1/auth/google/start");
    if (!data || !data.auth_url) throw new Error("伺服器沒有回傳授權網址");
    if (CapacitorBridge.isNative()) {
      // Capacitor WebView 以 _system 交給系統瀏覽器開啟
      const opened = window.open(data.auth_url, "_system");
      if (!opened) window.location.href = data.auth_url;
    } else {
      window.location.href = data.auth_url;
    }
  } catch (err) {
    showError($("loginError"), err.message);
  } finally {
    setTimeout(() => { if (btn) btn.disabled = false; }, 1500);
  }
}

function setupDeepLink() {
  if (!CapacitorBridge.isNative()) return;
  const App = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.App;
  if (!App) return;
  App.addListener("appUrlOpen", (ev) => { handleDeepLink(ev && ev.url); });
  if (typeof App.getLaunchUrl === "function") {
    App.getLaunchUrl().then((res) => { if (res && res.url) handleDeepLink(res.url); }).catch(() => {});
  }
}

async function handleDeepLink(raw) {
  if (!raw || raw.indexOf("meetsum://") !== 0) return;
  let url;
  try { url = new URL(raw.replace("meetsum://", "https://meetsum.local/")); } catch (_) { return; }
  const token = url.searchParams.get("token");
  const error = url.searchParams.get("error");
  if (error) {
    showError($("loginError"), `Google 登入失敗（${error}）`);
    return;
  }
  if (!token) return;
  try {
    state.token = token;
    const me = await api("/api/v1/auth/me");
    state.user = me && me.user ? me.user : me;
    await saveAuth(token, state.user);
    applyMode("cloud");
    await persistMode("cloud");
    if ($("appView").hidden) showApp();
    if (window.Entrance) Entrance.open();
  } catch (err) {
    state.token = null;
    showError($("loginError"), `Google 登入驗證失敗：${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// 裝置端資料（local-first）：不論哪個模式，結果都寫回裝置
// ---------------------------------------------------------------------------
async function cacheMeeting(patch = {}) {
  if (!window.Store || !state.meetingId) return;
  try {
    const existing = (await Store.meetings.get(state.meetingId)) || {};
    const title = ($("meetingTitle") && $("meetingTitle").textContent) || existing.name || "未命名會議";
    await Store.meetings.save({
      ...existing,
      id: state.meetingId,
      name: title,
      meeting_name: title,
      mode: state.appMode,
      status: patch.status || state.status || existing.status || "completed",
      language: ($("uploadForm") && $("uploadForm").elements.asr_language
        ? $("uploadForm").elements.asr_language.value : existing.language) || "zh",
      ...patch,
    });
  } catch (err) { console.warn("[Store] 儲存會議失敗:", err); }
}

async function cacheTranscript(transcript) {
  if (!window.Store || !state.meetingId || !transcript) return;
  try { await Store.transcripts.save(state.meetingId, transcript); }
  catch (err) { console.warn("[Store] 儲存逐字稿失敗:", err); }
}

async function cacheSummary(summary) {
  if (!window.Store || !state.meetingId || !summary) return;
  try { await Store.summaries.save(state.meetingId, summary); }
  catch (err) { console.warn("[Store] 儲存重點失敗:", err); }
}

async function loadLocalMeeting(meetingId) {
  if (!window.Store) return false;
  const meeting = await Store.meetings.get(meetingId);
  if (!meeting) return false;
  const transcript = await Store.transcripts.get(meetingId);
  const summary = await Store.summaries.get(meetingId);
  state.meetingId = String(meetingId);
  state.status = meeting.status || (summary ? "completed" : "transcribed");
  $("meetingTitle").textContent = meeting.meeting_name || meeting.name || "會議";
  $("stepTranscribing").textContent = meeting.mode === "local" ? "本機辨識" : "語音辨識";
  $("uploadCard").hidden = true;
  $("progressCard").hidden = false;
  renderStatus({ status: state.status, error: null });
  if (transcript) {
    state.transcript = transcript;
    review.index = -1;
    renderTranscript();
    updateReviewUI();
    $("transcriptCard").hidden = false;
  }
  if (summary) {
    state.summary = summary;
    syncSummaryLang();
    renderSnapshot(summary);
    $("summaryCard").hidden = false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// 本機模型管理（ASR：Breeze-ASR-26；摘要：Bonsai 27B 1-bit）
// ---------------------------------------------------------------------------
const LOCAL_MODEL_SPECS = [
  {
    id: "breeze-asr-26", name: "Breeze-ASR-26", kind: "asr",
    size: "約 0.6–4 GB", desc: "台語／華語／客語／英語；encoder 在 ANE",
    modelSize: "breeze-asr-26-coreml", quantization: "4bit",
  },
  {
    id: "bonsai-27b-1bit", name: "Bonsai 27B 1-bit", kind: "llm",
    size: "約 3.9 GB", desc: "本機摘要與重點整理（MLX）",
  },
];

async function loadModelPlugins() {
  const out = { asr: null, llm: null };
  try { out.asr = (await import('@meetsum-local-asr')).MeetsumLocalASR || null; } catch (_) { /* ignore */ }
  try { out.llm = (await import('@meetsum-local-llm')).MeetsumLocalLLM || null; } catch (_) { /* ignore */ }
  return out;
}

async function showLocalModelManager() {
  const dlg = $("modelDialog");
  if (!dlg) return;
  showError($("mdMsg"), "");
  const list = $("mdList");
  list.replaceChildren(el("p", "empty", "讀取模型資訊…"));
  if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();

  const plugins = await loadModelPlugins();
  if (!plugins.asr && !plugins.llm) {
    list.replaceChildren(el("p", "empty",
      "這個版本沒有內建原生模型模組（例如在瀏覽器或舊版 App）。請改用雲端模式，或安裝含原生模組的 iOS 版本。"));
    return;
  }

  const device = $("mdDevice");
  if (plugins.asr && plugins.asr.getDeviceCapabilities) {
    try {
      const cap = await plugins.asr.getDeviceCapabilities();
      const gb = Math.round((cap.totalMemoryMB || 0) / 1024 * 10) / 10;
      device.textContent = `這台裝置記憶體 ${gb} GB；建議 ASR ${cap.recommendedModelSize || "—"}。模型只下載一次，之後可離線使用。`;
    } catch (_) { /* ignore */ }
  }

  let statusById = {};
  if (plugins.asr && plugins.asr.getAvailableModels) {
    try {
      const res = await plugins.asr.getAvailableModels();
      for (const m of (res.models || [])) statusById[`asr:${m.name}`] = m;
    } catch (_) { /* ignore */ }
  }
  if (plugins.llm && plugins.llm.modelStatus) {
    try {
      const res = await plugins.llm.modelStatus();
      for (const m of (res.models || [])) statusById[`llm:${m.id}`] = m;
    } catch (_) { /* ignore */ }
  }

  list.replaceChildren();
  for (const spec of LOCAL_MODEL_SPECS) {
    const plugin = spec.kind === "asr" ? plugins.asr : plugins.llm;
    const key = spec.kind === "asr" ? `asr:${spec.modelSize}` : `llm:${spec.id}`;
    const info = statusById[key] || {};
    const downloaded = !!info.downloaded;

    const row = el("div", "model-row");
    const head = el("div", "model-head");
    head.append(el("span", "model-name", `${spec.name}${downloaded ? " ✓" : ""}`));
    head.append(el("span", "model-size", spec.size));
    const body = el("div", "model-desc", spec.desc);
    row.append(head, body);

    if (!plugin) {
      row.append(el("p", "hint", "尚未安裝對應的原生模組"));
      list.append(row);
      continue;
    }

    const status = el("div", "model-status", downloaded ? "已下載" : "尚未下載");
    const actions = el("div", "model-actions");
    if (!downloaded) {
      const btn = el("button", "btn primary small", "下載");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "下載中… 0%";
        try {
          if (spec.kind === "asr") {
            await plugins.asr.downloadModel({ modelSize: spec.modelSize, quantization: spec.quantization });
          } else {
            await plugins.llm.downloadModel({ modelId: spec.id });
          }
          btn.textContent = "已下載 ✓";
          status.textContent = "已下載";
          CapacitorBridge.hapticNotification('success').catch(() => {});
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "重試下載";
          showError($("mdMsg"), `下載失敗：${err.message}`);
        }
      });
      actions.append(btn);
    } else {
      const del = el("button", "btn ghost small", "刪除");
      del.type = "button";
      del.addEventListener("click", async () => {
        if (!window.confirm(`刪除「${spec.name}」模型？下次使用要重新下載。`)) return;
        try {
          if (spec.kind === "asr") await plugins.asr.deleteModel({ modelSize: spec.modelSize, quantization: spec.quantization });
          else await plugins.llm.deleteModel({ modelId: spec.id });
          showLocalModelManager();
        } catch (err) { showError($("mdMsg"), `刪除失敗：${err.message}`); }
      });
      actions.append(del);
    }
    row.append(status, actions);
    list.append(row);
  }
}

const mdClose = $("mdClose");
if (mdClose) mdClose.addEventListener("click", () => $("modelDialog").close());

// 模型下載進度（兩個外掛共用 modelProgress 事件）
(async () => {
  if (!CapacitorBridge.isNative()) return;
  try {
    const asr = (await import('@meetsum-local-asr')).MeetsumLocalASR;
    if (asr && asr.addListener) asr.addListener("transcriptionProgress", (ev) => updateModelProgressUI(ev)).catch(() => {});
  } catch (_) { /* ignore */ }
  try {
    const llm = (await import('@meetsum-local-llm')).MeetsumLocalLLM;
    if (llm && llm.addListener) llm.addListener("modelProgress", (ev) => updateModelProgressUI(ev)).catch(() => {});
  } catch (_) { /* ignore */ }
})();

function updateModelProgressUI(ev) {
  if (!ev) return;
  const pct = Math.round(ev.progress || 0);
  const label = ev.modelName || ev.modelId || "";
  for (const btn of document.querySelectorAll("#mdList .model-row")) {
    if (label && !btn.textContent.includes(label.split("_")[0])) continue;
    const b = btn.querySelector("button.btn.primary");
    if (b) b.textContent = `下載中… ${pct}%`;
  }
}

// ---------------------------------------------------------------------------
// 裝置上的會議紀錄與備份
//
// local-first 的重點不是「有沒有存」，而是「存了之後找得回來」。
// 這裡列出 Store 裡的會議，後端不在線也能打開逐字稿與重點。
// ---------------------------------------------------------------------------
function hdMsg(text, isError = false) {
  const box = $("hdMsg");
  if (!box) return;
  box.textContent = text;
  box.hidden = !text;
  box.classList.toggle("warn", !!isError);
}

function fmtHistoryTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function showMeetingHistory() {
  const dlg = $("historyDialog");
  if (!dlg || !window.Store) return;
  hdMsg("");
  const list = $("hdList");
  list.replaceChildren(el("p", "empty", "讀取中…"));
  if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();

  let meetings = [];
  try { meetings = await Store.meetings.list(); }
  catch (err) { list.replaceChildren(el("p", "empty", `讀取失敗：${err.message}`)); return; }

  list.replaceChildren();
  if (!meetings.length) {
    list.append(el("p", "empty", "這台裝置還沒有任何會議。完成一次辨識或摘要後就會出現在這裡。"));
    return;
  }
  for (const m of meetings) {
    const id = m.id;
    const row = el("div", "hd-row is-open");
    row.tabIndex = 0;
    row.append(el("div", "hd-title", m.meeting_name || m.name || "未命名會議"));
    const meta = el("div", "hd-meta");
    meta.append(
      el("span", null, m.mode === "local" ? "本機" : "雲端"),
      el("span", null, fmtHistoryTime(m.updated_at || m.created_at)),
      el("span", null, m.status || ""),
    );
    row.append(meta);
    const actions = el("div", "hd-actions");
    const openBtn = el("button", "btn primary small", "打開");
    openBtn.type = "button";
    openBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      dlg.close();
      const ok = await loadLocalMeeting(id).catch(() => false);
      if (!ok) showError($("jobError"), "讀不到這筆會議的裝置副本");
    });
    const del = el("button", "btn ghost small", "刪除");
    del.type = "button";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!window.confirm(`從這台裝置刪除「${m.meeting_name || m.name}」？雲端後端上的資料不會被刪。`)) return;
      await Store.meetings.remove(id);
      await Store.transcripts.remove(id);
      await Store.summaries.remove(id);
      showMeetingHistory();
    });
    actions.append(openBtn, del);
    row.append(actions);
    row.addEventListener("click", () => openBtn.click());
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") openBtn.click(); });
    list.append(row);
  }
}

function bytesToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

async function exportBackup() {
  if (!window.Store) return;
  hdMsg("");
  try {
    const data = await Store.exportAll();
    const json = JSON.stringify(data);
    const name = `meetsum-backup-${new Date().toISOString().slice(0, 10)}.json`;
    if (CapacitorBridge.isNative()) {
      await CapacitorBridge.writeFile(name, bytesToBase64(json), "Documents");
      hdMsg(`已存到 App 文件夾：${name}（可用 Finder 或「檔案」App 取出）`);
    } else {
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      hdMsg(`已匯出 ${name}`);
    }
  } catch (err) {
    hdMsg(`匯出失敗：${err.message}`, true);
  }
}

async function importBackup(file) {
  if (!file || !window.Store) return;
  hdMsg("");
  try {
    const data = JSON.parse(await file.text());
    await Store.importAll(data);
    const meetings = await Store.meetings.list();
    await showMeetingHistory();
    hdMsg(`已還原 ${meetings.length} 筆會議`);
  } catch (err) {
    hdMsg(`還原失敗：${err.message}`, true);
  }
}

function setupHistoryControls() {
  const btn = $("historyBtnTop");
  if (btn) btn.addEventListener("click", () => {
    CapacitorBridge.hapticImpact("light").catch(() => {});
    showMeetingHistory();
  });
  const close = $("hdClose");
  if (close) close.addEventListener("click", () => $("historyDialog").close());
  const exp = $("hdExport");
  if (exp) exp.addEventListener("click", exportBackup);
  const imp = $("hdImport");
  if (imp) imp.addEventListener("change", async () => {
    const file = imp.files && imp.files[0];
    imp.value = "";
    if (file) await importBackup(file);
  });
}

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

  const target = apiUrl(path);
  let res;
  try {
    res = await fetch(target, { method, headers, body });
  } catch (_) {
    const base = getServerUrl();
    throw new Error(
      base
        ? `無法連線到伺服器（${base}）。請確認後端已啟動，或點「伺服器」更改位址`
        : "無法連線到後端，請確認頁面是由後端提供"
    );
  }
  if (res.status === 204) return null;
  const contentType = res.headers.get("content-type") || "";
  if (res.ok && !contentType.includes("application/json")) {
    throw new Error(`伺服器回應不是 JSON（${target}）。請確認伺服器位址是否正確`);
  }
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
  const localEntry = $("localEntry");
  if (localEntry) localEntry.hidden = true;
  $("loginForm").hidden = register;
  $("registerForm").hidden = !register;
  showError($("loginError"), register ? "" : (message || ""));
  showError($("registerError"), "");
  if (register) updateRegRules();
}

function accountOk(name) { return /^[A-Za-z0-9_]{3,32}$/.test(name); }
function displayName(user) {
  const u = user || state.user;
  return (u && (u.display_name || u.username)) || "";
}

// 註冊表單：規則一開始就列出來，邊打邊打勾，不用等按下送出才知道
const REG_RULES = {
  ulen: (v) => v.username.trim().length >= 3 && v.username.trim().length <= 32,
  uchars: (v) => v.username.trim().length > 0 && /^[A-Za-z0-9_]*$/.test(v.username.trim()),
  plen: (v) => v.password.length >= 12 && v.password.length <= 200,
  pletter: (v) => /[A-Za-z]/.test(v.password),
  pdigit: (v) => /[0-9]/.test(v.password),
  pmatch: (v) => v.password2.length > 0 && v.password === v.password2,
};
const RULE_FIELD = { ulen: "username", uchars: "username", plen: "password", pletter: "password", pdigit: "password", pmatch: "password2" };
function regValues() {
  const f = $("registerForm");
  return { username: f.username.value, password: f.password.value, password2: f.password2.value };
}
function updateRegRules(showAll = false) {
  const v = regValues();
  for (const li of $("registerForm").querySelectorAll(".rules li")) {
    const rule = li.dataset.rule;
    const ok = REG_RULES[rule](v);
    const touched = showAll || v[RULE_FIELD[rule]].length > 0;
    li.classList.toggle("is-ok", ok);
    li.classList.toggle("is-bad", touched && !ok);
  }
}
$("registerForm").addEventListener("input", () => updateRegRules());
function passwordOk(password) {
  return password.length >= 12 && password.length <= 200 && /[A-Za-z]/.test(password) && /[0-9]/.test(password);
}

async function enterRoom(data, form) {
  state.token = data.access_token;
  state.user = data.user;
  // 儲存到安全儲存
  await saveAuth(state.token, state.user);
  form.reset();
  showAuth("login");
  if (window.Entrance) await Entrance.close(displayName());
  showApp();
  if (window.Entrance) Entrance.open();
}

$("showRegister").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('light').catch(() => {});
  showAuth("register");
});
$("showLogin").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('light').catch(() => {});
  showAuth("login");
});

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  CapacitorBridge.hapticImpact('medium').catch(() => {});
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
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  const f = new FormData(e.target);
  const username = String(f.get("username") || "").trim();
  const password = String(f.get("password") || "");
  const again = String(f.get("password2") || "");
  const display_name = String(f.get("display_name") || "").trim();
  showError($("registerError"), "");
  updateRegRules(true);
  if (display_name.length > 20) {
    showError($("registerError"), "稱呼最多 20 個字");
    return;
  }
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
      method: "POST", json: { username, password, display_name },
    });
    await enterRoom(data, e.target);
  } catch (err) { showError($("registerError"), err.message); }
});

$("logoutBtn").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  if (isLocalMode()) {
    exitToModeChoice();
    return;
  }
  try { await api("/api/v1/auth/logout", { method: "POST" }); } catch (_) {  }
  logoutLocal();
});

function logoutLocal(message) {
  stopPolling();
  if (window.assistant) window.assistant.onLogout();
  Object.assign(state, { token: null, user: null, meetingId: null, status: null, transcript: null, summary: null, proofread: null });
  // 清除安全儲存
  clearStoredAuth();
  $("appView").hidden = true;
  $("userBox").hidden = true;
  $("loginView").hidden = false;
  document.body.classList.add("login-mode");
  applyMode("cloud");
  if (window.Entrance) Entrance.greet();
  showAuth("login", message || "");
}

function showApp() {
  document.body.classList.remove("login-mode");
  $("loginView").hidden = true;
  $("appView").hidden = false;
  $("userBox").hidden = false;
  $("userName").textContent = displayName();
  $("userName").title = isLocalMode() ? "本機模式：資料只存在這台裝置" : `帳號：${state.user.username}`;
  if ($("modeBadge")) $("modeBadge").hidden = !isLocalMode();
  if ($("serverBtnTop")) $("serverBtnTop").hidden = isLocalMode();
  if (window.Entrance) Entrance.greet(displayName());
  resetMeeting();
  if (window.Glossary) window.Glossary.load();
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
$("newMeetingBtn").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  resetMeeting();
});

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

// 本地 ASR 模型選項
const LOCAL_ASR_MODELS = [
  { value: "breeze-asr-26-coreml", label: "Breeze-ASR-26（台語／華語／客語，ANE）⭐ 預設", size_mb: 4300 },
  { value: "tiny", label: "Tiny (~75 MB)", size_mb: 75 },
  { value: "base", label: "Base (~142 MB)", size_mb: 142 },
  { value: "small", label: "Small (~466 MB)", size_mb: 466 },
  { value: "medium", label: "Medium (~1.5 GB)", size_mb: 1500 },
  { value: "large-v3", label: "Large-v3 (~2.9 GB)", size_mb: 2900 },
  { value: "large-v3-turbo", label: "Large-v3 Turbo (~1.6 GB)", size_mb: 1600 },
];

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

// ASR 模式切換處理
function setAsrMode(mode) {
  state.asrMode = mode;
  const form = $("uploadForm");
  const cloudRadio = form.querySelector("input[name=asr_mode][value=cloud]");
  const localRadio = form.querySelector("input[name=asr_mode][value=local]");
  if (cloudRadio) cloudRadio.checked = mode === "cloud";
  if (localRadio) localRadio.checked = mode === "local";

  // 顯示/隱藏本地模式特有選項
  const isLocal = mode === "local";
  const localOptions = document.getElementById("localAsrOptions");
  if (localOptions) localOptions.hidden = !isLocal;

  const label = document.getElementById("asrModeLabel");
  if (label) label.textContent = isLocal ? "本機模式" : "雲端模式";

  // 更新提示文字
  const hint = $("asrModeHint");
  if (hint) {
    hint.textContent = isLocal
      ? "本機模式：音檔不離開這台裝置，需先下載 ASR 與摘要模型"
      : "雲端模式：上傳至伺服器辨識，支援多語言與聲紋識別";
  }

  // 若 UI 未提供本地模式選項（此版本僅雲端），忽略切換要求
  if (isLocal && !document.querySelector('input[name=asr_mode][value=local]')) return;

  // 如果是本地模式且在原生平台，檢查裝置能力
  if (isLocal && CapacitorBridge.isNative()) {
    checkLocalAsrCapabilities();
  }
}

// 監聽模式切換
for (const r of document.querySelectorAll("input[name=asr_mode]")) {
  r.addEventListener("change", () => setAsrMode(r.value));
}

// 建立並插入本地 ASR 選項 UI
function initLocalAsrOptions() {
  // 本地模式此版本未內建（僅雲端模式），UI 上不提供選項
  if (!document.querySelector('input[name=asr_mode][value=local]')) return;
  const asrLangField = $("asrLangField");
  if (asrLangField && !$("localAsrOptions")) {
    const localOptions = createLocalAsrOptions();
    asrLangField.parentNode.insertBefore(localOptions, asrLangField.nextSibling);
  }
}

// 在 DOM 準備好時初始化本地 ASR 選項
document.addEventListener('DOMContentLoaded', () => {
  initLocalAsrOptions();
});

// 檢查本地 ASR 裝置能力
async function checkLocalAsrCapabilities() {
  try {
    const { MeetsumLocalASR } = await import('@meetsum-local-asr');
    const capabilities = await MeetsumLocalASR.getDeviceCapabilities();
    console.log('[Local ASR] 裝置能力:', capabilities);

    // 更新模型選擇器的推薦標記
    updateLocalModelRecommendations(capabilities.recommendedModelSize);

    // 如果模型未下載，提示下載
    const recommendedModel = LOCAL_ASR_MODELS.find(m => m.value === capabilities.recommendedModelSize);
    if (recommendedModel) {
      const available = await MeetsumLocalASR.isModelAvailable({ modelSize: recommendedModel.value });
      if (!available.available) {
        showInfo($("uploadError"), `建議下載 ${recommendedModel.label} 模型以獲得最佳效能`, false);
      }
    }
  } catch (err) {
    console.warn('[Local ASR] 無法檢查裝置能力:', err);
  }
}

// 更新本地模型推薦標記
function updateLocalModelRecommendations(recommended) {
  const select = $("localModelSelect");
  if (!select) return;

  for (const option of select.options) {
    option.textContent = option.textContent.replace(' ⭐ 推薦', '');
    if (option.value === recommended) {
      option.textContent += ' ⭐ 推薦';
    }
  }
}

// 建立本地 ASR 選項 UI
function createLocalAsrOptions() {
  const container = el("div", "local-asr-options");
  container.id = "localAsrOptions";
  container.hidden = state.asrMode !== "local";

  // 模型選擇
  const modelGroup = el("div", "form-group");
  const modelLabel = el("label", null, "模型大小");
  const modelSelect = el("select", "line-input");
  modelSelect.id = "localModelSelect";
  modelSelect.name = "local_model_size";
  for (const model of LOCAL_ASR_MODELS) {
    const opt = el("option", null, model.label);
    opt.value = model.value;
    if (model.value === "breeze-asr-26-coreml") opt.selected = true;
    modelSelect.append(opt);
  }
  modelGroup.append(modelLabel, modelSelect);

  // 量化等級選擇
  const quantGroup = el("div", "form-group");
  const quantLabel = el("label", null, "量化等級");
  const quantSelect = el("select", "line-input");
  quantSelect.id = "localQuantSelect";
  quantSelect.name = "local_quantization";
  const quantOptions = [
    { value: "q4_k", label: "Q4_K (平衡，推薦)" },
    { value: "q5_k", label: "Q5_K (較高品質)" },
    { value: "q8_0", label: "Q8_0 (高品質)" },
    { value: "fp16", label: "FP16 (無量化，體積大)" },
  ];
  for (const q of quantOptions) {
    const opt = el("option", null, q.label);
    opt.value = q.value;
    if (q.value === "q4_k") opt.selected = true;
    quantSelect.append(opt);
  }
  quantGroup.append(quantLabel, quantSelect);

  // 講者辨識開關
  const diarGroup = el("div", "form-group");
  const diarLabel = el("label", "choice");
  const diarCheckbox = el("input", null, null);
  diarCheckbox.type = "checkbox";
  diarCheckbox.name = "local_diarization";
  diarCheckbox.checked = true;
  diarCheckbox.id = "localDiarization";
  diarLabel.append(diarCheckbox, "啟用講者辨識 (聲紋識別)");
  diarGroup.append(diarLabel);

  // VAD 開關
  const vadGroup = el("div", "form-group");
  const vadLabel = el("label", "choice");
  const vadCheckbox = el("input", null, null);
  vadCheckbox.type = "checkbox";
  vadCheckbox.name = "local_vad";
  vadCheckbox.checked = true;
  vadCheckbox.id = "localVad";
  vadLabel.append(vadCheckbox, "使用語音活動偵測 (VAD) 過濾靜音");
  vadGroup.append(vadLabel);

  // 模型管理按鈕
  const actionsGroup = el("div", "form-group");
  const actionsRow = el("div", "button-row");
  const downloadBtn = el("button", "btn ghost small", "下載/更新模型");
  downloadBtn.type = "button";
  downloadBtn.id = "localModelDownloadBtn";
  const checkBtn = el("button", "btn ghost small", "檢查模型狀態");
  checkBtn.type = "button";
  checkBtn.id = "localModelCheckBtn";
  const clearBtn = el("button", "btn ghost small", "清除快取");
  clearBtn.type = "button";
  clearBtn.id = "localModelClearBtn";
  actionsRow.append(downloadBtn, checkBtn, clearBtn);
  actionsGroup.append(actionsRow);

  // 進度顯示區
  const progressGroup = el("div", "form-group");
  progressGroup.id = "localModelProgressGroup";
  progressGroup.hidden = true;
  const progressLabel = el("label", null, "下載進度");
  const progressBar = el("div", "progress-bar");
  const progressFill = el("div", "progress-fill");
  progressFill.id = "localModelProgressFill";
  progressBar.append(progressFill);
  const progressText = el("span", "progress-text", "等待開始...");
  progressText.id = "localModelProgressText";
  progressGroup.append(progressLabel, progressBar, progressText);

  container.append(modelGroup, quantGroup, diarGroup, vadGroup, actionsGroup, progressGroup);

  // 綁定事件
  downloadBtn.addEventListener("click", handleLocalModelDownload);
  checkBtn.addEventListener("click", handleLocalModelCheck);
  clearBtn.addEventListener("click", handleLocalModelClear);

  return container;
}

// 處理本地模型下載
async function handleLocalModelDownload() {
  if (!CapacitorBridge.isNative()) {
    showError($("uploadError"), "本地模式僅支援 iOS 實機");
    return;
  }

  const modelSize = $("localModelSelect").value;
  let quantization = $("localQuantSelect").value;
  if (String(modelSize).startsWith("breeze")) quantization = "4bit";

  const progressGroup = $("localModelProgressGroup");
  const progressFill = $("localModelProgressFill");
  const progressText = $("localModelProgressText");
  const downloadBtn = $("localModelDownloadBtn");

  progressGroup.hidden = false;
  downloadBtn.disabled = true;
  downloadBtn.textContent = "下載中...";
  progressFill.style.width = "0%";
  progressText.textContent = "準備下載...";

  try {
    const { MeetsumLocalASR } = await import('@meetsum-local-asr');

    // 監聽下載進度
    const listener = await MeetsumLocalASR.addListener('transcriptionProgress', (progress) => {
      if (progress.modelName !== `${modelSize}_${quantization}`) return;
      const pct = progress.progress;
      progressFill.style.width = `${pct}%`;
      progressText.textContent = `${progress.status === 'downloading' ? '下載中' : progress.status === 'verifying' ? '驗證中' : progress.status === 'completed' ? '完成' : '失敗'} ${pct}%`;
      if (progress.bytesDownloaded && progress.totalBytes) {
        const mbDown = (progress.bytesDownloaded / 1024 / 1024).toFixed(1);
        const mbTotal = (progress.totalBytes / 1024 / 1024).toFixed(1);
        progressText.textContent += ` (${mbDown} / ${mbTotal} MB)`;
      }
      if (progress.error) {
        progressText.textContent += ` - ${progress.error}`;
      }
    });

    downloadBtn.disabled = false;
    downloadBtn.textContent = "取消下載";

    const result = await MeetsumLocalASR.downloadModel({ modelSize, quantization });

    listener.remove();

    if (result.success) {
      progressFill.style.width = "100%";
      progressText.textContent = "下載完成！";
      downloadBtn.textContent = "下載/更新模型";
      downloadBtn.disabled = false;
      showError($("uploadError"), "");
    } else {
      progressText.textContent = `失敗: ${result.error}`;
      downloadBtn.textContent = "下載/更新模型";
      downloadBtn.disabled = false;
      showError($("uploadError"), result.error || "下載失敗");
    }
  } catch (err) {
    progressText.textContent = `錯誤: ${err.message}`;
    downloadBtn.textContent = "下載/更新模型";
    downloadBtn.disabled = false;
    showError($("uploadError"), err.message);
  }
}

// 檢查本地模型狀態
async function handleLocalModelCheck() {
  if (!CapacitorBridge.isNative()) {
    showError($("uploadError"), "本地模式僅支援 iOS 實機");
    return;
  }

  try {
    const { MeetsumLocalASR } = await import('@meetsum-local-asr');
    const { models } = await MeetsumLocalASR.getAvailableModels();

    let msg = "模型狀態：\n";
    for (const m of models) {
      msg += `${m.name} (${m.quantization}): ${m.downloaded ? '✓ 已下載' : '✗ 未下載'} (${m.size_mb} MB)\n`;
    }
    alert(msg);
  } catch (err) {
    showError($("uploadError"), err.message);
  }
}

// 清除本地模型快取
async function handleLocalModelClear() {
  if (!CapacitorBridge.isNative()) {
    showError($("uploadError"), "本地模式僅支援 iOS 實機");
    return;
  }

  if (!window.confirm("確定要清除所有暫存檔案嗎？這不會刪除已下載的模型。")) return;

  try {
    const { MeetsumLocalASR } = await import('@meetsum-local-asr');
    await MeetsumLocalASR.clearCache();
    showError($("uploadError"), "快取已清除", false);
  } catch (err) {
    showError($("uploadError"), err.message);
  }
}

// 處理本地 ASR 上傳
async function handleLocalTranscription(form) {
  if (!CapacitorBridge.isNative()) {
    showError($("uploadError"), "本地模式僅支援 iOS 實機，請切換至雲端模式或使用 iOS App");
    return;
  }

  const audioFile = form.get("audio");
  if (!audioFile) {
    showError($("uploadError"), "請選擇音檔");
    return;
  }

  const language = form.get("asr_language") || "zh";
  const enableDiarization = form.get("local_diarization") === "on" || form.get("local_diarization") === "true";
  const modelSize = form.get("local_model_size") || "breeze-asr-26-coreml";
  let quantization = form.get("local_quantization") || "q4_k";
  if (String(modelSize).startsWith("breeze")) quantization = "4bit";
  const useVad = form.get("local_vad") === "on" || form.get("local_vad") === "true";

  // 先將音檔存到本地檔案系統
  showError($("uploadError"), "準備音檔...");
  $("uploadBtn").disabled = true;
  $("uploadBtn").textContent = "處理中…";

  try {
    // 讀取檔案並轉為 base64
    const base64 = await fileToBase64(audioFile);
    const fileName = `meeting_${Date.now()}.${audioFile.name.split('.').pop()}`;

    // 寫入檔案系統
    const { uri } = await CapacitorBridge.writeFile(fileName, base64, 'Documents');

    // 開始本地轉錄
    const { MeetsumLocalASR } = await import('@meetsum-local-asr');

    const { jobId } = await MeetsumLocalASR.transcribe({
      audioPath: uri,
      language,
      enableDiarization,
      modelSize,
      quantization,
      engine: String(modelSize).startsWith("breeze") ? "breezeasr" : "whisperkit",
      useVad,
    });

    state.localAsrJobId = jobId;
    state.meetingId = `local_${jobId}`;

    // 設定會議標題
    const meetingName = form.get("meeting_name") || `本地會議 ${new Date().toLocaleString()}`;
    $("meetingTitle").textContent = meetingName;
    $("stepTranscribing").textContent = `本地語音辨識 (${modelSize})`;

    // 隱藏上傳卡片，顯示進度
    $("uploadCard").hidden = true;
    $("progressCard").hidden = false;
    renderStatus({ status: "transcribing", error: null });

    // 監聽轉錄進度
    state.localAsrListener = await MeetsumLocalASR.addListener('transcriptionProgress', (progress) => {
      if (progress.modelName === 'transcription') {
        state.localAsrProgress = progress.progress;
        // 更新進度顯示
        updateLocalAsrProgress(progress);
      }
    });

    // 監聽完成事件
    const completeListener = await MeetsumLocalASR.addListener('transcriptionComplete', async (result) => {
      state.localAsrListener?.remove();
      completeListener.remove();
      await handleLocalAsrComplete(result);
    });

    // 監聽錯誤事件
    const errorListener = await MeetsumLocalASR.addListener('transcriptionError', async (error) => {
      state.localAsrListener?.remove();
      completeListener.remove();
      errorListener.remove();
      await handleLocalAsrError(error.message);
    });

  } catch (err) {
    showError($("uploadError"), err.message);
    $("uploadBtn").disabled = false;
    $("uploadBtn").textContent = "開始整理";
  }
}

// 更新本地 ASR 進度顯示
function updateLocalAsrProgress(progress) {
  // 更新波形動畫或進度文字
  const statusText = $("statusText");
  if (statusText) {
    statusText.textContent = `本地辨識中... ${progress.progress}% (${progress.status})`;
  }
}

// 處理本地 ASR 完成
async function handleLocalAsrComplete(result) {
  // 轉換結果格式以符合現有 UI
  const transcript = {
    version: 1,
    meeting_id: state.meetingId,
    asr_model: result.model_used || "whisperkit-local",
    segment_count: result.segments.length,
    segments: result.segments.map((seg, i) => ({
      segment_id: seg.segment_id || `S${String(i + 1).padStart(4, '0')}`,
      segment_index: i,
      start_ms: seg.start_ms,
      end_ms: seg.end_ms,
      text: seg.text,
      speaker: seg.speaker || "SPEAKER_00",
    })),
    asr_info: {
      mode: "local",
      model: result.model_used,
      language: result.language,
      duration_ms: result.duration_ms,
    },
  };

  state.transcript = transcript;
  state.status = "reviewing"; // 本地模式直接進入校對階段

  renderTranscript();
  renderStatus({ status: "transcribed", error: null });
  $("transcriptCard").hidden = false;

  // 寫回裝置，切換模式或重開 App 都不會失憶
  cacheMeeting({ status: "reviewing", name: $("meetingTitle").textContent, mode: "local" });
  cacheTranscript(transcript);

  // 更新步驟顯示
  for (const li of $("steps").children) {
    const step = li.dataset.step;
    if (["uploaded", "transcribing"].includes(step)) li.className = "done";
    else if (step === "proofreading") li.className = "active user";
    else li.className = "";
  }

  showError($("uploadError"), "");
}

// 處理本地 ASR 錯誤
async function handleLocalAsrError(message) {
  renderStatus({ status: "failed", error: { message, stage: "transcribing" } });
  showError($("jobError"), `本地辨識失敗：${message}`);
  $("uploadBtn").disabled = false;
  $("uploadBtn").textContent = "開始整理";
}

// 檔案轉 base64
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// 顯示資訊訊息 (非錯誤)
function showInfo(el, msg, isError = true) {
  el.textContent = msg;
  el.hidden = !msg;
  el.style.color = isError ? 'var(--error)' : 'var(--success)';
  setTimeout(() => { if (!isError) el.hidden = true; }, 5000);
}

$("uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  const form = new FormData(e.target);

  // 根據 ASR 模式分流處理
  if (state.asrMode === "local") {
    await handleLocalTranscription(form);
    return;
  }

  // 雲端模式：原有邏輯
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
    cacheMeeting({ status: data.status, name: data.meeting_name });
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
  catch (err) {
    // 後端連不上（例如 Colab 重啟）時，改讀裝置上的副本，避免失憶
    const ok = await loadLocalMeeting(meetingId).catch(() => false);
    if (!ok) showError($("jobError"), `開啟會議失敗：${err.message}`);
    return;
  }
  $("meetingTitle").textContent = st.meeting_name;
  $("stepTranscribing").textContent = st.source_type === "transcript" ? "自動分段" : "語音辨識";
  $("uploadCard").hidden = true;
  $("progressCard").hidden = false;
  renderStatus(st);
  cacheMeeting({ status: st.status, name: st.meeting_name });
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
  if (changed) cacheMeeting({ status: data.status, name: data.meeting_name });

  const failedStage = data.status === "failed" && data.error ? data.error.stage : null;
  const hasTranscript = ["proofreading", "reviewing", "transcribed", "summarizing", "completed"].includes(data.status)
    || ["proofreading", "summarizing"].includes(failedStage);
  if (hasTranscript && (!state.transcript || (changed && data.status !== "summarizing"))) await loadTranscript();
  if (data.status === "completed" && (changed || $("summaryCard").hidden)) await loadSummary();

  // 會議完成時發送本地通知 (僅發送一次)
  if (data.status === "completed" && changed && !state.notifiedMeetings.has(state.meetingId)) {
    state.notifiedMeetings.add(state.meetingId);
    const meetingName = data.meeting_name || "會議";
    try {
      await CapacitorBridge.scheduleNotification({
        id: Date.now(),
        title: "覓聲 MeetSum",
        body: `「${meetingName}」處理完成，重點已產生！`,
        extra: { meetingId: state.meetingId },
      });
      // 觸覺回饋
      CapacitorBridge.hapticNotification('success').catch(() => {});
    } catch (err) {
      console.warn('[Notification] 發送失敗:', err);
    }
  }

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
  cacheTranscript(t);
  if (state.status === "reviewing") gotoTypo(nextPending(-1), false);
  $("transcriptCard").hidden = false;
}

function renderTranscript() {
  if (window.Glossary) window.Glossary.hideSelBar();
  const list = $("transcriptList");
  const keep = list.scrollTop;
  const editable = state.status === "reviewing";
  const bySeg = {};
  for (const t of suggestions()) (bySeg[t.segment_id] = bySeg[t.segment_id] || []).push(t);
  list.replaceChildren();
  for (const seg of state.transcript.segments) {
    const li = el("li", editable ? "editable" : null);
    li.id = `seg-${seg.segment_id}`;

    // 講者標籤
    const speaker = seg.speaker || "SPEAKER_00";
    const speakerLabel = speaker.replace("SPEAKER_", "講者 ");
    const speakerBadge = el("span", `speaker-badge speaker-${speaker}`, `👤 ${speakerLabel}`);
    speakerBadge.dataset.speaker = speaker;
    speakerBadge.title = `點擊篩選 ${speakerLabel}`;
    speakerBadge.addEventListener("click", () => filterBySpeaker(speaker));

    const range = seg.start_ms == null ? "—" : `${fmtMs(seg.start_ms)}–${fmtMs(seg.end_ms)}`;
    const time = el("span", "time", range);
    time.append(el("span", "sid", seg.segment_id));
    li.append(time, speakerBadge, segmentText(seg, bySeg[seg.segment_id] || []));
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

  // 更新講者面板
  updateSpeakerPanel();
}

// ===== 講者管理功能 =====

// 目前的講者篩選狀態
let speakerFilter = null; // null = 顯示全部，否則為特定講者 ID

function updateSpeakerPanel() {
  if (!state.transcript) return;

  // 統計每位講者的段落數
  const speakerCounts = {};
  for (const seg of state.transcript.segments) {
    const s = seg.speaker || "SPEAKER_00";
    speakerCounts[s] = (speakerCounts[s] || 0) + 1;
  }
  const speakers = Object.keys(speakerCounts).sort();

  // 建立或更新講者面板
  let panel = $("speakerPanel");
  if (!panel) {
    panel = createSpeakerPanel();
    // 插入到 transcriptCard 的開頭
    const transcriptCard = $("transcriptCard");
    if (transcriptCard) {
      transcriptCard.insertBefore(panel, transcriptCard.firstChild);
    }
  }

  // 更新講者列表
  const list = panel.querySelector(".speaker-list");
  if (list) {
    list.replaceChildren();
    for (const speaker of speakers) {
      const count = speakerCounts[speaker];
      const item = createSpeakerItem(speaker, count);
      list.append(item);
    }
  }

  // 更新圖例
  const legend = panel.querySelector(".speaker-legend");
  if (legend) {
    legend.replaceChildren();
    for (const speaker of speakers) {
      const count = speakerCounts[speaker];
      const item = el("span", "speaker-legend-item");
      const colorDot = el("span", "speaker-color");
      colorDot.style.background = getSpeakerColor(speaker);
      item.append(colorDot, speaker.replace("SPEAKER_", "講者 "), el("span", "speaker-count", count));
      legend.append(item);
    }
  }
}

function createSpeakerPanel() {
  const panel = el("div", "speaker-panel");
  panel.id = "speakerPanel";

  const head = el("div", "speaker-panel-head");
  const title = el("h3", null, "講者");
  const clearFilter = el("button", "btn ghost small", "顯示全部");
  clearFilter.type = "button";
  clearFilter.addEventListener("click", () => filterBySpeaker(null));
  head.append(title, clearFilter);

  const list = el("div", "speaker-list");
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "講者列表");

  const actions = el("div", "speaker-actions");
  const renameBtn = el("button", "btn ghost small", "重新命名");
  renameBtn.type = "button";
  renameBtn.addEventListener("click", () => openSpeakerRenameModal());
  const mergeBtn = el("button", "btn ghost small", "合併講者");
  mergeBtn.type = "button";
  mergeBtn.addEventListener("click", () => openSpeakerMergeModal());
  actions.append(renameBtn, mergeBtn);

  const filterWrap = el("div", "speaker-filter");
  const filterCheckbox = el("input", null, null);
  filterCheckbox.type = "checkbox";
  filterCheckbox.id = "speakerFilterEnabled";
  filterCheckbox.addEventListener("change", () => {
    speakerFilter = filterCheckbox.checked ? (speakerFilter || Object.keys(getSpeakerCounts())[0] || null) : null;
    filterCheckbox.checked = !!speakerFilter;
    applySpeakerFilter();
  });
  const filterLabel = el("label", null, "啟用講者篩選");
  filterLabel.setAttribute("for", "speakerFilterEnabled");
  filterWrap.append(filterCheckbox, filterLabel);
  actions.append(filterWrap);

  const legend = el("div", "speaker-legend");

  panel.append(head, list, actions, legend);
  return panel;
}

function createSpeakerItem(speaker, count) {
  const item = el("div", "speaker-item");
  item.dataset.speaker = speaker;
  item.setAttribute("role", "option");
  item.setAttribute("aria-selected", String(speaker === speakerFilter));

  const colorDot = el("span", "speaker-color");
  colorDot.style.background = getSpeakerColor(speaker);

  const name = el("span", "speaker-name", speaker.replace("SPEAKER_", "講者 "));
  const countEl = el("span", "speaker-count", count);

  item.append(colorDot, name, countEl);
  item.addEventListener("click", () => filterBySpeaker(speaker === speakerFilter ? null : speaker));
  return item;
}

function getSpeakerCounts() {
  if (!state.transcript) return {};
  const counts = {};
  for (const seg of state.transcript.segments) {
    const s = seg.speaker || "SPEAKER_00";
    counts[s] = (counts[s] || 0) + 1;
  }
  return counts;
}

function getSpeakerColor(speaker) {
  // 從 CSS 類別名稱對應顏色
  const colors = {
    "SPEAKER_00": "#1565c0",
    "SPEAKER_01": "#c62828",
    "SPEAKER_02": "#2e7d32",
    "SPEAKER_03": "#ef6c00",
    "SPEAKER_04": "#7b1fa2",
    "SPEAKER_05": "#00695c",
    "SPEAKER_06": "#bf360c",
    "SPEAKER_07": "#4527a0",
    "SPEAKER_08": "#283593",
    "SPEAKER_09": "#558b2f",
    "SPEAKER_10": "#f57f17",
    "SPEAKER_11": "#616161",
    "SPEAKER_12": "#37474f",
    "SPEAKER_13": "#ad1457",
    "SPEAKER_14": "#006064",
    "SPEAKER_15": "#e65100",
  };
  return colors[speaker] || "#616161";
}

function filterBySpeaker(speaker) {
  speakerFilter = speaker;
  applySpeakerFilter();
  updateSpeakerPanelSelection();
}

function applySpeakerFilter() {
  const list = $("transcriptList");
  if (!list) return;

  for (const li of list.children) {
    const badge = li.querySelector(".speaker-badge");
    if (!badge) continue;
    const segSpeaker = badge.dataset.speaker;
    if (speakerFilter && segSpeaker !== speakerFilter) {
      li.style.display = "none";
    } else {
      li.style.display = "";
    }
  }

  // 更新面板上的篩選狀態
  const checkbox = $("speakerFilterEnabled");
  if (checkbox) checkbox.checked = !!speakerFilter;
}

function updateSpeakerPanelSelection() {
  const panel = $("speakerPanel");
  if (!panel) return;
  for (const item of panel.querySelectorAll(".speaker-item")) {
    const selected = item.dataset.speaker === speakerFilter;
    item.setAttribute("aria-selected", String(selected));
    item.classList.toggle("editing", false);
  }
}

// 講者重新命名 Modal
function openSpeakerRenameModal() {
  const speakers = Object.keys(getSpeakerCounts()).sort();
  if (!speakers.length) return;

  const modal = el("div", "modal-overlay");
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-labelledby="renameTitle" aria-modal="true">
      <h3 id="renameTitle">重新命名講者</h3>
      <p class="modal-hint">將系統自動偵測的講者代號改為易懂的名稱（如：張經理、李工程師）</p>
      <div class="modal-body" id="renameBody"></div>
      <div class="modal-actions">
        <button type="button" class="btn ghost" data-close>取消</button>
        <button type="button" class="btn primary" data-save>儲存</button>
      </div>
    </div>
  `;

  const body = modal.querySelector("#renameBody");
  for (const speaker of speakers) {
    const row = el("div", "rename-row");
    const badge = el("span", `speaker-badge speaker-${speaker}`, speaker.replace("SPEAKER_", "講者 "));
    const input = el("input", "rename-input");
    input.type = "text";
    input.placeholder = "輸入名稱...";
    input.dataset.speaker = speaker;
    input.value = getCustomSpeakerName(speaker) || "";
    row.append(badge, input);
    body.append(row);
  }

  document.body.append(modal);

  modal.querySelector("[data-close]").addEventListener("click", () => modal.remove());
  modal.querySelector("[data-save]").addEventListener("click", async () => {
    const mapping = {};
    for (const input of modal.querySelectorAll(".rename-input")) {
      const val = input.value.trim();
      if (val) mapping[input.dataset.speaker] = val;
    }
    await applySpeakerRename(mapping);
    modal.remove();
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.remove();
  });

  // 聚焦第一個輸入框
  const firstInput = modal.querySelector(".rename-input");
  if (firstInput) firstInput.focus();
}

function getCustomSpeakerName(speaker) {
  const stored = localStorage.getItem(`speakerName_${state.meetingId}_${speaker}`);
  return stored || "";
}

function setCustomSpeakerName(speaker, name) {
  if (name) {
    localStorage.setItem(`speakerName_${state.meetingId}_${speaker}`, name);
  } else {
    localStorage.removeItem(`speakerName_${state.meetingId}_${speaker}`);
  }
}

async function applySpeakerRename(mapping) {
  if (!state.meetingId || !Object.keys(mapping).length) return;

  try {
    // 呼叫 API 更新講者名稱
    const res = await api(`/api/v1/meetings/${state.meetingId}/transcript/speakers`, {
      method: "PUT",
      json: { mapping }
    });

    // 更新本地狀態
    for (const [oldName, newName] of Object.entries(mapping)) {
      setCustomSpeakerName(oldName, newName);
    }

    // 重新載入逐字稿
    await loadTranscript();
  } catch (err) {
    showError($("rpError") || $("uploadError"), `重新命名失敗：${err.message}`);
  }
}

// 講者合併 Modal
function openSpeakerMergeModal() {
  const speakers = Object.keys(getSpeakerCounts()).sort();
  if (speakers.length < 2) return;

  const modal = el("div", "modal-overlay");
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-labelledby="mergeTitle" aria-modal="true">
      <h3 id="mergeTitle">合併講者</h3>
      <p class="modal-hint">將多位被誤判為不同講者的片段合併為同一位講者</p>
      <div class="modal-body" id="mergeBody"></div>
      <div class="modal-actions">
        <button type="button" class="btn ghost" data-close>取消</button>
        <button type="button" class="btn primary" data-save>合併</button>
      </div>
    </div>
  `;

  const body = modal.querySelector("#mergeBody");

  // 目標講者選擇
  const targetGroup = el("div", "merge-group");
  targetGroup.append(el("label", null, "合併目標（保留這個講者）："));
  const targetSelect = el("select", "merge-select");
  targetSelect.id = "mergeTarget";
  for (const speaker of speakers) {
    const opt = el("option", null, speaker.replace("SPEAKER_", "講者 "));
    opt.value = speaker;
    targetSelect.append(opt);
  }
  targetGroup.append(targetSelect);
  body.append(targetGroup);

  // 來源講者選擇（可多選）
  const sourceGroup = el("div", "merge-group");
  sourceGroup.append(el("label", null, "要合併進去的講者（可多選）："));
  const sourceList = el("div", "merge-source-list");
  for (const speaker of speakers) {
    const row = el("label", "merge-source-row");
    const checkbox = el("input", null, null);
    checkbox.type = "checkbox";
    checkbox.value = speaker;
    checkbox.dataset.speaker = speaker;
    const badge = el("span", `speaker-badge speaker-${speaker}`, speaker.replace("SPEAKER_", "講者 "));
    row.append(checkbox, badge);
    sourceList.append(row);
  }
  sourceGroup.append(sourceList);
  body.append(sourceGroup);

  document.body.append(modal);

  modal.querySelector("[data-close]").addEventListener("click", () => modal.remove());
  modal.querySelector("[data-save]").addEventListener("click", async () => {
    const target = modal.querySelector("#mergeTarget").value;
    const sources = [...modal.querySelectorAll(".merge-source-row input:checked")].map(cb => cb.value);

    if (!sources.length) {
      alert("請至少選擇一個要合併的講者");
      return;
    }
    if (sources.includes(target)) {
      alert("目標講者不能同時是來源講者");
      return;
    }

    const mapping = {};
    for (const s of sources) mapping[s] = target;

    await applySpeakerRename(mapping);
    modal.remove();
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.remove();
  });
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

$("downloadJsonBtn").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('light').catch(() => {});
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
  if (window.Glossary) window.Glossary.renderTermCandidates();
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
$("typoPrev").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('light').catch(() => {});
  gotoTypo(review.index <= 0 ? suggestions().length - 1 : review.index - 1);
});
$("typoNext").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('light').catch(() => {});
  gotoTypo(review.index + 1);
});

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
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  const n = state.proofread ? state.proofread.counts.pending : 0;
  if (!n || !window.confirm(`把還沒處理的 ${n} 處全部改成 AI 建議的字？（之後還可以一處一處復原）`)) return;
  await decide("accept", null);
});

$("confirmBtn").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  const n = state.proofread ? state.proofread.counts.pending : 0;
  if (n && !window.confirm(`還有 ${n} 處疑似錯字沒處理，確認後這些地方會保留原文。確定要確認逐字稿嗎？`)) return;
  $("confirmBtn").disabled = true;
  try {
    if (isLocalMode()) {
      // 本機模式沒有雲端校對流程，直接確認逐字稿
      review.index = -1;
      renderStatus({ status: "transcribed", error: null });
      cacheMeeting({ status: "transcribed" });
      return;
    }
    const data = await api(`/api/v1/meetings/${state.meetingId}/transcript/confirm`, { method: "POST" });
    review.index = -1;
    renderStatus({ status: data.status, error: null });
    await loadTranscript();
  } catch (err) { showError($("rpError"), err.message); }
  finally { $("confirmBtn").disabled = false; }
});

$("reproofBtn").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  if (isLocalMode()) {
    showError($("jobError"), "本機模式目前不提供 AI 錯字校對，請直接確認逐字稿。");
    return;
  }
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
  CapacitorBridge.hapticImpact('medium').catch(() => {});
  $("summarizeBtn").disabled = true;
  try {
    if (isLocalMode()) {
      await localSummarize();
      return;
    }
    const data = await api(`/api/v1/meetings/${state.meetingId}/summary`,
      { method: "POST", json: { language: $("summaryLang").value } });
    renderStatus({ status: data.status, error: null });
    startPolling();
  } catch (err) {
    showError($("jobError"), err.message);
    $("summarizeBtn").disabled = false;
  }
});

// ---------------------------------------------------------------------------
// 本機摘要（Bonsai 27B / MLX）：結果寫回裝置
// ---------------------------------------------------------------------------
function asArray(v) { return Array.isArray(v) ? v : []; }

function normalizeLocalSummary(res, lang) {
  const now = new Date().toISOString();
  const parsed = (res && (res.json || res.summary)) || null;
  const dateInput = $("uploadForm") && $("uploadForm").elements.date;
  const sm = {
    meeting_name: ($("meetingTitle") && $("meetingTitle").textContent) || "會議重點",
    meeting_datetime: (dateInput && dateInput.value) || now.slice(0, 10),
    headline: (parsed && parsed.headline) || "",
    meeting_content: {
      decisions: asArray(parsed && parsed.decisions).map((d) => ({
        summary: d.summary || d.text || String(d),
        evidence: asArray(d.evidence),
      })),
      action_items: asArray(parsed && parsed.action_items).map((a) => ({
        assignees: asArray(a.assignees),
        task: a.task || "",
        due_date: a.due_date || null,
        due_text: a.due_text || null,
      })),
      discussions: asArray(parsed && parsed.discussions).map((d) => ({
        topic: d.topic || "",
        summary: d.summary || "",
        key_points: asArray(d.key_points),
        evidence: asArray(d.evidence),
      })),
      reports: asArray(parsed && parsed.reports).map((r) => ({
        topic: r.topic || "",
        summary: r.summary || "",
        evidence: asArray(r.evidence),
      })),
      next_meeting: (parsed && parsed.next_meeting) || { status: "not_mentioned" },
    },
    review_notes: asArray(parsed && parsed.review_notes),
    language: lang,
  };
  if (!parsed && res && res.text) {
    sm.meeting_content.discussions.push({
      topic: "本機摘要", summary: String(res.text).slice(0, 6000), key_points: [], evidence: [],
    });
  }
  return {
    summary: sm,
    model_name: (res && res.model) || "Bonsai 27B（本機）",
    updated_at: now,
    mode: "local",
  };
}

async function localSummarize() {
  const lang = $("summaryLang").value;
  const segs = (state.transcript && state.transcript.segments) || [];
  const text = segs.map((s) => `[${s.segment_id}] ${s.text}`).join("\n");
  if (!text) throw new Error("沒有逐字稿可以摘要");

  let mod;
  try { mod = await import('@meetsum-local-llm'); }
  catch (_) { throw new Error("本機摘要模組未安裝，請先下載模型"); }
  const LLM = mod.MeetsumLocalLLM;
  if (!LLM) throw new Error("本機摘要模組未安裝");

  $("uploadCard").hidden = true;
  $("progressCard").hidden = false;
  renderStatus({ status: "summarizing", error: null });

  let received = 0;
  let listener = null;
  try {
    listener = await LLM.addListener("llmToken", (ev) => {
      received += String((ev && ev.token) || "").length;
      const st = $("statusText");
      if (st) st.textContent = `本機摘要中… 已產生 ${received} 字`;
    });
  } catch (_) { listener = null; }

  try {
    const res = await LLM.summarize({
      transcript: text,
      language: lang,
      meetingName: ($("meetingTitle") && $("meetingTitle").textContent) || "",
      glossary: ((state.glossary && state.glossary.terms) || []).map((t) => t.term),
    });
    const data = normalizeLocalSummary(res, lang);
    state.summary = data;
    state.status = "completed";
    renderStatus({ status: "completed", error: null });
    syncSummaryLang();
    renderSnapshot(data);
    cacheSummary(data);
    cacheMeeting({ status: "completed" });
    $("summaryCard").hidden = false;
    CapacitorBridge.hapticNotification('success').catch(() => {});
  } finally {
    if (listener && listener.remove) { try { listener.remove(); } catch (_) { /* ignore */ } }
    $("summarizeBtn").disabled = false;
  }
}

const NEXT_LABEL = { confirmed: "已確認", tentative: "暫定", not_mentioned: "未提及" };

async function loadSummary() {
  let data;
  try { data = await api(`/api/v1/meetings/${state.meetingId}/summary`); }
  catch (err) {
    // 後端不在線時讀裝置上的副本
    const cached = window.Store ? await Store.summaries.get(state.meetingId).catch(() => null) : null;
    if (!cached) { showError($("jobError"), `讀取重點失敗：${err.message}`); return; }
    data = cached;
  }
  state.summary = data;
  syncSummaryLang();
  renderSnapshot(data);
  cacheSummary(data);
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

// 時間軸：每一類一條獨立的軌道，使用者自己勾要看哪幾類（預設只看決議，比較不擠）
const TL_KINDS = [
  { key: "decision", label: "決議", field: "decisions", text: (d) => d.summary },
  { key: "action", label: "待辦", field: "action_items", text: (a) => a.task },
  { key: "discussion", label: "討論", field: "discussions", text: (d) => d.topic || d.summary },
  { key: "report", label: "報告", field: "reports", text: (r) => r.topic || r.summary },
];
const TL_STORE = "meetsum.timelineKinds";
function loadTimelineKinds() {
  try {
    const saved = JSON.parse(localStorage.getItem(TL_STORE) || "null");
    if (Array.isArray(saved)) return new Set(saved.filter((k) => TL_KINDS.some((t) => t.key === k)));
  } catch (_) { /* 瀏覽器不給存就用預設 */ }
  return new Set(["decision"]);
}
function saveTimelineKinds(set) {
  try { localStorage.setItem(TL_STORE, JSON.stringify([...set])); } catch (_) { /* 忽略 */ }
}

function timelineBlock(mc, times) {
  const s = el("div", "block timeline");
  const head = el("div", "timeline-head");
  head.append(blockTitle("會議時間軸", "plain"));

  const shown = loadTimelineKinds();
  const filters = el("div", "tl-filters");
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", "時間軸要顯示的類別");
  const lanes = el("div", "tl-lanes");
  const empty = el("p", "empty tl-empty", "勾選上面的類別，時間軸就會顯示那一類的時間點。");

  const points = {};
  for (const k of TL_KINDS) {
    points[k.key] = (mc[k.field] || []).map((it) => ({ it, t: firstTime(it, times) })).filter((x) => x.t);
  }

  const chips = {};
  const allBtn = el("button", "tl-chip tl-all", "全部");
  allBtn.type = "button";

  const render = () => {
    lanes.replaceChildren();
    for (const k of TL_KINDS) {
      chips[k.key].setAttribute("aria-pressed", String(shown.has(k.key)));
      if (shown.has(k.key)) lanes.append(laneOf(k, points[k.key], times));
    }
    allBtn.setAttribute("aria-pressed", String(shown.size === TL_KINDS.length));
    empty.hidden = shown.size > 0;
    saveTimelineKinds(shown);
  };

  for (const k of TL_KINDS) {
    const b = el("button", `tl-chip tl-${k.key}`);
    b.type = "button";
    b.append(el("i", "tl-shape"), el("span", null, k.label), el("span", "tl-count", String(points[k.key].length)));
    b.title = `在時間軸上顯示或隱藏${k.label}`;
    b.addEventListener("click", () => {
      if (shown.has(k.key)) shown.delete(k.key); else shown.add(k.key);
      render();
    });
    chips[k.key] = b;
    filters.append(b);
  }
  allBtn.addEventListener("click", () => {
    if (shown.size === TL_KINDS.length) { shown.clear(); shown.add("decision"); }
    else for (const k of TL_KINDS) shown.add(k.key);
    render();
  });
  filters.append(allBtn);
  head.append(filters);

  const ticks = el("div", "ticks");
  for (let i = 0; i <= 4; i++) ticks.append(el("span", null, fmtMs((times.duration * i) / 4)));
  const ticksRow = el("div", "tl-ticks-row");
  ticksRow.append(el("span", "tl-lane-label"), ticks);

  render();
  s.append(head, lanes, empty, ticksRow);
  return s;
}

function laneOf(kind, pts, times) {
  const lane = el("div", `tl-lane tl-${kind.key}`);
  const label = el("span", "tl-lane-label", kind.label);
  const track = el("div", "track");
  track.append(el("div", "track-line"));
  if (!pts.length) track.append(el("span", "tl-none", `這場會議沒有標到時間的${kind.label}`));
  // 太靠近的點往上下錯開，不會疊在一起
  const sorted = [...pts].sort((a, b) => a.t.ms - b.t.ms);
  let lastPct = -100;
  let row = 0;
  sorted.forEach(({ it, t }, i) => {
    const pct = (t.ms / times.duration) * 100;
    row = pct - lastPct < 3 ? (row + 1) % 3 : 0;
    lastPct = pct;
    const b = el("button", "mark");
    b.type = "button";
    b.style.left = `${Math.min(100, Math.max(0, pct))}%`;
    b.dataset.row = String(row);
    const text = `${kind.label} ${i + 1}：${kind.text(it) || ""}　${fmtMs(t.ms)}`;
    b.title = text;
    b.setAttribute("aria-label", text);
    b.addEventListener("click", () => jumpTo(t.sid));
    track.append(b);
  });
  lane.append(label, track);
  return lane;
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
  const jsonStr = JSON.stringify(out, null, 2);
  const base64 = btoa(unescape(encodeURIComponent(jsonStr)));
  const filename = `重點_${safeName(sm.meeting_name)}_${stamp(data.updated_at)}.json`;

  if (window.CapacitorBridge?.writeFile) {
    try {
      await CapacitorBridge.writeFile(filename, base64, 'Documents');
      if (window.CapacitorBridge?.hapticNotification) {
        CapacitorBridge.hapticNotification('success').catch(() => {});
      }
      return;
    } catch (err) {
      console.warn('原生檔案寫入失敗，改用瀏覽器下載:', err);
    }
  }

  const blob = new Blob([jsonStr], { type: "application/json" });
  downloadBlob(blob, filename);
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

$("saveImageBtn").addEventListener("click", async () => {
  CapacitorBridge.hapticImpact('light').catch(() => {});
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
