let scans = [];
let currentId = null;
let pollTimer = null;
let lastJobState = "idle";

const page = document.body.dataset.page || "";

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
const btnScan = document.getElementById("btn-scan");
const btnInit = document.getElementById("btn-init");
const btnFull = document.getElementById("btn-full");

const elDate = document.getElementById("scan-date");
const elMeta = document.getElementById("scan-meta");
const elContent = document.getElementById("content");
const elHistory = document.getElementById("history-list");
const elHistoryEmpty = document.getElementById("history-empty");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");

const dialog = document.getElementById("confirm-dialog");
const confirmTitle = document.getElementById("confirm-title");
const confirmMessage = document.getElementById("confirm-message");

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function fetchStatus() {
  const r = await fetch("/api/status");
  return r.json();
}

function setControlsDisabled(disabled) {
  [btnScan, btnInit, btnFull, btnSaveConfig, btnTestSession, btnScheduleInstall]
    .filter(Boolean)
    .forEach((el) => {
      el.disabled = disabled;
    });
}

function renderSession(session) {
  if (!elSessionUser || !elSessionBadge || !elSub) return;
  if (session.ok) {
    elSessionUser.textContent = `@${session.username}`;
    elSessionBadge.className = "session-dot ok";
    elSub.textContent = session.source;
  } else {
    elSessionUser.textContent = "Non connecté";
    elSessionBadge.className = "session-dot err";
    elSub.textContent = session.error || "Configurer la session";
  }
}

function showConfigMsg(text, ok = true) {
  if (!elConfigMsg) return;
  elConfigMsg.textContent = text;
  elConfigMsg.className = ok ? "config-msg ok" : "config-msg err";
  elConfigMsg.classList.remove("hidden");
  setTimeout(() => elConfigMsg.classList.add("hidden"), 4000);
}

function parseScheduleTimes(raw) {
  return raw
    .split(/[,;\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function fillConfigForm(config) {
  if (!configForm) return;
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

async function loadConfig() {
  if (!configForm) return null;
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
  renderSession(status.session);
}

function askConfirm(title, message) {
  if (!dialog || !confirmTitle || !confirmMessage) return Promise.resolve(true);
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

function renderGroup(title, items, type) {
  const lines = items
    .map((c) => {
      if (type === "count") {
        return (
          `<div class="change-line ${type}">` +
          `<span class="change-op"></span>` +
          `<span><span class="change-user">@${esc(c.username)}</span> ` +
          `<span class="change-detail">${c.old_count} → ${c.new_count} abonnements</span></span>` +
          `</div>`
        );
      }
      return (
        `<div class="change-line ${type}">` +
        `<span class="change-op"></span>` +
        `<span><span class="change-user">@${esc(c.username)}</span> ` +
        `<span class="change-name">${esc(c.full_name)}</span></span>` +
        `</div>`
      );
    })
    .join("");
  return `<div class="changes-group"><div class="changes-group-title">${title}</div>${lines}</div>`;
}

function renderPersonSection(groups) {
  const blocks = groups
    .map((g) => {
      const countLabel =
        g.old_count != null && g.new_count != null
          ? `${g.old_count} → ${g.new_count} abonnements`
          : "";
      const title =
        `<div class="changes-group-title">` +
        `@${esc(g.username)}` +
        (countLabel ? ` <span class="change-detail">${countLabel}</span>` : "") +
        `</div>`;
      const lines = [];
      for (const a of g.adds) {
        lines.push(
          `<div class="change-line add"><span class="change-op"></span>` +
            `<span><span class="change-user">@${esc(a.username)}</span> ` +
            `<span class="change-name">${esc(a.full_name)}</span></span></div>`,
        );
      }
      for (const r of g.removes) {
        lines.push(
          `<div class="change-line remove"><span class="change-op"></span>` +
            `<span><span class="change-user">@${esc(r.username)}</span> ` +
            `<span class="change-name">${esc(r.full_name)}</span></span></div>`,
        );
      }
      return `<div class="changes-group person-group">${title}${lines.join("")}</div>`;
    })
    .join("");
  return `<div class="changes-section"><div class="changes-group-title">Abonnements des suivis</div>${blocks}</div>`;
}

function renderDetail(detail) {
  if (!elContent) return;
  const scan = detail.scan;
  if (!detail.has_changes) {
    elContent.innerHTML =
      `<p class="empty"><strong>Rien de nouveau</strong> sur ce scan.<br>` +
      `${scan.tracked_count} abonnements suivis sur ${scan.following_count} au total.</p>`;
    return;
  }

  const oldC = detail.old_count != null ? detail.old_count : "?";
  const hasListChanges = detail.adds.length || detail.removes.length;
  const header = hasListChanges ? `@${esc(scan.username)}` : "";
  const sub = hasListChanges ? `${oldC} → ${scan.following_count} abonnements` : "";
  const sections = [];
  if (detail.adds.length) sections.push(renderGroup("Nouveaux suivis", detail.adds, "add"));
  if (detail.person_changes?.length) sections.push(renderPersonSection(detail.person_changes));
  if (detail.counts.length) sections.push(renderGroup("Évolutions", detail.counts, "count"));
  if (detail.removes.length) sections.push(renderGroup("Suivis retirés", detail.removes, "remove"));

  elContent.innerHTML =
    `<article class="changes-card">` +
    (header ? `<header class="changes-card-header">${header}<div class="sub">${sub}</div></header>` : "") +
    sections.join("") +
    `</article>`;
}

function renderHistory() {
  if (!elHistory || !elHistoryEmpty) return;
  const empty = scans.length === 0;
  elHistoryEmpty.classList.toggle("hidden", !empty);
  elHistory.innerHTML = [...scans]
    .reverse()
    .map((s) => {
      const active = s.id === currentId ? " active" : "";
      const hasChanges = s.change_count > 0 ? " has-changes" : "";
      const changes = s.change_count > 0 ? `${s.change_count}` : "·";
      return (
        `<li><button type="button" class="history-item${active}${hasChanges}" data-id="${s.id}">` +
        `<span class="h-id">#${s.id}</span>` +
        `<span class="h-date">${esc(s.label)}</span>` +
        `<span class="h-changes">${changes}</span>` +
        `</button></li>`
      );
    })
    .join("");
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
  if (elDate) elDate.textContent = detail.scan.label;
  if (elMeta) {
    elMeta.textContent = `@${detail.scan.username} · ${detail.scan.tracked_count}/${detail.scan.following_count} · ${neighbors.index + 1}/${neighbors.total}`;
  }
  if (btnPrev) {
    btnPrev.disabled = neighbors.prev_id == null;
    btnPrev.onclick = () => neighbors.prev_id && showScan(neighbors.prev_id);
  }
  if (btnNext) {
    btnNext.disabled = neighbors.next_id == null;
    btnNext.onclick = () => neighbors.next_id && showScan(neighbors.next_id);
  }
  renderHistory();
  renderDetail(detail);
}

async function loadScans() {
  if (!elContent) return;
  scans = await fetch("/api/scans").then((r) => r.json());
  renderHistory();
  if (scans.length === 0) {
    if (elDate) elDate.textContent = "Aucun scan";
    if (elMeta) elMeta.textContent = "";
    elContent.innerHTML =
      '<p class="empty"><strong>Aucune donnée.</strong><br>Lance un scan depuis la page Actions pour commencer.</p>';
    if (btnPrev) btnPrev.disabled = true;
    if (btnNext) btnNext.disabled = true;
    return;
  }
  const target = currentId && scans.some((s) => s.id === currentId) ? currentId : scans[scans.length - 1].id;
  await showScan(target);
}

function stopPolling() {
  if (!pollTimer) return;
  clearInterval(pollTimer);
  pollTimer = null;
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    const status = await fetchStatus();
    renderSession(status.session);
    renderJob(status.job);
  }, 800);
}

function renderJob(job) {
  if (!elJobPanel || !elJobText || !elJobBar) return;
  if (job.state === "running") {
    setControlsDisabled(true);
    elJobPanel.classList.remove("hidden", "job-error");
    const pct = job.progress_total ? Math.round((job.progress_current / job.progress_total) * 100) : 0;
    const phaseLabels = { profile: "profil", baseline: "baseline", fetch: "liste" };
    const phase = job.progress_phase ? ` · ${phaseLabels[job.progress_phase] || job.progress_phase}` : "";
    elJobText.textContent = job.progress_user
      ? `[${job.progress_current}/${job.progress_total}] @${job.progress_user}${phase}`
      : "Connexion Instagram…";
    elJobBar.style.width = `${pct}%`;
    startPolling();
    lastJobState = "running";
    return;
  }

  setControlsDisabled(false);
  stopPolling();

  if (job.state === "done" && lastJobState === "running") {
    elJobPanel.classList.remove("hidden");
    elJobBar.style.width = "100%";
    elJobText.textContent = job.message;
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      fetch("/api/scan/reset", { method: "POST" });
    }, 3000);
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
  } else {
    elJobPanel.classList.add("hidden");
  }
  lastJobState = job.state === "idle" ? "idle" : lastJobState;
}

async function triggerScan(body) {
  const res = await fetch("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || "Impossible de lancer le scan.", false);
    return;
  }
  lastJobState = "idle";
  const job = await res.json();
  renderJob(job);
  startPolling();
}

async function initSettingsPage() {
  await loadConfig();
  if (configForm) configForm.addEventListener("submit", saveConfig);
  if (btnTestSession) {
    btnTestSession.onclick = async () => {
      btnTestSession.disabled = true;
      btnTestSession.textContent = "Test…";
      const session = await fetch("/api/session/test", { method: "POST" }).then((r) => r.json());
      btnTestSession.disabled = false;
      btnTestSession.textContent = "Tester la connexion";
      renderSession(session);
      if (session.ok) showConfigMsg(`Connecté en tant que @${session.username}`);
      else showConfigMsg(session.error || "Connexion impossible", false);
    };
  }
  if (btnScheduleInstall) {
    btnScheduleInstall.onclick = async () => {
      const ok = await askConfirm(
        "Installer le timer systemd ?",
        "Génère les unités systemd user avec les heures configurées.",
      );
      if (!ok) return;
      const res = await fetch("/api/schedule/install", { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showConfigMsg(err.detail || "Installation impossible", false);
        return;
      }
      const data = await res.json();
      showConfigMsg(`Timer installé (${data.times.join(", ")})`);
    };
  }
}

async function initActionsPage() {
  if (btnScan) {
    btnScan.onclick = async () => {
      const ok = await askConfirm(
        "Lancer un scan ?",
        "Compare tes abonnements avec le dernier enregistrement.",
      );
      if (ok) triggerScan({ init: false, full: false });
    };
  }
  if (btnInit) {
    btnInit.onclick = async () => {
      const ok = await askConfirm(
        "Baseline complète ?",
        "Référence propre, sans afficher de changement.",
      );
      if (ok) triggerScan({ init: true, full: false });
    };
  }
  if (btnFull) {
    btnFull.onclick = async () => {
      const ok = await askConfirm(
        "Scan complet ?",
        "Re-télécharge toute la liste, plus lent.",
      );
      if (ok) triggerScan({ init: false, full: true });
    };
  }
}

async function initChangesPage() {
  await loadScans();
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" && btnPrev) btnPrev.click();
    if (e.key === "ArrowRight" && btnNext) btnNext.click();
  });
}

(async function init() {
  const status = await fetchStatus();
  renderSession(status.session);
  renderJob(status.job);

  if (page === "settings") await initSettingsPage();
  if (page === "actions") await initActionsPage();
  if (page === "changes") await initChangesPage();
})();
