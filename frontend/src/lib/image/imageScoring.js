const WEIGHTS = {
  decision_impact: 0.30,
  action_necessity: 0.25,
  time_sensitivity: 0.15,
  risk: 0.15,
  conclusion_relevance: 0.10,
  information_value: 0.05,
};

const clamp = (value) => Math.max(0, Math.min(100, Number(value) || 0));

function textOf(item) {
  return [item.title, item.topic, item.summary, item.task, item.content]
    .filter(Boolean).join(" ").toLowerCase();
}

function hasAny(text, words) {
  return words.some((word) => text.includes(word));
}

export function scoreCard(card) {
  const text = textOf(card);
  const type = card.source_type;
  const evidence = Array.isArray(card.evidence_refs) ? card.evidence_refs.length : 0;
  const dimensions = {
    decision_impact: type === "decision" ? 75 : hasAny(text, ["決定", "確認", "方向", "decision"]) ? 55 : 20,
    action_necessity: type === "action" ? 80 : hasAny(text, ["要", "必須", "期限", "完成", "action"]) ? 50 : 15,
    time_sensitivity: hasAny(text, ["今天", "明天", "下週", "期限", "截止", "urgent", "asap"]) ? 85 : card.due_date || card.due_text ? 65 : 20,
    risk: hasAny(text, ["風險", "問題", "阻礙", "錯誤", "影響", "risk", "blocker"]) ? 75 : 15,
    conclusion_relevance: type === "decision" ? 85 : type === "action" ? 70 : 35,
    information_value: Math.min(100, 25 + evidence * 20 + (text.length > 40 ? 20 : 0)),
  };
  const total_score = Math.round(Object.entries(WEIGHTS)
    .reduce((sum, [key, weight]) => sum + dimensions[key] * weight, 0));
  return { ...card, dimension_scores: dimensions, total_score, priority: priorityOf(total_score) };
}

export function priorityOf(score) {
  if (score >= 75) return "P0";
  if (score >= 55) return "P1";
  if (score >= 35) return "P2";
  return "P3";
}

