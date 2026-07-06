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
  elMeta.textContent = `Scan #${scan.id} · ${neighbors.index + 1}/${neighbors.total}`;

  btnPrev.disabled = neighbors.prev_id == null;
  btnNext.disabled = neighbors.next_id == null;

  btnPrev.onclick = () => neighbors.prev_id && showScan(neighbors.prev_id);
  btnNext.onclick = () => neighbors.next_id && showScan(neighbors.next_id);

  renderDetail(detail);
}

function renderDetail(detail) {
  const withChanges = detail.snapshots_enriched.filter(
    (s) => s.adds.length || s.removes.length,
  );

  if (!detail.has_changes || withChanges.length === 0) {
    elContent.innerHTML = '<p class="empty">Aucun changement d\'abonnement ce scan.</p>';
    return;
  }

  elContent.innerHTML = withChanges
    .map((s) => {
      const oldC = s.old_count != null ? s.old_count : "?";
      const header = `@${s.friend_username} <span class="count">(${oldC} → ${s.following_count})</span>`;
      const adds = s.adds
        .map((c) => `<div class="change-line add">+ @${c.target_username}  ${escapeHtml(c.full_name)}</div>`)
        .join("");
      const removes = s.removes
        .map((c) => `<div class="change-line remove">- @${c.target_username}  ${escapeHtml(c.full_name)}</div>`)
        .join("");
      return `<section class="friend-block"><div class="friend-header">${header}</div>${adds}${removes}</section>`;
    })
    .join("");
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
