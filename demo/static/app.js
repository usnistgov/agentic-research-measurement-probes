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
      appendLog(type, `${stage}: ${JSON.stringify(data)}`);
    }
    return;
  }

  appendLog(type, summarize(type, stage, data || {}));

  switch (type) {
    case "stage_start":
      activateStage(stage);
      if (stage === "scanner" && data.total_chunks) {
        const prog = document.getElementById("scanner-progress");
        prog.style.display = "block";
        updateScannerProgress(0, data.total_chunks, 0);
      }
      break;

    case "stage_complete":
      if (stage === "scanner") {
        document.getElementById("scanner-progress").style.display = "none";
      }
      completeStage(stage, data);
      animateConnectorAfter(stage);
      break;

    case "section_start":
      activateStage("section_writer");
      setSectionCardState(data.order, data.section_title, "writing");
      break;

    case "section_complete":
      setSectionCardState(data.order, data.section_title, "done");
      break;

    case "probe_start":
      activateStage("probes");
      setSectionCardState(findOrderByTitle(data.section_title), data.section_title, "probing");
      break;

    case "probe_complete":
      completeStage("probes");
      renderProbeScores(data.section_title, data.results);
      break;

    case "pipeline_complete":
      document.getElementById("run-btn").disabled = false;
      break;

    case "error":
      document.getElementById("run-btn").disabled = false;
      break;
  }
}

// ---- Stage state management ----

const CONNECTOR_MAP = {
  manager: "manager-scanner",
  scanner: "scanner-synthesis",
  synthesis_manager: "synthesis-writer",
  section_writer: "writer-probes",
  probes: "probes-assembly",
};

function activateStage(stage) {
  const el = document.querySelector(`.stage[data-stage="${stage}"]`);
  if (!el) return;
  el.classList.remove("pending", "completed");
  el.classList.add("active");
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
        detail.innerHTML = "<strong>Report outline:</strong><ol>" +
          data.sections.map((s) => `<li>${escHtml(s)}</li>`).join("") +
          "</ol>";
        createSectionCards(data.sections);
      }
      break;

    case "assembly":
      detail.innerHTML = `Report assembled (<strong>${(data.report_length / 1000).toFixed(1)}k</strong> characters)`;
      break;
  }
}

function animateConnectorAfter(stage) {
  const key = CONNECTOR_MAP[stage];
  if (!key) return;
  const conn = document.querySelector(`.connector[data-connector="${key}"]`);
  if (conn) {
    conn.classList.add("data-flowing");
    setTimeout(() => conn.classList.remove("data-flowing"), 2000);
  }
}

// ---- Scanner progress ----
function updateScannerProgress(completed, total, relevant) {
  const fill = document.getElementById("scanner-fill");
  const text = document.getElementById("scanner-text");
  const pct = total > 0 ? (completed / total) * 100 : 0;
  fill.style.width = `${pct}%`;
  text.textContent = `${completed} / ${total} chunks (${relevant} relevant)`;
}

// ---- Section cards ----
let sectionTitles = [];

function createSectionCards(titles) {
  sectionTitles = titles;
  const container = document.getElementById("section-cards");
  container.innerHTML = "";
  titles.forEach((title, i) => {
    const card = document.createElement("div");
    card.className = "section-card";
    card.dataset.order = String(i + 1);
    card.dataset.title = title;
    card.textContent = title;
    card.title = title;
    container.appendChild(card);
  });
}

function findOrderByTitle(title) {
  const idx = sectionTitles.indexOf(title);
  return idx >= 0 ? idx + 1 : null;
}

function setSectionCardState(order, title, state) {
  if (!order && title) order = findOrderByTitle(title);
  if (!order) return;
  const card = document.querySelector(`.section-card[data-order="${order}"]`);
  if (!card) return;
  card.classList.remove("writing", "probing", "done");
  card.classList.add(state);
}

function renderProbeScores(sectionTitle, results) {
  const order = findOrderByTitle(sectionTitle);
  if (!order) return;
  const card = document.querySelector(`.section-card[data-order="${order}"]`);
  if (!card) return;

  const existing = card.querySelector(".probe-badges");
  if (existing) existing.remove();

  const badges = document.createElement("div");
  badges.className = "probe-badges";

  for (const [name, result] of Object.entries(results)) {
    const score = result.mean_score || 0;
    const badge = document.createElement("span");
    const shortName = name.replace("run_", "").replace("_probe", "").substring(0, 4).toUpperCase();
    badge.textContent = `${shortName}: ${score.toFixed(2)}`;
    badge.className = "probe-badge " + (score >= 0.7 ? "good" : score >= 0.4 ? "warn" : "bad");
    badge.title = `${name}: ${score.toFixed(3)}`;
    badges.appendChild(badge);
  }

  card.style.whiteSpace = "normal";
  card.style.maxWidth = "none";
  card.appendChild(badges);
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

// ---- Utilities ----
function escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function resetPipeline() {
  document.querySelectorAll(".stage").forEach((el) => {
    el.classList.remove("active", "completed");
    el.classList.add("pending");
  });
  document.querySelectorAll(".connector").forEach((el) => {
    el.classList.remove("data-flowing");
  });
  document.getElementById("scanner-progress").style.display = "none";
  document.getElementById("scanner-fill").style.width = "0%";
  document.getElementById("scanner-prefilter-note").textContent = "";
  document.getElementById("section-cards").innerHTML = "";
  document.getElementById("log-panel").innerHTML = "";
  document.querySelectorAll(".stage-detail").forEach((el) => { el.innerHTML = ""; });
  sectionTitles = [];
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
