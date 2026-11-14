import { scoreCard } from "./imageScoring.js";

const TYPE_ORDER = { decision: 0, action: 1, discussion: 2, report: 3 };
const FIELDS = [["decisions", "decision"], ["action_items", "action"], ["discussions", "discussion"], ["reports", "report"]];

function toCard(item, source_type, index) {
  const action = source_type === "action";
  const body = action ? item.task || item.summary || "" : item.summary || item.content || item.task || item.topic || "";
  const title = item.topic || item.title || (action ? item.task : "") || source_type;
  const ownerAndDue = [Array.isArray(item.assignees) ? item.assignees.filter(Boolean).join("、") : "", item.due_date || item.due_text || ""]
    .filter(Boolean).join("；");
  const content = [body, ownerAndDue].filter(Boolean).join(ownerAndDue && body ? "\n" : "");
  return {
    source_id: item.id || `${source_type}-${index + 1}`,
    source_type,
    title,
    content,
    summary: item.summary || null,
    task: item.task || null,
    assignees: Array.isArray(item.assignees) ? [...item.assignees] : [],
    due_date: item.due_date || null,
    due_text: item.due_text || null,
    related_ids: Array.isArray(item.related_ids) ? [...item.related_ids] : [],
    evidence_refs: Array.isArray(item.evidence) ? item.evidence.map((entry) => entry?.segment_id).filter(Boolean) : [],
  };
}

const stableOrder = (a, b) => b.total_score - a.total_score
  || TYPE_ORDER[a.source_type] - TYPE_ORDER[b.source_type]
  || String(a.source_id).localeCompare(String(b.source_id), "en");

/** Rule-based heuristic selection; topic coverage is reported only, never used to reorder cards. */
export function selectImageCards(meetingContent, maxCards = 5, { headline = "" } = {}) {
  const capacity = Math.max(0, Math.min(5, Number.isInteger(maxCards) ? maxCards : 5));
  const candidates = [];
  for (const [field, type] of FIELDS) {
    (Array.isArray(meetingContent?.[field]) ? meetingContent[field] : []).forEach((item, index) => {
      candidates.push(scoreCard(toCard(item || {}, type, index), { headline }));
    });
  }
  candidates.sort(stableOrder);
  const p0 = candidates.filter((card) => card.priority === "P0");
  const p1 = candidates.filter((card) => card.priority === "P1");
  const errors = p0.length > capacity
    ? [{ code: "P0_CAPACITY_EXCEEDED", message: `${p0.length} 項 P0 內容超過 ${capacity} 張卡片容量，已停止選卡。` }]
    : [];
  const cards = errors.length ? [] : [...p0, ...p1.slice(0, capacity - p0.length)];
  const topics = Array.isArray(meetingContent?.discussions)
    ? [...new Set(meetingContent.discussions.map((item) => item?.topic).filter(Boolean))]
    : [];
  return {
    max_cards: capacity,
    selected_count: cards.length,
    p0_count: p0.length,
    p1_count: cards.filter((card) => card.priority === "P1").length,
    errors,
    topic_coverage: { available_topics: topics.length, selected_topics: cards.filter((card) => card.source_type === "discussion").length },
    candidates,
    cards,
  };
}
