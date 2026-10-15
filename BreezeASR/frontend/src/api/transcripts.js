import { request } from "./http";

export function listTranscripts() {
  return request("/api/transcripts");
}

export function getTranscript(transcriptId) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}`);
}

export function deleteTranscript(transcriptId) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}`, {
    method: "DELETE",
  });
}

export function suggestTranscriptTags(transcriptId) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}/tags/suggest`, {
    method: "POST",
  });
}

export function updateTranscriptTags(transcriptId, tags) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}/tags`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
}

export function updateTranscriptTitle(transcriptId, title) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}/title`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function updateTranscriptSummary(transcriptId, summary) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}/summary`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ summary }),
  });
}

export function deleteTranscriptSummary(transcriptId) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}/summary`, {
    method: "DELETE",
  });
}

export function regenerateTranscriptSummary(transcriptId) {
  return request(`/api/transcripts/${encodeURIComponent(transcriptId)}/summary/regenerate`, {
    method: "POST",
  });
}
