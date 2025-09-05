// static/js/admin/home.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminDashboard || {};
  const fetchUrl = cfg.fetchUrl || cfg.Url || "/api/agendatec/v1/admin/stats/overview";

  let chSeries;
  const stateMap = {
    PENDING: "#mPending",
    RESOLVED_SUCCESS: "#mSolved",
    RESOLVED_NOT_COMPLETED: "#mNotCompleted",
    NO_SHOW: "#mNoShow",
    ATTENDED_OTHER_SLOT: "#mOtherSlot",
    CANCELED: "#mCanceled",
  };

  // Rango por defecto: últimos 7 días
  function initDates() {
    //const to = new Date();
    //const from = new Date(Date.now() - 7 * 86400000);
    const to = new Date ('2025-08-27');
    const from = new Date('2025-08-24');
    $("#fltTo").value = to.toISOString().slice(0, 10);
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

  async function loadOverview() {
    try {
      const r = await fetch(`${fetchUrl}?${qs()}`, { credentials: "include" });
      if (!r.ok) throw new Error("Bad response");
      const j = await r.json();

      // KPIs
      const totals = Object.fromEntries((j.totals || []).map((x) => [x.status, x.total]));
      for (const [st, sel] of Object.entries(stateMap)) {
        const v = totals[st] || 0;
        const el = $(sel);
        if (el) el.textContent = String(v);
      }

      // No-show rate
      $("#lblNoShowRate").textContent = (((j.no_show_rate || 0) * 100).toFixed(1) + "%");

      // Serie por hora (o fallback por día)
      const rawSeries = Array.isArray(j.series) ? j.series : [];
      const labels = rawSeries.map(x => formatHour(x.hour || x.day));
      const data = rawSeries.map(x => Number(x.total || 0));

      if (chSeries) chSeries.destroy?.();
      const host = document.querySelector("#paneSeries .seriesHost");
      const ctx = $("#chSeries");
      if (ctx && host) {
        // altura estable via CSS (.seriesHost)
        chSeries = new Chart(ctx, {
          type: "line",
          data: {
            labels,
            datasets: [{
              label: "Solicitudes",
              data,
              tension: 0.3,
              pointRadius: 2
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              tooltip: {
                callbacks: {
                  title(items) { return items?.[0]?.label || ""; },
                  label(c) { return ` ${c.dataset.label}: ${c.parsed.y}`; }
                }
              },
              legend: { display: false }
            },
            scales: {
              x: { ticks: { maxRotation: 0, autoSkip: true } },
              y: { beginAtZero: true, grace: "5%" }
            }
          }
        });
      }

      // Pendientes por coordinador (citas + bajas)
      const ul = $("#lstPendingByCoord");
      if (ul) {
        const combined = {};
        (j.pending_appointment || []).forEach(x => {
          combined[x.coordinator_id] = { name: x.coordinator_name, pending_app: x.pending, pending_drop: 0 };
        });
        (j.pending_drop || []).forEach(x => {
          if (!combined[x.coordinator_id]) combined[x.coordinator_id] = { name: x.coordinator_name, pending_app: 0, pending_drop: 0 };
          combined[x.coordinator_id].pending_drop = x.pending;
        });
        const items = Object.values(combined).map(x => `
          <li class="list-group-item d-flex justify-content-between align-items-center">
            <span>${escapeHtml(x.name || "—")}</span>
            <div>
              <span class="badge text-bg-primary me-2">${x.pending_app || 0}</span>
              <span class="badge text-bg-danger">${x.pending_drop || 0}</span>
            </div>
          </li>`).join("");
        ul.innerHTML = items || `<li class="list-group-item text-muted">Sin pendientes.</li>`;
      }
    } catch (e) {
      showToast?.("Error al cargar estadísticas", "error");
      console.error(e);
    }
  }

  function formatHour(isoish) {
    if (!isoish) return "";
    const d = new Date(isoish);
    if (isNaN(d.getTime())) return isoish;
    return d.toLocaleString("es-MX", {
      month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
      hour12: false
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

  // Rango
  $("#btnApplyRange")?.addEventListener("click", () => {
    loadOverview();
    // si hay un pastel visible, refresca también
    const tab = document.querySelector("#leftTabs .nav-link.active")?.id;
    if (tab === "tabPieGlobal" || tab === "tabPieMini") {
      window.__reloadPies?.();
    }
  });

  // Tabs: mostrar/ocultar controles de pastel y refrescar contenido de pestaña
  document.querySelectorAll('#leftTabs [data-bs-toggle="tab"]').forEach(btn => {
    btn.addEventListener('shown.bs.tab', (ev) => {
      const activeId = ev.target.id; // tabSeries | tabPieGlobal | tabPieMini
      const controls = $("#pieControls");
      if (controls) controls.classList.toggle("d-none", activeId === "tabSeries");

      if (activeId === "tabSeries") loadOverview();
      if (activeId === "tabPieGlobal" || activeId === "tabPieMini") {
        window.__reloadPies?.();
      }
    });
  });

  // Realtime
  (function wireRealtime() {
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 400);
      const debounced = debounce(() => {
        loadOverview();
        const tab = document.querySelector("#leftTabs .nav-link.active")?.id;
        if (tab === "tabPieGlobal" || tab === "tabPieMini") {
          window.__reloadPies?.();
        }
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

  function debounce(fn, wait) {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), wait); };
  }

  initDates();
  loadOverview(); // primera carga
})();
