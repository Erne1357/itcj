// static/js/admin/home_bars.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg     = window.__adminDashboard || {};
  const piesUrl = cfg.piesUrl || "/api/agendatec/v2/admin/stats/coordinators";
  const palette = window.AgendaTec?.ChartPalette;

  let chBarsGlobal = null;
  let chBarsCoord  = null;

  const STATUS_ORDER = palette?.STATUS_ORDER || [
    "PENDING", "RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED",
    "ATTENDED_OTHER_SLOT", "NO_SHOW", "CANCELED",
  ];
  const STATUS_LABEL = palette?.statusLabels || {
    PENDING: "Pendientes",
    RESOLVED_SUCCESS: "Resueltas",
    RESOLVED_NOT_COMPLETED: "No resueltas",
    ATTENDED_OTHER_SLOT: "Otro horario",
    NO_SHOW: "No asistió",
    CANCELED: "Canceladas",
  };
  const STATUS_COLORS = STATUS_ORDER.map((k) => palette?.statusColors?.[k] || "");

  function buildQuery() {
    const q = new URLSearchParams();
    const from = $("#fltFrom")?.value;
    const to   = $("#fltTo")?.value;
    if (from) q.set("from", from);
    if (to)   q.set("to", to);
    q.set("states", "1");
    return q.toString();
  }

  function destroy(ch) { try { ch?.destroy?.(); } catch {} return null; }

  function percSeriesFromStates(statesObj) {
    const total = STATUS_ORDER.reduce((a, k) => a + Number(statesObj?.[k] || 0), 0) || 1;
    return STATUS_ORDER.map((k) => Math.round((Number(statesObj?.[k] || 0) * 10000) / total) / 100);
  }

  // === EMPTY STATE ===
  function renderEmpty(host, message) {
    // Usar clases CSS (sin inline styles)
    host.classList.add("at-chart-host", "at-chart-host--empty");
    if (!host.querySelector(".at-empty--chart")) {
      const el = document.createElement("div");
      el.className = "at-empty--chart d-flex flex-column align-items-center justify-content-center py-4";
      el.innerHTML = `<i class="bi bi-bar-chart fs-2 text-muted opacity-50" aria-hidden="true"></i>
        <p class="mt-2 text-muted small mb-0">${message || "Sin datos para el rango seleccionado"}</p>`;
      host.appendChild(el);
    }
  }

  function clearEmpty(host) {
    host.querySelector(".at-empty--chart")?.remove();
    host.classList.remove("at-chart-host--empty");
  }

  async function loadBars() {
    const r = await fetch(`${piesUrl}?${buildQuery()}`, { credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();

    // ------ GLOBAL ------
    const labels      = STATUS_ORDER.map((k) => STATUS_LABEL[k]);
    const globalPerc  = percSeriesFromStates(j?.overall?.states || {});
    chBarsGlobal = destroy(chBarsGlobal);
    const cvG = $("#chBarsGlobal");
    const hostG = cvG?.closest(".border.rounded");
    if (cvG) {
      if (hostG) clearEmpty(hostG);
      const allZero = globalPerc.every((v) => v === 0);
      if (allZero) {
        if (hostG) renderEmpty(hostG, "Sin datos para el rango seleccionado");
      } else {
        chBarsGlobal = new Chart(cvG, {
          type: "bar",
          data: {
            labels,
            datasets: [{
              label: "% del total",
              data: globalPerc,
              backgroundColor: STATUS_COLORS,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: { beginAtZero: true, max: 100, ticks: { callback: (v) => v + "%" } },
            },
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.y}%` } },
            },
          },
        });
      }
    }

    // ------ POR COORDINADOR (apiladas 100%) ------
    const coords = (j.coordinators || []).slice().sort(
      (a, b) => (a.coordinator_name || "").localeCompare(b.coordinator_name || "")
    );
    const coordLabels = coords.map((c) => c.coordinator_name || `#${c.coordinator_id}`);

    const dataByStatus = {};
    STATUS_ORDER.forEach((k) => (dataByStatus[k] = []));
    for (const c of coords) {
      const st    = c?.totals?.states || {};
      const total = STATUS_ORDER.reduce((a, k) => a + Number(st[k] || 0), 0) || 1;
      STATUS_ORDER.forEach((k) => {
        dataByStatus[k].push(Math.round((Number(st[k] || 0) * 10000) / total) / 100);
      });
    }

    const datasets = STATUS_ORDER.map((k, i) => ({
      label: STATUS_LABEL[k],
      data: dataByStatus[k],
      backgroundColor: STATUS_COLORS[i] || "",
      stack: "pct",
    }));

    chBarsCoord = destroy(chBarsCoord);
    const cvC = $("#chBarsCoord");
    const hostC = cvC?.closest(".border.rounded");
    if (cvC) {
      if (hostC) clearEmpty(hostC);
      if (!coords.length) {
        if (hostC) renderEmpty(hostC, "Sin datos de coordinadores");
      } else {
        chBarsCoord = new Chart(cvC, {
          type: "bar",
          data: { labels: coordLabels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: "y",
            scales: {
              x: {
                beginAtZero: true, max: 100, stacked: true,
                ticks: { callback: (v) => v + "%" },
              },
              y: { stacked: true },
            },
            plugins: {
              tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.x}%` } },
            },
          },
        });
      }
    }
  }

  const onShowBars = async () => { try { await loadBars(); } catch (e) { console.error(e); } };
  document.getElementById("tabBarsGlobal")?.addEventListener("shown.bs.tab", onShowBars);
  document.getElementById("tabBarsCoord")?.addEventListener("shown.bs.tab",  onShowBars);

  if (
    document.getElementById("paneBarsGlobal")?.classList.contains("active") ||
    document.getElementById("paneBarsCoord")?.classList.contains("active")
  ) {
    onShowBars();
  }

  $("#btnApplyRange")?.addEventListener("click", onShowBars);

  (function wireRealtime() {
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 400);
      const debounced = ((fn, t) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), t); }; })(onShowBars, 600);
      s.off?.("appointment_created");
      s.off?.("drop_created");
      s.off?.("request_status_changed");
      s.on("appointment_created", debounced);
      s.on("drop_created", debounced);
      s.on("request_status_changed", debounced);
    };
    tryBind();
  })();
})();
