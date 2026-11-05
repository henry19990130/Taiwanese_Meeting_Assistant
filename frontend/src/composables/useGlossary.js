import { glossary, meeting, suggestions } from "../state.js";
import { api } from "./useApi.js";
import { $, el, showError } from "../lib/dom.js";
import { views } from "../views.js";

const termChecks = new Set();
let bound = false;

function setGlossary(data) {
  glossary.terms = data.terms || [];
  glossary.count = data.count || 0;
  glossary.limit = data.limit || glossary.limit;
  if (data.max_length) glossary.max_length = data.max_length;
}

export async function loadGlossary() {
  try {
    setGlossary(await api("/api/v1/glossary"));
  } catch (_) { return; }
  updateGlossaryUI();
}

export async function addTerms(list) {
  const terms = list.map((t) => t.trim()).filter(Boolean);
  if (!terms.length) return null;
  const out = await api("/api/v1/glossary", { method: "POST", json: { terms } });
  setGlossary(out);
  updateGlossaryUI();
  return out.result;
}

export function addResultText(r) {
  if (!r) return "";
  const parts = [];
  if (r.added.length) parts.push(`已加入 ${r.added.length} 個：${r.added.join("、")}`);
  if (r.duplicated.length) parts.push(`${r.duplicated.length} 個本來就有`);
  if (r.over_limit.length) parts.push(`詞彙庫已滿 ${glossary.limit} 個，${r.over_limit.join("、")} 沒有加入（請先刪掉一些）`);
  if (r.invalid.length) parts.push(`${r.invalid.length} 個太長沒有加入（每個詞最多 ${glossary.max_length || 30} 字）`);
  return parts.join("；") || "沒有新增任何詞";
}

function updateGlossaryUI() {
  const btn = $("glossaryBtn");
  if (btn) btn.textContent = `專有名詞詞彙庫（${glossary.count} / ${glossary.limit}）`;
  const count = $("gdCount");
  if (count) count.textContent = `${glossary.count} / ${glossary.limit}`;
  renderGlossaryList();
  renderTermCandidates();
}

export function openGlossary() {
  showError($("gdMsg"), "");
  const filter = $("gdFilter");
  if (filter) filter.value = "";
  renderGlossaryList();
  $("glossaryDialog").showModal();
  loadGlossary();
  $("gdInput").focus();
}

function renderGlossaryList() {
  const filter = $("gdFilter");
  const list = $("gdList");
  if (!filter || !list) return;
  const q = filter.value.trim();
  list.replaceChildren();
  const shown = glossary.terms.filter((t) => !q || t.term.includes(q));
  if (!shown.length) {
    list.append(el("li", "gd-empty", glossary.count ? "沒有符合的詞" : "還沒有任何詞。可以在上面新增，或在確認逐字稿時把改過的詞加進來。"));
    return;
  }
  for (const t of shown) {
    const item = el("li", "gd-chip");
    const del = el("button", null, "×");
    del.type = "button";
    del.title = `刪除「${t.term}」`;
    del.addEventListener("click", async () => {
      try {
        setGlossary(await api(`/api/v1/glossary/${t.id}`, { method: "DELETE" }));
        updateGlossaryUI();
      } catch (err) { showError($("gdMsg"), err.message); }
    });
    item.append(el("span", null, t.term), del);
    list.append(item);
  }
}

function termCandidates() {
  const have = new Set(glossary.terms.map((t) => t.term));
  const out = [];
  const add = (w) => {
    w = (w || "").trim();
    if (w && w.length <= 30 && !have.has(w) && !out.includes(w)) out.push(w);
  };
  for (const m of (meeting.proofread && meeting.proofread.manual) || []) add(m.replace);
  for (const t of suggestions()) if (t.status === "edited") add(t.applied);
  return out;
}

export function renderTermCandidates() {
  const box = $("rpTerms");
  if (!box) return;
  const cands = meeting.status === "reviewing" ? termCandidates() : [];
  box.hidden = !cands.length;
  const list = $("rpTermsList");
  list.replaceChildren();
  for (const w of cands) {
    const lab = el("label", "rp-term");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = termChecks.has(w);
    cb.addEventListener("change", () => { cb.checked ? termChecks.add(w) : termChecks.delete(w); updateTermsBtn(); });
    lab.append(cb, el("span", null, w));
    list.append(lab);
  }
  updateTermsBtn();
}

function updateTermsBtn() {
  const btn = $("rpTermsAdd");
  if (!btn) return;
  const n = termCandidates().filter((w) => termChecks.has(w)).length;
  const left = glossary.limit - glossary.count;
  btn.disabled = !n;
  btn.textContent = n ? `加入勾選的詞（${n}）　詞彙庫還可以放 ${left} 個` : `加入勾選的詞　詞彙庫還可以放 ${left} 個`;
}

export function rpMessage(text, warn) {
  const m = $("rpMsg");
  if (!m) return;
  m.textContent = text;
  m.className = warn ? "rp-msg warn" : "rp-msg";
  m.hidden = !text;
}

export function mountGlossary() {
  if (bound) return;
  bound = true;
  $("rpGlossaryBtn").addEventListener("click", openGlossary);
  $("gdClose").addEventListener("click", () => $("glossaryDialog").close());
  $("gdFilter").addEventListener("input", renderGlossaryList);
  $("gdForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const words = $("gdInput").value.split(/[\n,，、；;]+/);
    try {
      const r = await addTerms(words);
      if (!r) return;
      $("gdInput").value = "";
      const msg = $("gdMsg");
      msg.textContent = addResultText(r);
      msg.hidden = false;
      msg.className = r.over_limit.length || r.invalid.length ? "gd-msg warn" : "gd-msg";
    } catch (err) { showError($("gdMsg"), err.message); }
  });
  $("gdInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("gdForm").requestSubmit(); }
  });
  $("rpTermsAdd").addEventListener("click", async () => {
    const words = termCandidates().filter((w) => termChecks.has(w));
    try {
      const r = await addTerms(words);
      words.forEach((w) => termChecks.delete(w));
      rpMessage(addResultText(r), r && r.over_limit.length);
      renderTermCandidates();
    } catch (err) { showError($("rpError"), err.message); }
  });
}

views.renderTermCandidates = renderTermCandidates;
