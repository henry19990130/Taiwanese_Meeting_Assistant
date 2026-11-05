import { fmtDate, fmtMD } from "./dom.js";
import { buildFlow, segmentTimes } from "./flow.js";

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

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

export function drawShareImage(data) {
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
