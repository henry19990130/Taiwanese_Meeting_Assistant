// ---------------------------------------------------------------------------
// MeetSum 裝置端資料層（local-first）
//
// 「裝置為唯一真實來源」：不論本機模式或 Colab 模式，會議、逐字稿、重點、
// 名詞庫、個人設定一律先寫進裝置。後端只是算力，重啟或換 tunnel 都不會失憶。
//
// 以 IndexedDB 為主；若環境不支援（極少數）則退回 localStorage。
// ---------------------------------------------------------------------------

const DB_NAME = "meetsum";
const DB_VERSION = 1;
const STORES = ["kv", "meetings", "transcripts", "summaries", "glossary", "models"];

let _db = null;
let _fallback = false;

function openDB() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) { reject(new Error("no-indexeddb")); return; }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const name of STORES) {
        if (!db.objectStoreNames.contains(name)) {
          const keyPath = name === "kv" ? "k"
            : name === "transcripts" || name === "summaries" ? "meeting_id"
            : name === "models" ? "id"
            : "id";
          db.createObjectStore(name, { keyPath });
        }
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("idb-open-failed"));
  });
}

function tx(storeName, mode) {
  return _db.transaction(storeName, mode).objectStore(storeName);
}

function idbReq(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// ---- localStorage 後備 ------------------------------------------------------

const LS_PREFIX = "meetsum.ls.";

function lsGet(storeName, key) {
  try {
    const raw = localStorage.getItem(`${LS_PREFIX}${storeName}:${key}`);
    return raw == null ? undefined : JSON.parse(raw);
  } catch (_) { return undefined; }
}
function lsSet(storeName, key, value) {
  try { localStorage.setItem(`${LS_PREFIX}${storeName}:${key}`, JSON.stringify(value)); } catch (_) { /* ignore */ }
}
function lsDel(storeName, key) {
  try { localStorage.removeItem(`${LS_PREFIX}${storeName}:${key}`); } catch (_) { /* ignore */ }
}
function lsAll(storeName) {
  const out = [];
  try {
    const p = `${LS_PREFIX}${storeName}:`;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(p)) out.push(JSON.parse(localStorage.getItem(k)));
    }
  } catch (_) { /* ignore */ }
  return out;
}

async function init() {
  if (_db || _fallback) return;
  try {
    _db = await openDB();
  } catch (_) {
    _fallback = true;
    console.warn("[Store] IndexedDB 不可用，改用 localStorage 後備");
  }
}

// ---- 通用存讀 ---------------------------------------------------------------

async function put(storeName, keyPath, value) {
  await init();
  if (_fallback) { lsSet(storeName, value[keyPath], value); return value; }
  await idbReq(tx(storeName, "readwrite").put(value));
  return value;
}

async function get(storeName, key) {
  await init();
  if (_fallback) return lsGet(storeName, key);
  return idbReq(tx(storeName, "readonly").get(key));
}

async function del(storeName, key) {
  await init();
  if (_fallback) { lsDel(storeName, key); return; }
  await idbReq(tx(storeName, "readwrite").delete(key));
}

async function all(storeName) {
  await init();
  if (_fallback) return lsAll(storeName);
  return idbReq(tx(storeName, "readonly").getAll());
}

// ---- KV（設定、模式、個人資訊） --------------------------------------------

const kv = {
  async get(key, fallback = null) {
    const row = await get("kv", key);
    return row ? row.v : fallback;
  },
  async set(key, value) {
    return put("kv", "k", { k: key, v: value });
  },
  async remove(key) { return del("kv", key); },
  async keys() { return (await all("kv")).map((r) => r.k); },
};

// ---- 會議 / 逐字稿 / 重點 ---------------------------------------------------

const meetings = {
  async save(meeting) {
    const row = {
      id: String(meeting.id),
      name: meeting.name || meeting.meeting_name || "未命名會議",
      meeting_name: meeting.meeting_name || meeting.name || "未命名會議",
      date: meeting.date || new Date().toISOString().slice(0, 10),
      mode: meeting.mode || "cloud",           // 產生此會議的模式
      source: meeting.source || "audio",
      status: meeting.status || "completed",
      language: meeting.language || "zh",
      created_at: meeting.created_at || Date.now(),
      updated_at: Date.now(),
      ...meeting,
    };
    row.id = String(meeting.id);
    return put("meetings", "id", row);
  },
  async get(id) { return get("meetings", String(id)); },
  async remove(id) { return del("meetings", String(id)); },
  async list() {
    const rows = await all("meetings");
    return rows.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  },
};

const transcripts = {
  async save(meetingId, transcript) {
    return put("transcripts", "meeting_id", {
      meeting_id: String(meetingId),
      transcript,
      updated_at: Date.now(),
    });
  },
  async get(meetingId) {
    const row = await get("transcripts", String(meetingId));
    return row ? row.transcript : null;
  },
  async remove(meetingId) { return del("transcripts", String(meetingId)); },
};

const summaries = {
  async save(meetingId, summary) {
    return put("summaries", "meeting_id", {
      meeting_id: String(meetingId),
      summary,
      updated_at: Date.now(),
    });
  },
  async get(meetingId) {
    const row = await get("summaries", String(meetingId));
    return row ? row.summary : null;
  },
  async remove(meetingId) { return del("summaries", String(meetingId)); },
};

const glossary = {
  async save(term) {
    const id = String(term.id ?? term.term ?? Date.now());
    return put("glossary", "id", { ...term, id });
  },
  async list() { return all("glossary"); },
  async remove(id) { return del("glossary", String(id)); },
  async replaceAll(terms) {
    const cur = await all("glossary");
    for (const t of cur) await del("glossary", t.id);
    for (const t of terms || []) await glossary.save(t);
  },
};

// ---- 模型狀態（本機模式下載紀錄） ------------------------------------------

const models = {
  async save(record) { return put("models", "id", { updated_at: Date.now(), ...record }); },
  async get(id) { return get("models", String(id)); },
  async list() { return all("models"); },
  async remove(id) { return del("models", String(id)); },
};

// ---- 整包備份 / 還原（避免失憶） -------------------------------------------

async function exportAll() {
  const out = { version: 1, exported_at: Date.now() };
  for (const name of STORES) out[name] = await all(name);
  return out;
}

async function importAll(data) {
  if (!data || data.version !== 1) throw new Error("備份格式不支援");
  for (const name of STORES) {
    for (const row of data[name] || []) {
      const keyPath = name === "kv" ? "k"
        : name === "transcripts" || name === "summaries" ? "meeting_id"
        : "id";
      if (row[keyPath] === undefined) continue;
      await put(name, keyPath, row);
    }
  }
}

export const Store = {
  init,
  kv, meetings, transcripts, summaries, glossary, models,
  exportAll, importAll,
  get usingFallback() { return _fallback; },
};

// 其他 classic 風格的模組（app.js / glossary.js）透過 window 取用
window.Store = Store;

export default Store;
