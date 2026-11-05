import { meeting, suggestions } from "../state.js";
import { api } from "../composables/useApi.js";
import { $, el, fmtMs, showError } from "./dom.js";
import { actions, views } from "../views.js";
import { addResultText, addTerms, renderTermCandidates, rpMessage } from "../composables/useGlossary.js";

const review = { index: -1 };
const STATUS_LABEL = { pending: "待處理", accepted: "已套用", edited: "已自己改", ignored: "保留原文", outdated: "段落已手動修改" };
const sel = { info: null };
let bound = false;

function nextPending(from) {
  const list = suggestions();
  for (let k = 1; k <= list.length; k++) {
    const i = (from + k + list.length) % list.length;
    if (list[i].status === "pending") return i;
  }
  return -1;
}

export function renderTranscript() {
  hideSelBar();
  const list = $("transcriptList");
  if (!list || !meeting.transcript) return;
  const keep = list.scrollTop;
  const editable = meeting.status === "reviewing";
  const bySeg = {};
  for (const t of suggestions()) (bySeg[t.segment_id] = bySeg[t.segment_id] || []).push(t);
  list.replaceChildren();
  for (const seg of meeting.transcript.segments) {
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
  $("segmentCount").textContent = `（${meeting.transcript.segment_count} 段）`;
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
      const out = await api(`/api/v1/meetings/${meeting.meetingId}/transcript/segments/${seg.segment_id}`,
        { method: "PUT", json: { text: ta.value } });
      applyEditResult(out);
    } catch (err) { showError($("rpError"), err.message); save.disabled = false; }
  });
}

function updateReviewUI() {
  const reviewing = meeting.status === "reviewing";
  const p = meeting.proofread;
  const panel = $("reviewPanel");
  const reproofBtn = $("reproofBtn");
  if (panel) panel.hidden = !reviewing || !p;
  if (reproofBtn) reproofBtn.hidden = !((reviewing && p && p.problems.length) || meeting.failedStage === "proofreading");
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
  renderTermCandidates();
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
    box.append(el("p", "rp-done", meeting.proofread.counts.pending
      ? "按 ‹ › 或點逐字稿上的波浪線，一處一處處理。"
      : "全部處理完了。確認逐字稿沒問題，就按右上角「確認逐字稿」。"));
    return;
  }
  const seg = meeting.transcript.segments.find((x) => x.segment_id === t.segment_id);
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
  const m = document.querySelector(`#transcriptList mark[data-id="${CSS.escape(String(t.id))}"]`);
  const target = m || document.getElementById(`seg-${t.segment_id}`);
  if (m) m.classList.add("current");
  if (scroll && target) {
    const list = $("transcriptList");
    const offset = target.getBoundingClientRect().top - list.getBoundingClientRect().top;
    list.scrollTo({ top: list.scrollTop + offset - list.clientHeight / 2, behavior: "smooth" });
  }
}

async function decide(action, ids, replacement) {
  showError($("rpError"), "");
  const body = { action };
  if (ids) body.ids = ids;
  if (replacement != null) body.replacement = replacement;
  try {
    const out = await api(`/api/v1/meetings/${meeting.meetingId}/proofread/decisions`, { method: "POST", json: body });
    const from = review.index;
    applyEditResult(out, false);
    gotoTypo(action === "undo" ? from : nextPending(from));
  } catch (err) { showError($("rpError"), err.message); }
}

function applyEditResult(out, keepPosition = true) {
  meeting.transcript = out.transcript;
  meeting.proofread = out.proofread;
  renderTranscript();
  updateReviewUI();
  if (keepPosition) markCurrent();
}

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
  const seg = meeting.transcript.segments.find((x) => x.segment_id === sid);
  if (!seg || seg.text.substr(offset, text.length) !== text) return null;
  return { sid, offset, text, rect: range.getBoundingClientRect() };
}

function countIn(find) {
  let n = 0;
  for (const s of meeting.transcript.segments) {
    let i = 0;
    while ((i = s.text.indexOf(find, i)) >= 0) { n++; i += find.length; }
  }
  return n;
}

function showSelBar() {
  if (meeting.status !== "reviewing") return;
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

function hideSelBar() {
  const bar = $("selBar");
  if (bar) bar.hidden = true;
  sel.info = null;
}

async function doReplace(all) {
  const info = sel.info;
  if (!info) return;
  const replace = $("selInput").value.trim();
  const addTerm = $("selAddTerm").checked;
  const body = { find: info.text, replace };
  if (!all) Object.assign(body, { segment_id: info.sid, offset: info.offset });
  try {
    const out = await api(`/api/v1/meetings/${meeting.meetingId}/transcript/replace`, { method: "POST", json: body });
    hideSelBar();
    applyEditResult(out);
    let msg = `已把「${info.text}」改成「${replace}」，共 ${out.replaced} 處`;
    if (addTerm && replace) msg += `。${addResultText(await addTerms([replace]))}`;
    rpMessage(msg);
  } catch (err) { showError($("rpError"), err.message); }
}

function downloadJson() {
  if (!meeting.transcript) return;
  const out = { ...meeting.transcript, proofread: meeting.proofread };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `transcript-${meeting.meetingId}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function mountTranscript() {
  if (bound) return;
  bound = true;
  $("downloadJsonBtn").addEventListener("click", downloadJson);
  $("typoPrev").addEventListener("click", () => gotoTypo(review.index <= 0 ? suggestions().length - 1 : review.index - 1));
  $("typoNext").addEventListener("click", () => gotoTypo(review.index + 1));
  $("acceptAllBtn").addEventListener("click", async () => {
    const n = meeting.proofread ? meeting.proofread.counts.pending : 0;
    if (!n || !window.confirm(`把還沒處理的 ${n} 處全部改成 AI 建議的字？（之後還可以一處一處復原）`)) return;
    await decide("accept", null);
  });
  $("confirmBtn").addEventListener("click", () => actions.confirm());
  $("reproofBtn").addEventListener("click", () => actions.reproof());
  $("summarizeBtn").addEventListener("click", () => actions.summarize());
  $("summaryLang").addEventListener("change", () => { meeting.summaryLangTouched = true; });
  $("transcriptList").addEventListener("mouseup", () => setTimeout(showSelBar, 0));
  $("transcriptList").addEventListener("touchend", () => setTimeout(showSelBar, 300));
  $("transcriptList").addEventListener("scroll", hideSelBar);
  document.addEventListener("mousedown", (e) => {
    const bar = $("selBar");
    if (bar && !bar.hidden && !bar.contains(e.target)) hideSelBar();
  });
  $("selClose").addEventListener("click", hideSelBar);
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
}

views.renderTranscript = renderTranscript;
views.updateReviewUI = updateReviewUI;
views.gotoTypo = gotoTypo;
views.resetReview = () => { review.index = -1; };
views.nextPending = nextPending;
