export const $ = (id) => document.getElementById(id);

export function showError(el, msg) {
  if (!el) return;
  el.textContent = msg || "";
  el.hidden = !msg;
}

export function el(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
}

export function fmtMs(ms) {
  if (ms == null) return "?";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtMD(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const w = "日一二三四五六"[new Date(y, m - 1, d).getDay()];
  return `${m}/${d}（${w}）`;
}

export function fmtDate(dtm) {
  if (!dtm || !dtm.date) return "";
  const [y, m, d] = dtm.date.split("-").map(Number);
  const w = "日一二三四五六"[new Date(y, m - 1, d).getDay()];
  const t = [dtm.start_time, dtm.end_time].filter(Boolean).map((x) => x.slice(0, 5)).join("–");
  return `${y}/${m}/${d}（${w}）${t ? " " + t : ""}`;
}

export function safeName(s) {
  return (s || "會議").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 40);
}

export function stamp(iso) {
  const d = iso ? new Date(iso) : new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

export function downloadBlob(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
