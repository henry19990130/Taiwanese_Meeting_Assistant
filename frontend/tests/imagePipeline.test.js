import assert from "node:assert/strict";
import test from "node:test";
import { adaptSummaryForImage } from "../src/lib/image/imageAdapter.js";

const groundTruth = [
  ["DEC004", "decision"],
  ["DEC001", "decision"],
  ["A004", "action"],
  ["DEC002", "decision"],
  ["A007", "action"],
];

function fixture() {
  return {
    meeting_id: "ground-truth-meeting",
    model_name: "test",
    updated_at: "2026-11-09T10:00:00Z",
    summary: {
      meeting_name: "Ground Truth 測試會議",
      meeting_datetime: { date: "2026-11-09", start_time: "10:00:00", end_time: "11:00:00" },
      headline: "確認上線方向與後續待辦",
      meeting_content: {
        reports: [],
        discussions: [],
        decisions: groundTruth.filter(([, type]) => type === "decision").map(([id]) => ({
          id, summary: `${id} 已確認方向`, related_ids: [], evidence: [{ segment_id: `${id}-S`, quote: "確認方向" }],
        })),
        action_items: groundTruth.filter(([, type]) => type === "action").map(([id]) => ({
          id, task: `${id} 需要完成的工作`, assignees: [], due_date: null, due_text: "下週前",
          related_ids: [], evidence: [{ segment_id: `${id}-S`, quote: "需要完成" }],
        })),
        next_meeting: { status: "not_mentioned", evidence: [] },
      },
      review_notes: [],
    },
  };
}

test("image pipeline adapts and validates a summary", () => {
  const result = adaptSummaryForImage(fixture());
  assert.equal(result.summary.image_selection.selected_count, 5);
  assert.equal(result.summary.image_validation.render_ready, true);
  assert.deepEqual(result.summary.image_selection.cards.map((card) => card.source_id).sort(), groundTruth.map(([id]) => id).sort());
});

test("image pipeline preserves the priority contract", () => {
  const result = adaptSummaryForImage(fixture());
  for (const card of result.summary.image_selection.cards) {
    assert.match(card.priority, /^P[0-3]$/);
    assert.ok(card.total_score >= 0 && card.total_score <= 100);
  }
});

