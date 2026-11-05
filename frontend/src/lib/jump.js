import { $, el } from "./dom.js";

export function jumpTo(segmentId) {
  const li = document.getElementById(`seg-${segmentId}`);
  if (!li) return;
  li.scrollIntoView({ behavior: "smooth", block: "center" });
  li.classList.add("highlight");
  setTimeout(() => li.classList.remove("highlight"), 1800);
}

export function evidence(list) {
  if (!list || !list.length) return null;
  const box = el("div", "evidence");
  for (const ev of list) {
    const b = el("button", null, `${ev.segment_id}「${ev.quote}」`);
    b.type = "button";
    b.title = "跳到逐字稿原文";
    b.addEventListener("click", () => jumpTo(ev.segment_id));
    box.append(b);
  }
  return box;
}

export function focusId(id) {
  const node = $(id);
  if (node) node.focus();
}
