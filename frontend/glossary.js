state.glossary = { terms: [], count: 0, limit: 200 };
const termChecks = new Set();

async function loadGlossary() {
  try {
    state.glossary = await api("/api/v1/glossary");
  } catch (_) { return; }
  updateGlossaryUI();
}

async function addTerms(list) {
  const terms = list.map((t) => t.trim()).filter(Boolean);
  if (!terms.length) return null;
  const out = await api("/api/v1/glossary", { method: "POST", json: { terms } });
  state.glossary = out;
  updateGlossaryUI();
  return out.result;
}

function addResultText(r) {
  if (!r) return "";
  const parts = [];
  if (r.added.length) parts.push(`已加入 ${r.added.length} 個：${r.added.join("、")}`);
  if (r.duplicated.length) parts.push(`${r.duplicated.length} 個本來就有`);
  if (r.over_limit.length) parts.push(`詞彙庫已滿 ${state.glossary.limit} 個，${r.over_limit.join("、")} 沒有加入（請先刪掉一些）`);
  if (r.invalid.length) parts.push(`${r.invalid.length} 個太長沒有加入（每個詞最多 ${state.glossary.max_length || 30} 字）`);
  return parts.join("；") || "沒有新增任何詞";
}

function updateGlossaryUI() {
  const g = state.glossary;
  $("glossaryBtn").textContent = `專有名詞詞彙庫（${g.count} / ${g.limit}）`;
  $("gdCount").textContent = `${g.count} / ${g.limit}`;
  renderGlossaryList();
  renderTermCandidates();
}

function openGlossary() {
  showError($("gdMsg"), "");
  $("gdFilter").value = "";
  renderGlossaryList();
  $("glossaryDialog").showModal();
  loadGlossary();
  $("gdInput").focus();
}
$("glossaryBtn").addEventListener("click", openGlossary);
$("rpGlossaryBtn").addEventListener("click", openGlossary);
$("gdClose").addEventListener("click", () => $("glossaryDialog").close());

function renderGlossaryList() {
  const q = $("gdFilter").value.trim();
  const list = $("gdList");
  list.replaceChildren();
  const shown = state.glossary.terms.filter((t) => !q || t.term.includes(q));
  if (!shown.length) {
    list.append(el("li", "gd-empty", state.glossary.count ? "沒有符合的詞" : "還沒有任何詞。可以在上面新增，或在確認逐字稿時把改過的詞加進來。"));
    return;
  }
  for (const t of shown) {
    const item = el("li", "gd-chip");
    const del = el("button", null, "×");
    del.type = "button";
    del.title = `刪除「${t.term}」`;
    del.addEventListener("click", async () => {
      try {
        state.glossary = await api(`/api/v1/glossary/${t.id}`, { method: "DELETE" });
        updateGlossaryUI();
      } catch (err) { showError($("gdMsg"), err.message); }
    });
    item.append(el("span", null, t.term), del);
    list.append(item);
  }
}
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

function termCandidates() {
  const have = new Set(state.glossary.terms.map((t) => t.term));
  const out = [];
  const add = (w) => {
    w = (w || "").trim();
    if (w && w.length <= 30 && !have.has(w) && !out.includes(w)) out.push(w);
  };
  for (const m of (state.proofread && state.proofread.manual) || []) add(m.replace);
  for (const t of suggestions()) if (t.status === "edited") add(t.applied);
  return out;
}

function renderTermCandidates() {
  const box = $("rpTerms");
  if (!box) return;
  const cands = state.status === "reviewing" ? termCandidates() : [];
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
  const n = termCandidates().filter((w) => termChecks.has(w)).length;
  const left = state.glossary.limit - state.glossary.count;
  $("rpTermsAdd").disabled = !n;
  $("rpTermsAdd").textContent = n ? `加入勾選的詞（${n}）　詞彙庫還可以放 ${left} 個` : `加入勾選的詞　詞彙庫還可以放 ${left} 個`;
}
$("rpTermsAdd").addEventListener("click", async () => {
  const words = termCandidates().filter((w) => termChecks.has(w));
  try {
    const r = await addTerms(words);
    words.forEach((w) => termChecks.delete(w));
    rpMessage(addResultText(r), r && r.over_limit.length);
    renderTermCandidates();
  } catch (err) { showError($("rpError"), err.message); }
});

function rpMessage(text, warn) {
  const m = $("rpMsg");
  m.textContent = text;
  m.className = warn ? "rp-msg warn" : "rp-msg";
  m.hidden = !text;
}

const sel = { info: null };

function selectionInfo() {
  const s = window.getSelection();
  if (!s || s.isCollapsed || !s.rangeCount) return null;
  const range = s.getRangeAt(0);
  const spanOf = (node) => (node.nodeType === 1 ? node : node.parentElement)?.closest(".seg-text");
  const span = spanOf(range.startContainer);
  if (!span || span !== spanOf(range.endContainer)) return null;
  const text = range.toString();
  if (!text.trim() || text.length > 200) return null;
  const pre = document.createRange();
  pre.setStart(span, 0);
  pre.setEnd(range.startContainer, range.startOffset);
  const offset = pre.toString().length;
  const sid = span.closest("li").id.replace(/^seg-/, "");
  const seg = state.transcript.segments.find((x) => x.segment_id === sid);
  if (!seg || seg.text.substr(offset, text.length) !== text) return null;
  return { sid, offset, text, rect: range.getBoundingClientRect() };
}

function countIn(find) {
  let n = 0;
  for (const s of state.transcript.segments) {
    let i = 0;
    while ((i = s.text.indexOf(find, i)) >= 0) { n++; i += find.length; }
  }
  return n;
}

function showSelBar() {
  if (state.status !== "reviewing") return;
  const info = selectionInfo();
  if (!info) return;
  sel.info = info;
  const bar = $("selBar");
  $("selFrom").textContent = `「${info.text}」`;
  $("selInput").value = info.text;
  const n = countIn(info.text);
  $("selAll").hidden = n < 2;
  $("selAll").textContent = `全部 ${n} 處都改`;
  $("selAddTerm").checked = false;
  showError($("rpError"), "");
  bar.hidden = false;
  const w = bar.offsetWidth;
  const left = Math.min(Math.max(8, info.rect.left + window.scrollX), window.scrollX + document.documentElement.clientWidth - w - 8);
  bar.style.left = `${left}px`;
  bar.style.top = `${info.rect.bottom + window.scrollY + 8}px`;
  $("selInput").focus();
  $("selInput").select();
}
function hideSelBar() { $("selBar").hidden = true; sel.info = null; }

$("transcriptList").addEventListener("mouseup", () => setTimeout(showSelBar, 0));
$("transcriptList").addEventListener("touchend", () => setTimeout(showSelBar, 300));
$("transcriptList").addEventListener("scroll", hideSelBar);
document.addEventListener("mousedown", (e) => {
  if (!$("selBar").hidden && !$("selBar").contains(e.target)) hideSelBar();
});
$("selClose").addEventListener("click", hideSelBar);

async function doReplace(all) {
  const info = sel.info;
  if (!info) return;
  const replace = $("selInput").value.trim();
  const addTerm = $("selAddTerm").checked;
  const body = { find: info.text, replace };
  if (!all) Object.assign(body, { segment_id: info.sid, offset: info.offset });
  try {
    const out = await api(`/api/v1/meetings/${state.meetingId}/transcript/replace`, { method: "POST", json: body });
    hideSelBar();
    applyEditResult(out);
    let msg = `已把「${info.text}」改成「${replace}」，共 ${out.replaced} 處`;
    if (addTerm && replace) msg += `。${addResultText(await addTerms([replace]))}`;
    rpMessage(msg);
  } catch (err) { showError($("rpError"), err.message); }
}
$("selOne").addEventListener("click", () => doReplace(false));
$("selAll").addEventListener("click", () => doReplace(true));
$("selInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); doReplace(false); }
  if (e.key === "Escape") hideSelBar();
});
$("selTermOnly").addEventListener("click", async () => {
  const info = sel.info;
  if (!info) return;
  try {
    const r = await addTerms([info.text]);
    hideSelBar();
    rpMessage(addResultText(r), r && r.over_limit.length);
  } catch (err) { showError($("rpError"), err.message); }
});
