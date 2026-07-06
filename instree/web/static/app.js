let scans = [];
let currentId = null;

const elDate = document.getElementById("scan-date");
const elMeta = document.getElementById("scan-meta");
const elContent = document.getElementById("content");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");

async function loadScans() {
  scans = await fetch("/api/scans").then((r) => r.json());
  if (scans.length === 0) {
    elDate.textContent = "Aucun scan";
    elMeta.textContent = "Lance uv run instree scan --init";
    elContent.innerHTML = '<p class="empty">Pas encore de données.</p>';
    btnPrev.disabled = btnNext.disabled = true;
    return;
  }
  await showScan(scans[scans.length - 1].id);
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
    `#${scan.id} · ${neighbors.index + 1}/${neighbors.total}`;

  btnPrev.disabled = neighbors.prev_id == null;
  btnNext.disabled = neighbors.next_id == null;
  btnPrev.onclick = () => neighbors.prev_id && showScan(neighbors.prev_id);
  btnNext.onclick = () => neighbors.next_id && showScan(neighbors.next_id);

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
    .map(
      (c) =>
        `<div class="change-line add">+ @${c.username}  ${escapeHtml(c.full_name)}</div>`,
    )
    .join("");
  const counts = detail.counts
    .map(
      (c) =>
        `<div class="change-line count">~ @${c.username}  ` +
        `${c.old_count} → ${c.new_count} abonnements</div>`,
    )
    .join("");
  const removes = detail.removes
    .map(
      (c) =>
        `<div class="change-line remove">- @${c.username}  ${escapeHtml(c.full_name)}</div>`,
    )
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

document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") btnPrev.click();
  if (e.key === "ArrowRight") btnNext.click();
});

loadScans();
