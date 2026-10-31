function deckSlide(deck, { cls = "", kicker = "", title = "" } = {}) {
  const s = el("section", `slide ${cls}`.trim());
  const head = el("header", "slide-head");
  if (kicker) head.append(el("div", "slide-kicker", kicker));
  if (title) head.append(el("h2", "slide-title", title));
  const body = el("div", "slide-body");
  s.append(head, body, el("footer", "slide-foot"));
  deck.append(s);
  return body;
}

const deckOverflow = (body) => body.scrollHeight > body.clientHeight + 1;

function deckFlow(open, sections) {
  let body = open(false);
  for (const sec of sections) {
    if (!sec.items.length) continue;
    let list, wrap;
    const start = (cont) => {
      wrap = el("div", `sec ${sec.cls || ""}`.trim());
      if (sec.title) wrap.append(el("h3", null, cont ? `${sec.title}（續）` : sec.title));
      list = el("ul");
      wrap.append(list);
      body.append(wrap);
    };
    start(false);
    let placed = 0;
    for (const item of sec.items) {
      list.append(item);
      const alone = body.childElementCount === 1 && list.childElementCount === 1;
      if (deckOverflow(body) && !alone) {
        item.remove();
        if (!list.childElementCount) wrap.remove();
        body = open(true);
        start(placed > 0);
        list.append(item);
      }
      placed++;
    }
  }
}

function deckTable(open, headers, rows, colClasses = []) {
  let body, tbody;
  const start = (cont) => {
    body = open(cont);
    const table = el("table", "deck-table");
    const tr = el("tr");
    headers.forEach((h, i) => tr.append(el("th", colClasses[i] || null, h)));
    const thead = el("thead");
    thead.append(tr);
    tbody = el("tbody");
    table.append(thead, tbody);
    body.append(table);
  };
  start(false);
  for (const r of rows) {
    tbody.append(r);
    if (deckOverflow(body) && tbody.children.length > 1) {
      r.remove();
      start(true);
      tbody.append(r);
    }
  }
}

const li = (text, cls) => el("li", cls || null, text);

function buildDeck(data) {
  const sm = data.summary, mc = sm.meeting_content;
  const times = segmentTimes();
  const flow = buildFlow(mc, times);
  const deck = $("printDeck");
  deck.replaceChildren();
  const name = sm.meeting_name || "會議";

  {
    const s = el("section", "slide cover");
    s.append(el("div", "cover-kicker", "會議簡報"), el("h1", "cover-title", name));
    const meta = [fmtDate(sm.meeting_datetime)];
    if (times.duration) meta.push(`約 ${Math.round(times.duration / 60000) || 1} 分鐘`);
    s.append(el("div", "cover-meta", meta.filter(Boolean).join("　·　")));
    const hl = el("div", "cover-headline");
    hl.append(el("div", "cover-label", "一句話總結"), el("p", null, sm.headline || "（這次沒有產生一句話總結）"));
    s.append(hl);
    const kpis = el("div", "cover-kpis");
    for (const [label, n] of [["議題", flow.topics.length], ["決議", mc.decisions.length],
                              ["待辦", mc.action_items.length], ["需要確認", sm.review_notes.length]]) {
      const k = el("div", "cover-kpi");
      k.append(el("b", null, String(n)), el("span", null, label));
      kpis.append(k);
    }
    s.append(kpis, el("div", "cover-foot", `覓聲 MeetSum · 本地端整理${data.model_name ? " · " + data.model_name : ""}`));
    deck.append(s);
  }

  if (flow.topics.length) {
    const rows = flow.topics.map((tp, i) => {
      const item = el("li", "agenda-row");
      item.append(el("span", "agenda-no", String(i + 1)), el("span", "agenda-time", tp.t ? fmtMs(tp.t.ms) : "—"),
        el("span", "agenda-topic", tp.d.topic || "（未命名議題）"),
        el("span", tp.decisions.length ? "badge ok" : "badge", tp.decisions.length ? `決議 ${tp.decisions.length}` : "討論"));
      return item;
    });
    deckFlow((cont) => deckSlide(deck, { kicker: "AGENDA", title: cont ? "議程總覽（續）" : "議程總覽" }),
      [{ cls: "s-agenda", items: rows }]);
  }

  const actOf = (tp) => {
    const ids = new Set([tp.d.id, ...tp.decisions.map((d) => d.id)]);
    return mc.action_items.filter((a) => (a.related_ids || []).some((id) => ids.has(id)));
  };
  const dueText = (a) => (a.due_date ? fmtMD(a.due_date) : a.due_text || "未定期限");
  const whoText = (a) => (a.assignees.length ? a.assignees.join("、") : "未指定");
  flow.topics.forEach((tp, i) => {
    const kicker = `議題 ${i + 1} / ${flow.topics.length}${tp.t ? "　·　" + fmtMs(tp.t.ms) : ""}`;
    const title = tp.d.topic || "（未命名議題）";
    const pages = [];
    const page = (k) => {
      while (pages.length <= k) {
        const body = deckSlide(deck, { kicker, title: pages.length ? `${title}（續）` : title });
        body.classList.add("two-col");
        const left = el("div", "col-left"), right = el("div", "col-right");
        body.append(left, right);
        pages.push({ left, right });
      }
      return pages[k];
    };
    const kps = (tp.d.key_points && tp.d.key_points.length ? tp.d.key_points : [tp.d.summary || ""]).filter(Boolean);
    let L = 0, R = 0;
    deckFlow((cont) => page(cont ? ++L : (L = 0)).left, [
      { title: "現況", cls: "s-report", items: tp.reports.map((r) => li(r.summary || "")) },
      { title: "討論重點", cls: "s-points", items: kps.map((k) => li(k)) },
    ]);
    deckFlow((cont) => page(cont ? ++R : (R = 0)).right, [
      { title: "決議", cls: "s-decision", items: tp.decisions.length ? tp.decisions.map((d) => li(d.summary || "")) : [li("這個議題沒有做出決議", "none")] },
      { title: "相關待辦", cls: "s-todo", items: actOf(tp).map((a) => li(`${whoText(a)}｜${a.task}（${dueText(a)}）`)) },
    ]);
  });

  if (flow.loose.length || flow.looseReports.length) {
    deckFlow((cont) => deckSlide(deck, { kicker: "OTHERS", title: cont ? "其他重點（續）" : "其他重點" }), [
      { title: "現況報告", cls: "s-report", items: flow.looseReports.map((r) => li(`${r.topic ? r.topic + "：" : ""}${r.summary || ""}`)) },
      { title: "決議", cls: "s-decision", items: flow.loose.map((d) => li(d.summary || "")) },
    ]);
  }

  {
    const open = (cont) => deckSlide(deck, { kicker: "ACTION ITEMS", title: cont ? "待辦事項（續）" : "待辦事項" });
    if (!mc.action_items.length) {
      open(false).append(el("p", "empty-note", "這場會議沒有明確的待辦事項。"));
    } else {
      const rows = mc.action_items.map((a, i) => {
        const tr = el("tr");
        const who = el("td", a.assignees.length ? "c-who" : "c-who warn", whoText(a));
        const due = el("td", a.due_date || a.due_text ? "c-due" : "c-due muted", dueText(a));
        if (a.due_date && a.due_text) due.append(el("small", null, a.due_text));
        tr.append(el("td", "c-no", String(i + 1)), who, el("td", "c-task", a.task || ""), due);
        return tr;
      });
      deckTable(open, ["#", "負責", "待辦事項", "期限"], rows, ["c-no", "c-who", "c-task", "c-due"]);
    }
  }

  if (sm.review_notes.length) {
    deckFlow((cont) => deckSlide(deck, { kicker: "TO CONFIRM", title: cont ? "需要確認（續）" : "需要確認" }), [{
      cls: "s-review",
      items: sm.review_notes.map((n) => {
        const item = el("li");
        if (n.field) item.append(el("span", "badge warn", n.field));
        item.append(document.createTextNode(n.reason || ""));
        return item;
      }),
    }]);
  }

  {
    const nm = mc.next_meeting || {};
    const when = nm.status && nm.status !== "not_mentioned"
      ? [nm.date ? fmtMD(nm.date) : nm.date_text, nm.time].filter(Boolean).join(" ") || "時間未定"
      : "尚未排定";
    const s = el("section", "slide closing");
    s.append(el("div", "closing-label", "下次會議"), el("div", "closing-when", when));
    if (nm.status === "tentative") s.append(el("div", "closing-note", "（暫定，請再確認）"));
    s.append(el("div", "closing-foot", "完整逐字稿與原文依據，請見覓聲"), el("footer", "slide-foot"));
    deck.append(s);
  }

  const all = [...deck.querySelectorAll(".slide")];
  all.forEach((s, i) => {
    const f = s.querySelector(".slide-foot");
    if (!f) return;
    f.replaceChildren(el("span", null, `${name}　·　${fmtDate(sm.meeting_datetime)}`), el("span", null, `${i + 1} / ${all.length}`));
  });
  return all.length;
}

async function exportDeck() {
  if (!state.summary) return;
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  buildDeck(state.summary);
  const oldTitle = document.title;
  document.title = `會議簡報_${safeName(state.summary.summary.meeting_name)}`;
  document.body.classList.add("print-deck");
  const done = () => {
    document.body.classList.remove("print-deck");
    document.title = oldTitle;
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

$("deckBtn").addEventListener("click", exportDeck);
