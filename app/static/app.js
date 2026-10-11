/* FetalScan AI - viewer front-end */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  const state = {
    sid: null,
    meta: null,
    wc: 0, ww: 1,
    invert: false,
    overlay: false,     // heat-map available
    showOverlay: true,
    opacity: 0.7,
    result: null,
    activeFinding: null,
    views: {},          // axis -> view object
  };

  const AXES = ["axial", "coronal", "sagittal"];
  // number of slices per axis from volume shape [slices, rows, cols]
  const countFor = (axis) => ({ axial: state.meta.slices, coronal: state.meta.rows, sagittal: state.meta.cols }[axis]);

  /* ---------- toast ---------- */
  let toastTimer;
  function toast(msg, isErr = false) {
    const t = $("#toast");
    t.textContent = msg; t.className = "toast show" + (isErr ? " error" : "");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = "toast"), 3000);
  }

  /* ---------- view setup ---------- */
  function makeView(el) {
    const axis = el.dataset.axis;
    const canvas = $("canvas", el);
    const v = {
      axis, el, canvas, ctx: canvas.getContext("2d"),
      slider: $(".slice-slider", el), label: $(".view-overlay-text", el),
      index: 0, zoom: 1, panX: 0, panY: 0,
      img: null, heat: null, reqId: 0, dirty: true,
    };
    v.slider.addEventListener("input", () => setIndex(v, +v.slider.value));
    const body = $(".view-body", el);

    body.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (!state.sid) return;
      if (e.ctrlKey) { v.zoom = Math.min(10, Math.max(0.3, v.zoom * (e.deltaY < 0 ? 1.12 : 0.9))); draw(v); }
      else setIndex(v, v.index + (e.deltaY > 0 ? 1 : -1));
    }, { passive: false });

    let drag = null;
    body.addEventListener("mousedown", (e) => {
      if (!state.sid) return;
      drag = { x: e.clientX, y: e.clientY, btn: e.button, wc: state.wc, ww: state.ww, px: v.panX, py: v.panY };
    });
    body.addEventListener("contextmenu", (e) => e.preventDefault());
    window.addEventListener("mousemove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (drag.btn === 0) {
        const range = state.meta.max - state.meta.min || 1;
        state.wc = drag.wc + dx * range / 400;
        state.ww = Math.max(1, drag.ww + dy * range / 200);
        syncWL(); refreshAll(true);
      } else {
        v.panX = drag.px + dx; v.panY = drag.py + dy; draw(v);
      }
    });
    window.addEventListener("mouseup", () => (drag = null));
    body.addEventListener("dblclick", () => toggleMax(el));
    new ResizeObserver(() => draw(v)).observe(body);
    return v;
  }

  function toggleMax(el) {
    const grid = $("#viewers");
    const isMax = el.classList.contains("max");
    $$(".view", grid).forEach((x) => x.classList.remove("max"));
    grid.classList.toggle("single", !isMax);
    if (!isMax) el.classList.add("max");
    Object.values(state.views).forEach(draw);
  }

  function setIndex(v, i) {
    const n = countFor(v.axis);
    v.index = Math.max(0, Math.min(n - 1, i));
    v.slider.value = v.index;
    $("#idx-" + v.axis).textContent = `${v.index + 1} / ${n}`;
    fetchSlice(v);
  }

  /* ---------- fetching ---------- */
  let wlTimer;
  function refreshAll(debounce = false) {
    clearTimeout(wlTimer);
    const go = () => Object.values(state.views).forEach((v) => fetchSlice(v, false));
    debounce ? (wlTimer = setTimeout(go, 60)) : go();
  }

  function fetchSlice(v, withHeat = true) {
    if (!state.sid) return;
    const id = ++v.reqId;
    const wcq = state.invert ? -state.wc : state.wc;  // crude invert: flip window
    const base = `/api/series/${state.sid}/slice/${v.axis}/${v.index}?wc=${state.wc}&ww=${state.ww}&t=${id}`;
    const img = new Image();
    img.onload = () => { if (id !== v.reqId) return; v.img = img; draw(v); };
    img.src = base;
    if (withHeat && state.overlay) {
      const h = new Image();
      h.onload = () => { if (id !== v.reqId) return; v.heat = h; draw(v); };
      h.src = `/api/series/${state.sid}/heatmap/${v.axis}/${v.index}?t=${id}`;
    } else if (!state.overlay) v.heat = null;
  }

  /* ---------- drawing ---------- */
  function draw(v) {
    const body = v.canvas.parentElement;
    const W = body.clientWidth, H = body.clientHeight;
    if (!W || !H) return;
    if (v.canvas.width !== W || v.canvas.height !== H) { v.canvas.width = W; v.canvas.height = H; }
    const ctx = v.ctx;
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
    if (!v.img) return;
    const fit = Math.min(W / v.img.width, H / v.img.height) * v.zoom;
    const dw = v.img.width * fit, dh = v.img.height * fit;
    const x = (W - dw) / 2 + v.panX, y = (H - dh) / 2 + v.panY;
    ctx.imageSmoothingEnabled = true;
    if (state.invert) ctx.filter = "invert(1)";
    ctx.drawImage(v.img, x, y, dw, dh);
    ctx.filter = "none";
    if (v.heat && state.overlay && state.showOverlay) {
      ctx.globalAlpha = state.opacity;
      ctx.drawImage(v.heat, x, y, dw, dh);
      ctx.globalAlpha = 1;
    }
    // active finding crosshair
    const f = state.activeFinding;
    if (f) {
      const [sz, sy, sx] = f.centroid;   // slice,row,col
      const map = {
        axial:    { i: sz, px: sx / state.meta.cols,  py: sy / state.meta.rows },
        coronal:  { i: sy, px: sx / state.meta.cols,  py: sz / state.meta.slices },
        sagittal: { i: sx, px: sy / state.meta.rows,  py: sz / state.meta.slices },
      }[v.axis];
      if (Math.abs(map.i - v.index) < 6) {
        const cx = x + map.px * dw, cy = y + map.py * dh;
        ctx.strokeStyle = "#ffeb3b"; ctx.lineWidth = 1.5; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.arc(cx, cy, 18, 0, Math.PI * 2); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#ffeb3b"; ctx.font = "11px sans-serif";
        const txt = `#${f.id} ${f.label}`, tw = ctx.measureText(txt).width;
        ctx.fillText(txt, cx + 22 + tw > W - 6 ? cx - 22 - tw : cx + 22, cy + 4);
      }
    }
    v.label.textContent = `WC ${state.wc.toFixed(0)}  WW ${state.ww.toFixed(0)}  Zoom ${(v.zoom * 100).toFixed(0)}%`;
  }

  /* ---------- window / level ---------- */
  function syncWL() {
    const m = state.meta; if (!m) return;
    const range = m.max - m.min || 1;
    $("#wc").value = ((state.wc - m.min) / range) * 100;
    $("#ww").value = (state.ww / range) * 100;
    $("#wcVal").textContent = state.wc.toFixed(0);
    $("#wwVal").textContent = state.ww.toFixed(0);
  }
  $("#wc").addEventListener("input", (e) => { const m = state.meta; if (!m) return; state.wc = m.min + (e.target.value / 100) * (m.max - m.min); syncWL(); refreshAll(true); });
  $("#ww").addEventListener("input", (e) => { const m = state.meta; if (!m) return; state.ww = Math.max(1, (e.target.value / 100) * (m.max - m.min)); syncWL(); refreshAll(true); });
  $$(".chip[data-preset]").forEach((b) => b.addEventListener("click", () => {
    const m = state.meta; if (!m) return;
    const r = m.max - m.min;
    const p = b.dataset.preset;
    if (p === "invert") { state.invert = !state.invert; Object.values(state.views).forEach(draw); return; }
    if (p === "default") { state.wc = m.default_wc; state.ww = m.default_ww; }
    if (p === "soft") { state.wc = m.min + r * 0.35; state.ww = r * 0.5; }
    if (p === "bone") { state.wc = m.min + r * 0.65; state.ww = r * 0.9; }
    syncWL(); refreshAll();
  }));
  $("#resetViewBtn").addEventListener("click", () => Object.values(state.views).forEach((v) => { v.zoom = 1; v.panX = v.panY = 0; draw(v); }));
  $("#layoutBtn").addEventListener("click", () => toggleMax($(".view[data-axis=axial]")));

  $("#overlayToggle").addEventListener("change", (e) => { state.showOverlay = e.target.checked; Object.values(state.views).forEach(draw); });
  $("#opacity").addEventListener("input", (e) => { state.opacity = e.target.value / 100; $("#opVal").textContent = e.target.value + "%"; Object.values(state.views).forEach(draw); });

  /* ---------- loading series ---------- */
  async function loadSeries(meta) {
    state.sid = meta.series_id; state.meta = meta;
    state.wc = meta.default_wc; state.ww = meta.default_ww;
    state.overlay = false; state.result = null; state.activeFinding = null; state.invert = false;
    $("#overlayToggle").disabled = true;
    $("#analyzeBtn").disabled = false; $("#reportBtn").disabled = true;
    $("#findings").innerHTML = '<p class="muted">No analysis run yet.</p>';
    $("#findingCount").textContent = "";
    $("#summaryStatus").textContent = "Idle";
    $("#summaryBody").innerHTML = `<div class="placeholder"><div class="big">&#129504;</div><p>Series loaded (${meta.slices} slices).<br>Click <b>Run AI Analysis</b> to start.</p></div>`;

    const sp = meta.spacing.map((x) => x.toFixed(2)).join(" × ");
    $("#metaTable").innerHTML = `
      <tr><td>Patient</td><td>${meta.patient_name}</td></tr>
      <tr><td>Patient ID</td><td>${meta.patient_id}</td></tr>
      <tr><td>Modality</td><td>${meta.modality}</td></tr>
      <tr><td>Study date</td><td>${meta.study_date}</td></tr>
      <tr><td>Series</td><td>${meta.series_description}</td></tr>
      <tr><td>Dimensions</td><td>${meta.cols} × ${meta.rows} × ${meta.slices}</td></tr>
      <tr><td>Spacing (mm)</td><td>${sp}</td></tr>
      <tr><td>Bits stored</td><td>${meta.bits}</td></tr>
      <tr><td>Source</td><td>${meta.source}</td></tr>`;
    syncWL();
    AXES.forEach((axis) => {
      const v = state.views[axis];
      const n = countFor(axis);
      v.slider.max = n - 1; v.slider.disabled = false;
      v.zoom = 1; v.panX = v.panY = 0; v.heat = null;
      setIndex(v, Math.floor(n / 2));
    });
    toast(`Loaded ${meta.slices} slices`);
  }

  $("#fileInput").addEventListener("change", async (e) => {
    const files = [...e.target.files]; if (!files.length) return;
    const fd = new FormData(); files.forEach((f) => fd.append("files", f, f.name));
    toast(`Uploading ${files.length} file(s)...`);
    try {
      const r = await fetch("/api/upload", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      loadSeries(j);
    } catch (err) { toast("Upload failed: " + err.message, true); }
    e.target.value = "";
  });

  $("#demoBtn").addEventListener("click", async () => {
    toast("Loading demo dataset...");
    try {
      const r = await fetch("/api/demo", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      loadSeries(j);
    } catch (err) { toast("Demo load failed: " + err.message, true); }
  });

  /* ---------- analysis ---------- */
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function runProgress(promise) {
    const modal = $("#progressModal"), steps = $$("#steps li"), fill = $("#barFill"), txt = $("#progressText");
    steps.forEach((s) => (s.className = ""));
    fill.style.width = "0%"; modal.classList.add("show");
    const durations = [500, 700, 800, 1800, 700, 500];
    let pct = 0;
    for (let i = 0; i < steps.length; i++) {
      steps[i].classList.add("active");
      const target = ((i + 1) / steps.length) * 100;
      const t0 = performance.now();
      while (performance.now() - t0 < durations[i]) {
        pct = Math.min(target, pct + 1.5);
        fill.style.width = pct + "%"; txt.textContent = Math.round(pct) + "%";
        await sleep(30);
      }
      if (i === 3) await promise;      // make sure backend finished before "post-processing"
      steps[i].classList.remove("active"); steps[i].classList.add("done");
    }
    fill.style.width = "100%"; txt.textContent = "100%";
    await sleep(350);
    modal.classList.remove("show");
  }

  $("#analyzeBtn").addEventListener("click", async () => {
    if (!state.sid) return;
    $("#analyzeBtn").disabled = true;
    $("#summaryStatus").textContent = "Running...";
    const req = fetch(`/api/series/${state.sid}/analyze`, { method: "POST" }).then(async (r) => {
      const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j;
    });
    try {
      await runProgress(req.catch(() => null));
      const result = await req;
      showResult(result);
    } catch (err) {
      $("#progressModal").classList.remove("show");
      toast("Analysis failed: " + err.message, true);
      $("#summaryStatus").textContent = "Error";
    }
    $("#analyzeBtn").disabled = false;
  });

  function showResult(result) {
    state.result = result; state.overlay = true;
    $("#overlayToggle").disabled = false; $("#overlayToggle").checked = true; state.showOverlay = true;
    $("#reportBtn").disabled = false;
    const s = result.summary;
    $("#summaryStatus").textContent = "Complete";
    const risk = Math.round(s.overall_risk * 100);
    const col = s.abnormal ? "var(--danger)" : "var(--ok)";
    $("#summaryBody").innerHTML = `
      <div class="verdict ${s.abnormal ? "abnormal" : "normal"}">
        <div class="ring" style="background: conic-gradient(${col} ${risk}%, #2a2f3a 0)"><span>${risk}%</span></div>
        <div>
          <h4>${s.abnormal ? "Abnormality detected" : "No abnormality detected"}</h4>
          <p>${s.impression}</p>
        </div>
      </div>
      <div class="stats">
        <div class="stat"><div class="v">${s.num_findings}</div><div class="l">Findings</div></div>
        <div class="stat"><div class="v">${s.fetal_volume_cm3}</div><div class="l">Fetal vol (cm³)</div></div>
        <div class="stat"><div class="v">${s.inference_time_s}s</div><div class="l">Inference</div></div>
      </div>
      <p class="muted small" style="margin:10px 0 0">${s.model} v${s.version} · threshold ${s.threshold} · ${s.analysed_at}</p>`;

    $("#findingCount").textContent = result.findings.length;
    const box = $("#findings");
    if (!result.findings.length) { box.innerHTML = '<p class="muted">No suspicious regions found.</p>'; }
    else box.innerHTML = result.findings.map((f) => `
      <div class="finding" data-id="${f.id}">
        <div class="top"><span class="label">#${f.id} ${f.label}</span><span class="sev ${f.severity}">${f.severity}</span></div>
        <div class="desc">${f.description}</div>
        <div class="conf"><div style="width:${f.confidence * 100}%"></div></div>
        <div class="meta"><span>${f.region}</span><span>conf ${(f.confidence * 100).toFixed(1)}%</span></div>
        <div class="meta"><span>Vol ${f.volume_mm3} mm³</span><span>${f.extent_mm.join(" × ")} mm</span></div>
      </div>`).join("");
    $$(".finding", box).forEach((el) => el.addEventListener("click", () => {
      const f = result.findings.find((x) => x.id == el.dataset.id);
      state.activeFinding = f;
      $$(".finding", box).forEach((x) => x.classList.toggle("active", x === el));
      const [sz, sy, sx] = f.centroid;
      setIndex(state.views.axial, sz); setIndex(state.views.coronal, sy); setIndex(state.views.sagittal, sx);
    }));
    refreshAll();
    if (result.findings.length) $(".finding", box).click();
    toast(s.abnormal ? `${s.num_findings} finding(s) detected` : "Analysis complete: no abnormality");
  }

  $("#reportBtn").addEventListener("click", () => { if (state.sid) window.open(`/report/${state.sid}`, "_blank"); });

  /* ---------- init ---------- */
  $$(".view[data-axis]").forEach((el) => (state.views[el.dataset.axis] = makeView(el)));
  // ?demo=1 auto-loads the demo dataset, &analyze=1 also runs the analysis
  const qs = new URLSearchParams(location.search);
  if (qs.get("demo")) {
    $("#demoBtn").click();
    if (qs.get("analyze")) { const t = setInterval(() => { if (state.sid) { clearInterval(t); $("#analyzeBtn").click(); } }, 200); }
  }
  window.addEventListener("keydown", (e) => {
    if (!state.sid) return;
    const v = state.views.axial;
    if (e.key === "ArrowUp" || e.key === "ArrowRight") setIndex(v, v.index + 1);
    if (e.key === "ArrowDown" || e.key === "ArrowLeft") setIndex(v, v.index - 1);
  });
})();
