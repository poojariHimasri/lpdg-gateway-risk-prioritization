/**
 * LPDG Gateway Risk Dashboard - Enterprise Frontend Controller
 * Connects directly to the existing Flask API endpoints.
 */

(function () {
  "use strict";

  // In-memory cache for gateway master metadata
  const gatewayCache = new Map();

  // Application State
  const state = {
    currentWeek: "2026-02-02",
    currentRanker: "cost_risk",
    recommendations: [],
    loading: false,
    rerunning: false,
  };

  // DOM Elements
  const dom = {
    weekSelect: document.getElementById("week-select"),
    rankerSelect: document.getElementById("ranker-select"),
    btnLoad: document.getElementById("btn-load-ranking"),
    btnRerun: document.getElementById("btn-rerun-ranking"),
    rerunSpinner: document.getElementById("rerun-spinner"),
    rerunText: document.getElementById("rerun-text"),
    filterInput: document.getElementById("table-filter-input"),
    tableBody: document.getElementById("ranking-tbody"),
    tableLoading: document.getElementById("table-loading"),
    tableError: document.getElementById("table-error"),
    errorTitle: document.getElementById("error-title"),
    errorDesc: document.getElementById("error-desc"),
    btnRetry: document.getElementById("btn-retry"),
    tableWrapper: document.getElementById("table-wrapper"),
    
    // KPI elements
    kpiGateways: document.getElementById("kpi-gateways-count"),
    kpiHighestScore: document.getElementById("kpi-highest-score"),
    kpiMetersRisk: document.getElementById("kpi-meters-risk"),
    kpiSelectedWeek: document.getElementById("kpi-selected-week"),
    kpiActiveRanker: document.getElementById("kpi-active-ranker"),
    
    // Status elements
    apiBadge: document.getElementById("api-status-badge"),
    apiStatusText: document.getElementById("api-status-text"),
    lastUpdatedTime: document.getElementById("last-updated-time"),
    
    // Modal elements
    modal: document.getElementById("gateway-modal"),
    modalClose: document.getElementById("btn-close-modal"),
    modalDone: document.getElementById("btn-modal-done"),
    modalRankBadge: document.getElementById("modal-rank-badge"),
    modalGatewayId: document.getElementById("modal-gateway-id"),
    modalRawMac: document.getElementById("modal-raw-mac"),
    modalExplanationText: document.getElementById("modal-explanation-text"),
    
    // Modal metadata fields
    metaRegion: document.getElementById("meta-region"),
    metaSiteType: document.getElementById("meta-site-type"),
    metaMeters: document.getElementById("meta-meters"),
    metaHwModel: document.getElementById("meta-hw-model"),
    metaFwVersion: document.getElementById("meta-fw-version"),
    metaAntenna: document.getElementById("meta-antenna"),
    metaInstalledOn: document.getElementById("meta-installed-on"),
    metaTenant: document.getElementById("meta-tenant"),
    
    // Toast notification
    toast: document.getElementById("toast-banner"),
    toastIcon: document.getElementById("toast-icon"),
    toastMessage: document.getElementById("toast-message"),
    toastClose: document.getElementById("toast-close"),
  };

  /**
   * Initialize dashboard event listeners and fetch initial data
   */
  async function init() {
    setupEventListeners();
    await checkApiHealth();
    // Periodic health check every 30s
    setInterval(checkApiHealth, 30000);
    // Initial load
    await loadRanking();
  }

  /**
   * Bind event listeners
   */
  function setupEventListeners() {
    dom.btnLoad.addEventListener("click", () => loadRanking());
    dom.btnRerun.addEventListener("click", () => rerunRanking());
    dom.btnRetry.addEventListener("click", () => loadRanking());
    
    dom.weekSelect.addEventListener("change", (e) => {
      state.currentWeek = e.target.value;
      loadRanking();
    });

    dom.rankerSelect.addEventListener("change", (e) => {
      state.currentRanker = e.target.value;
      loadRanking();
    });

    dom.filterInput.addEventListener("input", (e) => {
      renderTable(state.recommendations, e.target.value.trim().toLowerCase());
    });

    // Modal close events
    dom.modalClose.addEventListener("click", closeModal);
    dom.modalDone.addEventListener("click", closeModal);
    dom.modal.addEventListener("click", (e) => {
      if (e.target === dom.modal) closeModal();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !dom.modal.classList.contains("hidden")) {
        closeModal();
      }
    });

    dom.toastClose.addEventListener("click", hideToast);
  }

  /**
   * Check backend service liveness via GET /api/health
   */
  async function checkApiHealth() {
    try {
      const resp = await fetch("/api/health");
      if (resp.ok) {
        const data = await resp.json();
        dom.apiBadge.className = "status-badge status-healthy";
        dom.apiStatusText.textContent = "API Healthy";
        dom.apiBadge.title = `Service: ${data.service} | Engine: ${data.ranker || "loaded"} | Path: ${data.data_dir}`;
      } else {
        dom.apiBadge.className = "status-badge status-offline";
        dom.apiStatusText.textContent = "API Degraded";
      }
    } catch (err) {
      dom.apiBadge.className = "status-badge status-offline";
      dom.apiStatusText.textContent = "API Offline";
      dom.apiBadge.title = "Cannot reach backend on port 5000";
    }
  }

  /**
   * Fetch gateway asset profile via GET /api/gateways/<id>
   */
  async function fetchGatewayDetails(gatewayId) {
    if (gatewayCache.has(gatewayId)) {
      return gatewayCache.get(gatewayId);
    }
    try {
      const resp = await fetch(`/api/gateways/${encodeURIComponent(gatewayId)}`);
      if (!resp.ok) return null;
      const data = await resp.json();
      gatewayCache.set(gatewayId, data);
      return data;
    } catch (err) {
      console.warn(`Could not load metadata for ${gatewayId}:`, err);
      return null;
    }
  }

  /**
   * Load weekly ranking recommendations via GET /api/predictions
   */
  async function loadRanking() {
    if (state.loading) return;
    setLoadingState(true);

    state.currentWeek = dom.weekSelect.value;
    state.currentRanker = dom.rankerSelect.value;

    try {
      const url = `/api/predictions?week=${encodeURIComponent(state.currentWeek)}&ranker=${encodeURIComponent(state.currentRanker)}`;
      const resp = await fetch(url);

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.error || `Server responded with HTTP ${resp.status}`);
      }

      const data = await resp.json();
      state.recommendations = data.recommendations || [];

      // Concurrently fetch gateway master metadata for all 15 sites
      await Promise.all(
        state.recommendations.map(async (rec) => {
          rec.metadata = await fetchGatewayDetails(rec.gateway_id);
        })
      );

      updateKpis(state.recommendations);
      renderTable(state.recommendations, dom.filterInput.value.trim().toLowerCase());
      
      dom.lastUpdatedTime.textContent = new Date().toLocaleTimeString();
      showTableState(true);
    } catch (err) {
      console.error("loadRanking failed:", err);
      dom.errorTitle.textContent = "Unable to load gateway recommendations";
      dom.errorDesc.textContent = err.message || "Failed to communicate with the LPDG backend service.";
      showTableState(false, true);
    } finally {
      setLoadingState(false);
    }
  }

  /**
   * Rerun predictions batch job via POST /api/predictions/run
   */
  async function rerunRanking() {
    if (state.rerunning) return;
    state.rerunning = true;

    dom.btnRerun.disabled = true;
    dom.rerunSpinner.classList.remove("hidden");
    dom.rerunText.textContent = "Rerunning...";
    showToast("Triggering batch calculation across all 8 scored weeks...", "info");

    try {
      const resp = await fetch("/api/predictions/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ranker: state.currentRanker,
          out: "predictions.csv",
        }),
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.error || `Rerun failed with HTTP ${resp.status}`);
      }

      const resData = await resp.json();
      showToast(resData.message || "Ranking batch completed successfully! Refreshed predictions.csv.", "success");
      // Refresh current displayed week
      await loadRanking();
    } catch (err) {
      console.error("rerunRanking failed:", err);
      showToast(`Rerun failed: ${err.message}`, "error");
    } finally {
      state.rerunning = false;
      dom.btnRerun.disabled = false;
      dom.rerunSpinner.classList.add("hidden");
      dom.rerunText.textContent = "Rerun Ranking";
    }
  }

  /**
   * Update Summary KPI cards
   */
  function updateKpis(recs) {
    dom.kpiGateways.textContent = recs.length;
    dom.kpiSelectedWeek.textContent = state.currentWeek;
    dom.kpiActiveRanker.textContent = state.currentRanker === "cost_risk" ? "Cost-Aware Risk" : "Three Sigma";

    if (recs.length === 0) {
      dom.kpiHighestScore.textContent = "--";
      dom.kpiMetersRisk.textContent = "--";
      return;
    }

    const scores = recs.map((r) => Number(r.score) || 0);
    const maxScore = Math.max(...scores);
    dom.kpiHighestScore.textContent = maxScore.toFixed(maxScore >= 100 ? 1 : 1);

    // Sum installed meters across the 15 gateways from metadata
    let totalMeters = 0;
    let validCounts = 0;
    for (const r of recs) {
      if (r.metadata && r.metadata.n_meters_installed != null) {
        totalMeters += Number(r.metadata.n_meters_installed) || 0;
        validCounts++;
      }
    }
    dom.kpiMetersRisk.textContent = validCounts > 0 ? totalMeters.toLocaleString() : "--";
  }

  /**
   * Render the recommendations table with search filtering
   */
  function renderTable(recs, filterText = "") {
    dom.tableBody.innerHTML = "";

    const filtered = recs.filter((r) => {
      if (!filterText) return true;
      const meta = r.metadata || {};
      const searchTarget = `${r.gateway_id} ${r.rank} ${meta.region || ""} ${meta.site_type || ""} ${r.reason}`.toLowerCase();
      return searchTarget.includes(filterText);
    });

    if (filtered.length === 0) {
      const row = document.createElement("tr");
      row.innerHTML = `<td colspan="9" style="text-align: center; padding: 40px; color: var(--text-muted);">
        No gateways matching "${escapeHtml(filterText)}"
      </td>`;
      dom.tableBody.appendChild(row);
      return;
    }

    for (const r of filtered) {
      const meta = r.metadata || {};
      const tr = document.createElement("tr");

      // Priority determination based on rank position
      let priorityClass = "priority-moderate";
      let priorityText = "Moderate";
      if (r.rank <= 5) {
        priorityClass = "priority-critical";
        priorityText = "Critical";
      } else if (r.rank <= 10) {
        priorityClass = "priority-high";
        priorityText = "High";
      }

      const rankBadgeClass = r.rank <= 3 ? "rank-badge rank-top3" : "rank-badge rank-default";
      const regionText = meta.region || '<span style="color:var(--text-muted)">--</span>';
      const siteText = meta.site_type || '<span style="color:var(--text-muted)">--</span>';
      const metersText = meta.n_meters_installed != null ? meta.n_meters_installed : "--";

      tr.innerHTML = `
        <td class="col-rank"><span class="${rankBadgeClass}">${r.rank}</span></td>
        <td class="col-id"><span class="gateway-pill">${escapeHtml(r.gateway_id)}</span></td>
        <td class="col-score">${Number(r.score).toFixed(1)}</td>
        <td class="col-priority"><span class="priority-badge ${priorityClass}">${priorityText}</span></td>
        <td class="col-region">${escapeHtml(regionText)}</td>
        <td class="col-site">${escapeHtml(siteText)}</td>
        <td class="col-meters">${metersText}</td>
        <td class="col-reason"><div class="reason-text" title="${escapeHtml(r.reason)}">${escapeHtml(r.reason)}</div></td>
        <td class="col-action"><button class="btn-inspect" aria-label="Inspect gateway ${r.gateway_id}">Inspect</button></td>
      `;

      tr.addEventListener("click", () => openGatewayModal(r));
      dom.tableBody.appendChild(tr);
    }
  }

  /**
   * Open the detailed inspection modal and fetch explanation
   */
  async function openGatewayModal(item) {
    const meta = item.metadata || {};
    dom.modalRankBadge.textContent = `Rank #${item.rank}`;
    dom.modalGatewayId.textContent = item.gateway_id;
    dom.modalRawMac.textContent = meta.raw_gateway_id ? `Hardware ID: ${meta.raw_gateway_id}` : `ID: ${item.gateway_id}`;

    // Populate existing metadata
    dom.metaRegion.textContent = meta.region || "--";
    dom.metaSiteType.textContent = meta.site_type || "--";
    dom.metaMeters.textContent = meta.n_meters_installed != null ? `${meta.n_meters_installed} meters` : "--";
    dom.metaHwModel.textContent = meta.hw_model || "--";
    dom.metaFwVersion.textContent = meta.fw_version || "--";
    dom.metaAntenna.textContent = meta.antenna_type || "--";
    dom.metaInstalledOn.textContent = meta.installed_on || "--";
    dom.metaTenant.textContent = meta.tenant || "--";

    // Immediate display of known recommendation reason
    dom.modalExplanationText.textContent = item.reason;

    dom.modal.classList.remove("hidden");

    // Fetch deep explanation from GET /api/gateways/<id>/explain?week=YYYY-MM-DD
    try {
      const expUrl = `/api/gateways/${encodeURIComponent(item.gateway_id)}/explain?week=${encodeURIComponent(state.currentWeek)}`;
      const expResp = await fetch(expUrl);
      if (expResp.ok) {
        const expData = await expResp.json();
        if (expData && expData.reason) {
          dom.modalExplanationText.textContent = expData.reason;
        }
      }
    } catch (err) {
      console.warn("Could not fetch extended explanation:", err);
    }
  }

  function closeModal() {
    dom.modal.classList.add("hidden");
  }

  /**
   * Show/hide loading and table states
   */
  function setLoadingState(loading) {
    state.loading = loading;
    dom.btnLoad.disabled = loading;
    if (loading) {
      dom.tableLoading.classList.remove("hidden");
      dom.tableError.classList.add("hidden");
      dom.tableWrapper.classList.add("hidden");
    } else {
      dom.tableLoading.classList.add("hidden");
    }
  }

  function showTableState(showTable, showError = false) {
    if (showTable) {
      dom.tableWrapper.classList.remove("hidden");
      dom.tableError.classList.add("hidden");
    } else if (showError) {
      dom.tableWrapper.classList.add("hidden");
      dom.tableError.classList.remove("hidden");
    }
  }

  /**
   * Toast notification helper
   */
  let toastTimer = null;
  function showToast(message, type = "info") {
    clearTimeout(toastTimer);
    dom.toastMessage.textContent = message;
    dom.toastIcon.textContent = type === "success" ? "✅" : type === "error" ? "❌" : "ℹ️";
    dom.toast.classList.remove("hidden");
    toastTimer = setTimeout(hideToast, 4000);
  }

  function hideToast() {
    dom.toast.classList.add("hidden");
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Launch when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
