import { scoreCard } from "./imageScoring.js";

const TYPE_ORDER = { decision: 0, action: 1, discussion: 2, report: 3 };

function toCard(item, source_type, index) {
  const content = source_type === "action" ? item.task : item.summary || item.topic || "";
  return {
    source_id: item.id || `${source_type}-${index + 1}`,
    source_type,
    title: item.topic || item.task || source_type,
    content,
    summary: item.summary || null,
    task: item.task || null,
    due_date: item.due_date || null,
    due_text: item.due_text || null,
    assignees: Array.isArray(item.assignees) ? [...item.assignees] : [],
    related_ids: Array.isArray(item.related_ids) ? [...item.related_ids] : [],
    evidence_refs: Array.isArray(item.evidence) ? item.evidence.map((e) => e.segment_id).filter(Boolean) : [],
  };
}

export function selectImageCards(meetingContent, maxCards = 5) {
  const cards = [];
  for (const [field, type] of [["decisions", "decision"], ["action_items", "action"], ["discussions", "discussion"], ["reports", "report"]]) {
    (Array.isArray(meetingContent?.[field]) ? meetingContent[field] : []).forEach((item, index) => {
      cards.push(scoreCard(toCard(item, type, index)));
    });
  }
  cards.sort((a, b) => b.total_score - a.total_score || TYPE_ORDER[a.source_type] - TYPE_ORDER[b.source_type]);
  const selected = cards.slice(0, Math.max(0, maxCards));
  return {
    max_cards: maxCards,
    selected_count: selected.length,
    p0_count: selected.filter((card) => card.priority === "P0").length,
    p1_count: selected.filter((card) => card.priority === "P1").length,
    cards: selected,
  };
}

