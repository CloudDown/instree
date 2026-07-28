let scans = [];
let currentId = null;
let pollTimer = null;
let lastJobState = "idle";
let changesSearchQuery = "";
let searchIndex = [];
/** Filtres légende actifs = types masqués dans la liste. */
const legendHidden = new Set();

const page = document.body.dataset.page || "";
const t = (key, vars) => I18n.t(key, vars);

const elSessionUser = document.getElementById("session-user");
const elSessionBadge = document.getElementById("session-badge");
const elSub = document.getElementById("header-sub");
let latestSession = null;

const configForm = document.getElementById("config-form");
const elCfgSessionid = document.getElementById("cfg-sessionid");
const elCfgDsUserId = document.getElementById("cfg-ds-user-id");
const elCfgNInput = document.getElementById("cfg-n-input");
const elCfgWatchNInput = document.getElementById("cfg-watch-n-input");
const elCfgWatchFollowing = document.getElementById("cfg-watch-following");
const elCfgRefetchMutuals = document.getElementById("cfg-refetch-mutuals");
const elCfgSkipUnchanged = document.getElementById("cfg-skip-unchanged");
const elCfgPartialFetch = document.getElementById("cfg-partial-fetch");
const elCfgPageSleep = document.getElementById("cfg-page-sleep");
const elCfgPageSize = document.getElementById("cfg-page-size");
const elCfgScheduleInterval = document.getElementById("cfg-schedule-interval");
const elCfgAutostart = document.getElementById("cfg-autostart");
const elCfgHost = document.getElementById("cfg-host");
const elCfgPort = document.getElementById("cfg-port");
const elConfigMsg = document.getElementById("config-msg");
const btnSaveConfig = document.getElementById("btn-save-config");
const btnTestSession = document.getElementById("btn-test-session");
const elProfileList = document.getElementById("profile-list");
const btnProfileAdd = document.getElementById("btn-profile-add");
const elProfileImportFile = document.getElementById("profile-import-file");

const elJobPanel = document.getElementById("job-panel");
const elJobTextProfiles = document.getElementById("job-text-profiles");
const elJobBarProfiles = document.getElementById("job-bar-profiles");
const elJobWatchBlock = document.getElementById("job-watch-block");
const elJobTextWatch = document.getElementById("job-text-watch");
const elJobBarWatch = document.getElementById("job-bar-watch");
const btnScan = document.getElementById("btn-scan");
const elHomeScanTitle = document.getElementById("home-scan-title");
const btnStopScan = document.getElementById("btn-stop-scan");
const btnInit = document.getElementById("btn-init");
const elWebScheduleHint = document.getElementById("web-schedule-hint");
const elWebBaselinePending = document.getElementById("web-baseline-pending");

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

const VERIFIED_BADGE =
  `<span class="badge-verified" title="Compte vérifié" aria-label="Compte vérifié">` +
  `<img src="/static/img/verified-badge.png" alt="" width="16" height="16"></span>`;

function mutualBadge() {
  return (
    `<span class="badge-mutual" title="${esc(t("changes.badgeMutual"))}">` +
    `${esc(t("changes.badgeMutual"))}</span>`
  );
}

function igUser(username, className = "change-user") {
  const u = String(username || "").replace(/^@/, "").trim();
  if (!u) return "";
  const cls = className ? ` class="${className}"` : "";
  return (
    `<a href="${igProfileUrl(u)}"${cls} target="_blank" rel="noopener noreferrer">@${esc(u)}</a>`
  );
}

function changeIdentity(c) {
  return (
    `<span class="change-user-wrap">${igUser(c.username)}</span> ` +
    `<span class="change-name">${esc(c.full_name)}</span>`
  );
}

function renderChangeLine(c, type, { showMutual = false } = {}) {
  const flags = [];
  if (showMutual && c.is_mutual) flags.push("mutual");
  if (c.is_verified) flags.push("verified");
  const trailing = [];
  if (showMutual && c.is_mutual) trailing.push(mutualBadge());
  if (c.is_verified) trailing.push(VERIFIED_BADGE);
  const trail =
    trailing.length > 0
      ? `<span class="change-trail">${trailing.join("")}</span>`
      : "";
  return (
    `<div class="change-line ${type}" data-kind="${esc(type)}" data-flags="${esc(flags.join(" "))}">` +
    `<span class="change-op"></span>` +
    `<span class="change-main">${changeIdentity(c)}</span>` +
    `${trail}` +
    `</div>`
  );
}

function lineHiddenByLegend(line) {
  if (!legendHidden.size) return false;
  const kind = line.dataset.kind || "";
  if (kind && legendHidden.has(kind)) return true;
  const flags = (line.dataset.flags || "").split(/\s+/).filter(Boolean);
  if (legendHidden.has("mutual") && flags.includes("mutual")) return true;
  if (legendHidden.has("verified") && flags.includes("verified")) return true;
  return false;
}

function syncLegendFilterButtons() {
  document.querySelectorAll(".legend-filter").forEach((btn) => {
    const key = btn.dataset.filter;
    const on = legendHidden.has(key);
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function initLegendFilters() {
  document.querySelectorAll(".legend-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.filter;
      if (!key) return;
      if (legendHidden.has(key)) legendHidden.delete(key);
      else legendHidden.add(key);
      syncLegendFilterButtons();
      applyChangesSearch();
    });
  });
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
  }).format(d);
}

async function fetchStatus() {
  const r = await fetch("/api/status");
  return r.json();
}

let scanResume = { can_resume: false };
let latestJob = { state: "idle", is_baseline: false };
let latestWebMode = document.body.dataset.webMode === "true";

function renderScanAction() {
  if (!btnScan) return;
  const resume = Boolean(scanResume?.can_resume);
  const btnKey = resume ? "actions.resumeBtn" : "actions.scanBtn";
  const titleKey = resume ? "actions.resumeTitle" : "actions.title";
  btnScan.dataset.i18n = btnKey;
  btnScan.textContent = t(btnKey);
  if (elHomeScanTitle) {
    elHomeScanTitle.dataset.i18n = titleKey;
    elHomeScanTitle.textContent = t(titleKey);
  }
}

function renderWebSchedule(status) {
  if (!elWebScheduleHint && !elWebBaselinePending) return;
  const sched = status?.scan_schedule;
  if (elWebScheduleHint && sched) {
    elWebScheduleHint.textContent = t("webSchedule.hint", {
      hour: sched.daily_hour,
      tz: sched.timezone_label || sched.timezone,
    });
  }
  if (elWebBaselinePending) {
    elWebBaselinePending.classList.toggle("hidden", !status?.pending_baseline);
  }
}

async function refreshScanAction() {
  try {
    const status = await fetchStatus();
    latestWebMode = Boolean(status.web_mode);
    latestJob = status.job || latestJob;
    scanResume = status.scan_resume || { can_resume: false };
    renderScanAction();
    renderWebSchedule(status);
    if (page === "changes") renderHistory();
    return status;
  } catch {
    return null;
  }
}

function setControlsDisabled(disabled) {
  [btnScan, btnInit, btnSaveConfig, btnTestSession, btnProfileAdd]
    .filter(Boolean)
    .forEach((el) => {
      el.disabled = disabled;
    });
  if (elProfileList) {
    elProfileList.querySelectorAll("button").forEach((el) => {
      el.disabled = disabled;
    });
  }
  if (btnStopScan) {
    btnStopScan.disabled = !disabled;
    btnStopScan.classList.toggle("hidden", !disabled);
  }
}

function renderSession(session) {
  latestSession = session || null;
  if (elProfileList) {
    // Sur Paramètres, le @ est rendu dans les cartes de session.
    renderProfiles(latestProfiles);
    return;
  }
  if (!elSessionUser || !elSessionBadge || !elSub) return;
  if (session?.ok) {
    elSessionUser.innerHTML = session.username
      ? igUser(session.username)
      : esc(t("session.configured"));
    elSessionBadge.className = "session-dot ok";
    elSub.textContent = session.note ? `${session.source} · ${session.note}` : session.source;
  } else {
    elSessionUser.textContent = t("session.notConnected");
    elSessionBadge.className = "session-dot err";
    elSub.textContent = session?.error || t("session.configure");
  }
}

function showConfigMsg(text, ok = true) {
  if (!elConfigMsg) return;
  elConfigMsg.textContent = text;
  elConfigMsg.className = ok ? "config-msg ok" : "config-msg err";
  elConfigMsg.classList.remove("hidden");
  setTimeout(() => elConfigMsg.classList.add("hidden"), 4000);
}

let lastLoadedSessionid = "";

function supportsTextSecurity() {
  try {
    return (
      typeof CSS !== "undefined" &&
      CSS.supports &&
      CSS.supports("-webkit-text-security", "disc")
    );
  } catch {
    return false;
  }
}

function setSecretValue(input, value, { masked = true } = {}) {
  if (!input) return;
  const v = value || "";
  input.classList.toggle("is-secret-masked", masked);
  if (supportsTextSecurity()) {
    input.type = "text";
  } else {
    input.type = masked ? "password" : "text";
  }
  input.value = v;
  // Re-applique au cas où le navigateur a vidé le champ.
  queueMicrotask(() => {
    if (input.value !== v) input.value = v;
  });
}

function syncWatchFollowingUi() {
  if (!elCfgWatchFollowing || !elCfgWatchNInput) return;
  const enabled = elCfgWatchFollowing.checked;
  elCfgWatchNInput.disabled = !enabled;
  elCfgWatchNInput.closest(".field")?.classList.toggle("is-disabled", !enabled);
}

function fillConfigForm(config) {
  if (!configForm) return;
  elCfgNInput.value = String(config.n ?? "MAX");
  elCfgWatchNInput.value = String(config.watch_n ?? "MAX");
  if (elCfgWatchFollowing) {
    elCfgWatchFollowing.checked = config.watch_following !== false;
  }
  if (elCfgRefetchMutuals) {
    elCfgRefetchMutuals.checked = Boolean(config.refetch_mutuals);
  }
  if (elCfgSkipUnchanged) {
    elCfgSkipUnchanged.checked = config.skip_unchanged_profiles !== false;
  }
  if (elCfgPartialFetch) {
    elCfgPartialFetch.checked = config.partial_fetch !== false;
  }
  syncWatchFollowingUi();
  elCfgPageSleep.value = config.page_sleep;
  elCfgPageSize.value = config.page_size ?? 200;
  if (elCfgScheduleInterval) {
    elCfgScheduleInterval.value = config.schedule_interval_minutes ?? 0;
  }
  if (elCfgAutostart) {
    elCfgAutostart.checked = Boolean(config.autostart_on_boot);
  }
  if (elCfgHost) elCfgHost.value = config.host || "127.0.0.1";
  if (elCfgPort) elCfgPort.value = config.port || 1488;
  elCfgSessionid.placeholder = t("settings.sessionPaste");
  elCfgDsUserId.placeholder = t("settings.userIdPaste");
  lastLoadedSessionid = config.sessionid || "";
  const sidMasked = elCfgSessionid?.classList.contains("is-secret-masked") !== false;
  const uidMasked = elCfgDsUserId?.classList.contains("is-secret-masked") !== false;
  setSecretValue(elCfgSessionid, lastLoadedSessionid, { masked: sidMasked });
  setSecretValue(elCfgDsUserId, config.ds_user_id || "", { masked: uidMasked });
  // Sync bouton œil
  document.querySelectorAll("[data-secret-toggle]").forEach((btn) => {
    const id = btn.getAttribute("data-secret-toggle");
    const input = id ? document.getElementById(id) : null;
    if (!input) return;
    const shown = !input.classList.contains("is-secret-masked") && input.type !== "password";
    btn.setAttribute("aria-pressed", shown ? "true" : "false");
  });
}

function initSecretToggles() {
  document.querySelectorAll("[data-secret-toggle]").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-secret-toggle");
      const input = id ? document.getElementById(id) : null;
      if (!input) return;
      const currentlyMasked =
        input.classList.contains("is-secret-masked") || input.type === "password";
      const showPlain = currentlyMasked;
      setSecretValue(input, input.value, { masked: !showPlain });
      btn.setAttribute("aria-pressed", showPlain ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        t(showPlain ? "settings.hideSecret" : "settings.showSecret")
      );
    });
  });
}

let latestProfiles = [];

function renderProfiles(profiles) {
  if (!elProfileList) return;
  const list = Array.isArray(profiles) ? profiles : [];
  latestProfiles = list;
  const liveUser =
    latestSession?.ok && latestSession.username
      ? String(latestSession.username).replace(/^@/, "")
      : "";
  elProfileList.innerHTML = list
    .map((p) => {
      const pending = Boolean(p.pending);
      const user =
        (!pending && p.active && liveUser) || p.ig_username || p.username || "";
      const connected = Boolean(user) || Boolean(p.sessionid_set) ||
        (!pending && p.active && latestSession?.ok);
      const userHtml = user
        ? igUser(user, "session-user")
        : connected
          ? `<span class="session-user">${esc(t("session.configured"))}</span>`
          : `<span class="session-user is-empty">${esc(t("session.notConnected"))}</span>`;
      const ok = connected;
      const del =
        !pending && list.length > 1 && !p.active
          ? `<button type="button" class="profile-delete" data-profile-delete="${esc(p.id)}" title="${esc(t("session.delete"))}" aria-label="${esc(t("session.delete"))}">×</button>`
          : "";
      const actions = pending
        ? ""
        : `<div class="profile-actions">` +
          `<button type="button" class="btn btn-ghost btn-sm" data-profile-export="${esc(p.id)}">${esc(t("session.export"))}</button>` +
          `<button type="button" class="btn btn-ghost btn-sm" data-profile-import="${esc(p.id)}">${esc(t("session.import"))}</button>` +
          `</div>`;
      return (
        `<li class="profile-card${p.active ? " is-active" : ""}${pending ? " is-pending" : ""}" data-profile-id="${esc(p.id)}">` +
        `<div class="profile-head">` +
        `<button type="button" class="profile-select" data-profile-id="${esc(p.id)}"${pending ? " disabled" : ""}>` +
        `<span class="session-dot ${ok ? "ok" : "err"}" aria-hidden="true"></span>` +
        `<span class="profile-select-main">${userHtml}</span>` +
        `</button>${del}</div>${actions}</li>`
      );
    })
    .join("");
}

async function applyProfilePayload(data) {
  if (data.config) fillConfigForm(data.config);
  if (data.session) renderSession(data.session);
  if (data.profiles) renderProfiles(data.profiles);
  if (page === "changes" && typeof loadScans === "function") {
    await loadScans();
  }
}

async function switchProfile(id) {
  const res = await fetch("/api/profiles/active", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || t("session.switchError"), false);
    return;
  }
  await applyProfilePayload(await res.json());
  showConfigMsg(t("session.switched"));
}

async function addProfile() {
  if (btnProfileAdd?.disabled) return;
  if (btnProfileAdd) btnProfileAdd.disabled = true;

  const previous = latestProfiles.map((p) => ({ ...p }));
  renderProfiles([
    ...previous,
    {
      id: "__pending__",
      label: "",
      active: false,
      username: "",
      ig_username: "",
      sessionid_set: false,
      pending: true,
    },
  ]);

  try {
    const res = await fetch("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "" }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      renderProfiles(previous);
      showConfigMsg(err.detail || t("session.addError"), false);
      return;
    }
    const data = await res.json();
    if (data.profiles) renderProfiles(data.profiles);
    showConfigMsg(t("session.added"));
  } catch {
    renderProfiles(previous);
    showConfigMsg(t("session.addError"), false);
  } finally {
    if (btnProfileAdd) btnProfileAdd.disabled = false;
  }
}

async function removeProfile(id) {
  const ok = await askConfirm(t("session.deleteTitle"), t("session.deleteMsg"));
  if (!ok) return;
  const res = await fetch(`/api/profiles/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || t("session.deleteError"), false);
    return;
  }
  const data = await res.json();
  renderProfiles(data.profiles);
  showConfigMsg(t("session.deleted"));
}

async function exportProfile(id) {
  if (!id) {
    showConfigMsg(t("session.exportError"), false);
    return;
  }
  const url = `/api/profiles/${encodeURIComponent(id)}/export`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || t("session.exportError"), false);
    return;
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || "instree-session.zip";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
  showConfigMsg(t("session.exported"));
}

async function importProfileFile(file) {
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  body.append("activate", "true");
  const res = await fetch("/api/profiles/import", { method: "POST", body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showConfigMsg(err.detail || t("session.importError"), false);
    return;
  }
  await applyProfilePayload(await res.json());
  showConfigMsg(t("session.imported"));
}

async function loadConfig() {
  if (!configForm) return null;
  const config = await fetch("/api/config").then((r) => r.json());
  fillConfigForm(config);
  return config;
}

async function refreshSessionUi() {
  const status = await fetchStatus();
  renderSession(status.session);
  renderProfiles(status.profiles || []);
  return status;
}

async function resolveIgUsername() {
  const session = await fetch("/api/session/test", { method: "POST" }).then((r) =>
    r.json()
  );
  renderSession(session);
  if (session.ok) {
    const status = await fetchStatus();
    renderProfiles(status.profiles || []);
  } else {
    await refreshSessionUi();
  }
  return session;
}

function buildConfigBody() {
  return {
    username: "",
    n: elCfgNInput.value.trim(),
    watch_n: elCfgWatchNInput.value.trim(),
    max_person_following: "MAX",
    page_sleep: Number(elCfgPageSleep.value),
    page_size: Number(elCfgPageSize.value),
    host: elCfgHost?.value?.trim() || "127.0.0.1",
    port: Number(elCfgPort?.value || 1488),
    autostart_on_boot: Boolean(elCfgAutostart?.checked),
    schedule_interval_minutes: Number(elCfgScheduleInterval?.value || 0),
    watch_following: Boolean(elCfgWatchFollowing?.checked),
    refetch_mutuals: Boolean(elCfgRefetchMutuals?.checked),
    skip_unchanged_profiles: Boolean(elCfgSkipUnchanged?.checked),
    partial_fetch: Boolean(elCfgPartialFetch?.checked),
    sessionid: elCfgSessionid.value.trim(),
    ds_user_id: elCfgDsUserId.value.trim(),
  };
}

async function persistConfigFromForm() {
  const res = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildConfigBody()),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || t("settings.saveError"));
  }
  const data = await res.json();
  fillConfigForm(data.config);
  await refreshSessionUi();
  return data;
}

async function saveConfig(e) {
  e.preventDefault();
  const pastedSession = elCfgSessionid.value.trim();
  const sessionChanged =
    Boolean(pastedSession) && pastedSession !== lastLoadedSessionid;
  try {
    await persistConfigFromForm();
  } catch (err) {
    showConfigMsg(err.message || t("settings.saveError"), false);
    return;
  }
  showConfigMsg(t("settings.saved"));

  // Nouveau sessionid collé → résoudre le @ Instagram pour la carte Session.
  if (sessionChanged) {
    const session = await resolveIgUsername();
    if (session.ok && session.username) {
      showConfigMsg(t("settings.connectedAs", { user: session.username }));
    } else if (!session.ok) {
      showConfigMsg(session.error || t("settings.connectionFailed"), false);
    }
  }
}

function askConfirm(title, message) {
  if (!dialog || !confirmTitle || !confirmMessage) {
    return Promise.resolve(window.confirm(`${title}\n\n${message}`));
  }
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
  const lines = items.map((c) => renderChangeLine(c, type)).join("");
  return `<div class="changes-group"><div class="changes-group-title">${title}</div>${lines}</div>`;
}

function personDeltaBadge(g) {
  const addN = g.adds?.length || 0;
  const remN = g.removes?.length || 0;
  if (!addN && !remN) return "";
  const parts = [];
  if (addN) parts.push(`<span class="person-delta-add">+${addN}</span>`);
  if (remN) parts.push(`<span class="person-delta-remove">−${remN}</span>`);
  return ` <span class="person-delta">(${parts.join(" ")})</span>`;
}

function renderPersonSection(groups) {
  const blocks = groups
    .map((g) => {
      const title =
        `<div class="person-group-title">` +
        igUser(g.username, "person-subject") +
        personDeltaBadge(g) +
        `</div>`;
      const lines = [];
      for (const a of g.adds) {
        lines.push(renderChangeLine(a, "add", { showMutual: true }));
      }
      for (const r of g.removes) {
        lines.push(renderChangeLine(r, "remove", { showMutual: true }));
      }
      for (const x of g.gones || []) {
        lines.push(renderChangeLine(x, "gone", { showMutual: true }));
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
  if (detail.adds.length) mutualSections.push(renderGroup(t("changes.newMutuals"), detail.adds, "list-add"));
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

function normalizeSearch(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/^@/, "")
    .trim();
}

function matchesChangesSearch(text) {
  const q = normalizeSearch(changesSearchQuery);
  if (!q) return true;
  return normalizeSearch(text).includes(q);
}

function rowMatchesSearch(row) {
  return (
    matchesChangesSearch(row.username) ||
    matchesChangesSearch(row.full_name) ||
    matchesChangesSearch(row.subject_username || "")
  );
}

function scanIdsMatchingSearch() {
  const q = normalizeSearch(changesSearchQuery);
  if (!q) return null;
  const ids = new Set();
  for (const row of searchIndex) {
    if (rowMatchesSearch(row)) ids.add(row.scan_id);
  }
  return ids;
}

function applyHistorySearchFilter() {
  if (!elHistory) return;
  const matchIds = scanIdsMatchingSearch();
  elHistory.querySelectorAll(".history-item").forEach((btn) => {
    const id = Number(btn.dataset.id);
    const hit = !matchIds || matchIds.has(id);
    btn.classList.toggle("search-miss", Boolean(matchIds) && !hit);
    btn.classList.toggle("search-hit", Boolean(matchIds) && hit);
  });
}

function applyChangesSearch() {
  if (!elContent) return;
  const q = changesSearchQuery.trim();
  const searchActive = q.length > 0;
  const legendActive = legendHidden.size > 0;
  const filtering = searchActive || legendActive;

  elContent.querySelectorAll(".change-line").forEach((line) => {
    const hay = line.textContent || "";
    const hideSearch = searchActive && !matchesChangesSearch(hay);
    const hideLegend = lineHiddenByLegend(line);
    line.classList.toggle("hidden", hideSearch || hideLegend);
  });

  elContent.querySelectorAll(".person-group").forEach((group) => {
    const subject = group.querySelector(".person-group-title")?.textContent || "";
    const subjectMatch = searchActive && matchesChangesSearch(subject);
    const lines = [...group.querySelectorAll(".change-line")];
    if (subjectMatch) {
      // Sujet mutuel : garder les lignes qui matchent aussi, sinon toutes
      // (puis re-appliquer le filtre légende).
      const anyTarget = lines.some((line) =>
        matchesChangesSearch(line.textContent || ""),
      );
      lines.forEach((line) => {
        const hideSearch =
          anyTarget && !matchesChangesSearch(line.textContent || "");
        line.classList.toggle("hidden", hideSearch || lineHiddenByLegend(line));
      });
      const anyLine = lines.some((line) => !line.classList.contains("hidden"));
      group.classList.toggle("hidden", !anyLine);
      return;
    }
    const anyLine = lines.some((line) => !line.classList.contains("hidden"));
    group.classList.toggle("hidden", filtering && !anyLine);
  });

  elContent.querySelectorAll(".changes-group:not(.person-group)").forEach((group) => {
    const lines = [...group.querySelectorAll(".change-line")];
    const anyLine = lines.some((line) => !line.classList.contains("hidden"));
    group.classList.toggle("hidden", filtering && !anyLine);
  });

  elContent.querySelectorAll(".changes-card").forEach((card) => {
    const groups = [...card.querySelectorAll(".changes-group")];
    const anyGroup = groups.some((g) => !g.classList.contains("hidden"));
    card.classList.toggle("hidden", filtering && groups.length > 0 && !anyGroup);
  });

  elContent.querySelectorAll(".changes-section").forEach((section) => {
    const groups = [...section.querySelectorAll(".person-group")];
    const anyGroup = groups.some((g) => !g.classList.contains("hidden"));
    section.classList.toggle("hidden", filtering && groups.length > 0 && !anyGroup);
  });

  const layout = elContent.querySelector(".changes-layout");
  let anyVisible = false;
  if (layout) {
    anyVisible = [...layout.children].some((el) => !el.classList.contains("hidden"));
  } else if (!filtering) {
    anyVisible = true;
  }

  applyHistorySearchFilter();

  const matchIds = scanIdsMatchingSearch();
  const otherHits = matchIds
    ? [...matchIds].filter((id) => id !== currentId).sort((a, b) => b - a)
    : [];

  if (elChangesSearchEmpty) {
    const hasLayout = Boolean(layout);
    const showEmpty = filtering && hasLayout && !anyVisible;
    elChangesSearchEmpty.classList.toggle("hidden", !showEmpty);
    if (showEmpty) {
      if (searchActive && otherHits.length) {
        const links = otherHits
          .slice(0, 8)
          .map((id) => `<button type="button" class="search-scan-link" data-id="${id}">#${id}</button>`)
          .join(" ");
        elChangesSearchEmpty.innerHTML =
          `${esc(t("changes.searchEmptyOther"))} ${links}` +
          (otherHits.length > 8 ? "…" : "");
        elChangesSearchEmpty.querySelectorAll(".search-scan-link").forEach((btn) => {
          btn.onclick = () => showScan(Number(btn.dataset.id));
        });
      } else {
        elChangesSearchEmpty.textContent = t("changes.searchEmpty");
      }
    }
  }
  if (layout) {
    layout.classList.toggle("hidden", filtering && !anyVisible);
  }
}

function renderHistory() {
  if (!elHistory || !elHistoryEmpty) return;
  if (
    latestWebMode &&
    isJobActive(latestJob.state) &&
    (latestJob.is_baseline || scanResume?.is_baseline)
  ) {
    elHistoryEmpty.classList.remove("hidden");
    elHistoryEmpty.textContent = t("webSchedule.baselineInProgress");
    elHistory.innerHTML = "";
    return;
  }
  const empty = scans.length === 0;
  elHistoryEmpty.classList.toggle("hidden", !empty);
  if (empty) {
    elHistoryEmpty.textContent = t("changes.historyEmpty");
  }
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
  applyHistorySearchFilter();
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
  const [scanList, index] = await Promise.all([
    fetch("/api/scans").then((r) => r.json()),
    fetch("/api/search-index").then((r) => r.json()).catch(() => []),
  ]);
  scans = scanList;
  searchIndex = Array.isArray(index) ? index : [];
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
    latestWebMode = Boolean(status.web_mode);
    latestJob = status.job || latestJob;
    renderSession(status.session);
    renderJob(status.job);
    if (status.web_mode) renderWebSchedule(status);
    if (status.scan_resume) {
      scanResume = status.scan_resume;
      renderScanAction();
    }
    if (page === "changes") renderHistory();
  }, 800);
}

function jobMessage(job) {
  if (job.message_key === "job.rateLimited" && job.cooldown_until) {
    const secs = Math.max(0, Math.ceil(job.cooldown_until - Date.now() / 1000));
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return t("job.rateLimitedWait", {
      time: `${m}:${String(s).padStart(2, "0")}`,
    });
  }
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
    cooldown: t("job.cooldownPhase"),
    page: t("job.pagePhase"),
  };
  return map[phase] || phase;
}

function isJobActive(state) {
  return state === "running" || state === "stopping";
}

function renderJob(job) {
  if (!elJobPanel) return;
  latestJob = job || latestJob;

  if (isJobActive(job.state)) {
    setControlsDisabled(true);
    if (btnStopScan) {
      btnStopScan.disabled = job.state === "stopping";
      btnStopScan.textContent =
        job.state === "stopping" ? t("actions.stopping") : t("actions.stopScan");
      btnStopScan.classList.toggle("hidden", false);
    }
    elJobPanel.classList.remove("hidden", "job-error");

    const cooldownActive =
      job.cooldown_until && job.cooldown_until * 1000 > Date.now();

    if (elJobTextProfiles && elJobBarProfiles) {
      if (cooldownActive || job.progress_phase === "cooldown") {
        elJobTextProfiles.textContent = jobMessage({
          ...job,
          message_key: "job.rateLimited",
        });
        elJobBarProfiles.style.width = "15%";
      } else if (job.state === "stopping") {
        elJobTextProfiles.textContent = t("job.stopping");
        elJobBarProfiles.style.width = elJobBarProfiles.style.width || "40%";
      } else {
        const phase = job.progress_phase;
        if (phase === "mutuals") {
          elJobTextProfiles.textContent = t("job.loadingMutuals");
          elJobBarProfiles.style.width = "30%";
        } else if (job.progress_user) {
          const pct = job.progress_total
            ? Math.round((job.progress_current / job.progress_total) * 100)
            : 0;
          const phaseSuffix =
            phase && phase !== "profile" ? ` · ${phaseLabel(phase)}` : "";
          elJobTextProfiles.innerHTML = `[${job.progress_current}/${job.progress_total}] ${igUser(job.progress_user)}${esc(phaseSuffix)}`;
          elJobBarProfiles.style.width = `${pct}%`;
        } else {
          elJobTextProfiles.textContent = t("job.connecting");
          elJobBarProfiles.style.width = "5%";
        }
      }
    }

    const watchActive =
      !cooldownActive &&
      job.state !== "stopping" &&
      job.watch_user &&
      (job.watch_phase === "baseline" ||
        job.watch_phase === "fetch" ||
        job.watch_phase === "page");
    if (elJobWatchBlock) {
      elJobWatchBlock.classList.toggle("hidden", !watchActive);
    }
    if (watchActive && elJobTextWatch && elJobBarWatch) {
      const total = Number(job.watch_total) || 0;
      const current = Number(job.watch_current) || 0;
      const pct = total
        ? Math.round((current / total) * 100)
        : current > 0
          ? 50
          : 0;
      const phaseSuffix = job.watch_phase ? ` · ${phaseLabel(job.watch_phase)}` : "";
      const counter = total > 0 ? `[${current}/${total}]` : `[${current}]`;
      elJobTextWatch.innerHTML = `${igUser(job.watch_user)} ${counter}${esc(phaseSuffix)}`;
      elJobBarWatch.style.width = `${Math.min(pct, 100)}%`;
    }

    const justStarted = !isJobActive(lastJobState);
    startPolling();
    if (justStarted && page === "changes") {
      void loadScans();
    }
    if (page === "changes") renderHistory();
    lastJobState = job.state;
    return;
  }

  setControlsDisabled(false);
  if (btnStopScan) btnStopScan.textContent = t("actions.stopScan");
  stopPolling();

  const msg = jobMessage(job);
  const wasActive = isJobActive(lastJobState);

  if (["done", "error", "cancelled"].includes(job.state) && wasActive) {
    void refreshScanAction();
  }

  if (job.state === "done" && wasActive) {
    elJobPanel.classList.remove("hidden");
    if (elJobBarProfiles) elJobBarProfiles.style.width = "100%";
    if (elJobTextProfiles) elJobTextProfiles.textContent = msg;
    if (elJobWatchBlock) elJobWatchBlock.classList.add("hidden");
    lastJobState = "done";
    if (page === "changes") void loadScans();
    setTimeout(() => {
      elJobPanel.classList.add("hidden");
      fetch("/api/scan/reset", { method: "POST" });
    }, 3000);
  } else if (
    ["done", "error", "cancelled"].includes(job.state) &&
    !wasActive &&
    !isJobActive(lastJobState)
  ) {
    elJobPanel.classList.add("hidden");
    void fetch("/api/scan/reset", { method: "POST" });
    lastJobState = "idle";
  } else if (job.state === "error" && wasActive) {
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
    }, 8000);
  } else if (job.state === "cancelled" && wasActive) {
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
  if (body.init && page === "changes") {
    currentId = null;
    await loadScans();
  }
}

let watchBlacklistMutuals = [];
let watchBlacklistSaveTimer = 0;

function syncBlacklistSummary() {
  const elSummary = document.getElementById("blacklist-summary");
  if (!elSummary) return;
  const total = watchBlacklistMutuals.length;
  const excluded = watchBlacklistMutuals.filter((m) => m.blacklisted).length;
  elSummary.textContent = total
    ? t("settings.blacklistSummary", { excluded, total })
    : "";
}

function renderWatchBlacklist() {
  const elList = document.getElementById("blacklist-list");
  const elEmpty = document.getElementById("blacklist-empty");
  const elSearch = document.getElementById("blacklist-search");
  if (!elList) return;
  const q = String(elSearch?.value || "")
    .trim()
    .toLowerCase()
    .replace(/^@/, "");
  const rows = watchBlacklistMutuals.filter((m) => {
    if (!q) return true;
    const u = String(m.username || "").toLowerCase();
    const n = String(m.full_name || "").toLowerCase();
    return u.includes(q) || n.includes(q);
  });
  elEmpty?.classList.toggle("hidden", watchBlacklistMutuals.length > 0);
  elList.innerHTML = rows
    .map((m) => {
      const user = esc(m.username);
      const name = m.full_name ? esc(m.full_name) : "";
      const count = Number(m.following_count || 0);
      const countLabel = count
        ? esc(t("settings.blacklistFollowing", { n: count }))
        : "";
      const sub = [name, countLabel].filter(Boolean).join(" · ");
      const checked = m.blacklisted ? " checked" : "";
      const excluded = m.blacklisted ? " is-excluded" : "";
      return (
        `<li>` +
        `<label class="blacklist-item${excluded}">` +
        `<input type="checkbox" data-blacklist-user="${user}"${checked}>` +
        `<span class="blacklist-meta">` +
        `<span class="blacklist-user">@${user}</span>` +
        (sub ? `<span class="blacklist-sub">${sub}</span>` : "") +
        `</span>` +
        `</label>` +
        `</li>`
      );
    })
    .join("");
  syncBlacklistSummary();
}

async function persistWatchBlacklist() {
  const usernames = watchBlacklistMutuals
    .filter((m) => m.blacklisted)
    .map((m) => m.username);
  const res = await fetch("/api/watch-blacklist", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usernames }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || t("settings.blacklistSaveError"));
  }
}

function scheduleWatchBlacklistSave() {
  clearTimeout(watchBlacklistSaveTimer);
  watchBlacklistSaveTimer = setTimeout(async () => {
    const elMsg = document.getElementById("blacklist-msg") || document.getElementById("config-msg");
    try {
      await persistWatchBlacklist();
      if (elMsg) {
        elMsg.textContent = t("settings.blacklistSaved");
        elMsg.classList.remove("hidden", "is-err");
        elMsg.classList.add("is-ok");
      } else {
        showConfigMsg(t("settings.blacklistSaved"));
      }
    } catch (err) {
      const msg = err.message || t("settings.blacklistSaveError");
      if (elMsg) {
        elMsg.textContent = msg;
        elMsg.classList.remove("hidden", "is-ok");
        elMsg.classList.add("is-err");
      } else {
        showConfigMsg(msg, false);
      }
    }
  }, 350);
}

async function initWatchBlacklist() {
  const elList = document.getElementById("blacklist-list");
  const elSearch = document.getElementById("blacklist-search");
  if (!elList) return;
  try {
    const data = await fetch("/api/mutuals").then((r) => r.json());
    watchBlacklistMutuals = Array.isArray(data.mutuals) ? data.mutuals : [];
  } catch {
    watchBlacklistMutuals = [];
  }
  renderWatchBlacklist();
  if (elSearch && !elSearch.dataset.bound) {
    elSearch.dataset.bound = "1";
    elSearch.addEventListener("input", () => renderWatchBlacklist());
  }
  if (!elList.dataset.bound) {
    elList.dataset.bound = "1";
    elList.addEventListener("change", (e) => {
      const input = e.target.closest("input[data-blacklist-user]");
      if (!input) return;
      const user = String(input.dataset.blacklistUser || "").toLowerCase();
      const row = watchBlacklistMutuals.find(
        (m) => String(m.username || "").toLowerCase() === user,
      );
      if (!row) return;
      row.blacklisted = Boolean(input.checked);
      renderWatchBlacklist();
      scheduleWatchBlacklistSave();
    });
  }
}

async function initSettingsPage() {
  initSecretToggles();
  if (elCfgWatchFollowing) {
    elCfgWatchFollowing.addEventListener("change", syncWatchFollowingUi);
  }
  await loadConfig();
  if (configForm) configForm.addEventListener("submit", saveConfig);
  if (btnProfileAdd) btnProfileAdd.onclick = () => addProfile();
  if (elProfileImportFile) {
    elProfileImportFile.addEventListener("change", async () => {
      const file = elProfileImportFile.files?.[0];
      elProfileImportFile.value = "";
      if (file) await importProfileFile(file);
    });
  }
  if (elProfileList) {
    elProfileList.addEventListener("click", (e) => {
      const del = e.target.closest("[data-profile-delete]");
      if (del) {
        removeProfile(del.dataset.profileDelete);
        return;
      }
      const exp = e.target.closest("[data-profile-export]");
      if (exp) {
        exportProfile(exp.dataset.profileExport);
        return;
      }
      const imp = e.target.closest("[data-profile-import]");
      if (imp) {
        elProfileImportFile?.click();
        return;
      }
      const card = e.target.closest(".profile-card");
      const sel = e.target.closest(".profile-select");
      if (sel && card && !card.classList.contains("is-active")) {
        switchProfile(card.dataset.profileId || sel.dataset.profileId);
      }
    });
  }
  if (btnTestSession) {
    const labelEl =
      btnTestSession.querySelector(".btn-test-label") || btnTestSession;
    let testBtnResetTimer = 0;
    const setTestBtnState = (state) => {
      btnTestSession.classList.remove("is-ok", "is-err", "is-testing");
      if (state) btnTestSession.classList.add(`is-${state}`);
      if (state === "testing") {
        labelEl.textContent = t("settings.testing");
      } else if (state === "ok") {
        labelEl.textContent = t("settings.testOk");
      } else if (state === "err") {
        labelEl.textContent = t("settings.testFail");
      } else {
        labelEl.textContent = t("settings.testSession");
      }
    };

    btnTestSession.onclick = async () => {
      clearTimeout(testBtnResetTimer);
      btnTestSession.disabled = true;
      setTestBtnState("testing");
      try {
        try {
          await persistConfigFromForm();
        } catch (err) {
          setTestBtnState("err");
          showConfigMsg(err.message || t("settings.saveError"), false);
          return;
        }
        const session = await resolveIgUsername();
        await loadConfig();
        if (session.ok) {
          setTestBtnState("ok");
          if (session.note) showConfigMsg(session.note);
          else showConfigMsg(t("settings.connectedAs", { user: session.username }));
        } else {
          setTestBtnState("err");
          showConfigMsg(session.error || t("settings.connectionFailed"), false);
        }
      } catch {
        setTestBtnState("err");
        showConfigMsg(t("settings.connectionFailed"), false);
      } finally {
        btnTestSession.disabled = false;
        // Garde le V / X un moment, puis revient au libellé normal.
        testBtnResetTimer = setTimeout(() => setTestBtnState(null), 4000);
      }
    };
  }

  // Cookies déjà là mais @ pas encore mémorisé → résoudre une fois.
  const st = await fetchStatus();
  const active = (st.profiles || []).find((p) => p.active);
  if (
    st.config?.sessionid_set &&
    !st.session?.username &&
    !active?.ig_username
  ) {
    await resolveIgUsername();
  }
}

async function initChangesPage() {
  await loadScans();
  await refreshScanAction();
  if (btnScan) {
    btnScan.onclick = async () => {
      const resume = Boolean(scanResume?.can_resume);
      const ok = await askConfirm(
        t(resume ? "actions.confirmResumeTitle" : "actions.confirmScanTitle"),
        t(resume ? "actions.confirmResumeMsg" : "actions.confirmScanMsg"),
      );
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
  initLegendFilters();
  syncLegendFilterButtons();
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
  renderScanAction();
  if (page === "settings") loadConfig();
  if (page === "changes") {
    void fetchStatus().then((st) => {
      latestWebMode = Boolean(st.web_mode);
      latestJob = st.job || latestJob;
      renderWebSchedule(st);
      renderHistory();
    });
    if (currentId) showScan(currentId);
    else loadScans();
  }
  if (btnStopScan && !btnStopScan.disabled) btnStopScan.textContent = t("actions.stopScan");
}

function initProfileMenu() {
  const menu = document.getElementById("profile-menu");
  const trigger = document.getElementById("profile-menu-trigger");
  const panel = document.getElementById("profile-menu-panel");
  const logoutBtn = document.getElementById("btn-logout");
  if (!menu || !trigger || !panel) return;

  const setOpen = (open) => {
    menu.classList.toggle("is-open", open);
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
    panel.hidden = !open;
  };

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(panel.hidden);
  });

  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target)) setOpen(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") setOpen(false);
  });

  if (logoutBtn) {
    logoutBtn.onclick = async () => {
      setOpen(false);
      await fetch("/api/auth/logout", { method: "POST" });
      location.href = "/login";
    };
  }
}

async function init() {
  await I18n.ready;
  initLangSwitch();
  initProfileMenu();
  window.addEventListener("instree:locale", onLocaleChange);

  let status = await fetchStatus();
  if (["done", "error", "cancelled"].includes(status.job?.state)) {
    await fetch("/api/scan/reset", { method: "POST" });
    status = await fetchStatus();
  }
  latestWebMode = Boolean(status.web_mode);
  latestJob = status.job || latestJob;
  lastJobState = isJobActive(status.job?.state) ? status.job.state : "idle";
  renderSession(status.session);
  renderProfiles(status.profiles || []);
  renderJob(status.job);
  renderWebSchedule(status);

  if (page === "settings") await initSettingsPage();
  // blacklist page: dedicated exclusions UI (not embedded in settings form)
  if (page === "blacklist") {
    await I18n.ready;
    I18n.applyI18n();
    await initWatchBlacklist();
  }
  if (page === "changes") await initChangesPage();
}

init();
