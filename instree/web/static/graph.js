(() => {
  const hasI18n = () => typeof I18n !== "undefined";
  const t = (key, vars) => (hasI18n() ? I18n.t(key, vars) : key);
  const elCanvas = document.getElementById("graph-canvas");
  const elEmpty = document.getElementById("graph-empty");
  const elPanel = document.getElementById("graph-panel");
  const elStage = document.getElementById("graph-stage");
  const elBtnFullscreen = document.getElementById("graph-btn-fullscreen");
  const elSearchForm = document.getElementById("graph-search-form");
  const elSearchInput = document.getElementById("graph-search-input");
  const elSearchMsg = document.getElementById("graph-search-msg");

  const STORAGE_KEY = "instree.graph.display";

  const DEFAULT_SETTINGS = {
    showRoot: true,
    showIsolates: true,
    showLabels: true,
    showIntraLinks: true,
    showLinks: true,
    hiddenClusters: [],
    nodeSize: 1.2,
    linkOpacity: 0.35,
    linkWidth: 0.6,
    ringScale: 0.5,
    spacingScale: 1.0,
    targetGroups: 0,
  };

  let graph = null;
  let resizeHandler = null;
  let rawGraphData = null;
  let rawLinks = [];
  let layoutCenters = null;
  let clusterMeta = [];
  let maxGroups = 20;
  let settings = loadSettings();
  let panelBound = false;
  let reloadTimer = null;

  function clamp(val, min, max) {
    return Math.min(max, Math.max(min, val));
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { ...DEFAULT_SETTINGS, hiddenClusters: [] };
      const parsed = JSON.parse(raw);
      return {
        ...DEFAULT_SETTINGS,
        ...parsed,
        hiddenClusters: Array.isArray(parsed.hiddenClusters) ? parsed.hiddenClusters : [],
        showIntraLinks: parsed.showIntraLinks ?? true,
        targetGroups: Math.max(0, Number(parsed.targetGroups) || 0),
        linkOpacity: clamp(parsed.linkOpacity ?? DEFAULT_SETTINGS.linkOpacity, 0, 1),
        ringScale: clamp(parsed.ringScale ?? DEFAULT_SETTINGS.ringScale, 0.2, 1),
        spacingScale: clamp(parsed.spacingScale ?? DEFAULT_SETTINGS.spacingScale, 0.5, 1),
      };
    } catch {
      return { ...DEFAULT_SETTINGS, hiddenClusters: [] };
    }
  }

  function saveSettings() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* ignore quota errors */
    }
  }

  function destroyGraph() {
    if (resizeHandler) {
      window.removeEventListener("resize", resizeHandler);
      resizeHandler = null;
    }
    if (graph) {
      graph._destructor?.();
      graph = null;
    }
    if (elCanvas) elCanvas.innerHTML = "";
  }

  function nodeStepForGroup(size, spacingScale = 1) {
    const MIN = 14;
    return (MIN + Math.sqrt(size) * 4.5) * spacingScale;
  }

  function footprintForGroup(size, spacingScale = 1) {
    const step = nodeStepForGroup(size, spacingScale);
    return step * Math.sqrt(size) + 28;
  }

  function buildClusterLayout(nodes, { ringScale = 0.5, spacingScale = 1 } = {}) {
    const byCluster = new Map();
    for (const n of nodes) {
      if (n.group === "root") continue;
      if (!byCluster.has(n.cluster)) byCluster.set(n.cluster, []);
      byCluster.get(n.cluster).push(n);
    }

    const keys = [...byCluster.keys()].sort((a, b) => {
      if (a === -1) return 1;
      if (b === -1) return -1;
      return byCluster.get(b).length - byCluster.get(a).length || a - b;
    });

    const centers = new Map();
    const GROUP_GAP = 90;
    const ROOT_CLEAR = 36;
    const GOLDEN = Math.PI * (3 - Math.sqrt(5));

    const socialKeys = keys.filter((k) => k !== -1);
    const isolateKeys = keys.filter((k) => k === -1);

    const metaOf = (key) => {
      const count = byCluster.get(key).length;
      const nodeStep = nodeStepForGroup(count, spacingScale);
      const footprint = footprintForGroup(count, spacingScale);
      return { key, count, nodeStep, footprint, color: byCluster.get(key)[0]?.color };
    };

    const social = socialKeys.map(metaOf);
    const isolates = isolateKeys.map(metaOf);

    function placeOnRing(items, baseR) {
      if (!items.length) return;
      const gapHalf = GROUP_GAP / 2;
      const maxFp = Math.max(...items.map((m) => m.footprint));
      let R = baseR;

      const totalAngleAt = (r) =>
        items.reduce(
          (sum, m) => sum + 2 * Math.asin(Math.min(1, (m.footprint + gapHalf) / r)),
          0,
        );

      const sumChord = items.reduce((s, m) => s + m.footprint + gapHalf, 0);
      R = Math.max(R, ROOT_CLEAR + maxFp + 52, sumChord / Math.PI);

      while (totalAngleAt(R) > 2 * Math.PI - 0.15) R += 12;

      items.sort((a, b) => b.footprint - a.footprint);
      let angle = -Math.PI / 2;
      for (const m of items) {
        const sector = 2 * Math.asin(Math.min(1, (m.footprint + gapHalf) / R));
        const a = angle + sector / 2;
        angle += sector + 0.12;
        m.x = Math.cos(a) * R;
        m.y = Math.sin(a) * R;
        m.r = R;
      }
    }

    const maxSocialFp = social.length ? Math.max(...social.map((m) => m.footprint)) : 0;
    placeOnRing(social, ROOT_CLEAR + maxSocialFp + 58);

    if (isolates.length) {
      const innerR = social.length ? social[0].r : ROOT_CLEAR + 80;
      const maxIsoFp = Math.max(...isolates.map((m) => m.footprint));
      placeOnRing(isolates, innerR + maxIsoFp + GROUP_GAP);
    }

    for (const m of [...social, ...isolates]) {
      m.x *= ringScale;
      m.y *= ringScale;
      m.r *= ringScale;
    }

    for (const m of [...social, ...isolates]) {
      centers.set(m.key, {
        x: m.x,
        y: m.y,
        size: m.count,
        color: m.color || "#60a5fa",
        footprint: m.footprint,
        nodeStep: m.nodeStep,
      });
    }

    for (const [key, members] of byCluster) {
      const c = centers.get(key);
      const step = c.nodeStep;
      members.forEach((n, j) => {
        const angle = j * GOLDEN;
        const jr = step * Math.sqrt(j + 1);
        n.x = c.x + Math.cos(angle) * jr;
        n.y = c.y + Math.sin(angle) * jr;
      });
    }

    const root = nodes.find((n) => n.group === "root");
    if (root) {
      root.x = 0;
      root.y = 0;
      root.fx = 0;
      root.fy = 0;
    }

    return { centers };
  }

  function extractClusterMeta(nodes) {
    const byCluster = new Map();
    for (const n of nodes) {
      if (n.group !== "cluster") continue;
      if (!byCluster.has(n.cluster)) {
        byCluster.set(n.cluster, { id: n.cluster, color: n.color, count: 0 });
      }
      byCluster.get(n.cluster).count += 1;
    }
    return [...byCluster.values()].sort((a, b) => b.count - a.count || a.id - b.id);
  }

  function isNodeVisible(n) {
    if (n.group === "root") return settings.showRoot;
    if (n.group === "isolate") return settings.showIsolates;
    if (n.group === "cluster") return !settings.hiddenClusters.includes(n.cluster);
    return true;
  }

  function linkEndpointId(endpoint) {
    return typeof endpoint === "object" ? endpoint.id : endpoint;
  }

  function linkColorFor(l) {
    if (l.kind === "bridge") {
      return `rgba(255, 255, 255, ${settings.linkOpacity})`;
    }
    const s = typeof l.source === "object" ? l.source : null;
    const color = s?.color || "#60a5fa";
    if (color.length === 7) {
      const a = Math.round(settings.linkOpacity * 0.75 * 255)
        .toString(16)
        .padStart(2, "0");
      return `${color}${a}`;
    }
    return color;
  }

  function configureLinkForce() {
    graph
      .d3Force("link")
      .distance((l) => {
        if (l.kind === "bridge") return 180;
        const s = typeof l.source === "object" ? l.source : null;
        if (!s || s.cluster == null) return 36;
        const c = layoutCenters?.get(s.cluster);
        const step = c ? c.nodeStep : nodeStepForGroup(6, settings.spacingScale);
        return step * 2.6;
      })
      .strength((l) => (l.kind === "bridge" ? 0.015 : 0.06));
  }

  function filterGraphData(data) {
    const visibleIds = new Set(data.nodes.filter(isNodeVisible).map((n) => n.id));
    const nodes = data.nodes.filter((n) => visibleIds.has(n.id));
    const links = rawLinks
      .filter((l) => {
        const source = linkEndpointId(l.source);
        const target = linkEndpointId(l.target);
        if (!visibleIds.has(source) || !visibleIds.has(target)) return false;
        if (l.kind === "social") return settings.showIntraLinks;
        return settings.showLinks;
      })
      .map((l) => ({
        source: linkEndpointId(l.source),
        target: linkEndpointId(l.target),
        kind: l.kind,
      }));
    return { nodes, links };
  }

  function pinToCenters(nodes, centers) {
    return (alpha) => {
      for (const n of nodes) {
        if (n.group === "root") continue;
        const c = centers.get(n.cluster);
        if (!c) continue;
        const k = n.group === "isolate" ? 0.12 : 0.22;
        n.vx += (c.x - n.x) * k * alpha;
        n.vy += (c.y - n.y) * k * alpha;
      }
    };
  }

  function updateStats(visible) {
    const elNodes = document.getElementById("graph-stat-nodes");
    const elLinks = document.getElementById("graph-stat-links");
    const elGroups = document.getElementById("graph-stat-groups");
    if (!elNodes) return;

    const visibleGroups = clusterMeta.filter(
      (c) => !settings.hiddenClusters.includes(c.id),
    ).length;
    elNodes.textContent = String(visible.nodes.length);
    elLinks.textContent = String(visible.links.length);
    elGroups.textContent = String(visibleGroups);
  }

  function formatTargetGroupsLabel(val) {
    if (!val || val < 2) return t("graph.targetGroupsAuto");
    return String(val);
  }

  function syncTargetGroupsControl() {
    const el = document.getElementById("graph-opt-target-groups");
    const out = document.getElementById("graph-opt-target-groups-val");
    if (el) {
      el.min = "0";
      el.max = String(Math.max(maxGroups, 2));
      const clamped =
        settings.targetGroups >= 2
          ? clamp(settings.targetGroups, 2, maxGroups)
          : 0;
      settings.targetGroups = clamped;
      el.value = String(clamped);
    }
    if (out) out.textContent = formatTargetGroupsLabel(settings.targetGroups);
  }

  function syncPanelFromSettings() {
    const setChecked = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.checked = val;
    };
    const setRange = (id, val, outId, fmt) => {
      const el = document.getElementById(id);
      const out = document.getElementById(outId);
      if (el) el.value = String(val);
      if (out) out.textContent = fmt(val);
    };

    setChecked("graph-opt-root", settings.showRoot);
    setChecked("graph-opt-isolates", settings.showIsolates);
    setChecked("graph-opt-labels", settings.showLabels);
    setChecked("graph-opt-intra-links", settings.showIntraLinks);
    setChecked("graph-opt-links", settings.showLinks);
    setRange("graph-opt-node-size", settings.nodeSize, "graph-opt-node-size-val", (v) => v.toFixed(1));
    setRange(
      "graph-opt-link-opacity",
      Math.round(settings.linkOpacity * 100),
      "graph-opt-link-opacity-val",
      (v) => `${v}%`,
    );
    setRange("graph-opt-link-width", settings.linkWidth, "graph-opt-link-width-val", (v) => v.toFixed(1));
    setRange(
      "graph-opt-ring-scale",
      Math.round(settings.ringScale * 100),
      "graph-opt-ring-scale-val",
      (v) => `${v}%`,
    );
    setRange(
      "graph-opt-spacing",
      Math.round(settings.spacingScale * 100),
      "graph-opt-spacing-val",
      (v) => `${v}%`,
    );
    syncTargetGroupsControl();

    document.querySelectorAll(".graph-cluster-item input").forEach((input) => {
      const id = Number(input.dataset.cluster);
      input.checked = !settings.hiddenClusters.includes(id);
    });
  }

  function formatGroupName(rank) {
    const prefixes = { fr: "Groupe", en: "Group", es: "Grupo" };
    const lang = (hasI18n() && I18n.getLocale?.()) || "fr";
    return `${prefixes[lang] ?? prefixes.fr} ${rank}`;
  }

  function renderClusterList() {
    const list = document.getElementById("graph-cluster-list");
    if (!list) return;
    list.innerHTML = "";

    if (!clusterMeta.length) {
      const empty = document.createElement("p");
      empty.className = "graph-cluster-empty";
      empty.textContent = t("graph.noGroups");
      empty.style.cssText = "margin:0;font-size:0.72rem;color:var(--muted)";
      list.appendChild(empty);
      return;
    }

    clusterMeta.forEach((c, i) => {
      const label = document.createElement("label");
      label.className = "graph-cluster-item";

      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.cluster = String(c.id);
      input.checked = !settings.hiddenClusters.includes(c.id);

      const swatch = document.createElement("span");
      swatch.className = "graph-cluster-swatch";
      swatch.style.background = c.color;

      const name = document.createElement("span");
      name.className = "graph-cluster-label";
      name.textContent = formatGroupName(i + 1);

      const count = document.createElement("span");
      count.className = "graph-cluster-count";
      count.textContent = String(c.count);

      label.append(input, swatch, name, count);
      list.appendChild(label);

      input.addEventListener("change", () => {
        const hidden = new Set(settings.hiddenClusters);
        if (input.checked) hidden.delete(c.id);
        else hidden.add(c.id);
        settings.hiddenClusters = [...hidden];
        applySettings(false);
      });
    });
  }

  function readPanelSettings() {
    settings.showRoot = document.getElementById("graph-opt-root")?.checked ?? true;
    settings.showIsolates = document.getElementById("graph-opt-isolates")?.checked ?? true;
    settings.showLabels = document.getElementById("graph-opt-labels")?.checked ?? true;
    settings.showIntraLinks = document.getElementById("graph-opt-intra-links")?.checked ?? true;
    settings.showLinks = document.getElementById("graph-opt-links")?.checked ?? true;
    settings.nodeSize = Number(document.getElementById("graph-opt-node-size")?.value ?? 1.2);
    settings.linkOpacity =
      Number(document.getElementById("graph-opt-link-opacity")?.value ?? 35) / 100;
    settings.linkWidth = Number(document.getElementById("graph-opt-link-width")?.value ?? 0.6);
    settings.ringScale =
      Number(document.getElementById("graph-opt-ring-scale")?.value ?? 50) / 100;
    settings.spacingScale =
      Number(document.getElementById("graph-opt-spacing")?.value ?? 100) / 100;
  }

  function applySettings(relayout = false) {
    if (!rawGraphData || !graph) return;
    saveSettings();

    if (relayout) {
      const nodesCopy = rawGraphData.nodes.map((n) => ({ ...n }));
      const layout = buildClusterLayout(nodesCopy, {
        ringScale: settings.ringScale,
        spacingScale: settings.spacingScale,
      });
      layoutCenters = layout.centers;
      rawGraphData = { ...rawGraphData, nodes: nodesCopy };
      graph.d3Force("cluster", pinToCenters(rawGraphData.nodes, layoutCenters));
    }

    const visible = filterGraphData(rawGraphData);
    graph.graphData(visible);
    graph.nodeRelSize(settings.nodeSize);
    graph.linkColor(linkColorFor);
    graph.linkWidth(settings.linkWidth);
    configureLinkForce();
    updateStats(visible);
    graph.d3ReheatSimulation();
    graph.refresh?.();
  }

  function bindPanelControls() {
    const onToggle = () => {
      readPanelSettings();
      applySettings(false);
    };

    const onLayout = () => {
      readPanelSettings();
      applySettings(true);
    };

    document.getElementById("graph-opt-root")?.addEventListener("change", onToggle);
    document.getElementById("graph-opt-isolates")?.addEventListener("change", onToggle);
    document.getElementById("graph-opt-labels")?.addEventListener("change", onToggle);
    document.getElementById("graph-opt-intra-links")?.addEventListener("change", onToggle);
    document.getElementById("graph-opt-links")?.addEventListener("change", onToggle);

    document.getElementById("graph-opt-node-size")?.addEventListener("input", (e) => {
      document.getElementById("graph-opt-node-size-val").textContent = Number(e.target.value).toFixed(1);
      readPanelSettings();
      applySettings(false);
    });

    document.getElementById("graph-opt-link-opacity")?.addEventListener("input", (e) => {
      document.getElementById("graph-opt-link-opacity-val").textContent = `${e.target.value}%`;
      readPanelSettings();
      applySettings(false);
    });

    document.getElementById("graph-opt-link-width")?.addEventListener("input", (e) => {
      document.getElementById("graph-opt-link-width-val").textContent = Number(e.target.value).toFixed(1);
      readPanelSettings();
      applySettings(false);
    });

    document.getElementById("graph-opt-ring-scale")?.addEventListener("change", onLayout);
    document.getElementById("graph-opt-spacing")?.addEventListener("change", onLayout);
    document.getElementById("graph-opt-ring-scale")?.addEventListener("input", (e) => {
      document.getElementById("graph-opt-ring-scale-val").textContent = `${e.target.value}%`;
    });
    document.getElementById("graph-opt-spacing")?.addEventListener("input", (e) => {
      document.getElementById("graph-opt-spacing-val").textContent = `${e.target.value}%`;
    });

    document.getElementById("graph-opt-target-groups")?.addEventListener("input", (e) => {
      const val = Number(e.target.value) || 0;
      document.getElementById("graph-opt-target-groups-val").textContent =
        formatTargetGroupsLabel(val);
    });
    document.getElementById("graph-opt-target-groups")?.addEventListener("change", () => {
      const val = Number(document.getElementById("graph-opt-target-groups")?.value) || 0;
      settings.targetGroups = val >= 2 ? val : 0;
      settings.hiddenClusters = [];
      saveSettings();
      syncTargetGroupsControl();
      if (reloadTimer) clearTimeout(reloadTimer);
      reloadTimer = setTimeout(() => loadGraph({ keepPanel: true }), 120);
    });

    document.getElementById("graph-btn-fit")?.addEventListener("click", () => {
      graph?.zoomToFit(400, 80);
    });

    document.getElementById("graph-btn-reset")?.addEventListener("click", () => {
      const needReload = settings.targetGroups >= 2;
      settings = { ...DEFAULT_SETTINGS, hiddenClusters: [] };
      syncPanelFromSettings();
      saveSettings();
      if (needReload) loadGraph({ keepPanel: true });
      else applySettings(true);
    });
  }

  function buildGraph(data) {
    destroyGraph();
    rawGraphData = {
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    };
    rawLinks = data.links.map((l) => ({
      source: l.source,
      target: l.target,
      kind: l.kind,
    }));
    clusterMeta = extractClusterMeta(rawGraphData.nodes);
    if (data.stats?.max_groups) {
      maxGroups = Math.max(2, Number(data.stats.max_groups) || 20);
    }
    if (settings.targetGroups >= 2) {
      settings.targetGroups = clamp(settings.targetGroups, 2, maxGroups);
    }

    const layout = buildClusterLayout(rawGraphData.nodes, {
      ringScale: settings.ringScale,
      spacingScale: settings.spacingScale,
    });
    layoutCenters = layout.centers;

    elPanel?.classList.remove("hidden");
    renderClusterList();
    syncPanelFromSettings();
    if (!panelBound) {
      bindPanelControls();
      panelBound = true;
    }

    const visible = filterGraphData(rawGraphData);

    graph = ForceGraph()(elCanvas)
      .graphData(visible)
      .backgroundColor("#000000")
      .nodeId("id")
      .nodeVal("val")
      .nodeRelSize(settings.nodeSize)
      .nodeLabel((n) => {
        const full = n.full_name ? ` — ${n.full_name}` : "";
        return `${n.name}${full}`;
      })
      .nodeColor((n) => n.color || "#888")
      .nodeCanvasObjectMode(() => "after")
      .nodeCanvasObject((node, ctx, globalScale) => {
        if (!settings.showLabels) return;
        if (globalScale < 0.4 && node.group !== "root") return;
        const label = node.name;
        const fontSize = Math.max(9 / globalScale, 2);
        ctx.font = `${fontSize}px ui-monospace, monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = node.color || "#ccc";
        const r = Math.sqrt(Math.max(node.val || 1, 0.5)) * settings.nodeSize;
        ctx.fillText(label, node.x, node.y + r + 3);
      })
      .linkColor(linkColorFor)
      .linkWidth(settings.linkWidth)
      .enableNodeDrag(true)
      .cooldownTicks(100)
      .d3AlphaDecay(0.04)
      .d3VelocityDecay(0.4)
      .onNodeClick((node) => {
        const u = String(node.id || "").replace(/^@/, "");
        if (u) window.open(`https://www.instagram.com/${u}/`, "_blank", "noopener,noreferrer");
      });

    graph.d3Force("charge").strength((n) => (n.group === "root" ? -4 : -55));
    configureLinkForce();
    graph.d3Force("cluster", pinToCenters(rawGraphData.nodes, layoutCenters));
    graph.d3Force("center", null);

    updateStats(visible);

    let fitted = false;
    graph.onEngineStop(() => {
      if (!fitted) {
        fitted = true;
        graph.zoomToFit(600, 120);
      }
    });

    resizeHandler = () => {
      graph.width(elCanvas.clientWidth);
      graph.height(elCanvas.clientHeight);
    };
    resizeHandler();
    window.addEventListener("resize", resizeHandler);
  }

  async function loadGraph({ keepPanel = false } = {}) {
    elEmpty.classList.add("hidden");
    if (!keepPanel) elPanel?.classList.add("hidden");

    let data;
    try {
      const qs =
        settings.targetGroups >= 2 ? `?groups=${settings.targetGroups}` : "";
      const res = await fetch(`/api/graph${qs}`);
      if (!res.ok) throw new Error("bad status");
      data = await res.json();
    } catch {
      elEmpty.classList.remove("hidden");
      return;
    }

    if (!data.nodes?.length) {
      destroyGraph();
      elEmpty.classList.remove("hidden");
      return;
    }

    buildGraph(data);
  }

  function normalizeGraphQuery(text) {
    return String(text || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/^@/, "")
      .trim();
  }

  function isFullscreen() {
    return Boolean(
      elStage &&
        (document.fullscreenElement === elStage ||
          document.webkitFullscreenElement === elStage),
    );
  }

  function syncFullscreenUi() {
    const fs = isFullscreen();
    elStage?.classList.toggle("is-fullscreen", fs);
    if (elBtnFullscreen) {
      const key = fs ? "graph.btnFullscreenExit" : "graph.btnFullscreen";
      elBtnFullscreen.title = t(key);
      elBtnFullscreen.setAttribute("aria-label", t(key));
    }
    if (!fs) {
      elSearchMsg?.classList.add("hidden");
    }
    if (graph && elCanvas) {
      graph.width(elCanvas.clientWidth);
      graph.height(elCanvas.clientHeight);
    }
  }

  async function toggleFullscreen() {
    if (!elStage) return;
    try {
      if (isFullscreen()) {
        if (document.exitFullscreen) await document.exitFullscreen();
        else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      } else if (elStage.requestFullscreen) {
        await elStage.requestFullscreen();
      } else if (elStage.webkitRequestFullscreen) {
        elStage.webkitRequestFullscreen();
      }
    } catch {
      /* user gesture / browser policy */
    }
  }

  function showSearchMsg(key) {
    if (!elSearchMsg) return;
    elSearchMsg.textContent = t(key);
    elSearchMsg.classList.remove("hidden");
  }

  function findNodeByQuery(query) {
    const q = normalizeGraphQuery(query);
    if (!q || !rawGraphData?.nodes?.length) return null;
    const scored = [];
    for (const n of rawGraphData.nodes) {
      const id = normalizeGraphQuery(n.id);
      const name = normalizeGraphQuery(n.name);
      const full = normalizeGraphQuery(n.full_name);
      let score = 0;
      if (id === q || name === q) score = 3;
      else if (id.startsWith(q) || name.startsWith(q)) score = 2;
      else if (id.includes(q) || name.includes(q) || full.includes(q)) score = 1;
      if (score) scored.push({ node: n, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored[0]?.node || null;
  }

  function focusNode(node) {
    if (!graph || !node) return;
    const x = Number(node.x) || 0;
    const y = Number(node.y) || 0;
    graph.centerAt(x, y, 700);
    graph.zoom(Math.max(graph.zoom() || 1, 3.2), 700);
  }

  function searchAndFocus(query) {
    const node = findNodeByQuery(query);
    if (!node) {
      showSearchMsg("graph.searchNotFound");
      return;
    }
    if (!isNodeVisible(node)) {
      showSearchMsg("graph.searchHidden");
      return;
    }
    elSearchMsg?.classList.add("hidden");
    const live = graph
      ?.graphData()
      ?.nodes?.find((n) => n.id === node.id);
    focusNode(live || node);
  }

  function bindFullscreenControls() {
    elBtnFullscreen?.addEventListener("click", () => toggleFullscreen());
    document.addEventListener("fullscreenchange", syncFullscreenUi);
    document.addEventListener("webkitfullscreenchange", syncFullscreenUi);

    elSearchForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      searchAndFocus(elSearchInput?.value || "");
    });
  }

  async function init() {
    if (hasI18n()) await I18n.ready;

    function initLangSwitch() {
      document.querySelectorAll(".lang-btn[data-lang]").forEach((btn) => {
        btn.onclick = async () => {
          await I18n.setLocale(btn.dataset.lang);
        };
      });
    }

    function onLocaleChange() {
      I18n.applyI18n();
      syncTargetGroupsControl();
      renderClusterList();
      syncFullscreenUi();
      if (rawGraphData && graph) {
        updateStats(filterGraphData(rawGraphData));
      }
    }

    if (hasI18n()) {
      I18n.applyI18n();
      initLangSwitch();
      window.addEventListener("instree:locale", onLocaleChange);
    }

    bindFullscreenControls();
    syncFullscreenUi();

    if (typeof ForceGraph !== "function") {
      elEmpty.classList.remove("hidden");
      return;
    }

    await loadGraph();
  }

  init();
})();
