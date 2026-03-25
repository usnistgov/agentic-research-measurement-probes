// ---- WebSocket connection ----
let ws = null;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {};
  ws.onclose = () => {};
  ws.onerror = () => {};

  ws.onmessage = (evt) => {
    const event = JSON.parse(evt.data);
    dispatch(event);
  };
}

// ---- Event dispatcher ----
function dispatch(event) {
  const { type, stage, data } = event;

  if (type === "server_config") {
    document.getElementById("model").value = data.model || "";
    return;
  }

  if (type === "scanner_prefilter") {
    const pct = ((data.kept / data.total) * 100).toFixed(1);
    const note = document.getElementById("scanner-prefilter-note");
    if (note) note.textContent = `BM25 prefilter: ${data.kept} / ${data.total} chunks kept (${pct}%)`;
    updateScannerProgress(0, data.kept, 0);
    return;
  }

  if (type === "scanner_progress") {
    updateScannerProgress(data.completed, data.total, data.relevant_so_far);
    return;
  }

  if (type === "probe_metric_progress") {
    updateProbeMetricProgress(data.section_title, data.probe_name, data.completed, data.total);
    return;
  }

  switch (type) {
    case "stage_start":
      if (stage === "assembly") {
        // All probes are done when assembly starts
      }
      activateStage(stage);
      if (stage === "scanner" && data.total_chunks) {
        const prog = document.getElementById("scanner-progress");
        prog.style.display = "block";
        updateScannerProgress(0, data.total_chunks, 0);
      }
      scrollToActive(document.querySelector(`.stage[data-stage="${stage}"]`));
      break;

    case "stage_complete":
      if (stage === "scanner") {
        document.getElementById("scanner-progress").style.display = "none";
      }
      completeStage(stage, data);
      animateConnectorAfter(stage);
      break;

    case "section_start":
      activateSectionWriterStage(data.order);
      scrollToActive(document.querySelector(`.section-writer-stage[data-section-order="${data.order}"]`));
      break;

    case "section_complete":
      completeSectionWriterStage(data.order);
      break;

    case "probe_start":
      probeCount++;
      addProbeSectionGroup(data.section_title, data.order);
      drawConnectionLine(data.order, data.section_title);
      scrollToActive(document.querySelector(`.probe-group[data-title="${CSS.escape(data.section_title)}"]`));
      break;

    case "probe_metric_start":
      activateProbeMetric(data.section_title, data.probe_name, data.total_citations);
      scrollProbesColumn(data.section_title, data.probe_name);
      break;

    case "probe_metric_complete":
      completeProbeMetric(data.section_title, data.probe_name, data.mean_score, data.first_failure);
      scrollProbesColumn(data.section_title, data.probe_name);
      break;

    case "probe_complete":
      completeProbeSectionGroup(data.section_title);
      removeConnectionLine(data.section_title);
      animateConnector("writer-assembly");
      break;

    case "pipeline_complete":
      document.getElementById("run-btn").disabled = false;
      break;

    case "error":
      document.getElementById("run-btn").disabled = false;
      break;
  }
}

// ---- Stage flash helpers ----

function pulseActive(stage) {
  const el = document.querySelector(`.stage[data-stage="${stage}"]`);
  if (!el) return;
  el.classList.remove('flash-pulse');
  void el.offsetWidth;
  el.classList.add('flash-pulse');
  setTimeout(() => el.classList.remove('flash-pulse'), 2500);
}

// ---- Stage state management ----

const CONNECTOR_MAP = {
  manager: "manager-scanner",
  scanner: "scanner-synthesis",
  synthesis_manager: "synthesis-writer",
};

function activateStage(stage) {
  const el = document.querySelector(`.stage[data-stage="${stage}"]`);
  if (!el) return;
  el.classList.remove("pending", "completed", "waiting");
  el.classList.add("active");
}

function waitStage(stage) {
  const el = document.querySelector(`.stage[data-stage="${stage}"]`);
  if (!el || el.classList.contains("pending")) return;
  el.classList.remove("active", "completed");
  el.classList.add("waiting");
}

function completeStage(stage, data) {
  const el = document.querySelector(`.stage[data-stage="${stage}"]`);
  if (!el) return;
  el.classList.remove("pending", "active");
  el.classList.add("completed");

  const detail = document.getElementById(`${stage}-detail`);
  if (!detail || !data) return;

  switch (stage) {
    case "manager":
      if (data.sub_questions) {
        detail.innerHTML = "<strong>Sub-questions:</strong><ol>" +
          data.sub_questions.map((q) => `<li>${escHtml(q)}</li>`).join("") +
          "</ol>";
      }
      break;

    case "scanner":
      detail.innerHTML =
        `<strong>${data.evidence_count}</strong> evidence items from ` +
        `<strong>${data.relevant_count}</strong> relevant judgments ` +
        `across <strong>${data.total_chunks}</strong> chunks`;
      break;

    case "synthesis_manager":
      if (data.sections) {
        const titles = data.sections.map((s) => typeof s === "string" ? s : s.title);
        detail.innerHTML = "<strong>Report outline:</strong><ol>" +
          titles.map((t) => `<li>${escHtml(t)}</li>`).join("") +
          "</ol>";
        createSectionWriterStages(data.sections);
      }
      break;

    case "assembly":
      detail.innerHTML = `Report assembled (<strong>${(data.report_length / 1000).toFixed(1)}k</strong> characters)`;
      break;
  }
}

function animateConnector(key) {
  const conn = document.querySelector(`.connector[data-connector="${key}"]`);
  if (!conn) return;
  conn.classList.add("data-flowing");
  setTimeout(() => conn.classList.remove("data-flowing"), 3000);
}

function animateConnectorAfter(stage) {
  const key = CONNECTOR_MAP[stage];
  if (key) animateConnector(key);
}

// ---- Scanner progress ----
function updateScannerProgress(completed, total, relevant) {
  const fill = document.getElementById("scanner-fill");
  const text = document.getElementById("scanner-text");
  const pct = total > 0 ? (completed / total) * 100 : 0;
  fill.style.width = `${pct}%`;
  text.textContent = `${completed} / ${total} chunks (${relevant} relevant)`;
}

// ---- Section writer stages (tree branches) ----
let sectionOrderMap = {};
let probeCount = 0;

function createSectionWriterStages(sections) {
  sectionOrderMap = {};
  const container = document.getElementById("section-writer-stages");
  container.innerHTML = "";
  sections.forEach((sec, i) => {
    const title = typeof sec === "string" ? sec : sec.title;
    const order = typeof sec === "string" ? i + 1 : sec.order;
    sectionOrderMap[order] = i;

    const el = document.createElement("div");
    el.className = "section-writer-stage";
    el.dataset.sectionOrder = String(order);
    el.innerHTML = `<span class="section-writer-order">${order}</span><span class="section-writer-title">Writing: ${escHtml(title)}</span>`;
    container.appendChild(el);
  });

  document.getElementById("tree-container").style.display = "block";
}

function activateSectionWriterStage(order) {
  const el = document.querySelector(`.section-writer-stage[data-section-order="${order}"]`);
  if (!el) return;
  el.classList.remove("completed");
  el.classList.add("active");
}

function completeSectionWriterStage(order) {
  const el = document.querySelector(`.section-writer-stage[data-section-order="${order}"]`);
  if (!el) return;
  el.classList.remove("active");
  el.classList.add("completed");
}

// ---- Per-section probe groups (right column) ----

const PROBE_METRICS = [
  { key: "citation_faithfulness", label: "Faithfulness" },
  { key: "citation_completeness", label: "Completeness" },
  { key: "citation_sufficiency", label: "Sufficiency" },
];

function addProbeSectionGroup(sectionTitle, order) {
  const container = document.getElementById("probe-section-groups");
  const group = document.createElement("div");
  group.className = "probe-group probing";
  group.dataset.title = sectionTitle;
  if (order != null) group.dataset.order = String(order);

  const header = document.createElement("div");
  header.className = "probe-group-header";
  header.innerHTML = `<span class="probe-group-spinner"></span><span class="probe-group-title">${escHtml(sectionTitle)}</span>`;
  group.appendChild(header);

  const metrics = document.createElement("div");
  metrics.className = "probe-group-metrics";
  for (const { key, label } of PROBE_METRICS) {
    const m = document.createElement("div");
    m.className = "probe-metric pending";
    m.dataset.probe = key;
    m.innerHTML = `<div class="probe-metric-header"><span class="probe-metric-icon"></span><span class="probe-metric-name">${label}</span><span class="probe-metric-count"></span><span class="probe-metric-score"></span></div><div class="probe-metric-progress"></div>`;
    metrics.appendChild(m);
  }
  group.appendChild(metrics);

  container.appendChild(group);
}

function _findProbeMetric(sectionTitle, probeName) {
  const group = document.querySelector(`.probe-group[data-title="${CSS.escape(sectionTitle)}"]`);
  if (!group) return null;
  return group.querySelector(`.probe-metric[data-probe="${probeName}"]`);
}

function activateProbeMetric(sectionTitle, probeName, totalCitations) {
  const el = _findProbeMetric(sectionTitle, probeName);
  if (!el) return;
  el.classList.remove("pending", "completed");
  el.classList.add("active");

  const countEl = el.querySelector(".probe-metric-count");
  if (countEl && totalCitations > 0) {
    countEl.textContent = `${totalCitations} citations`;
  }
}

function updateProbeMetricProgress(sectionTitle, probeName, completed, total) {
  // No-op: progress bar removed in favor of failure display
}

function completeProbeMetric(sectionTitle, probeName, score, firstFailure) {
  const el = _findProbeMetric(sectionTitle, probeName);
  if (!el) return;
  el.classList.remove("pending", "active");
  el.classList.add("completed");

  const scoreEl = el.querySelector(".probe-metric-score");
  if (scoreEl && score != null) {
    scoreEl.textContent = score.toFixed(2);
    scoreEl.style.color = score >= 0.7 ? "#3fb950" : score >= 0.4 ? "#d29922" : "#f85149";
  }

  // Show first failure verdict and rationale
  const progEl = el.querySelector(".probe-metric-progress");
  if (progEl) {
    if (firstFailure) {
      const verdictColor = firstFailure.score >= 0.7 ? "#d29922" : firstFailure.score >= 0.4 ? "#d29922" : "#f85149";
      progEl.innerHTML = `<div class="probe-failure-detail"><span class="probe-failure-verdict" style="color:${verdictColor}">${escHtml(firstFailure.verdict)}</span><span class="probe-failure-rationale">${escHtml(firstFailure.rationale)}</span></div>`;
    } else {
      progEl.innerHTML = "";
    }
  }
}

function scrollProbesColumn(sectionTitle, probeName) {
  const el = _findProbeMetric(sectionTitle, probeName);
  if (!el) return;
  const column = document.querySelector(".probes-column");
  if (!column) return;
  const elRect = el.getBoundingClientRect();
  const colRect = column.getBoundingClientRect();
  const offset = elRect.bottom - colRect.bottom;
  if (offset > 0) {
    column.scrollBy({ top: offset + 20, behavior: "smooth" });
  }
}

function completeProbeSectionGroup(sectionTitle) {
  const group = document.querySelector(`.probe-group[data-title="${CSS.escape(sectionTitle)}"]`);
  if (!group) return;
  group.classList.remove("probing");
  group.classList.add("done");
}

// ---- Connection lines between section writers (left) and probe groups (right) ----

const activeConnections = {};

function drawConnectionLine(order, sectionTitle) {
  const writerEl = document.querySelector(`.section-writer-stage[data-section-order="${order}"]`);
  const probeEl = document.querySelector(`.probe-group[data-title="${CSS.escape(sectionTitle)}"]`);
  if (!writerEl || !probeEl) return;

  const svg = document.getElementById("connection-lines");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
  line.classList.add("connection-line");
  line.dataset.title = sectionTitle;
  svg.appendChild(line);

  activeConnections[sectionTitle] = { order, line };
  updateConnectionLine(sectionTitle);
}

function updateConnectionLine(sectionTitle) {
  const conn = activeConnections[sectionTitle];
  if (!conn) return;

  const writerEl = document.querySelector(`.section-writer-stage[data-section-order="${conn.order}"]`);
  const probeEl = document.querySelector(`.probe-group[data-title="${CSS.escape(sectionTitle)}"]`);
  if (!writerEl || !probeEl) return;

  const wr = writerEl.getBoundingClientRect();
  const pr = probeEl.getBoundingClientRect();

  // Start from right edge of section writer, vertically centered
  const x1 = wr.right;
  const y1 = wr.top + wr.height / 2;
  // End at left edge of probe group, vertically centered
  const x2 = pr.left;
  const y2 = pr.top + pr.height / 2;

  // Bezier curve bowing right
  const cx = x1 + (x2 - x1) * 0.5;
  const d = `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`;
  conn.line.setAttribute("d", d);
}

function removeConnectionLine(sectionTitle) {
  const conn = activeConnections[sectionTitle];
  if (!conn) return;
  conn.line.remove();
  delete activeConnections[sectionTitle];
}

// Update connection line positions on scroll/resize
function updateAllConnectionLines() {
  for (const title of Object.keys(activeConnections)) {
    updateConnectionLine(title);
  }
}

window.addEventListener("scroll", updateAllConnectionLines, true);
window.addEventListener("resize", updateAllConnectionLines);

// ---- Utilities ----
function escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---- Auto-scroll to keep active elements visible ----
function scrollToActive(el) {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
}

function resetPipeline() {
  document.querySelectorAll(".stage").forEach((el) => {
    el.classList.remove("active", "completed", "waiting");
    el.classList.add("pending");
  });
  document.querySelectorAll(".connector").forEach((el) => {
    el.classList.remove("data-flowing");
  });
  document.getElementById("scanner-progress").style.display = "none";
  document.getElementById("scanner-fill").style.width = "0%";
  document.getElementById("scanner-prefilter-note").textContent = "";
  document.getElementById("section-writer-stages").innerHTML = "";
  document.getElementById("tree-container").style.display = "none";
  document.getElementById("probe-section-groups").innerHTML = "";
  document.querySelectorAll(".stage-detail").forEach((el) => { el.innerHTML = ""; });

  // Clear connection lines
  const svg = document.getElementById("connection-lines");
  svg.innerHTML = "";
  for (const key of Object.keys(activeConnections)) delete activeConnections[key];

  sectionOrderMap = {};
  probeCount = 0;
}

// ---- Form handler ----
document.getElementById("run-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const question = document.getElementById("question").value.trim();
  const corpusDir = document.getElementById("corpus-dir").value.trim();
  const model = document.getElementById("model").value.trim();
  if (!question || !corpusDir) return;

  resetPipeline();
  document.getElementById("run-btn").disabled = true;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: "start", question, corpus_dir: corpusDir, model }));
  } else {
    document.getElementById("run-btn").disabled = false;
  }
});

// ---- Initialize ----
connect();
