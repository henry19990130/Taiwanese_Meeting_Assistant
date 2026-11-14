import assert from "node:assert/strict";
import test from "node:test";
import { adaptSummaryForImage } from "../src/lib/image/imageAdapter.js";
import { scoreCard, WEIGHTS } from "../src/lib/image/imageScoring.js";
import { selectImageCards } from "../src/lib/image/imageSelector.js";
import { validateImageData } from "../src/lib/image/imageValidator.js";
import { readFile } from "node:fs/promises";

function entry(id, summary, extra = {}) {
  return { id, summary, related_ids: [], evidence: [{ segment_id: `${id}-seg`, quote: summary }], ...extra };
}

function fixture() {
  return {
    meeting_id: "meeting-1", updated_at: "2026-11-09T10:00:00Z", model_name: "test",
    summary: {
      meeting_name: "測試會議", meeting_datetime: { date: "2026-11-09", start_time: "10:00", end_time: "11:00" },
      headline: "確認修正版後再評估上線",
      meeting_content: {
        decisions: [entry("D1", "確認修正版後再評估上線")],
        action_items: [{ id: "A1", task: "先不要上線，收到修正版後由小林重新檢查", assignees: ["小林"], due_date: "2026-11-20", due_text: "週五前", related_ids: [], evidence: [{ segment_id: "A1-seg", quote: "先不要上線" }] }],
        discussions: [{ ...entry("X1", "沒有風險，目前僅討論備案"), topic: "上線條件" }],
        reports: [entry("R1", "本週一般進度")],
        next_meeting: { date: "2026-11-27", date_text: null, time: "10:00", status: "tentative", evidence: [] },
      },
      review_notes: [],
    },
  };
}

test("six dimensions use declared weights and deterministic heuristic scoring", () => {
  const scored = scoreCard({ source_id: "x", source_type: "discussion", title: "進度", content: "本週完成" });
  assert.deepEqual(Object.values(WEIGHTS), [0.3, 0.25, 0.15, 0.15, 0.1, 0.05]);
  const expected = Math.round(Object.entries(WEIGHTS).reduce((sum, [key, weight]) => sum + scored.dimension_scores[key] * weight, 0));
  assert.equal(scored.total_score, expected);
  assert.deepEqual(scoreCard({ source_id: "x", source_type: "discussion", title: "進度", content: "本週完成" }), scored);
  assert.ok(Object.values(scored.dimension_scores).every((value) => value >= 0 && value <= 100));
});

test("decision type does not automatically become P0 and explicit P0 items are retained", () => {
  const selected = selectImageCards({ decisions: [entry("D1", "一般決定")], action_items: [entry("A1", "禁止上線，等待修復")] }, 5);
  assert.notEqual(selected.candidates.find((card) => card.source_id === "D1").priority, "P0");
  assert.equal(selected.cards[0].source_id, "A1");
  assert.equal(selected.cards[0].priority, "P0");
});

test("more than five explicit P0 items reports capacity error and selects none", () => {
  const decisions = Array.from({ length: 6 }, (_, index) => entry(`D${index}`, "不得上線，重大變更"));
  const selected = selectImageCards({ decisions });
  assert.equal(selected.cards.length, 0);
  assert.equal(selected.errors[0].code, "P0_CAPACITY_EXCEEDED");
});

test("P1 cards are sorted by score rather than input order", () => {
  const selected = selectImageCards({ reports: [entry("low", "一般背景補充"), entry("high", "必須今天完成部署確認，期限今天", { due_text: "今天" })] });
  assert.equal(selected.cards[0].source_id, "high");
  assert.ok(selected.cards.every((card) => card.priority === "P0" || card.priority === "P1"));
});

test("adapter preserves negation, uncertainty, assignee, deadline and source data", () => {
  const original = fixture();
  const before = structuredClone(original);
  const adapted = adaptSummaryForImage(original);
  assert.deepEqual(original, before);
  const action = adapted.summary.image_selection.cards.find((card) => card.source_id === "A1");
  assert.ok(action.content.includes("先不要上線"));
  assert.ok(action.content.includes("收到修正版後"));
  assert.deepEqual(action.assignees, ["小林"]);
  assert.equal(action.due_date, "2026-11-20");
  assert.equal(adapted.summary.meeting_content.next_meeting.status, "tentative");
  assert.equal(adapted.summary.image_validation.render_ready, true);
});

test("missing optional collections adapt safely and low candidate count is not padded", () => {
  const result = adaptSummaryForImage({ summary: { meeting_name: "會議", meeting_datetime: {}, meeting_content: {} } });
  assert.equal(result.summary.image_selection.cards.length, 0);
  assert.deepEqual(result.summary.meeting_content.discussions, []);
  assert.equal(result.summary.next_meeting_status, "not_mentioned");
});

test("validator rejects unknown sources and inconsistent totals", () => {
  const adapted = adaptSummaryForImage(fixture());
  const unknown = structuredClone(adapted);
  unknown.summary.image_selection.cards[0].source_id = "missing";
  assert.ok(validateImageData(unknown).warnings.some((item) => item.code === "UNKNOWN_SOURCE_ID"));
  const inconsistent = structuredClone(adapted);
  inconsistent.summary.image_selection.cards[0].total_score += 1;
  assert.ok(validateImageData(inconsistent).warnings.some((item) => item.code === "INCONSISTENT_TOTAL_SCORE"));
});

test("renderer reads selected cards and summary download validates before rendering", async () => {
  const renderer = await readFile(new URL("../src/lib/image/summaryCardsImage.js", import.meta.url), "utf8");
  const view = await readFile(new URL("../src/lib/summaryView.js", import.meta.url), "utf8");
  assert.match(renderer, /image_selection\?\.cards/);
  assert.doesNotMatch(renderer, /flow\.topics|mc\.action_items\.slice/);
  assert.match(view, /if \(!validation\.render_ready\) throw/);
  assert.ok(view.indexOf("adaptSummaryForImage(meeting.summary)") < view.indexOf("drawSummaryCardsImage(imageData)"));
  assert.match(view, /finally\s*\{[\s\S]*button\.disabled = false/);
});
