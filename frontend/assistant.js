const scribe = (() => {
  const body = $("agBody"), shadow = $("agShadow"), badge = $("asBadge");
  const imgs = Object.fromEntries([...body.querySelectorAll(".ag-pose")].map((i) => [i.dataset.pose, i]));
  const LABEL = { idle: "", search: "查資料中", listen: "聆聽中", proofread: "校對中", summary: "整理重點", done: "完成！", sleep: "" };

  const BASE = { breath: 1, bf: 0.3, sway: 1.2, sf: 0.16, tilt: 0, bob: 0, bobf: 1, shake: 0, shf: 6 };
  const STATE = {
    idle:      { pose: "idle" },
    search:    { pose: "search", breath: 0.8, bf: 0.45, sway: 3, sf: 0.3, tilt: 2, bob: 1.2, bobf: 0.9 },
    listen:    { pose: "listen", breath: 1.2, bf: 0.5, sway: 2.4, sf: 0.45, tilt: 1.5 },
    proofread: { pose: "proofread", breath: 0.6, bf: 0.4, sway: 0.5, sf: 0.2, tilt: -1, shake: 1.1, shf: 7 },
    summary:   { pose: "summary", bf: 0.6, sway: 1.5, sf: 0.3, bob: 4, bobf: 1.5 },
    done:      { pose: "done", bf: 0.6, sway: 0 },
    sleep:     { pose: "sleep", breath: 2.4, bf: 0.18, sway: 0.8, sf: 0.08, tilt: -3 },
  };
  const ACTS = {
    wave:  { pose: "wave", ms: 2000, sway: 3, sf: 0.9, hop: 1 },
    think: { pose: "think", ms: 2800, tilt: -2.5, sway: 0.6, sf: 0.2 },
    hop:   { pose: "idle", ms: 1100, hop: 2 },
    look:  { pose: "idle", ms: 2600, sway: 5, sf: 0.35 },
  };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  let cur = "idle", pose = "idle", z = 1, lastAct = null, acting = false;
  let tAct = null, tSleep = null, tDone = null, tBlink = null, tHop = [];

  function setPose(name, snap = false) {
    if (name === pose || !imgs[name]) return;
    const a = imgs[pose], b = imgs[name];
    b.style.zIndex = ++z;
    a.classList.toggle("snap", snap); b.classList.toggle("snap", snap);
    b.classList.remove("out"); b.classList.add("on");
    a.classList.remove("on"); a.classList.add("out");
    pose = name;
    if (!snap) kick(0.9);
  }

  const p = { ...BASE }, goal = { ...BASE };
  const ph = { b: 0, s: 0, k: 0, h: 0 };
  let lean = 0, leanGoal = 0, jy = 0, jv = 0, sq = 0, sqv = 0, raf = 0, last = 0;
  let unit = 1;
  function measure() { unit = (body.offsetWidth || 176) / 176; }
  window.addEventListener("resize", measure);
  function aim(extra) { Object.assign(goal, BASE, extra); }
  function kick(v) { sqv += v; }
  function hop(n = 1) {
    tHop.forEach(clearTimeout); tHop = [];
    for (let i = 0; i < n; i++) {
      tHop.push(setTimeout(() => { kick(1.6); tHop.push(setTimeout(() => { jv = -230; }, 90)); }, i * 420));
    }
  }
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - (last || now)) / 1000); last = now;
    const k = 1 - Math.exp(-dt / 0.3);
    for (const key in BASE) p[key] += (goal[key] - p[key]) * k;
    lean += (leanGoal - lean) * (1 - Math.exp(-dt / 0.4));
    const TAU = Math.PI * 2;
    ph.b += dt * p.bf * TAU; ph.s += dt * p.sf * TAU; ph.k += dt * p.shf * TAU; ph.h += dt * p.bobf * TAU;
    if (jv || jy) {
      jy += jv * dt; jv += 1500 * dt;
      if (jy >= 0) { jy = 0; if (jv > 120) kick(jv * 0.004); jv = 0; }
    }
    sqv += (-320 * sq - 16 * sqv) * dt; sq += sqv * dt;
    const br = Math.sin(ph.b) * p.breath;
    const sx = (1 - br * 0.006) * (1 + sq * 0.05);
    const sy = (1 + br * 0.012) * (1 - sq * 0.05);
    const y = (-Math.abs(Math.sin(ph.h)) * p.bob + jy) * unit;
    const x = Math.sin(ph.k) * p.shake * unit;
    const rot = p.tilt + Math.sin(ph.s) * p.sway + lean;
    body.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) rotate(${rot.toFixed(2)}deg) scale(${sx.toFixed(4)}, ${sy.toFixed(4)})`;
    const lift = Math.min(1, -y / (40 * unit));
    shadow.style.transform = `scale(${(1 - lift * 0.35).toFixed(3)})`;
    shadow.style.opacity = (1 - lift * 0.5).toFixed(3);
  }

  function scheduleBlink() {
    clearTimeout(tBlink);
    tBlink = setTimeout(() => {
      if (cur === "idle" && pose === "idle") {
        const blink = (then) => { setPose("blink", true); setTimeout(() => { if (pose === "blink") setPose("idle", true); then && setTimeout(then, 160); }, 120); };
        Math.random() < 0.25 ? blink(() => blink()) : blink();
      }
      scheduleBlink();
    }, 2500 + Math.random() * 3500);
  }

  function show(s) {
    clearTimeout(tAct); clearTimeout(tDone); acting = false;
    cur = s;
    setPose(STATE[s].pose);
    aim(STATE[s]);
    badge.textContent = LABEL[s]; badge.hidden = !LABEL[s];
    if (s === "done") hop(2);
    if (s === "idle") { scheduleAct(); armSleep(); }
  }
  function playAct(name) {
    if (cur !== "idle") return;
    const a = ACTS[name];
    clearTimeout(tAct); acting = true; lastAct = name;
    setPose(a.pose); aim(a);
    if (a.hop) hop(a.hop);
    tAct = setTimeout(() => { acting = false; setPose("idle"); aim(STATE.idle); scheduleAct(); }, a.ms);
  }
  function scheduleAct() {
    clearTimeout(tAct);
    tAct = setTimeout(() => {
      if (cur !== "idle" || acting) return;
      const pool = Object.keys(ACTS).filter((k) => k !== lastAct);
      playAct(pool[Math.floor(Math.random() * pool.length)]);
    }, 4000 + Math.random() * 4000);
  }
  function armSleep() { clearTimeout(tSleep); tSleep = setTimeout(() => { if (cur === "idle") show("sleep"); }, 25000); }
  function wake() { if (cur === "sleep") { show("idle"); hop(1); } else if (cur === "idle") armSleep(); }

  let job = null, chatBusy = false;
  function refresh(prevWorking) {
    const want = chatBusy ? "search" : job || null;
    if (want) { if (want !== cur) show(want); return; }
    if (prevWorking) { show("done"); tDone = setTimeout(() => show("idle"), 2000); return; }
    if (cur !== "idle" && cur !== "sleep" && cur !== "done") show("idle");
  }
  const JOB = { uploaded: "listen", transcribing: "listen", proofreading: "proofread", summarizing: "summary" };

  let lastMove = 0;
  window.addEventListener("pointermove", (e) => {
    const now = performance.now();
    if (now - lastMove < 50) return;
    lastMove = now;
    const r = body.getBoundingClientRect();
    if (!r.width) return;
    leanGoal = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width * 4))) * 3;
    wake();
  }, { passive: true });
  window.addEventListener("keydown", wake);

  return {
    start() {
      show("idle"); scheduleBlink(); measure();
      if (!reduce && !raf) { last = 0; raf = requestAnimationFrame(frame); }
    },
    stop() {
      [tAct, tSleep, tDone, tBlink, ...tHop].forEach(clearTimeout);
      cancelAnimationFrame(raf); raf = 0;
    },
    hop() { if (cur === "sleep") show("idle"); hop(1); },
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
  scribe.setBusy(true);
  try { return await fn(); }
  catch (err) { botText(`出了點問題：${err.message}`); backChips(); return null; }
  finally { wait.remove(); as.busy = false; $("asSend").disabled = false; scribe.setBusy(false); }
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
  }), "鉛筆小書記正在翻會議紀錄…");
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
    botText(`嗨 ${(state.user && state.user.username) || ""}，我是鉛筆小書記！需要什麼幫助？選一個開始，或直接在下面問我。`);
    showMenu();
    loadOverview().catch(() => {});
  }
  $("asInput").focus();
}
function closePanel() {
  as.open = false;
  $("asPanel").hidden = true;
  $("asLauncher").setAttribute("aria-expanded", "false");
  $("asLauncher").setAttribute("aria-label", "打開會議小幫手（鉛筆小書記）");
}
$("asLauncher").addEventListener("click", () => { scribe.hop(); as.open ? closePanel() : openPanel(); });
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
    scribe.start();
    setTimeout(() => { $("asHint").hidden = true; }, 9000);
  },
  onLogout() {
    scribe.stop();
    closePanel();
    $("assistant").hidden = true;
    body().replaceChildren();
    Object.assign(as, { greeted: false, history: [], overview: null, mode: "chat" });
  },
  onStatus(status) { scribe.setJob(status); },
};
