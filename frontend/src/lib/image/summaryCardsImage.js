import { fmtDate, fmtMD } from "../dom.js";

const FONT = '"Noto Sans TC", "Noto Sans CJK TC", "PingFang TC", "Microsoft JhengHei", sans-serif';
const MAX_CANVAS_SIDE = 32767;
const MAX_CANVAS_AREA = 268_000_000;

function linesFor(ctx, value, width) {
  const lines = [];
  for (const paragraph of String(value ?? "").split("\n")) {
    if (!paragraph) { lines.push(""); continue; }
    let line = "";
    for (const character of paragraph) {
      if (line && ctx.measureText(line + character).width > width) {
        lines.push(line);
        line = character;
      } else line += character;
    }
    lines.push(line);
  }
  return lines;
}

function roundedRect(ctx, x, y, width, height, radius) {
  ctx.beginPath(); ctx.moveTo(x + radius, y); ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius); ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius); ctx.closePath();
}

export function drawSummaryCardsImage(data) {
  const W = 1024, SCALE = 2, PAD = 40, INNER = W - PAD * 2;
  const sm = data?.summary;
  const mc = sm?.meeting_content || {};
  const cards = sm?.image_selection?.cards;
  if (!Array.isArray(cards) || cards.length > 5) throw new Error("圖片卡片資料無效，無法繪製。");
  const canvas = document.createElement("canvas");
  const measure = canvas.getContext("2d");
  if (!measure) throw new Error("瀏覽器無法建立 Canvas。");
  measure.font = `400 22px ${FONT}`;
  const C = { bg: "#fbf8f2", dark: "#2b2420", green: "#5e7a5a", soft: "#f3e9da", ink: "#2b2420", muted: "#5f544a", line: "#e6daca", white: "#ffffff" };
  const sections = [];
  const addSection = (title, body, { font = 23, fill = C.white, label = "" } = {}) => {
    measure.font = `400 ${font}px ${FONT}`;
    const bodyLines = linesFor(measure, body, INNER - 44);
    const labelLines = label ? linesFor(measure, label, INNER - 44) : [];
    const lineHeight = font + 13;
    const height = 62 + (labelLines.length + bodyLines.length) * lineHeight + 24;
    sections.push({ title, bodyLines, labelLines, height, font, lineHeight, fill });
  };
  addSection("核心結論", sm?.headline || "未提供核心結論", { font: 25, fill: C.soft });
  const topics = [...new Set((Array.isArray(mc.discussions) ? mc.discussions : []).map((item) => item?.topic).filter(Boolean))];
  addSection("本次議題概覽", topics.length ? topics.join("、") : "未整理出明確議題", { font: 21 });
  const labels = { decision: "決議", action: "待辦", discussion: "討論", report: "報告" };
  cards.forEach((card, index) => {
    const details = [];
    if (card.source_type === "action") {
      details.push(`負責人：${card.assignees?.filter(Boolean).join("、") || "未指定"}`);
      details.push(`期限：${card.due_date ? fmtMD(card.due_date) : card.due_text || "未提及"}`);
    }
    if (card.related_ids?.length) details.push(`相關項目：${card.related_ids.join("、")}`);
    if (card.evidence_refs?.length) details.push(`來源依據：${card.evidence_refs.join("、")}`);
    const body = [card.content || "（來源內容為空）", ...details].join("\n");
    addSection(`${index + 1}. ${labels[card.source_type] || "會議內容"} · ${card.priority} · ${card.title}`, body,
      { font: 21, label: `來源 ID：${card.source_id}　評分：${card.total_score}` });
  });
  const next = mc.next_meeting || {};
  const status = { confirmed: "已確認", tentative: "暫定", not_mentioned: "尚未排定" }[next.status] || "尚未排定";
  const nextWhen = next.status === "not_mentioned" ? status : `${[next.date ? fmtMD(next.date) : next.date_text, next.time].filter(Boolean).join(" ") || "時間未定"}（${status}）`;
  addSection("下次會議", nextWhen, { font: 23, fill: C.soft });

  const titleLines = linesFor(measure, `${sm?.meeting_name || "會議"}｜會議摘要`, INNER);
  const dateLines = linesFor(measure, fmtDate(sm?.meeting_datetime), INNER);
  const titleHeight = titleLines.length * 56 + dateLines.length * 34 + 50;
  const totalHeight = titleHeight + sections.reduce((sum, section) => sum + section.height + 20, 0) + PAD;
  const outWidth = W * SCALE, outHeight = Math.ceil(totalHeight * SCALE);
  if (outHeight > MAX_CANVAS_SIDE || outWidth > MAX_CANVAS_SIDE || outWidth * outHeight > MAX_CANVAS_AREA) {
    throw new Error("圖片內容超出瀏覽器 Canvas 安全尺寸，請減少摘要內容後再試。");
  }
  canvas.width = outWidth; canvas.height = outHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("瀏覽器無法建立 Canvas 繪圖環境。");
  ctx.scale(SCALE, SCALE); ctx.textBaseline = "top"; ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, totalHeight);
  let y = PAD;
  const drawLines = (lines, x, startY, font, color, lineHeight, weight = 400) => {
    ctx.font = `${weight} ${font}px ${FONT}`; ctx.fillStyle = color;
    lines.forEach((line, index) => ctx.fillText(line, x, startY + index * lineHeight));
  };
  drawLines(titleLines, PAD, y, 39, C.dark, 48, 800); y += titleLines.length * 48 + 8;
  drawLines(dateLines, PAD, y, 20, C.muted, 30); y += dateLines.length * 30 + 36;
  for (const section of sections) {
    ctx.fillStyle = section.fill; roundedRect(ctx, PAD, y, INNER, section.height, 16); ctx.fill();
    drawLines([section.title], PAD + 22, y + 17, 25, C.green, 32, 800);
    let textY = y + 59;
    if (section.labelLines.length) {
      drawLines(section.labelLines, PAD + 22, textY, 16, C.muted, 23); textY += section.labelLines.length * 23 + 7;
    }
    drawLines(section.bodyLines, PAD + 22, textY, section.font, C.ink, section.lineHeight);
    y += section.height + 20;
  }
  return canvas;
}
