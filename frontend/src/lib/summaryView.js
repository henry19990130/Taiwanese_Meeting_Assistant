import { meeting } from "../state.js";
import { api } from "../composables/useApi.js";
import { $, downloadBlob, el, fmtDate, fmtMD, fmtMs, safeName, stamp } from "./dom.js";
import { firstTime, segmentTimes } from "./flow.js";
import { evidence, jumpTo } from "./jump.js";
import { drawShareImage } from "./shareImage.js";
import { exportDeck } from "./deckView.js";
import { views } from "../views.js";

let summaryBound = false;

const NEXT_LABEL = { confirmed: "已確認", tentative: "暫定", not_mentioned: "未提及" };
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

function kpi(label, value, kind, sub) {
  const box = el("div", `kpi kpi-${kind}`);
  box.append(el("div", "kpi-label", label), el("div", value.length > 4 ? "kpi-value small" : "kpi-value", value));
  if (sub) box.append(el("div", "kpi-sub", sub));
  return box;
}
function blockTitle(text, kind) {
  return el("h3", `block-title t-${kind}`, text);
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
function laneOf(kind, pts, times) {
  const lane = el("div", `tl-lane tl-${kind.key}`);
  const label = el("span", "tl-lane-label", kind.label);
  const track = el("div", "track");
  track.append(el("div", "track-line"));
  if (!pts.length) track.append(el("span", "tl-none", `這場會議沒有標到時間的${kind.label}`));
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

export function renderSnapshot(data) {
  const sm = data.summary;
  const mc = sm.meeting_content;
  const times = segmentTimes();
  const segCount = meeting.transcript ? meeting.transcript.segment_count : null;
  $("snapTitle").textContent = sm.meeting_name || "會議重點";
  const metaParts = [fmtDate(sm.meeting_datetime)];
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
  const nodes = [
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
  ].filter(Boolean);
  $("snapBody").replaceChildren(...nodes);
  const when = data.updated_at ? new Date(data.updated_at).toLocaleString("zh-TW", { hour12: false }) : "";
  $("snapFoot").textContent = `由 ${data.model_name || "LLM"} 在本地端整理　·　產生時間 ${when}　·　點時間可回到逐字稿原文確認`;
}

views.renderSnapshot = renderSnapshot;

export function mountSummary() {
  if (summaryBound) return;
  summaryBound = true;
  $("saveImageBtn").addEventListener("click", () => {
    if (!meeting.summary) return;
    const canvas = drawShareImage(meeting.summary);
    canvas.toBlob((blob) => {
      if (blob) downloadBlob(blob, `會議快照_${safeName(meeting.summary.summary.meeting_name)}_${stamp(meeting.summary.updated_at)}.png`);
    }, "image/png");
  });
  $("deckBtn").addEventListener("click", () => exportDeck());
  $("downloadSummaryBtn").addEventListener("click", async () => {
    const data = meeting.summary;
    if (!data) return;
    let llm = null;
    try { llm = await api("/api/v1/health"); } catch (_) { /* 匯出時沒有健康資訊就略過模型參數 */ }
    const sm = data.summary;
    const out = {
      exported_at: new Date().toISOString(),
      meeting: { id: data.meeting_id, name: sm.meeting_name, datetime: sm.meeting_datetime },
      generated_at: data.updated_at,
      model_name: data.model_name,
      llm_settings_at_export: llm ? { temperature: llm.llm_temperature, seed: llm.llm_seed, num_ctx: llm.llm_num_ctx, think: llm.llm_think } : null,
      transcript_segment_count: meeting.transcript ? meeting.transcript.segment_count : null,
      headline: sm.headline,
      meeting_content: sm.meeting_content,
      review_notes: sm.review_notes,
      transcript_proofread: meeting.proofread ? meeting.proofread.counts : null,
    };
    downloadBlob(new Blob([JSON.stringify(out, null, 2)], { type: "application/json" }),
      `重點_${safeName(sm.meeting_name)}_${stamp(data.updated_at)}.json`);
  });
}
