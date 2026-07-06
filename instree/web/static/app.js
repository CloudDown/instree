let scans = [];
let currentId = null;
let pollTimer = null;
let lastJobState = "idle";

const elSub = document.getElementById("header-sub");
const elBadge = document.getElementById("session-badge");
const elFooter = document.getElementById("footer-config");
const elJobPanel = document.getElementById("job-panel");
const elJobText = document.getElementById("job-text");
const elJobBar = document.getElementById("job-bar");
const elDate = document.getElementById("scan-date");
const elMeta = document.getElementById("scan-meta");
const elContent = document.getElementById("content");
const elHistory = document.getElementById("history-list");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const btnScan = document.getElementById("btn-scan");
const btnInit = document.getElementById("btn-init");
const btnFull = document.getElementById("btn-full");

function setButtonsDisabled(disabled) {
  btnScan.disabled = btnInit.disabled = btnFull.disabled = disabled;
}

async function fetchStatus() {
  return fetch("/api/status").then((r) => r.json());
}

async function loadScans() {
  scans = await fetch("/api/scans").then((r) => r.json());
  renderHistory();
  if (scans.length === 0) {
    elDate.textContent = "Aucun scan";
    elMeta.textContent = "Lance un scan ou une baseline";
    elContent.innerHTML = '<p class="empty">Pas encore de données.</p>';
    btnPrev.disabled = btnNext.disabled = true;
    return;
  }
  const target = currentId && scans.some((s) => s.id === currentId)
    ? currentId
    : scans[scans.length - 1].id;
  await showScan(target);
}

function renderHistory() {
  elHistory.innerHTML = [...scans].reverse().map((s) => {
    const active = s.id === currentId ? " active" : "";
    const changes = s.change_count > 0 ? `${s.change_count} Δ` : "—";
    return `<li><button type="button" class="history-item${active}" data-id="${s.id}">` +
      `<span class="h-id">#${s.id}</span>` +
      `<span class="h-date">${s.label}</span>` +
      `<span class="h-changes">${changes}</span>` +
      `</button></li>`;
  }).join("");

  elHistory.querySelectorAll(".history-item").forEach((btn) => {
    btn.onclick = () => showScan(Number(btn.dataset.id));
  });
}

async function showScan(id) {
  currentId = id;
  const [detail, neighbors] = await Promise.all([
    fetch(`/api/scans/${id}`).then((r) => r.json()),
    fetch(`/api/scans/${id}/neighbors`).then((r) => r.json()),
  ]);

  const scan = detail.scan;
  elDate.textContent = scan.label;
  elMeta.textContent =
    `@${scan.username} · ${scan.tracked_count}/${scan.following_count} · ` +
    `${neighbors.index + 1}/${neighbors.total}`;

  btnPrev.disabled = neighbors.prev_id == null;
  btnNext.disabled = neighbors.next_id == null;
  btnPrev.onclick = () => neighbors.prev_id && showScan(neighbors.prev_id);
  btnNext.onclick = () => neighbors.next_id && showScan(neighbors.next_id);

  renderHistory();
  renderDetail(detail);
}

function renderDetail(detail) {
  const scan = detail.scan;

  if (!detail.has_changes) {
    elContent.innerHTML =
      `<p class="empty">Aucun changement · ${scan.tracked_count} abonnements suivis.</p>`;
    return;
  }

  const oldC = detail.old_count != null ? detail.old_count : "?";
  const header =
    `@${scan.username} <span class="count">(${oldC} → ${scan.following_count})</span>`;
  const adds = detail.adds
    .map((c) => `<div class="change-line add">+ @${c.username}  ${escapeHtml(c.full_name)}</div>`)
    .join("");
  const counts = detail.counts
    .map(
      (c) =>
        `<div class="change-line count">~ @${c.username}  ` +
        `${c.old_count} → ${c.new_count} abonnements</div>`,
    )
    .join("");
  const removes = detail.removes
    .map((c) => `<div class="change-line remove">- @${c.username}  ${escapeHtml(c.full_name)}</div>`)
    .join("");

  elContent.innerHTML =
    `<section class="scan-block"><div class="scan-header">${header}</div>${adds}${counts}${removes}</section>`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderStatus(status) {
  const { session, config, job } = status;
  if (session.ok) {
    elBadge.textContent = `@${session.username}`;
    elBadge.className = "badge ok";
    elSub.textContent = `via ${session.source}`;
  } else {
    elBadge.textContent = "Hors ligne";
    elBadge.className = "badge err";
    elSub.textContent = session.error || "Session requise";
  }

  const nLabel = config.n > 0 ? config.n : "tous";
  elFooter.textContent =
    `${nLabel} abonnements suivis · planifié ${config.schedule_times.join(", ")}`;

  if (job.state === "running") {
    setButtonsDisabled(true);
    elJobPanel.classList.remove("hidden");
    elJobPanel.classList.remove("job-error");
    const pct = job.progress_total
      ? Math.round((job.progress_current / job.progress_total) * 100)
      : 0;
    elJobText.textContent = job.progress_user
      ? `[${job.progress_current}/${job.progress_total}] @${job.progress_user}`
      : "Connexion…";
    elJobBar.style.width = `${pct}%`;
    startPolling();
    lastJobState = "running";
    return;
  }

  setButtonsDisabled(false);
  elJobPanel.classList.add("hidden");
  stopPolling();

  if (job.state === "done" && lastJobState === "running") {
    elJobPanel.classList.remove("hidden");
    elJobBar.style.width = "100%";
    elJobText.textContent = job.message;
    loadScans();
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      fetch("/api/scan/reset", { method: "POST" });
    }, 3500);
  } else if (job.state === "error" && lastJobState === "running") {
    elJobPanel.classList.remove("hidden");
    elJobPanel.classList.add("job-error");
    elJobBar.style.width = "0%";
    elJobText.textContent = job.message;
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      elJobPanel.classList.remove("job-error");
      fetch("/api/scan/reset", { method: "POST" });
    }, 5000);
  }

  lastJobState = job.state === "idle" ? "idle" : lastJobState;
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    const status = await fetchStatus();
    renderStatus(status);
  }, 800);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function triggerScan(body) {
  const res = await fetch("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "Impossible de lancer le scan");
    return;
  }
  lastJobState = "idle";
  const job = await res.json();
  const status = await fetchStatus();
  renderStatus({ ...status, job });
  startPolling();
}

btnScan.onclick = () => triggerScan({ init: false, full: false });
btnInit.onclick = () => {
  if (!scans.length || confirm("Reconstruire la baseline ?")) {
    triggerScan({ init: true, full: false });
  }
};
btnFull.onclick = () => triggerScan({ init: false, full: true });

document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") btnPrev.click();
  if (e.key === "ArrowRight") btnNext.click();
});

(async function init() {
  const status = await fetchStatus();
  renderStatus(status);
  await loadScans();
})();
