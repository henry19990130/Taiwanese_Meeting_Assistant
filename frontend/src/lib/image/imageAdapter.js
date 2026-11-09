import { selectImageCards } from "./imageSelector.js";
import { validateImageData } from "./imageValidator.js";

// Convert the API summary shape into the stable, renderer-facing image model.
// The renderer should not need to know how summaries are persisted or fetched.

const LIST_FIELDS = ["reports", "discussions", "decisions", "action_items"];

const asList = (value) => (Array.isArray(value) ? value : []);

function cloneItem(item) {
  return item && typeof item === "object" ? { ...item } : {};
}

function adaptNextMeeting(value) {
  const next = value && typeof value === "object" ? value : {};
  return {
    date: next.date || null,
    date_text: next.date_text || null,
    time: next.time || null,
    status: next.status || "not_mentioned",
    evidence: asList(next.evidence).map(cloneItem),
  };
}

/**
 * Adapt one GET /api/v1/meetings/{id}/summary response for image rendering.
 * This function is intentionally side-effect free and keeps the source data
 * untouched so the page renderer can continue using the API response.
 */
export function adaptSummaryForImage(data) {
  const root = data && typeof data === "object" ? data : {};
  const source = root.summary && typeof root.summary === "object" ? root.summary : root;
  const content = source.meeting_content && typeof source.meeting_content === "object"
    ? source.meeting_content
    : {};

  const meetingDatetime = source.meeting_datetime && typeof source.meeting_datetime === "object"
    ? source.meeting_datetime
    : {};

  const meetingContent = {};
  for (const field of LIST_FIELDS) meetingContent[field] = asList(content[field]).map(cloneItem);
  meetingContent.next_meeting = adaptNextMeeting(content.next_meeting);
  const selection = selectImageCards(meetingContent);

  const adapted = {
    meeting_id: root.meeting_id || null,
    model_name: root.model_name || null,
    updated_at: root.updated_at || null,
    summary: {
      meeting_name: source.meeting_name || "會議",
      meeting_datetime: {
        date: meetingDatetime.date || null,
        start_time: meetingDatetime.start_time || null,
        end_time: meetingDatetime.end_time || null,
      },
      headline: source.headline || "",
      meeting_content: meetingContent,
      review_notes: asList(source.review_notes).map(cloneItem),
      language: source.language || "zh",
      image_selection: selection,
    },
  };
  const validation = validateImageData(adapted);
  adapted.summary.image_selection = { ...selection };
  adapted.summary.image_validation = validation;
  return adapted;
}
