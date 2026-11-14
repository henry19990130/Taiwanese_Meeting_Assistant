const WEIGHTS = Object.freeze({
  decision_impact: 0.30,
  action_necessity: 0.25,
  time_sensitivity: 0.15,
  risk: 0.15,
  conclusion_relevance: 0.10,
  information_value: 0.05,
});

const clamp = (value) => Math.max(0, Math.min(100, value));
const textOf = (card) => [card.title, card.content, card.summary, card.task].filter(Boolean).join(" ");
const matches = (text, patterns) => patterns.some((pattern) => pattern.test(text));
const NEGATION = /(?:沒有|無|未|不|並非|毋須|暫不|不要|先不要|不可|不得|no\b|not\b|without\b)/iu;
const URGENCY = /(?:今天|明天|本週|下週|\d{4}[-/]?\d{1,2}[-/]?\d{1,2}|期限|截止|盡快|立即|urgent|asap)/iu;
const RISK = /(?:風險|阻礙|故障|資安|違規|重大影響|無法上線|risk|blocker)/iu;
const ACTION = /(?:需要|必須|負責|請|完成|處理|提交|修正|確認|安排|上線|action)/iu;
const MAJOR = /(?:正式決議|重大變更|全面停用|立即停止|禁止上線|不得上線|資安事件|法規違規|資料外洩)/iu;
const CONDITIONAL_PROHIBITION = /(?:先不要|暫不|不得|禁止|不可|停止|不要).{0,16}(?:上線|發布|部署|啟用|刪除|公開)/iu;

/** Deterministic rule-based heuristic; not validated semantic importance. */
export function scoreCard(card, { headline = "" } = {}) {
  const text = textOf(card);
  const normalized = text.toLocaleLowerCase("zh-TW");
  const negated = NEGATION.test(normalized);
  const explicitRisk = RISK.test(normalized) && !negated;
  const due = Boolean(card.due_date || card.due_text);
  const assignee = Array.isArray(card.assignees) && card.assignees.some(Boolean);
  const related = Array.isArray(card.related_ids) ? card.related_ids.length : 0;
  const evidence = Array.isArray(card.evidence_refs) ? card.evidence_refs.length : 0;
  const headlineTerms = String(headline).split(/[\s，。；：、,.!?]+/u).filter((part) => part.length >= 2);
  const headlineMatches = headlineTerms.some((term) => normalized.includes(term.toLocaleLowerCase("zh-TW")));
  const dimensions = {
    decision_impact: clamp(card.source_type === "decision" ? (MAJOR.test(normalized) ? 95 : 60) : explicitRisk ? 70 : 25),
    action_necessity: clamp((card.source_type === "action" ? 55 : 20) + (ACTION.test(normalized) && !negated ? 20 : 0) + (assignee ? 10 : 0) + (due ? 15 : 0)),
    time_sensitivity: clamp(URGENCY.test(normalized) && !negated ? 80 : due ? 65 : 15),
    risk: clamp(explicitRisk ? (MAJOR.test(normalized) ? 95 : 70) : CONDITIONAL_PROHIBITION.test(normalized) ? 80 : 10),
    conclusion_relevance: clamp((headlineMatches ? 70 : 25) + (card.source_type === "decision" ? 15 : 0) + Math.min(related, 3) * 5),
    information_value: clamp(20 + Math.min(evidence, 3) * 15 + Math.min(related, 3) * 10 + (text.length >= 40 ? 15 : 0)),
  };
  const total_score = Math.round(Object.entries(WEIGHTS).reduce((sum, [key, weight]) => sum + dimensions[key] * weight, 0));
  const explicitP0 = MAJOR.test(normalized) || CONDITIONAL_PROHIBITION.test(normalized) || (explicitRisk && matches(normalized, [/(?:重大|嚴重|立即|已發生|事件)/iu]));
  return { ...card, dimension_scores: dimensions, total_score, priority: priorityOf(total_score, { explicitP0, source_type: card.source_type }) };
}

export function priorityOf(score, { explicitP0 = false, source_type = "" } = {}) {
  if (explicitP0) return "P0";
  if (score >= 35) return "P1";
  if (score >= 15) return "P2";
  return "P3";
}

export { WEIGHTS };
