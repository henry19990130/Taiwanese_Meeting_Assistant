import { WEIGHTS } from "./imageScoring.js";

const PRIORITIES = new Set(["P0", "P1", "P2", "P3"]);
const TYPES = new Set(["decision", "action", "discussion", "report"]);
const warning = (code, message, source_id = null) => ({ code, message, source_id });

/** Validate selection provenance and arithmetic; cannot verify semantic fidelity against transcripts. */
export function validateImageData(data) {
  const warnings = [];
  const summary = data?.summary || {};
  const content = summary.meeting_content || {};
  const selection = summary.image_selection || {};
  const cards = selection.cards;
  if (!summary.meeting_name) warnings.push(warning("MISSING_MEETING_NAME", "缺少會議名稱"));
  if (!summary.meeting_datetime?.date) warnings.push(warning("MISSING_MEETING_DATE", "缺少會議日期"));
  if (!Array.isArray(cards)) warnings.push(warning("INVALID_CARDS", "圖片卡片不是陣列"));
  if (selection.errors?.length) warnings.push(...selection.errors.map((error) => warning(error.code, error.message)));
  const safeCards = Array.isArray(cards) ? cards : [];
  if (safeCards.length > 5) warnings.push(warning("TOO_MANY_CARDS", "圖片卡片數量超過五項"));
  if (Array.isArray(selection.candidates)) {
    const eligible = selection.candidates.filter((card) => card.priority === "P0" || card.priority === "P1");
    const expected = eligible.slice(0, 5);
    if (expected.length !== safeCards.length || expected.some((card, index) => card.source_id !== safeCards[index]?.source_id)) {
      warnings.push(warning("INVALID_SELECTION_ORDER", "已選卡片未依 P0 保留及 P1 評分順序產生"));
    }
  }

  const originals = new Map();
  for (const [field, type] of [["decisions", "decision"], ["action_items", "action"], ["discussions", "discussion"], ["reports", "report"]]) {
    for (const item of Array.isArray(content[field]) ? content[field] : []) {
      if (item?.id) originals.set(item.id, { item, type });
    }
  }
  const allP0 = Array.isArray(selection.candidates) ? selection.candidates.filter((card) => card.priority === "P0") : [];
  const cardIds = new Set(safeCards.map((card) => card?.source_id));
  for (const card of safeCards) {
    const id = card?.source_id;
    const original = originals.get(id);
    if (!id) warnings.push(warning("MISSING_SOURCE_ID", "卡片缺少 source_id"));
    if (!original) warnings.push(warning("UNKNOWN_SOURCE_ID", "source_id 找不到對應摘要項目", id));
    if (!TYPES.has(card?.source_type) || original && card.source_type !== original.type) warnings.push(warning("INVALID_SOURCE_TYPE", "卡片類型無效或與來源不符", id));
    if (!PRIORITIES.has(card?.priority)) warnings.push(warning("INVALID_PRIORITY", "卡片優先級無效", id));
    if (!card?.title || !card?.content) warnings.push(warning("MISSING_CARD_CONTENT", "卡片缺少標題或內容", id));
    if (!Array.isArray(card?.assignees) || !Array.isArray(card?.related_ids) || !Array.isArray(card?.evidence_refs)) warnings.push(warning("INVALID_CARD_FIELDS", "卡片必要欄位格式無效", id));
    const dimensions = card?.dimension_scores || {};
    const dimensionNames = Object.keys(WEIGHTS);
    if (dimensionNames.some((key) => !Number.isFinite(dimensions[key]) || dimensions[key] < 0 || dimensions[key] > 100)) {
      warnings.push(warning("INVALID_DIMENSION_SCORE", "六維度分數必須介於 0 到 100", id));
    } else {
      const expected = Math.round(Object.entries(WEIGHTS).reduce((sum, [key, weight]) => sum + dimensions[key] * weight, 0));
      if (card.total_score !== expected) warnings.push(warning("INCONSISTENT_TOTAL_SCORE", `總分應為 ${expected}`, id));
    }
    if (original) {
      const sourceText = [original.item.task, original.item.summary, original.item.topic, original.item.content].filter(Boolean).join("\n");
      if (sourceText && !card.content.includes(sourceText) && !String(card.summary || "").includes(sourceText) && !String(card.task || "").includes(sourceText)) {
        warnings.push(warning("SOURCE_TEXT_LOST", "卡片未保留完整原始內容", id));
      }
      if (original.type === "action") {
        const owners = Array.isArray(original.item.assignees) ? original.item.assignees.filter(Boolean) : [];
        if (owners.some((owner) => !card.assignees.includes(owner))) warnings.push(warning("ASSIGNEE_LOST", "卡片未保留負責人", id));
        if ((original.item.due_date || original.item.due_text) && card.due_date !== original.item.due_date && card.due_text !== original.item.due_text) warnings.push(warning("DEADLINE_LOST", "卡片未保留期限", id));
      }
    }
    for (const relatedId of Array.isArray(card?.related_ids) ? card.related_ids : []) {
      if (!originals.has(relatedId)) warnings.push(warning("UNKNOWN_RELATED_ID", `related_id 找不到：${relatedId}`, id));
    }
  }
  if (allP0.length > 5) warnings.push(warning("P0_CAPACITY_EXCEEDED", `${allP0.length} 項 P0 內容超過五張容量`));
  else for (const card of allP0) if (!cardIds.has(card.source_id)) warnings.push(warning("P0_NOT_SELECTED", "符合 P0 規則的項目未保留", card.source_id));
  const sourceNext = content.next_meeting?.status || "not_mentioned";
  if (summary.next_meeting_status !== sourceNext) warnings.push(warning("NEXT_MEETING_STATUS_LOST", "下次會議狀態未保留"));
  return { render_ready: warnings.length === 0, warnings };
}
