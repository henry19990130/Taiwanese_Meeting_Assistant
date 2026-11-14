const PRIORITIES = new Set(["P0", "P1", "P2", "P3"]);
const TYPES = new Set(["decision", "action", "discussion", "report"]);

const warning = (code, message, source_id = null) => ({ code, message, source_id });

/** Validate the renderer-facing image model without mutating it. */
export function validateImageData(data) {
  const warnings = [];
  const summary = data?.summary || {};
  const content = summary.meeting_content || {};
  const selection = summary.image_selection || {};
  const cards = Array.isArray(selection.cards) ? selection.cards : [];
  const allIds = new Set();

  if (!summary.meeting_name) warnings.push(warning("MISSING_MEETING_NAME", "缺少會議名稱"));
  if (!summary.meeting_datetime?.date) warnings.push(warning("MISSING_MEETING_DATE", "缺少會議日期"));
  if (!Array.isArray(cards)) warnings.push(warning("INVALID_CARDS", "圖片卡片不是陣列"));
  if (cards.length > (selection.max_cards || 5)) {
    warnings.push(warning("TOO_MANY_CARDS", "圖片卡片數量超過上限"));
  }

  for (const field of ["reports", "discussions", "decisions", "action_items"]) {
    for (const item of Array.isArray(content[field]) ? content[field] : []) {
      if (item?.id) allIds.add(item.id);
    }
  }

  for (const card of cards) {
    const id = card?.source_id || null;
    if (!id) warnings.push(warning("MISSING_SOURCE_ID", "卡片缺少 source_id"));
    if (id && !allIds.has(id)) warnings.push(warning("UNKNOWN_SOURCE_ID", "source_id 找不到對應摘要項目", id));
    if (!TYPES.has(card?.source_type)) warnings.push(warning("INVALID_SOURCE_TYPE", "卡片類型無效", id));
    if (!PRIORITIES.has(card?.priority)) warnings.push(warning("INVALID_PRIORITY", "卡片優先級無效", id));
    if (!Number.isFinite(card?.total_score) || card.total_score < 0 || card.total_score > 100) {
      warnings.push(warning("INVALID_SCORE", "卡片分數必須介於 0 到 100", id));
    }
    if (!card?.title || !card?.content) warnings.push(warning("MISSING_CARD_CONTENT", "卡片缺少標題或內容", id));
    if (!Array.isArray(card?.evidence_refs)) warnings.push(warning("INVALID_EVIDENCE_REFS", "evidence_refs 必須是陣列", id));
    for (const relatedId of Array.isArray(card?.related_ids) ? card.related_ids : []) {
      if (!allIds.has(relatedId)) warnings.push(warning("UNKNOWN_RELATED_ID", `related_id 找不到：${relatedId}`, id));
    }
  }

  return {
    render_ready: warnings.length === 0,
    warnings,
  };
}

