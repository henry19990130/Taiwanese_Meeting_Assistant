import { reactive } from "vue";

export const session = reactive({
  token: null,
  user: null,
  entered: false,
});

export const meeting = reactive({
  meetingId: null,
  status: null,
  failedStage: null,
  transcript: null,
  summary: null,
  summaryLangTouched: false,
  proofread: null,
  pollTimer: null,
});

export const glossary = reactive({
  terms: [],
  count: 0,
  limit: 200,
  max_length: 30,
});

export function suggestions() {
  return (meeting.proofread && meeting.proofread.suggestions) || [];
}
