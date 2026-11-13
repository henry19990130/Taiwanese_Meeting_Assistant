window.MeetUI = (() => {
  const byId = (id) => document.getElementById(id);
  const BASE_TITLE = document.title;
  let peaks = null;
  let timer = null;
  let startedAt = null;

  const fmtSize = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
  const fmtClock = (sec) => {
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  };

  function setupDropzone(zoneId, chipId, isAudio) {
    const zone = byId(zoneId), chip = byId(chipId);
    if (!zone || !chip) return;
    const input = zone.querySelector("input[type=file]");
    const on = () => zone.classList.add("is-over");
    const off = () => zone.classList.remove("is-over");
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, on));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, off));
    input.addEventListener("change", async () => {
      const f = input.files && input.files[0];
      zone.classList.toggle("has-file", !!f);
      chip.hidden = !f;
      if (!f) { if (isAudio) peaks = null; return; }
      chip.textContent = `${f.name} · ${fmtSize(f.size)}`;
      if (isAudio) {
        peaks = null;
        const info = await decodePeaks(f);
        if (info && input.files[0] === f) {
          peaks = info.peaks;
          chip.textContent = `${f.name} · ${fmtSize(f.size)} · ${fmtClock(info.duration)}`;
        }
      }
    });
  }

  async function decodePeaks(file) {
    if (!window.OfflineAudioContext || file.size > 300 * 1048576) return null;
    try {
      const buf = await file.arrayBuffer();
      const ctx = new OfflineAudioContext(1, 1, 8000);
      const audio = await ctx.decodeAudioData(buf);
      const data = audio.getChannelData(0);
      const n = 240, step = Math.max(1, Math.floor(data.length / n));
      const out = [];
      let max = 0;
      for (let i = 0; i < n; i++) {
        let sum = 0;
        const from = i * step, to = Math.min(data.length, from + step);
        for (let j = from; j < to; j += 4) sum += data[j] * data[j];
        const rms = Math.sqrt(sum / Math.max(1, (to - from) / 4));
        out.push(rms);
        if (rms > max) max = rms;
      }
      return { peaks: out.map((v) => (max ? Math.pow(v / max, 0.7) : 0)), duration: audio.duration };
    } catch (_) {
      return null;
    }
  }

  function drawWave(done) {
    const box = byId("waveBox"), canvas = byId("waveCanvas");
    if (!box || !canvas || !peaks) return;
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    const g = canvas.getContext("2d");
    g.scale(dpr, dpr);
    g.clearRect(0, 0, w, h);
    const gap = 2, barW = 3, count = Math.max(10, Math.floor((w - 24) / (barW + gap)));
    const pad = 12, usable = h - pad * 2;
    g.fillStyle = done ? "#5E7A5A" : "#D9C4A3";
    for (let i = 0; i < count; i++) {
      const v = peaks[Math.floor((i / count) * peaks.length)] || 0;
      const bh = Math.max(3, v * usable);
      const x = 12 + i * (barW + gap), y = (h - bh) / 2;
      g.beginPath();
      if (g.roundRect) g.roundRect(x, y, barW, bh, 1.5); else g.rect(x, y, barW, bh);
      g.fill();
    }
  }

  function startTimer() {
    if (timer) return;
    startedAt = startedAt || Date.now();
    const tick = () => { const e = byId("elapsed"); if (e) e.textContent = `已經過 ${fmtClock((Date.now() - startedAt) / 1000)}`; };
    tick();
    timer = setInterval(tick, 1000);
  }
  function stopTimer() { if (timer) clearInterval(timer); timer = null; }

  const FLOW_OF = {
    new: "upload", uploaded: "listen", transcribing: "listen", proofreading: "listen",
    reviewing: "proof", transcribed: "proof", summarizing: "summary", completed: "summary",
  };
  const TITLE_OF = {
    uploaded: "正在整理音訊…", transcribing: "正在聽…", proofreading: "聽懂了，正在找可能聽錯的地方…",
    reviewing: "聽懂了，請你確認逐字稿。", transcribed: "逐字稿確認好了。", summarizing: "正在整理重點…",
    completed: "整理好了。", failed: "這一步沒有成功。",
  };

  function onStatus(status, failedStage) {
    const flow = status === "failed" ? (FLOW_OF[failedStage] || "listen") : (FLOW_OF[status] || "upload");
    const order = ["upload", "listen", "proof", "summary"];
    const cur = order.indexOf(flow);
    for (const li of byId("flowSteps").children) {
      const i = order.indexOf(li.dataset.flow);
      li.className = i === cur ? "is-current" : (i < cur ? "is-done" : "");
    }
    const hero = byId("homeHero");
    if (hero) hero.hidden = flow !== "upload";

    if (status === "new") {
      stopTimer(); startedAt = null; peaks = null;
      for (const id of ["audioChip", "transcriptChip"]) { const c = byId(id); if (c) c.hidden = true; }
      document.querySelectorAll(".dropzone").forEach((z) => z.classList.remove("has-file", "is-over"));
      document.title = BASE_TITLE;
      return;
    }
    const t = byId("listenTitle");
    if (t) t.textContent = TITLE_OF[status] || "";

    const listening = ["uploaded", "transcribing"].includes(status);
    const box = byId("waveBox");
    if (box) {
      box.hidden = !peaks || flow !== "listen";
      box.classList.toggle("is-scanning", listening);
      requestAnimationFrame(() => drawWave(!listening));
    }
    if (["uploaded", "transcribing", "proofreading", "summarizing"].includes(status)) startTimer();
    else stopTimer();
    document.title = flow === "listen" && status !== "failed" ? `（聆聽中）${BASE_TITLE}`
      : status === "reviewing" ? `● 逐字稿好了｜${BASE_TITLE}` : BASE_TITLE;
  }

  async function loadInfo() {
    try {
      const r = await fetch("/api/v1/health");
      if (!r.ok) return;
      const d = await r.json();
      if (d.asr_engine === "fake") byId("infoAsr").textContent = "fake（假逐字稿）";
      else if (d.asr_models) byId("infoAsr").textContent = "依會議語言切換（中／台／客／英）";
      else if (d.asr_engine) byId("infoAsr").textContent = d.asr_engine;
      if (d.llm_model) byId("infoLlm").textContent = d.llm_model;
    } catch (_) {  }
  }

  setupDropzone("audioField", "audioChip", true);
  setupDropzone("transcriptField", "transcriptChip", false);
  window.addEventListener("resize", () => { const b = byId("waveBox"); if (b && !b.hidden) drawWave(!b.classList.contains("is-scanning")); });

  return { onStatus, loadInfo };
})();
