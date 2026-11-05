import { meeting } from "../state.js";

export function segmentTimes() {
  const map = {};
  let duration = 0;
  for (const seg of (meeting.transcript && meeting.transcript.segments) || []) {
    if (seg.start_ms != null) map[seg.segment_id] = seg.start_ms;
    if (seg.end_ms != null) duration = Math.max(duration, seg.end_ms);
  }
  return { map, duration };
}

export function firstTime(item, times) {
  for (const ev of item.evidence || []) {
    if (times.map[ev.segment_id] != null) return { ms: times.map[ev.segment_id], sid: ev.segment_id };
  }
  return null;
}

export function buildFlow(mc, times) {
  const norm = (t) => (t || "").replace(/[\s與跟和及、]/g, "");
  const topics = mc.discussions.map((d, i) => ({ d, t: firstTime(d, times), order: i, reports: [], decisions: [] }));
  topics.sort((a, b) => (a.t && b.t ? a.t.ms - b.t.ms : a.order - b.order));
  for (const r of mc.reports) {
    let target = topics.find((x) => norm(x.d.topic) && norm(x.d.topic) === norm(r.topic));
    const rt = firstTime(r, times);
    if (!target && rt) {
      let best = Infinity;
      for (const x of topics) if (x.t && Math.abs(x.t.ms - rt.ms) < best) { best = Math.abs(x.t.ms - rt.ms); target = x; }
    }
    if (target) target.reports.push(r);
  }
  const byId = Object.fromEntries(topics.map((x) => [x.d.id, x]));
  const loose = [];
  for (const dec of mc.decisions) {
    const target = (dec.related_ids || []).map((id) => byId[id]).find(Boolean);
    (target ? target.decisions : loose).push(dec);
  }
  const usedReports = new Set(topics.flatMap((x) => x.reports));
  const looseReports = mc.reports.filter((r) => !usedReports.has(r));
  return { topics, loose, looseReports };
}
