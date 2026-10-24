const knight = (() => {
  const svg = document.getElementById("knightSvg");
  const badge = $("asBadge");
  const LABEL = { idle: "", search: "查資料中", listen: "聆聽中", proofread: "校對中", summary: "整理重點", done: "完成！", sleep: "" };
  const FACE = { idle: ["open", "smile"], search: ["open", "flat"], listen: ["closed", "o"], proofread: ["open", "flat"],
                 summary: ["open", "big"], done: ["happy", "big"], sleep: ["closed", "o"] };
  const ACT = { twirl: [900, ["open", "smile"]], wave: [1600, ["happy", "big"]], stretch: [1800, ["closed", "o"]],
                look: [2200, ["open", "smile"]], hop: [1000, ["happy", "smile"]] };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let cur = "idle", lastAct = null, tAct = null, tSleep = null, tDone = null;

  function face(f) { svg.dataset.eyes = f[0]; svg.dataset.mouth = f[1]; }
  function show(s) {
    clearTimeout(tAct); clearTimeout(tDone); delete svg.dataset.act;
    cur = s; svg.dataset.state = s; face(FACE[s]);
    badge.textContent = LABEL[s]; badge.hidden = !LABEL[s];
    if (s === "idle") { scheduleAct(); armSleep(); }
  }
  function playAct(name) {
    if (cur !== "idle") return;
    clearTimeout(tAct);
    const [ms, f] = ACT[name];
    svg.dataset.act = name; face(f); lastAct = name;
    tAct = setTimeout(() => { delete svg.dataset.act; face(FACE.idle); scheduleAct(); }, ms + 150);
  }
  function scheduleAct() {
    clearTimeout(tAct);
    if (reduce) return;
    tAct = setTimeout(() => {
      if (cur !== "idle") return;
      const pool = Object.keys(ACT).filter((k) => k !== lastAct);
      playAct(pool[Math.floor(Math.random() * pool.length)]);
    }, 3500 + Math.random() * 3500);
  }
  function armSleep() { clearTimeout(tSleep); tSleep = setTimeout(() => { if (cur === "idle") show("sleep"); }, 25000); }

  let job = null, chatBusy = false;
  function refresh(prevWorking) {
    const want = chatBusy ? "search" : job || null;
    if (want) { if (want !== cur) show(want); return; }
    if (prevWorking) { show("done"); tDone = setTimeout(() => show("idle"), 1900); return; }
    if (cur !== "idle" && cur !== "sleep" && cur !== "done") show("idle");
  }
  const JOB = { uploaded: "listen", transcribing: "listen", proofreading: "proofread", summarizing: "summary" };

  let lastMove = 0;
  window.addEventListener("pointermove", (e) => {
    const now = performance.now();
    if (now - lastMove < 40) return;
    lastMove = now;
    const r = svg.getBoundingClientRect();
    if (!r.width) return;
    const dx = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width * 3)));
    const dy = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height * 0.42)) / (r.height * 3)));
    svg.style.setProperty("--ex", `${(dx * 2.6).toFixed(2)}px`);
    svg.style.setProperty("--ey", `${(dy * 1.8).toFixed(2)}px`);
    if (cur === "sleep") show("idle"); else if (cur === "idle") armSleep();
  }, { passive: true });
  window.addEventListener("keydown", () => { if (cur === "sleep") show("idle"); else if (cur === "idle") armSleep(); });

  return {
    start() { show("idle"); },
    stop() { clearTimeout(tAct); clearTimeout(tSleep); clearTimeout(tDone); },
    hop() { if (cur === "sleep") show("idle"); playAct("hop"); },
    setJob(status) {
      const was = Boolean(job || chatBusy);
      job = JOB[status] || null;
      refresh(was && !job && !chatBusy && status !== "failed");
    },
    setBusy(v) { const was = Boolean(job || chatBusy); chatBusy = v; refresh(was && !chatBusy && !job); },
  };
})();

const as = { open: false, greeted: false, mode: "chat", history: [], overview: null, busy: false };
const ICON = {
  meeting: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  summary: '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h5"/>',
  todo: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>',
  quote: '<path d="M7 8H5a2 2 0 0 0-2 2v6h6v-6H5M19 8h-2a2 2 0 0 0-2 2v6h6v-6h-4"/>',
};
const KIND = { segment: "逐字稿", decision: "決議", action: "待辦", discussion: "討論", report: "報告", meeting: "會議" };

function svgIcon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("width", "20"); s.setAttribute("height", "20"); s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "2");
  s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICON[name];
  return s;
}
function body() { return $("asBody"); }
function scrollDown() { const b = body(); b.scrollTop = b.scrollHeight; }
function add(node) { body().append(node); scrollDown(); return node; }
function md(iso) { return iso ? fmtMD(iso) : ""; }

function botText(text) { return add(el("div", "as-msg bot", text)); }
function userText(text) { return add(el("div", "as-msg user", text)); }
function chips(list) {
  const box = el("div", "as-chips");
  for (const [label, fn] of list) {
    const b = el("button", null, label);
    b.type = "button";
    b.addEventListener("click", () => { box.remove(); fn(); });
    box.append(b);
  }
  return add(box);
}
function backChips(extra = []) { chips([...extra, ["回到選單", showMenu]]); }
function setMode(mode, placeholder) {
  as.mode = mode;
  $("asInput").placeholder = placeholder || "或直接輸入跟會議有關的問題";
  $("asInput").focus();
}

function cardActions(meetingId, segmentId) {
  const acts = el("div", "acts");
  const open = el("button", null, segmentId ? "跳到原文" : "開啟會議");
  open.type = "button";
  open.addEventListener("click", () => openMeeting(meetingId, segmentId));
  acts.append(open);
  return acts;
}

async function call(fn, waitText = "查資料中…") {
  const wait = add(el("div", "as-msg wait", waitText));
  as.busy = true; $("asSend").disabled = true;
  knight.setBusy(true);
  try { return await fn(); }
  catch (err) { botText(`出了點問題：${err.message}`); backChips(); return null; }
  finally { wait.remove(); as.busy = false; $("asSend").disabled = false; knight.setBusy(false); }
}

function showMenu() {
  setMode("chat");
  const box = el("div", "as-menu");
  const opts = [
    ["meeting", "找某場會議", "用關鍵字、月份或人名找會議", menuMeetings],
    ["search", "找會議裡講過的內容", "例如「上線日為什麼延後？」", menuContent],
    ["summary", "看某場會議的重點", "決議、待辦、需要確認的事項", menuSummary],
    ["todo", "查待辦事項", "誰負責什麼、快到期的、沒有負責人的", menuActions],
    ["quote", "這句話出自哪場會議", "貼上一句話，找出處和前後文", menuQuote],
  ];
  for (const [icon, title, desc, fn] of opts) {
    const b = el("button", "as-opt");
    b.type = "button";
    const txt = el("span");
    txt.append(el("b", null, title), el("small", null, desc));
    b.append(svgIcon(icon), txt);
    b.addEventListener("click", () => { userText(title); fn(); });
    box.append(b);
  }
  add(box);
}

function menuMeetings() {
  botText("要找哪一場？輸入關鍵字、月份或人名（例如：預算、9月、建宏）。");
  setMode("meetings", "例如：預算、9月、建宏");
  chips([["列出最近的會議", () => doMeetings("")]]);
}
async function doMeetings(input) {
  const params = new URLSearchParams();
  const t = input.trim();
  const people = (as.overview && as.overview.people) || [];
  if (/^(\d{1,2}月|上個月|這個月|本月|這週|上週|最近\d+天|\d{1,2}\/\d{1,2})$/.test(t)) params.set("period", t);
  else if (people.includes(t)) params.set("person", t);
  else if (t) params.set("q", t);
  const r = await call(() => api(`/api/v1/assistant/meetings?${params}`));
  if (!r) return;
  if (!r.meetings.length) { botText("沒有找到符合的會議。"); backChips([["換個關鍵字", menuMeetings]]); return; }
  botText(t ? `找到 ${r.count} 場會議：` : "最近的會議：");
  for (const m of r.meetings) {
    const c = el("div", "as-card");
    c.append(el("div", "t", m.name), el("div", "m", `${md(m.date)}　·　決議 ${m.decisions}、待辦 ${m.action_items}`));
    if (m.headline) c.append(el("div", "q", m.headline));
    const acts = cardActions(m.meeting_id, null);
    const sum = el("button", null, "看重點");
    sum.type = "button";
    sum.addEventListener("click", () => doSummary(m.meeting_id, m.name));
    acts.prepend(sum);
    c.append(acts);
    add(c);
  }
  setMode("chat");
  backChips();
}

function menuContent() {
  botText("想找什麼？直接問就可以，例如「上線日為什麼延後？」「誰說要找外包？」");
  setMode("chat", "例如：上線日為什麼延後？");
}

async function menuSummary() {
  const o = await call(() => loadOverview());
  if (!o) return;
  if (!o.recent.length) { botText("你的帳號還沒有已確認逐字稿的會議。"); backChips(); return; }
  botText(o.recent.length > 8 ? "要看哪一場？這裡列出最近 8 場，比較早的可以用關鍵字找。" : "要看哪一場？");
  chips([...o.recent.slice(0, 8).map((m) => [`${md(m.date)} ${m.name}`, () => doSummary(m.meeting_id, m.name)]),
         ["用關鍵字找其他會議", () => { userText("用關鍵字找其他會議"); menuMeetings(); }]]);
}
async function doSummary(meetingId, name) {
  userText(`看「${name}」的重點`);
  const r = await call(() => api(`/api/v1/assistant/meetings/${meetingId}/summary`));
  if (!r) return;
  const c = el("div", "as-card");
  c.append(el("div", "t", `${r.name}　${md(r.date)}`));
  if (r.headline) c.append(el("div", "q", r.headline));
  if (r.decisions.length) {
    c.append(el("div", "m", "決議"));
    for (const d of r.decisions) c.append(el("div", null, `✓ ${d.text}`));
  }
  if (r.action_items.length) {
    c.append(el("div", "m", "待辦"));
    for (const a of r.action_items) {
      const who = a.assignees.length ? a.assignees.join("、") : "未指定";
      c.append(el("div", a.assignees.length ? null : "as-warn", `→ ${a.task}（${who}｜${a.due ? fmtDue(a.due) : "未定"}）`));
    }
  }
  if (r.review_notes.length) c.append(el("div", "m as-warn", `需要確認 ${r.review_notes.length} 項`));
  c.append(cardActions(r.meeting_id, null));
  add(c);
  backChips();
}
function fmtDue(due) { return /^\d{4}-\d{2}-\d{2}$/.test(due) ? md(due) : due; }

async function menuActions() {
  botText("要查哪一種待辦？");
  chips([
    ["指定某個人", async () => {
      const o = await call(() => loadOverview());
      if (!o) return;
      if (!o.people.length) { botText("還沒有任何指定負責人的待辦。"); backChips(); return; }
      botText("要查誰的？");
      chips(o.people.slice(0, 12).map((p) => [p, () => doActions({ assignee: p }, `${p}負責的待辦`)]));
    }],
    ["這週到期的", () => doActions({ due: "這週" }, "這週到期的待辦")],
    ["下週到期的", () => doActions({ due: "下週" }, "下週到期的待辦")],
    ["還沒有負責人的", () => doActions({ unassigned: "true" }, "還沒有負責人的待辦")],
  ]);
}
async function doActions(params, title) {
  userText(title);
  const r = await call(() => api(`/api/v1/assistant/actions?${new URLSearchParams(params)}`));
  if (!r) return;
  if (!r.items.length) { botText(`沒有${title}。`); backChips([["查其他待辦", menuActions]]); return; }
  botText(`${title}共 ${r.count} 項：`);
  const byRef = Object.fromEntries(r.sources.map((s) => [s.n, s]));
  for (const a of r.items) {
    const s = byRef[a.ref] || {};
    const c = el("div", "as-card");
    c.append(el("div", "t", a.task));
    const who = el("div", a.assignees[0] === "未指定" ? "m as-warn" : "m",
      `負責：${a.assignees.join("、")}　期限：${fmtDue(a.due)}`);
    c.append(who, el("div", "m", `${a.meeting}　${md(a.meeting_date)}${s.time ? "　" + s.time : ""}`));
    c.append(cardActions(s.meeting_id, s.segment_id));
    add(c);
  }
  backChips([["查其他待辦", menuActions]]);
}

function menuQuote() {
  botText("把那句話貼上來，記得大概的也可以。我會找出是哪場會議、第幾分鐘說的。");
  setMode("quote", "貼上那句話");
}
async function doQuote(text) {
  const r = await call(() => api("/api/v1/assistant/quote", { method: "POST", json: { text } }), "比對中…");
  if (!r) return;
  setMode("chat");
  if (!r.results.length) {
    botText("你的會議紀錄裡沒有找到相似的句子。如果只記得大概的意思，可以用「找會議裡講過的內容」問問看。");
    backChips([["再找一句", menuQuote]]);
    return;
  }
  const top = r.results[0];
  botText(top.confidence === "high"
    ? `這句話出自「${top.meeting}」（${md(top.date)}），大約在 ${top.time}：`
    : "沒有找到一模一樣的句子，最像的是這幾處，請你確認：");
  for (const q of r.results) {
    const c = el("div", "as-card");
    const t = el("div", "t");
    t.append(el("span", q.confidence === "high" ? "as-tag" : "as-tag maybe", q.confidence === "high" ? "高度符合" : "可能是"),
      document.createTextNode(`${q.meeting}　${md(q.date)}　${q.time}`));
    c.append(t);
    const ctx = el("ul", "ctx");
    for (const line of q.context) ctx.append(el("li", line.match ? "hit" : null, `${line.time}　${line.text}`));
    c.append(ctx, cardActions(q.meeting_id, q.segment_id));
    add(c);
  }
  backChips([["再找一句", menuQuote]]);
}

async function doChat(question) {
  const r = await call(() => api("/api/v1/assistant/chat", {
    method: "POST", json: { question, history: as.history.slice(-6) },
  }), "鉛筆小騎士正在翻會議紀錄…");
  if (!r) return;
  as.history.push({ role: "user", content: question }, { role: "assistant", content: r.text });
  if (r.trace && r.trace.length) {
    const tr = el("div", "as-trace");
    for (const t of r.trace) tr.append(el("div", null, `已查：${TOOL_LABEL[t.tool] || t.tool}${traceArgs(t.args)} → ${t.count} 筆`));
    add(tr);
  }
  const msg = el("div", "as-msg bot");

  for (const part of r.text.split(/(\[\d{1,3}\])/)) {
    const m = part.match(/^\[(\d{1,3})\]$/);
    if (m) {
      const sup = el("sup", null, `[${m[1]}]`);
      sup.addEventListener("click", () => { const t = document.getElementById(`as-src-${m[1]}`); if (t) t.scrollIntoView({ block: "nearest" }); });
      msg.append(sup);
    } else msg.append(document.createTextNode(part));
  }
  add(msg);
  for (const s of r.sources || []) {
    const c = el("div", "as-card");
    c.id = `as-src-${s.n}`;
    const t = el("div", "t");
    t.append(el("span", "n", `[${s.n}]`), document.createTextNode(`${s.meeting_name}　${md(s.date)}${s.time ? "　" + s.time : ""}`));
    c.append(t, el("div", "m", KIND[s.kind] || ""), el("div", "q", s.text.length > 90 ? s.text.slice(0, 89) + "…" : s.text));
    c.append(cardActions(s.meeting_id, s.segment_id));
    add(c);
  }
  if (r.kind === "refuse") showMenu(); else backChips();
}
const TOOL_LABEL = { search_meetings: "找會議", search_content: "搜尋內容", get_meeting_summary: "讀會議重點",
                     list_action_items: "查待辦", find_quote: "找出處" };
function traceArgs(args) {
  const v = Object.values(args || {}).filter((x) => x !== "" && x != null && x !== false).map(String);
  return v.length ? `「${v.join("、").slice(0, 30)}」` : "";
}

async function loadOverview() {
  as.overview = await api("/api/v1/assistant/overview");
  return as.overview;
}

function openPanel() {
  as.open = true;
  $("asPanel").hidden = false;
  $("asHint").hidden = true;
  $("asLauncher").setAttribute("aria-expanded", "true");
  $("asLauncher").setAttribute("aria-label", "收起會議小幫手");
  if (!as.greeted) {
    as.greeted = true;
    botText(`嗨 ${(state.user && state.user.username) || ""}，我是鉛筆小騎士！需要什麼幫助？選一個開始，或直接在下面問我。`);
    showMenu();
    loadOverview().catch(() => {});
  }
  $("asInput").focus();
}
function closePanel() {
  as.open = false;
  $("asPanel").hidden = true;
  $("asLauncher").setAttribute("aria-expanded", "false");
  $("asLauncher").setAttribute("aria-label", "打開會議小幫手（鉛筆小騎士）");
}
$("asLauncher").addEventListener("click", () => { knight.hop(); as.open ? closePanel() : openPanel(); });
$("asClose").addEventListener("click", closePanel);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && as.open) closePanel(); });

$("asForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("asInput").value.trim();
  if (!text || as.busy) return;
  $("asInput").value = "";
  userText(text);
  if (as.mode === "meetings") doMeetings(text);
  else if (as.mode === "quote") doQuote(text);
  else doChat(text);
});

window.assistant = {
  onLogin() {
    $("assistant").hidden = false;
    $("asHint").hidden = false;
    knight.start();
    setTimeout(() => { $("asHint").hidden = true; }, 9000);
  },
  onLogout() {
    knight.stop();
    closePanel();
    $("assistant").hidden = true;
    body().replaceChildren();
    Object.assign(as, { greeted: false, history: [], overview: null, mode: "chat" });
  },
  onStatus(status) { knight.setJob(status); },
};
