import { request } from "./http";

export function createJob(file) {
  const body = new FormData();
  body.append("file", file);
  return request("/api/jobs", { method: "POST", body });
}

export function fetchJob(jobId) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`);
}
