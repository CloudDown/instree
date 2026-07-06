let scans = [];
let currentId = null;
let pollTimer = null;
let lastJobState = "idle";

const elSessionUser = document.getElementById("session-user");
const elSessionBadge = document.getElementById("session-badge");
const elSub = document.getElementById("header-sub");
const configForm = document.getElementById("config-form");
const elCfgUsername = document.getElementById("cfg-username");
const elCfgSessionid = document.getElementById("cfg-sessionid");
const elCfgDsUserId = document.getElementById("cfg-ds-user-id");
const elCfgNInput = document.getElementById("cfg-n-input");
const elCfgWatchNInput = document.getElementById("cfg-watch-n-input");
const elCfgPageSleep = document.getElementById("cfg-page-sleep");
const elCfgScheduleInput = document.getElementById("cfg-schedule-input");
const elCfgHost = document.getElementById("cfg-host");
const elCfgPort = document.getElementById("cfg-port");
const elConfigMsg = document.getElementById("config-msg");
const btnSaveConfig = document.getElementById("btn-save-config");
const btnTestSession = document.getElementById("btn-test-session");
const btnScheduleInstall = document.getElementById("btn-schedule-install");
const elJobPanel = document.getElementById("job-panel");
const elJobText = document.getElementById("job-text");
const elJobBar = document.getElementById("job-bar");
const elDate = document.getElementById("scan-date");
const elMeta = document.getElementById("scan-meta");
const elContent = document.getElementById("content");
const elHistory = document.getElementById("history-list");
const elHistoryEmpty = document.getElementById("history-empty");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const btnScan = document.getElementById("btn-scan");
const btnInit = document.getElementById("btn-init");
const btnFull = document.getElementById("btn-full");
const dialog = document.getElementById("confirm-dialog");
const confirmTitle = document.getElementById("confirm-title");
const confirmMessage = document.getElementById("confirm-message");
const confirmOk = document.getElementById("confirm-ok");

function setScanButtonsDisabled(disabled) {
  btnScan.disabled = disabled;
  btnInit.disabled = disabled;
  btnFull.disabled = disabled;
  btnSaveConfig.disabled = disabled;
  btnTestSession.disabled = disabled;
  btnScheduleInstall.disabled = disabled;
}

function showConfigMsg(text, ok = true) {
  elConfigMsg.textContent = text;
  elConfigMsg.className = ok ? "config-msg ok" : "config-msg err";
  elConfigMsg.classList.remove("hidden");
  setTimeout(() => elConfigMsg.classList.add("hidden"), 4000);
}

function fillConfigForm(config) {
  elCfgUsername.value = config.username || "";
  elCfgNInput.value = config.n;
  elCfgWatchNInput.value = config.watch_n;
  elCfgPageSleep.value = config.page_sleep;
  elCfgScheduleInput.value = (config.schedule_times || []).join(", ");
  elCfgHost.value = config.host || "127.0.0.1";
  elCfgPort.value = config.port || 8765;
  elCfgSessionid.placeholder = config.sessionid_set
    ? "Déjà configuré — laisser vide pour conserver"
    : "Coller le sessionid Instagram";
  elCfgDsUserId.placeholder = config.ds_user_id_set
    ? "Déjà configuré — laisser vide pour conserver"
    : "Coller le ds_user_id";
  elCfgSessionid.value = "";
  elCfgDsUserId.value = "";
}

function parseScheduleTimes(raw) {
  return raw
    .split(/[,;\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

async function loadConfig() {
  const config = await fetch("/api/config").then((r) => r.json());
  fillConfigForm(config);
  return config;
}

async function saveConfig(e) {
  e.preventDefault();
  const body = {
    username: elCfgUsername.value.trim().replace(/^@/, ""),
    n: Number(elCfgNInput.value),
    watch_n: Number(elCfgWatchNInput.value),
    page_sleep: Number(elCfgPageSleep.value),
    host: elCfgHost.value.trim(),
    port: Number(elCfgPort.value),
    schedule_times: parseScheduleTimes(elCfgScheduleInput.value),
    sessionid: elCfgSessionid.value.trim(),
    ds_user_id: elCfgDsUserId.value.trim(),
  };
  const res = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || "Erreur lors de l'enregistrement", false);
    return;
  }
  const data = await res.json();
  fillConfigForm(data.config);
  showConfigMsg("Configuration enregistrée");
  const status = await fetchStatus();
  renderStatus(status);
}

function askConfirm(title, message) {
  return new Promise((resolve) => {
    confirmTitle.textContent = title;
    confirmMessage.textContent = message;
    dialog.returnValue = "";
    dialog.showModal();
    const onClose = () => {
      dialog.removeEventListener("close", onClose);
      resolve(dialog.returnValue === "ok");
    };
    dialog.addEventListener("close", onClose);
  });
}

async function fetchStatus() {
  const r = await fetch("/api/status");
  return r.json();
}

async function loadScans() {
  scans = await fetch("/api/scans").then((r) => r.json());
  renderHistory();
  if (scans.length === 0) {
    elDate.textContent = "Aucun scan";
    elMeta.textContent = "";
    elContent.innerHTML =
      '<p class="empty"><strong>Aucune donnée.</strong><br>Lance un scan depuis le panneau de gauche pour commencer.</p>';
    btnPrev.disabled = btnNext.disabled = true;
    return;
  }
  const target =
    currentId && scans.some((s) => s.id === currentId)
      ? currentId
      : scans[scans.length - 1].id;
  await showScan(target);
}

function renderHistory() {
  const empty = scans.length === 0;
  elHistoryEmpty.classList.toggle("hidden", !empty);
  elHistory.innerHTML = [...scans].reverse().map((s) => {
    const active = s.id === currentId ? " active" : "";
    const hasChanges = s.change_count > 0 ? " has-changes" : "";
    const changes = s.change_count > 0 ? `${s.change_count}` : "·";
    return (
      `<li><button type="button" class="history-item${active}${hasChanges}" data-id="${s.id}">` +
      `<span class="h-id">#${s.id}</span>` +
      `<span class="h-date">${escapeHtml(s.label)}</span>` +
      `<span class="h-changes">${changes}</span>` +
      `</button></li>`
    );
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
  elMeta.textContent = `@${scan.username} · ${scan.tracked_count}/${scan.following_count} · ${neighbors.index + 1}/${neighbors.total}`;

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
      `<p class="empty"><strong>Rien de nouveau</strong> sur ce scan.<br>` +
      `${scan.tracked_count} abonnements suivis sur ${scan.following_count} au total.</p>`;
    return;
  }

  const oldC = detail.old_count != null ? detail.old_count : "?";
  const hasListChanges = detail.adds.length || detail.removes.length;
  const header = hasListChanges ? `@${escapeHtml(scan.username)}` : "";
  const sub = hasListChanges ? `${oldC} → ${scan.following_count} abonnements` : "";

  const sections = [];
  if (detail.adds.length) {
    sections.push(renderGroup("Nouveaux suivis", detail.adds, "add"));
  }
  if (detail.person_changes && detail.person_changes.length) {
    sections.push(renderPersonSection(detail.person_changes));
  }
  if (detail.counts.length) {
    sections.push(renderGroup("Évolutions", detail.counts, "count"));
  }
  if (detail.removes.length) {
    sections.push(renderGroup("Suivis retirés", detail.removes, "remove"));
  }

  const cardHeader = header
    ? `<header class="changes-card-header">${header}<div class="sub">${sub}</div></header>`
    : "";

  elContent.innerHTML =
    `<article class="changes-card">` +
    cardHeader +
    sections.join("") +
    `</article>`;
}

function renderPersonSection(groups) {
  const blocks = groups.map((g) => {
    const countLabel =
      g.old_count != null && g.new_count != null
        ? `${g.old_count} → ${g.new_count} abonnements`
        : "";
    const title =
      `<div class="changes-group-title">` +
      `@${escapeHtml(g.username)}` +
      (countLabel ? ` <span class="change-detail">${countLabel}</span>` : "") +
      `</div>`;
    const lines = [];
    for (const a of g.adds) {
      lines.push(
        `<div class="change-line add">` +
        `<span class="change-op"></span>` +
        `<span><span class="change-user">@${escapeHtml(a.username)}</span> ` +
        `<span class="change-name">${escapeHtml(a.full_name)}</span></span>` +
        `</div>`,
      );
    }
    for (const r of g.removes) {
      lines.push(
        `<div class="change-line remove">` +
        `<span class="change-op"></span>` +
        `<span><span class="change-user">@${escapeHtml(r.username)}</span> ` +
        `<span class="change-name">${escapeHtml(r.full_name)}</span></span>` +
        `</div>`,
      );
    }
    return `<div class="changes-group person-group">${title}${lines.join("")}</div>`;
  }).join("");
  return `<div class="changes-section"><div class="changes-group-title section-title">Abonnements des suivis</div>${blocks}</div>`;
}

function renderGroup(title, items, type) {
  const lines = items.map((c) => {
    if (type === "count") {
      return (
        `<div class="change-line ${type}">` +
        `<span class="change-op"></span>` +
        `<span><span class="change-user">@${escapeHtml(c.username)}</span> ` +
        `<span class="change-detail">${c.old_count} → ${c.new_count} abonnements</span></span>` +
        `</div>`
      );
    }
    return (
      `<div class="change-line ${type}">` +
      `<span class="change-op"></span>` +
      `<span><span class="change-user">@${escapeHtml(c.username)}</span> ` +
      `<span class="change-name">${escapeHtml(c.full_name)}</span></span>` +
      `</div>`
    );
  }).join("");
  return `<div class="changes-group"><div class="changes-group-title">${title}</div>${lines}</div>`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderStatus(status) {
  const { session, job } = status;

  if (session.ok) {
    elSessionUser.textContent = `@${session.username}`;
    elSessionBadge.className = "session-dot ok";
    elSub.textContent = session.source;
  } else {
    elSessionUser.textContent = "Non connecté";
    elSessionBadge.className = "session-dot err";
    elSub.textContent = session.error || "Configurer la session ci-dessous";
  }

  if (job.state === "running") {
    setScanButtonsDisabled(true);
    elJobPanel.classList.remove("hidden", "job-error");
    const pct = job.progress_total
      ? Math.round((job.progress_current / job.progress_total) * 100)
      : 0;
    const phaseLabels = { profile: "profil", baseline: "baseline", fetch: "liste" };
    const phase = job.progress_phase
      ? ` · ${phaseLabels[job.progress_phase] || job.progress_phase}`
      : "";
    elJobText.textContent = job.progress_user
      ? `[${job.progress_current}/${job.progress_total}] @${job.progress_user}${phase}`
      : "Connexion Instagram…";
    elJobBar.style.width = `${pct}%`;
    startPolling();
    lastJobState = "running";
    return;
  }

  setScanButtonsDisabled(false);
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
    renderStatus(await fetchStatus());
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
    confirmTitle.textContent = "Erreur";
    confirmMessage.textContent = err.detail || "Impossible de lancer le scan.";
    dialog.showModal();
    return;
  }
  lastJobState = "idle";
  const job = await res.json();
  const status = await fetchStatus();
  renderStatus({ ...status, job });
  startPolling();
}

btnScan.onclick = async () => {
  const ok = await askConfirm(
    "Lancer un scan ?",
    "Compare tes abonnements avec le dernier enregistrement. Durée estimée : 1 à 2 minutes.",
  );
  if (ok) triggerScan({ init: false, full: false });
};

btnInit.onclick = async () => {
  const ok = await askConfirm(
    "Baseline complète ?",
    "Enregistre l'état actuel comme référence. Les prochains scans compareront à partir de ce point. Aucun changement ne sera affiché.",
  );
  if (ok) triggerScan({ init: true, full: false });
};

btnFull.onclick = async () => {
  const ok = await askConfirm(
    "Scan complet ?",
    "Re-télécharge toute la liste d'abonnements (~100 appels API). Plus lent qu'un scan incrémental.",
  );
  if (ok) triggerScan({ init: false, full: true });
};

configForm.addEventListener("submit", saveConfig);

btnTestSession.onclick = async () => {
  btnTestSession.disabled = true;
  btnTestSession.textContent = "Test…";
  const session = await fetch("/api/session/test", { method: "POST" }).then((r) => r.json());
  btnTestSession.textContent = "Tester la connexion";
  btnTestSession.disabled = false;
  const status = await fetchStatus();
  renderStatus({ ...status, session });
  if (session.ok) {
    showConfigMsg(`Connecté en tant que @${session.username}`);
  } else {
    showConfigMsg(session.error || "Connexion impossible", false);
  }
};

btnScheduleInstall.onclick = async () => {
  const ok = await askConfirm(
    "Installer le timer systemd ?",
    "Génère les unités systemd dans ~/.config/systemd/user/ avec les heures configurées. Puis lance : systemctl --user daemon-reload && systemctl --user enable --now instree-scan.timer",
  );
  if (!ok) return;
  btnScheduleInstall.disabled = true;
  const res = await fetch("/api/schedule/install", { method: "POST" });
  btnScheduleInstall.disabled = false;
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || "Installation impossible", false);
    return;
  }
  const data = await res.json();
  showConfigMsg(`Timer installé (${data.times.join(", ")})`);
};

document.addEventListener("keydown", (e) => {
  if (dialog.open) return;
  if (e.key === "ArrowLeft") btnPrev.click();
  if (e.key === "ArrowRight") btnNext.click();
});

(async function init() {
  await loadConfig();
  const status = await fetchStatus();
  renderStatus(status);
  await loadScans();
})();
