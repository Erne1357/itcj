// static/js/admin/home.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminDashboard || {};
  const fetchUrl = cfg.fetchUrl || "/api/agendatec/v2/admin/stats/overview";
  const periodsUrl = cfg.periodsUrl || "/api/agendatec/v2/periods";

  // === ESTADO GLOBAL DEL MÓDULO ===
  let chSeries;
  let activePeriodId = null;
  let periodsData = {};
  const stateMap = {
    PENDING:                "#mPending",
    RESOLVED_SUCCESS:       "#mSolved",
    RESOLVED_NOT_COMPLETED: "#mNotCompleted",
    NO_SHOW:                "#mNoShow",
    ATTENDED_OTHER_SLOT:    "#mOtherSlot",
    CANCELED:               "#mCanceled",
  };

  // === TABS QUE MUESTRAN PIE CONTROLS ===
  const PIE_TABS = new Set(["tabPieGlobal", "tabPieMini"]);

  // === SKELETON INICIAL ===
  function showKpiSkeleton() {
    const grid = document.querySelector(".row.g-2.g-md-3:first-of-type");
    if (!grid || !window.AgendaTec?.Skeleton) return;
    // Marcar KPIs como cargando con aria-busy
    grid.querySelectorAll(".metric-card").forEach((card) => {
      card.setAttribute("aria-busy", "true");
      const valueEl = card.querySelector(".metric-value");
      if (valueEl) {
        valueEl.innerHTML = window.AgendaTec.Skeleton.line("40%");
      }
    });
  }

  // === CARGA DE PERÍODOS ===
  async function loadPeriods() {
    try {
      const r = await fetch(periodsUrl, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const periods = Array.isArray(data) ? data : (data.items || data.periods || []);

      periods.forEach((p) => { periodsData[p.id] = p; });

      const activePeriod = periods.find((p) => p.status === "ACTIVE");
      if (activePeriod) activePeriodId = activePeriod.id;

      const periodSelect = $("#fltPeriod");
      const options = [
        { id: "all", name: "Todos los períodos" },
        ...periods.map((p) => ({ id: p.id, name: p.name })),
      ];
      periodSelect.innerHTML = options
        .map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`)
        .join("");

      if (activePeriodId) {
        periodSelect.value = activePeriodId;
        setPeriodDates(activePeriodId);
      } else {
        periodSelect.value = "all";
        initDefaultDates();
      }
    } catch {
      initDefaultDates();
    }
  }

  function setPeriodDates(periodId) {
    const period = periodsData[periodId];
    if (!period) return;
    if (period.start_date) $("#fltFrom").value = period.start_date.slice(0, 10);
    if (period.end_date)   $("#fltTo").value   = period.end_date.slice(0, 10);
  }

  function initDefaultDates() {
    const to = new Date();
    const from = new Date(Date.now() - 7 * 86400000);
    $("#fltTo").value   = to.toISOString().slice(0, 10);
    $("#fltFrom").value = from.toISOString().slice(0, 10);
  }

  function qs() {
    const q = new URLSearchParams();
    const f = $("#fltFrom")?.value;
    const t = $("#fltTo")?.value;
    if (f) q.set("from", f);
    if (t) q.set("to", t);
    return q.toString();
  }

  // === CARGA DE OVERVIEW ===
  async function loadOverview() {
    try {
      const r = await fetch(`${fetchUrl}?${qs()}`, { credentials: "include" });
      if (!r.ok) throw new Error("Bad response");
      const j = await r.json();

      // KPIs
      const totals = Object.fromEntries(
        (j.totals || []).map((x) => [x.status, x.total])
      );
      for (const [st, sel] of Object.entries(stateMap)) {
        const el = $(sel);
        if (el) {
          el.textContent = String(totals[st] || 0);
          el.closest(".metric-card")?.removeAttribute("aria-busy");
        }
      }

      // No-show rate
      const noShowEl = $("#lblNoShowRate");
      if (noShowEl) noShowEl.textContent = (((j.no_show_rate || 0) * 100).toFixed(1) + "%");

      // Serie por hora
      const rawSeries = Array.isArray(j.series) ? j.series : [];
      const labels = rawSeries.map((x) => formatHour(x.hour || x.day));
      const data   = rawSeries.map((x) => Number(x.total || 0));

      if (chSeries) chSeries.destroy?.();
      const host = document.querySelector("#paneSeries .seriesHost");
      const ctx  = $("#chSeries");
      if (ctx && host) {
        const allZero = data.every((v) => v === 0);
        if (allZero || data.length === 0) {
          renderChartEmpty(host, ctx);
        } else {
          removeChartEmpty(host);
          chSeries = new Chart(ctx, {
            type: "line",
            data: {
              labels,
              datasets: [{
                label: "Solicitudes",
                data,
                tension: 0.3,
                pointRadius: 2,
                borderColor: getComputedStyle(document.documentElement).getPropertyValue("--at-primary").trim(),
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                tooltip: {
                  callbacks: {
                    title: (items) => items?.[0]?.label || "",
                    label: (c) => ` ${c.dataset.label}: ${c.parsed.y}`,
                  },
                },
                legend: { display: false },
              },
              scales: {
                x: { ticks: { maxRotation: 0, autoSkip: true } },
                y: { beginAtZero: true, grace: "5%" },
              },
            },
          });
        }
      }

      // Pendientes por coordinador
      renderPendingList(j);

    } catch {
      showToast?.("Error al cargar estadísticas", "error");
    }
  }

  function renderPendingList(j) {
    const ul = $("#lstPendingByCoord");
    if (!ul) return;
    const combined = {};
    (j.pending_appointment || []).forEach((x) => {
      combined[x.coordinator_id] = { name: x.coordinator_name, pending_app: x.pending, pending_drop: 0 };
    });
    (j.pending_drop || []).forEach((x) => {
      if (!combined[x.coordinator_id])
        combined[x.coordinator_id] = { name: x.coordinator_name, pending_app: 0, pending_drop: 0 };
      combined[x.coordinator_id].pending_drop = x.pending;
    });

    const entries = Object.values(combined);
    if (!entries.length) {
      ul.innerHTML = `<li class="list-group-item text-muted small">Sin pendientes.</li>`;
      return;
    }
    ul.innerHTML = entries.map((x) => {
      const total = (x.pending_app || 0) + (x.pending_drop || 0);
      return `
        <li class="list-group-item d-flex justify-content-between align-items-center py-2">
          <span class="small">${escapeHtml(x.name || "—")}</span>
          <div class="d-flex gap-2 align-items-center">
            <span class="badge text-bg-primary at-badge-num">${x.pending_app || 0}</span>
            <span class="badge text-bg-danger at-badge-num">${x.pending_drop || 0}</span>
            <span class="badge text-bg-dark at-badge-num">${total}</span>
          </div>
        </li>`;
    }).join("");
  }

  // === CHART EMPTY STATE ===
  function renderChartEmpty(host, canvas) {
    // Ocultar canvas y marcar host via clases CSS (sin inline styles)
    host.classList.add("at-chart-host", "at-chart-host--empty");
    if (!host.querySelector(".at-empty")) {
      const div = document.createElement("div");
      div.className = "at-empty position-absolute top-50 start-50 translate-middle text-center";
      div.innerHTML = `
        <i class="bi bi-bar-chart fs-1 text-muted opacity-50" aria-hidden="true"></i>
        <p class="mt-2 text-muted small mb-0">Sin datos para el rango seleccionado</p>`;
      host.appendChild(div);
    }
  }

  function removeChartEmpty(host) {
    const empty = host.querySelector(".at-empty");
    if (empty) empty.remove();
    host.classList.remove("at-chart-host--empty");
  }

  // === PIE CONTROLS VISIBILIDAD ===
  function syncPieControls(activeTabId) {
    const controls = $("#pieControls");
    if (!controls) return;
    if (PIE_TABS.has(activeTabId)) {
      controls.classList.remove("d-none");
    } else {
      controls.classList.add("d-none");
    }
  }

  // === FILTROS MOBILE (botón oculto junto con inputs) ===
  function syncApplyBtnVisibility() {
    // La clase d-none d-md-inline-block en el botón en el template lo maneja Bootstrap
    // pero lo inicializamos correctamente si no tiene la clase aún
    const btn = $("#btnApplyRange");
    if (btn && !btn.classList.contains("d-none") && !btn.classList.contains("d-md-inline-block")) {
      // Asegurar coherencia: el botón ya tiene d-none d-md-inline-block aplicado desde home.html
    }
  }

  // === EVENT LISTENERS ===
  $("#fltPeriod")?.addEventListener("change", (e) => {
    const periodId = e.target.value;
    if (periodId && periodId !== "all") {
      setPeriodDates(periodId);
    } else {
      initDefaultDates();
    }
    loadOverview();
    const tab = document.querySelector("#leftTabs .nav-link.active")?.id;
    if (PIE_TABS.has(tab)) window.__reloadPies?.();
  });

  $("#btnApplyRange")?.addEventListener("click", () => {
    loadOverview();
    const tab = document.querySelector("#leftTabs .nav-link.active")?.id;
    if (PIE_TABS.has(tab)) window.__reloadPies?.();
  });

  // Tabs: mostrar/ocultar pieControls y refrescar contenido
  document.querySelectorAll('#leftTabs [data-bs-toggle="tab"]').forEach((btn) => {
    btn.addEventListener("shown.bs.tab", (ev) => {
      const activeId = ev.target.id;
      syncPieControls(activeId);

      if (activeId === "tabSeries") loadOverview();
      if (PIE_TABS.has(activeId))  window.__reloadPies?.();
    });
  });

  // === TIEMPO REAL ===
  (function wireRealtime() {
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 400);
      const debounced = debounce(() => {
        loadOverview();
        const tab = document.querySelector("#leftTabs .nav-link.active")?.id;
        if (PIE_TABS.has(tab)) window.__reloadPies?.();
      }, 500);
      s.off?.("appointment_created");
      s.off?.("drop_created");
      s.off?.("request_status_changed");
      s.on("appointment_created", debounced);
      s.on("drop_created", debounced);
      s.on("request_status_changed", debounced);
    };
    tryBind();
  })();

  // Indicador de socket (si usa socket, montamos el dot al lado de los KPIs)
  if (window.AgendaTec?.SocketStatus) {
    const kpiGrid = document.querySelector("#dashKpis");
    if (kpiGrid) {
      window.AgendaTec.SocketStatus.mount({ anchor: kpiGrid });
    }
  }

  // === UTILIDADES ===
  function formatHour(isoish) {
    if (!isoish) return "";
    const d = new Date(isoish);
    if (isNaN(d.getTime())) return isoish;
    return d.toLocaleString("es-MX", {
      month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
      hour12: false,
    });
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function debounce(fn, wait) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), wait); };
  }

  // === INICIALIZAR ===
  showKpiSkeleton();
  // Iniciar pieControls ocultos (tab activo es Serie)
  syncPieControls("tabSeries");

  loadPeriods().then(() => {
    loadOverview();
  });
})();
