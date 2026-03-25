// ---- WebSocket connection ----
let ws = null;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => appendLog("system", "Connected to server");
  ws.onclose = () => appendLog("system", "Disconnected from server");
  ws.onerror = () => appendLog("error", "WebSocket error");

  ws.onmessage = (evt) => {
    const event = JSON.parse(evt.data);
    dispatch(event);
  };
}

// ---- Event summary formatter ----
function summarize(type, stage, data) {
  switch (type) {
    case "stage_start":
      switch (stage) {
        case "manager":           return "Manager: decomposing question into sub-questions";
        case "scanner":           return `Scanner: evaluating ${data.total_chunks} chunks × ${data.num_questions} questions`;
        case "synthesis_manager": return "Synthesis manager: planning report outline";
        case "assembly":          return "Assembly: building final report";
        default:                  return `${stage}: starting`;
      }
    case "stage_complete":
      switch (stage) {
        case "manager":           return `Manager done: ${data.sub_questions?.length ?? "?"} sub-questions`;
        case "scanner":           return `Scanner done: ${data.relevant_count} relevant → ${data.evidence_count} evidence items`;
        case "synthesis_manager": return `Outline ready: ${data.num_sections} sections`;
        case "assembly":          return `Report assembled (${((data.report_length || 0) / 1000).toFixed(1)}k chars)`;
        default:                  return `${stage}: complete`;
      }
    case "section_start":
      return `Writing section ${data.order}/${data.total_sections}: ${data.section_title}`;
    case "section_complete":
      return `Section done: "${data.section_title}" (${data.citations_used?.length ?? 0} citations)`;
    case "probe_start":
      return `Probing: "${data.section_title}"`;
    case "probe_metric_start":
      return `  Running ${data.probe_name} probe on "${data.section_title}" (${data.total_citations} citations)`;
    case "probe_metric_complete":
      return `  ${data.probe_name}: ${(data.mean_score || 0).toFixed(2)}`;
    case "probe_complete": {
      const scores = Object.entries(data.results || {})
        .map(([name, r]) => `${name.replace("run_", "").replace("_probe", "")}: ${(r.mean_score || 0).toFixed(2)}`)
        .join(", ");
      return `Probes done: "${data.section_title}"${scores ? " — " + scores : ""}`;
    }
    case "scanner_progress":
      return `Scanner: ${data.completed}/${data.total} chunks (${data.relevant_so_far} relevant)`;
    case "pipeline_complete":
      return "Pipeline complete";
    case "error":
      return `Error: ${data.message || "unknown"}`;
    default:
      return `${stage}: ${type}`;
  }
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
    if (data.completed % 25 === 0 || data.completed === data.total) {
      appendLog(type, summarize(type, stage, data));
    }
    return;
  }

  if (type === "probe_metric_progress") return;

  appendLog(type, summarize(type, stage, data || {}));

  switch (type) {
    case "stage_start":
      if (stage === "assembly") completeStage("probes", {});
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
      waitStage("probes");
      scrollToActive(document.querySelector(`.section-writer-stage[data-section-order="${data.order}"]`));
      break;

    case "section_complete":
      completeSectionWriterStage(data.order);
      animateConnector("writer-probes");
      break;

    case "probe_start":
      probeCount++;
      if (probeCount === 1) activateStage("probes");
      else pulseActive("probes");
      addProbeSectionGroup(data.section_title);
      scrollToActive(document.querySelector(`.probe-group[data-title="${CSS.escape(data.section_title)}"]`));
      break;

    case "probe_metric_start":
      activateProbeMetric(data.section_title, data.probe_name, data.total_citations);
      break;

    case "probe_metric_progress":
      updateProbeMetricProgress(data.section_title, data.probe_name, data.completed, data.total);
      break;

    case "probe_metric_complete":
      completeProbeMetric(data.section_title, data.probe_name, data.mean_score);
      break;

    case "probe_complete":
      completeProbeSectionGroup(data.section_title);
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

// Pulse an already-active stage to show it's being invoked again.
function pulseActive(stage) {
  const el = document.querySelector(`.stage[data-stage="${stage}"]`);
  if (!el) return;
  el.classList.remove('flash-pulse');
  void el.offsetWidth; // force reflow to restart animation
  el.classList.add('flash-pulse');
  setTimeout(() => el.classList.remove('flash-pulse'), 2500);
}

// ---- Stage state management ----

const CONNECTOR_MAP = {
  manager: "manager-scanner",
  scanner: "scanner-synthesis",
  synthesis_manager: "synthesis-writer",
  probes: "probes-assembly",
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
        // data.sections is now [{title, order}, ...]
        const titles = data.sections.map((s) => typeof s === "string" ? s : s.title);
        const orders = data.sections.map((s) => typeof s === "string" ? null : s.order);
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
let sectionOrderMap = {}; // order -> index for lookup
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

  // Show the tree container now that we have branches
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

// ---- Per-section probe groups (section title + 3 child metrics) ----

const PROBE_METRICS = [
  { key: "citation_faithfulness", label: "Faithfulness" },
  { key: "citation_completeness", label: "Completeness" },
  { key: "citation_sufficiency", label: "Sufficiency" },
];

function addProbeSectionGroup(sectionTitle) {
  const container = document.getElementById("probe-section-groups");
  const group = document.createElement("div");
  group.className = "probe-group probing";
  group.dataset.title = sectionTitle;

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
    m.innerHTML = `<span class="probe-metric-icon"></span><span class="probe-metric-name">${label}</span><span class="probe-metric-progress"></span><span class="probe-metric-score"></span>`;
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

  const progEl = el.querySelector(".probe-metric-progress");
  if (progEl && totalCitations > 0) {
    progEl.innerHTML = `<span class="probe-progress-bar"><span class="probe-progress-fill" style="width:0%"></span></span><span class="probe-progress-text">0/${totalCitations}</span>`;
  }
}

function updateProbeMetricProgress(sectionTitle, probeName, completed, total) {
  const el = _findProbeMetric(sectionTitle, probeName);
  if (!el) return;
  const fill = el.querySelector(".probe-progress-fill");
  const text = el.querySelector(".probe-progress-text");
  if (fill) fill.style.width = `${total > 0 ? (completed / total) * 100 : 0}%`;
  if (text) text.textContent = `${completed}/${total}`;
}

function completeProbeMetric(sectionTitle, probeName, score) {
  const el = _findProbeMetric(sectionTitle, probeName);
  if (!el) return;
  el.classList.remove("pending", "active");
  el.classList.add("completed");

  // Replace progress bar with score
  const progEl = el.querySelector(".probe-metric-progress");
  if (progEl) progEl.innerHTML = "";

  const scoreEl = el.querySelector(".probe-metric-score");
  if (scoreEl && score != null) {
    scoreEl.textContent = score.toFixed(2);
    scoreEl.style.color = score >= 0.7 ? "#3fb950" : score >= 0.4 ? "#d29922" : "#f85149";
  }
}

function completeProbeSectionGroup(sectionTitle) {
  const group = document.querySelector(`.probe-group[data-title="${CSS.escape(sectionTitle)}"]`);
  if (!group) return;
  group.classList.remove("probing");
  group.classList.add("done");
}

// ---- Log panel ----
function appendLog(type, message) {
  const panel = document.getElementById("log-panel");
  const entry = document.createElement("div");
  entry.className = "log-entry";

  const now = new Date();
  const time = now.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

  let typeClass = "progress";
  if (type.includes("start") || type === "system") typeClass = "start";
  else if (type.includes("complete")) typeClass = "complete";
  else if (type === "error") typeClass = "error";

  entry.innerHTML = `<span class="log-time">${time}</span> <span class="log-type ${typeClass}">${escHtml(type)}</span> ${escHtml(message)}`;
  panel.appendChild(entry);
  panel.scrollTop = panel.scrollHeight;
}

// ---- Auto-scroll to keep active elements visible ----
function scrollToActive(el) {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---- Utilities ----
function escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
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
  document.getElementById("log-panel").innerHTML = "";
  document.querySelectorAll(".stage-detail").forEach((el) => { el.innerHTML = ""; });
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
    appendLog("error", "Not connected to server");
    document.getElementById("run-btn").disabled = false;
  }
});

// ---- Initialize ----
connect();
