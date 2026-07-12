let scans = [];
let currentId = null;
let pollTimer = null;
let lastJobState = "idle";
let changesSearchQuery = "";

const page = document.body.dataset.page || "";
const t = (key, vars) => I18n.t(key, vars);

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
const elCfgPageSize = document.getElementById("cfg-page-size");
const elCfgScheduleInterval = document.getElementById("cfg-schedule-interval");
const elCfgAutostart = document.getElementById("cfg-autostart");
const elCfgHost = document.getElementById("cfg-host");
const elCfgPort = document.getElementById("cfg-port");
const elConfigMsg = document.getElementById("config-msg");
const btnSaveConfig = document.getElementById("btn-save-config");
const btnTestSession = document.getElementById("btn-test-session");

const elJobPanel = document.getElementById("job-panel");
const elJobTextProfiles = document.getElementById("job-text-profiles");
const elJobBarProfiles = document.getElementById("job-bar-profiles");
const elJobWatchBlock = document.getElementById("job-watch-block");
const elJobTextWatch = document.getElementById("job-text-watch");
const elJobBarWatch = document.getElementById("job-bar-watch");
const btnScan = document.getElementById("btn-scan");
const btnStopScan = document.getElementById("btn-stop-scan");
const btnInit = document.getElementById("btn-init");

const elDate = document.getElementById("scan-date");
const elMeta = document.getElementById("scan-meta");
const elScanSubject = document.getElementById("scan-subject");
const elScanSubjectUser = document.getElementById("scan-subject-user");
const elScanSubjectSub = document.getElementById("scan-subject-sub");
const elContent = document.getElementById("content");
const elHistory = document.getElementById("history-list");
const elHistoryEmpty = document.getElementById("history-empty");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const elChangesSearch = document.getElementById("changes-search");
const elChangesSearchEmpty = document.getElementById("changes-search-empty");

const dialog = document.getElementById("confirm-dialog");
const confirmTitle = document.getElementById("confirm-title");
const confirmMessage = document.getElementById("confirm-message");

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function igProfileUrl(username) {
  const u = String(username || "").replace(/^@/, "").trim();
  return u ? `https://www.instagram.com/${encodeURIComponent(u)}/` : "#";
}

function igUser(username, className = "change-user") {
  const u = String(username || "").replace(/^@/, "").trim();
  if (!u) return "";
  const cls = className ? ` class="${className}"` : "";
  return (
    `<a href="${igProfileUrl(u)}"${cls} target="_blank" rel="noopener noreferrer">@${esc(u)}</a>`
  );
}

function formatScanDate(scannedAt) {
  if (!scannedAt) return "—";
  const raw = String(scannedAt).trim();
  const d = new Date(raw.includes("T") ? raw : raw.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return raw;
  const locale =
    I18n.getLocale() === "fr" ? "fr-FR" : I18n.getLocale() === "es" ? "es-ES" : "en-GB";
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

async function fetchStatus() {
  const r = await fetch("/api/status");
  return r.json();
}

function setControlsDisabled(disabled) {
  [btnScan, btnInit, btnSaveConfig, btnTestSession]
    .filter(Boolean)
    .forEach((el) => {
      el.disabled = disabled;
    });
  if (btnStopScan) {
    btnStopScan.disabled = !disabled;
    btnStopScan.classList.toggle("hidden", !disabled);
  }
}

function renderSession(session) {
  if (!elSessionUser || !elSessionBadge || !elSub) return;
  if (session.ok) {
    elSessionUser.innerHTML = igUser(session.username);
    elSessionBadge.className = "session-dot ok";
    elSub.textContent = session.note ? `${session.source} · ${session.note}` : session.source;
  } else {
    elSessionUser.textContent = t("session.notConnected");
    elSessionBadge.className = "session-dot err";
    elSub.textContent = session.error || t("session.configure");
  }
}

function showConfigMsg(text, ok = true) {
  if (!elConfigMsg) return;
  elConfigMsg.textContent = text;
  elConfigMsg.className = ok ? "config-msg ok" : "config-msg err";
  elConfigMsg.classList.remove("hidden");
  setTimeout(() => elConfigMsg.classList.add("hidden"), 4000);
}

function fillConfigForm(config) {
  if (!configForm) return;
  elCfgUsername.value = config.username || "";
  elCfgNInput.value = String(config.n ?? "100");
  elCfgWatchNInput.value = String(config.watch_n ?? "MAX");
  elCfgPageSleep.value = config.page_sleep;
  elCfgPageSize.value = config.page_size ?? 200;
  if (elCfgScheduleInterval) {
    elCfgScheduleInterval.value = config.schedule_interval_minutes ?? 0;
  }
  if (elCfgAutostart) {
    elCfgAutostart.checked = Boolean(config.autostart_on_boot);
  }
  elCfgHost.value = config.host || "127.0.0.1";
  elCfgPort.value = config.port || 8765;
  elCfgSessionid.placeholder = config.sessionid_set
    ? t("settings.sessionKeep")
    : t("settings.sessionPaste");
  elCfgDsUserId.placeholder = config.ds_user_id_set
    ? t("settings.sessionKeep")
    : t("settings.userIdPaste");
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
    n: elCfgNInput.value.trim(),
    watch_n: elCfgWatchNInput.value.trim(),
    page_sleep: Number(elCfgPageSleep.value),
    page_size: Number(elCfgPageSize.value),
    host: elCfgHost.value.trim(),
    port: Number(elCfgPort.value),
    autostart_on_boot: Boolean(elCfgAutostart?.checked),
    schedule_interval_minutes: Number(elCfgScheduleInterval?.value || 0),
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
    showConfigMsg(err.detail || t("settings.saveError"), false);
    return;
  }
  const data = await res.json();
  fillConfigForm(data.config);
  showConfigMsg(t("settings.saved"));
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
    .map(
      (c) =>
        `<div class="change-line ${type}">` +
        `<span class="change-op"></span>` +
        `<span><span class="change-user-wrap">${igUser(c.username)}</span> ` +
        `<span class="change-name">${esc(c.full_name)}</span></span>` +
        `</div>`,
    )
    .join("");
  return `<div class="changes-group"><div class="changes-group-title">${title}</div>${lines}</div>`;
}

function renderPersonSection(groups) {
  const blocks = groups
    .map((g) => {
      const title =
        `<div class="person-group-title">` +
        igUser(g.username, "person-subject") +
        `</div>`;
      const lines = [];
      for (const a of g.adds) {
        lines.push(
          `<div class="change-line add"><span class="change-op"></span>` +
            `<span><span class="change-user-wrap">${igUser(a.username)}</span> ` +
            `<span class="change-name">${esc(a.full_name)}</span></span></div>`,
        );
      }
      for (const r of g.removes) {
        lines.push(
          `<div class="change-line remove"><span class="change-op"></span>` +
            `<span><span class="change-user-wrap">${igUser(r.username)}</span> ` +
            `<span class="change-name">${esc(r.full_name)}</span></span></div>`,
        );
      }
      for (const x of g.gones || []) {
        lines.push(
          `<div class="change-line gone"><span class="change-op"></span>` +
            `<span><span class="change-user-wrap">${igUser(x.username)}</span> ` +
            `<span class="change-name">${esc(x.full_name)}</span></span></div>`,
        );
      }
      return `<div class="changes-group person-group">${title}${lines.join("")}</div>`;
    })
    .join("");
  return `<div class="changes-section changes-section--panel-full"><div class="person-section-body">${blocks}</div></div>`;
}

function updateScanSubject(detail) {
  if (!elScanSubject || !elScanSubjectUser || !elScanSubjectSub) return;
  const scan = detail?.scan;
  const hasListChanges = Boolean(
    detail?.adds?.length || detail?.removes?.length || detail?.gones?.length,
  );
  if (!scan || !hasListChanges) {
    elScanSubject.hidden = true;
    elScanSubjectUser.innerHTML = "";
    elScanSubjectSub.textContent = "";
    return;
  }
  const oldC = detail.old_count != null ? detail.old_count : "?";
  elScanSubjectUser.innerHTML = igUser(scan.username);
  elScanSubjectSub.textContent = `${oldC} → ${scan.following_count} ${t("changes.subscriptions")}`;
  elScanSubject.hidden = false;
}

function renderDetail(detail) {
  if (!elContent) return;

  const scan = detail.scan;
  updateScanSubject(detail);

  if (!detail.has_changes) {
    elContent.innerHTML =
      `<p class="empty"><strong>${t("changes.nothingNew")}</strong> ${t("changes.nothingNewHint")}<br>` +
      `${t("changes.mutualsTracked", { count: scan.tracked_count })}</p>`;
    applyChangesSearch();
    return;
  }

  const mutualSections = [];
  if (detail.adds.length) mutualSections.push(renderGroup(t("changes.newMutuals"), detail.adds, "add"));
  if (detail.removes.length) mutualSections.push(renderGroup(t("changes.lostMutuals"), detail.removes, "remove"));
  if (detail.gones?.length) mutualSections.push(renderGroup(t("changes.goneAccounts"), detail.gones, "gone"));
  const personSection = detail.person_changes?.length
    ? renderPersonSection(detail.person_changes)
    : "";

  const mutualCard = mutualSections.length
    ? `<article class="changes-card">${mutualSections.join("")}</article>`
    : "";

  elContent.innerHTML =
    `<div class="changes-layout">` + mutualCard + personSection + `</div>`;
  applyChangesSearch();
}

function matchesChangesSearch(text) {
  const q = changesSearchQuery.trim().toLowerCase().replace(/^@/, "");
  if (!q) return true;
  return String(text || "")
    .toLowerCase()
    .replace(/^@/, "")
    .includes(q);
}

function applyChangesSearch() {
  if (!elContent) return;
  const q = changesSearchQuery.trim();
  const active = q.length > 0;

  elContent.querySelectorAll(".change-line").forEach((line) => {
    const hay = line.textContent || "";
    line.classList.toggle("hidden", active && !matchesChangesSearch(hay));
  });

  elContent.querySelectorAll(".person-group").forEach((group) => {
    const subject = group.querySelector(".person-group-title")?.textContent || "";
    const subjectMatch = matchesChangesSearch(subject);
    const lines = [...group.querySelectorAll(".change-line")];
    if (active && subjectMatch) {
      lines.forEach((line) => line.classList.remove("hidden"));
      group.classList.remove("hidden");
      return;
    }
    const anyLine = lines.some((line) => !line.classList.contains("hidden"));
    group.classList.toggle("hidden", active && !anyLine);
  });

  elContent.querySelectorAll(".changes-group:not(.person-group)").forEach((group) => {
    const lines = [...group.querySelectorAll(".change-line")];
    const anyLine = lines.some((line) => !line.classList.contains("hidden"));
    group.classList.toggle("hidden", active && !anyLine);
  });

  elContent.querySelectorAll(".changes-card").forEach((card) => {
    const groups = [...card.querySelectorAll(".changes-group")];
    const anyGroup = groups.some((g) => !g.classList.contains("hidden"));
    card.classList.toggle("hidden", active && groups.length > 0 && !anyGroup);
  });

  elContent.querySelectorAll(".changes-section").forEach((section) => {
    const groups = [...section.querySelectorAll(".person-group")];
    const anyGroup = groups.some((g) => !g.classList.contains("hidden"));
    section.classList.toggle("hidden", active && groups.length > 0 && !anyGroup);
  });

  const layout = elContent.querySelector(".changes-layout");
  let anyVisible = false;
  if (layout) {
    anyVisible = [...layout.children].some((el) => !el.classList.contains("hidden"));
  } else if (!active) {
    anyVisible = true;
  }

  if (elChangesSearchEmpty) {
    const hasLayout = Boolean(layout);
    elChangesSearchEmpty.classList.toggle("hidden", !(active && hasLayout && !anyVisible));
  }
  if (layout) {
    layout.classList.toggle("hidden", active && !anyVisible);
  }
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
        `<span class="h-date">${esc(formatScanDate(s.scanned_at))}</span>` +
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
  if (elDate) {
    elDate.textContent = formatScanDate(detail.scan.scanned_at);
    if (detail.scan.scanned_at) {
      elDate.dateTime = detail.scan.scanned_at.replace(" ", "T");
    }
  }
  if (elMeta) {
    elMeta.innerHTML = `${igUser(detail.scan.username)} · ${detail.scan.tracked_count} ${t("changes.mutualsMeta")} · ${neighbors.index + 1}/${neighbors.total}`;
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
    if (elDate) elDate.textContent = t("changes.noScan");
    if (elMeta) elMeta.textContent = "";
    elContent.innerHTML =
      `<p class="empty"><strong>${t("changes.noDataTitle")}</strong><br>${t("changes.noDataHint")}</p>`;
    if (btnPrev) btnPrev.disabled = true;
    if (btnNext) btnNext.disabled = true;
    if (elChangesSearchEmpty) elChangesSearchEmpty.classList.add("hidden");
    if (elScanSubject) {
      elScanSubject.hidden = true;
      if (elScanSubjectUser) elScanSubjectUser.innerHTML = "";
      if (elScanSubjectSub) elScanSubjectSub.textContent = "";
    }
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

function jobMessage(job) {
  if (job.message_key) {
    if (job.message_key === "job.done" && job.result?.scan_id) {
      return t("job.done", { id: job.result.scan_id });
    }
    return t(job.message_key);
  }
  return job.message || "";
}

function phaseLabel(phase) {
  const map = {
    profile: t("job.profilePhase"),
    baseline: t("job.baselinePhase"),
    fetch: t("job.fetchPhase"),
    mutuals: t("job.loadingMutuals"),
  };
  return map[phase] || phase;
}

function renderJob(job) {
  if (!elJobPanel) return;

  if (job.state === "running") {
    setControlsDisabled(true);
    elJobPanel.classList.remove("hidden", "job-error");

    if (elJobTextProfiles && elJobBarProfiles) {
      const phase = job.progress_phase;
      if (phase === "mutuals") {
        elJobTextProfiles.textContent = t("job.loadingMutuals");
        elJobBarProfiles.style.width = "30%";
      } else if (job.progress_user) {
        const pct = job.progress_total
          ? Math.round((job.progress_current / job.progress_total) * 100)
          : 0;
        const phaseSuffix = phase && phase !== "profile" ? ` · ${phaseLabel(phase)}` : "";
        elJobTextProfiles.innerHTML = `[${job.progress_current}/${job.progress_total}] ${igUser(job.progress_user)}${esc(phaseSuffix)}`;
        elJobBarProfiles.style.width = `${pct}%`;
      } else {
        elJobTextProfiles.textContent = t("job.connecting");
        elJobBarProfiles.style.width = "5%";
      }
    }

    const watchActive =
      job.watch_user &&
      (job.watch_phase === "baseline" || job.watch_phase === "fetch" || job.watch_phase === "page");
    if (elJobWatchBlock) {
      elJobWatchBlock.classList.toggle("hidden", !watchActive);
    }
    if (watchActive && elJobTextWatch && elJobBarWatch) {
      const pct = job.watch_total
        ? Math.round((job.watch_current / job.watch_total) * 100)
        : job.watch_current > 0
          ? 50
          : 0;
      const phaseSuffix = job.watch_phase ? ` · ${phaseLabel(job.watch_phase)}` : "";
      elJobTextWatch.innerHTML = `${igUser(job.watch_user)} [${job.watch_current}/${job.watch_total || "?"}]${esc(phaseSuffix)}`;
      elJobBarWatch.style.width = `${Math.min(pct, 100)}%`;
    }

    startPolling();
    lastJobState = "running";
    return;
  }

  setControlsDisabled(false);
  stopPolling();

  const msg = jobMessage(job);

  if (job.state === "done" && lastJobState === "running") {
    elJobPanel.classList.remove("hidden");
    if (elJobBarProfiles) elJobBarProfiles.style.width = "100%";
    if (elJobTextProfiles) elJobTextProfiles.textContent = msg;
    if (elJobWatchBlock) elJobWatchBlock.classList.add("hidden");
    lastJobState = "done";
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      fetch("/api/scan/reset", { method: "POST" });
    }, 3000);
  } else if (job.state === "error" && lastJobState === "running") {
    elJobPanel.classList.remove("hidden");
    elJobPanel.classList.add("job-error");
    if (elJobBarProfiles) elJobBarProfiles.style.width = "0%";
    if (elJobTextProfiles) elJobTextProfiles.textContent = msg;
    if (elJobWatchBlock) elJobWatchBlock.classList.add("hidden");
    lastJobState = "error";
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      elJobPanel.classList.remove("job-error");
      fetch("/api/scan/reset", { method: "POST" });
    }, 5000);
  } else if (job.state === "cancelled" && lastJobState === "running") {
    elJobPanel.classList.remove("hidden");
    if (elJobBarProfiles) elJobBarProfiles.style.width = "0%";
    if (elJobTextProfiles) elJobTextProfiles.textContent = msg;
    if (elJobWatchBlock) elJobWatchBlock.classList.add("hidden");
    lastJobState = "cancelled";
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      fetch("/api/scan/reset", { method: "POST" });
    }, 3000);
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
    showConfigMsg(err.detail || t("actions.scanError"), false);
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
      btnTestSession.textContent = t("settings.testing");
      const session = await fetch("/api/session/test", { method: "POST" }).then((r) => r.json());
      btnTestSession.disabled = false;
      btnTestSession.textContent = t("settings.testSession");
      renderSession(session);
      if (session.ok) {
        if (session.note) showConfigMsg(session.note);
        else showConfigMsg(t("settings.connectedAs", { user: session.username }));
        await loadConfig();
      } else showConfigMsg(session.error || t("settings.connectionFailed"), false);
    };
  }
}

async function initChangesPage() {
  await loadScans();
  if (btnScan) {
    btnScan.onclick = async () => {
      const ok = await askConfirm(t("actions.confirmScanTitle"), t("actions.confirmScanMsg"));
      if (ok) triggerScan({ init: false });
    };
  }
  if (btnInit) {
    btnInit.onclick = async () => {
      const ok = await askConfirm(t("actions.confirmBaselineTitle"), t("actions.confirmBaselineMsg"));
      if (ok) triggerScan({ init: true });
    };
  }
  if (btnStopScan) {
    btnStopScan.onclick = async () => {
      btnStopScan.disabled = true;
      btnStopScan.textContent = t("actions.stopping");
      const res = await fetch("/api/scan/cancel", { method: "POST" });
      if (!res.ok) {
        btnStopScan.disabled = false;
        btnStopScan.textContent = t("actions.stopScan");
        return;
      }
      renderJob(await res.json());
    };
  }
  document.addEventListener("keydown", (e) => {
    if (e.target === elChangesSearch || e.target?.closest?.("input, textarea")) return;
    if (e.key === "ArrowLeft" && btnPrev) btnPrev.click();
    if (e.key === "ArrowRight" && btnNext) btnNext.click();
  });

  if (elChangesSearch) {
    elChangesSearch.value = changesSearchQuery;
    elChangesSearch.addEventListener("input", () => {
      changesSearchQuery = elChangesSearch.value;
      applyChangesSearch();
    });
  }
}

function initLangSwitch() {
  document.querySelectorAll("[data-lang]").forEach((btn) => {
    btn.onclick = async () => {
      await I18n.setLocale(btn.dataset.lang);
    };
  });
}

function onLocaleChange() {
  I18n.applyI18n();
  if (page === "settings") loadConfig();
  if (page === "changes" && currentId) showScan(currentId);
  else if (page === "changes") loadScans();
  if (btnStopScan && !btnStopScan.disabled) btnStopScan.textContent = t("actions.stopScan");
}

async function init() {
  await I18n.ready;
  initLangSwitch();
  window.addEventListener("instree:locale", onLocaleChange);

  const status = await fetchStatus();
  renderSession(status.session);
  renderJob(status.job);

  if (page === "settings") await initSettingsPage();
  if (page === "changes") await initChangesPage();
}

init();
