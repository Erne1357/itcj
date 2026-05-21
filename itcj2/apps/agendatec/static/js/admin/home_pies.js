// static/js/admin/home_pies.js
(() => {
  if (window.__homePiesMounted) return;
  window.__homePiesMounted = true;

  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminDashboard || {};
  const piesUrl = cfg.piesUrl || "/api/agendatec/v2/admin/stats/coordinators";
  const palette = window.AgendaTec?.ChartPalette;

  if (!window.Chart) {
    console.warn("[home_pies] Chart.js no está cargado");
    return;
  }

  window.__reloadPies = reloadPies;

  let chGlobal = null;
  const miniCharts = new Map();
  let suppressDayChange = false;

  const STATE_ORDER = palette?.STATUS_ORDER || [
    "PENDING", "RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED",
    "ATTENDED_OTHER_SLOT", "NO_SHOW", "CANCELED",
  ];
  const STATE_LABEL = palette?.statusLabels || {
    PENDING: "Pendientes",
    RESOLVED_SUCCESS: "Resueltas",
    RESOLVED_NOT_COMPLETED: "Atendidas sin resolver",
    ATTENDED_OTHER_SLOT: "Otro horario",
    NO_SHOW: "No asistió",
    CANCELED: "Canceladas",
  };
  const STATE_COLORS = STATE_ORDER.map((k) => palette?.statusColors?.[k] || "");

  function buildQuery() {
    const q = new URLSearchParams();
    const from = $("#fltFrom")?.value;
    const to   = $("#fltTo")?.value;
    if (from) q.set("from", from);
    if (to)   q.set("to", to);
    if ($("#pieByDay")?.checked) q.set("by_day", "1");
    q.set("states", "1");
    return q.toString();
  }

  function toStatesArray(totals) {
    const st = totals?.states || {};
    return STATE_ORDER.map((code) => ({
      label: STATE_LABEL[code],
      value: Number(st[code] || 0),
    }));
  }

  function sum(arr, key = "value") {
    return (arr || []).reduce((a, b) => a + Number(b?.[key] || 0), 0);
  }

  function debounce(fn, t) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), t); }; }

  function escapeHtml(s) {
    return (s || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function destroyGlobal() { try { chGlobal?.destroy?.(); } catch {} chGlobal = null; }
  function destroyMiniCharts() { miniCharts.forEach((ch) => { try { ch.destroy?.(); } catch {} }); miniCharts.clear(); }

  // === EMPTY STATE HELPER ===
  function showEmpty(container, message) {
    // Usar clases CSS (sin inline styles)
    container.classList.add("at-chart-host", "at-chart-host--empty");
    let el = container.querySelector(".at-empty--chart");
    if (!el) {
      el = document.createElement("div");
      el.className = "at-empty--chart position-absolute top-50 start-50 translate-middle text-center at-chart-empty-overlay";
      container.appendChild(el);
    }
    el.innerHTML = `
      <i class="bi bi-pie-chart fs-1 text-muted opacity-50" aria-hidden="true"></i>
      <p class="mt-1 text-muted small mb-0">${escapeHtml(message || "Sin datos")}</p>`;
  }

  function hideEmpty(container) {
    container.querySelector(".at-empty--chart")?.remove();
    container.classList.remove("at-chart-host--empty");
  }

  // === RENDER: Global ===
  function drawGlobal(data, total) {
    destroyGlobal();
    const host = document.querySelector("#panePieGlobal .pieHost");
    const cv   = $("#chCoordGlobal");
    if (!cv) return;

    const hasData = data.some((d) => d.value > 0);
    if (!hasData) {
      if (host) showEmpty(host, "Sin datos para el rango seleccionado");
      const lbl = $("#lblGlobalTotal");
      if (lbl) lbl.textContent = "Total: 0";
      return;
    }
    if (host) { hideEmpty(host); }

    chGlobal = new Chart(cv, {
      type: "pie",
      data: {
        labels: data.map((d) => d.label),
        datasets: [{
          data: data.map((d) => d.value),
          backgroundColor: STATE_COLORS,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 120,
        plugins: { legend: { position: "bottom" } },
        animation: { duration: 250 },
      },
    });
    const lbl = $("#lblGlobalTotal");
    if (lbl) lbl.textContent = `Total: ${Number(total || 0)}`;
  }

  // === RENDER: Por coordinador ===
  function drawMini(coordList, byDay, selectedDay) {
    const grid = $("#miniPieGrid");
    if (!grid) return;
    destroyMiniCharts();
    grid.innerHTML = "";

    if (!coordList || coordList.length === 0) {
      grid.innerHTML = `<div class="col-12"><div class="at-empty py-4 text-center">
        <i class="bi bi-pie-chart fs-3 text-muted opacity-50"></i>
        <p class="mt-2 text-muted small mb-0">Sin datos de coordinadores</p>
      </div></div>`;
      return;
    }

    for (const c of coordList) {
      const totals = (!byDay || !selectedDay)
        ? c.totals
        : (c.days || []).find((x) => x.day === selectedDay) || { total: 0, states: {} };

      const data  = toStatesArray(totals);
      const total = Number(totals?.total || sum(data));
      const hasData = data.some((d) => d.value > 0);

      const col = document.createElement("div");
      col.className = "col-12 col-sm-6 col-md-4";
      col.innerHTML = `
        <div class="at-card at-card--bordered p-2 h-100">
          <div class="d-flex justify-content-between align-items-center mb-1">
            <strong class="text-truncate small" title="${escapeHtml(c.coordinator_name || "—")}">${escapeHtml(c.coordinator_name || "—")}</strong>
            <small class="text-muted">#${c.coordinator_id}</small>
          </div>
          <div class="miniPieBox position-relative" style="height:180px;">
            ${hasData
              ? `<canvas id="miniPie-${c.coordinator_id}" style="width:100%;height:100%;"></canvas>`
              : `<div class="at-empty--chart position-absolute top-50 start-50 translate-middle text-center">
                   <i class="bi bi-pie-chart text-muted opacity-50" aria-hidden="true"></i>
                   <p class="text-muted" style="font-size:var(--at-text-xs);">Sin datos</p>
                 </div>`
            }
          </div>
          <small class="text-muted">Total: ${total}</small>
        </div>`;
      grid.appendChild(col);

      if (hasData) {
        const canvas = col.querySelector("canvas");
        const chart  = new Chart(canvas, {
          type: "pie",
          data: {
            labels: data.map((d) => d.label),
            datasets: [{
              data: data.map((d) => d.value),
              backgroundColor: STATE_COLORS,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            resizeDelay: 120,
            plugins: { legend: { display: false } },
            animation: { duration: 250 },
          },
        });
        miniCharts.set(c.coordinator_id, chart);
      }
    }
  }

  function setDayOptions(days) {
    const sel = $("#pieDay");
    if (!sel) return null;
    const prev = sel.value;
    const existing = Array.from(sel.options).map((o) => o.value);
    const same = days.length === existing.length && days.every((d, i) => d === existing[i]);

    suppressDayChange = true;
    if (!same) {
      sel.innerHTML = days.map((d) => `<option value="${d}">${d}</option>`).join("");
    }
    sel.value = (prev && days.includes(prev)) ? prev : (days[0] || "");
    suppressDayChange = false;
    return sel.value || null;
  }

  // === FETCH + ORQUESTACIÓN ===
  async function reloadPies() {
    try {
      const byDay = $("#pieByDay")?.checked;
      const r = await fetch(`${piesUrl}?${buildQuery()}`, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();

      let selectedDay = null;
      const sel = $("#pieDay");
      if (byDay) {
        const days = (j.overall_by_day || []).map((d) => d.day);
        if (sel) sel.hidden = days.length === 0;
        selectedDay = setDayOptions(days);
      } else {
        if (sel) { sel.hidden = true; sel.innerHTML = ""; }
      }

      let totalsGlobal = j.overall || { total: 0, states: {} };
      if (byDay && selectedDay) {
        const dobj = (j.overall_by_day || []).find((x) => x.day === selectedDay);
        if (dobj) totalsGlobal = dobj;
      }
      const dataGlobal = toStatesArray(totalsGlobal);
      drawGlobal(dataGlobal, totalsGlobal?.total ?? sum(dataGlobal));
      drawMini(j.coordinators || [], byDay, selectedDay);

    } catch (e) {
      try { showToast?.("Error al cargar pasteles de coordinadores", "error"); } catch {}
      console.error("[home_pies] reload error:", e);
      destroyGlobal();
      destroyMiniCharts();
      const grid = $("#miniPieGrid");
      if (grid) grid.innerHTML = `<div class="text-muted small">No se pudo cargar.</div>`;
    }
  }

  // === CONTROLES ===
  $("#btnPiesReload")?.addEventListener("click", reloadPies);
  $("#pieByDay")?.addEventListener("change", () => {
    const el = $("#pieDay");
    if (el) el.hidden = !$("#pieByDay").checked;
    reloadPies();
  });
  $("#pieDay")?.addEventListener("change", () => {
    if (suppressDayChange) return;
    reloadPies();
  });

  document.addEventListener("shown.bs.tab", (ev) => {
    const id = ev?.target?.id;
    if (id === "tabPieGlobal" || id === "tabPieMini") reloadPies();
  });

  const activeTabId = document.querySelector("#leftTabs .nav-link.active")?.id;
  if (activeTabId === "tabPieGlobal" || activeTabId === "tabPieMini") {
    reloadPies();
  }
})();
