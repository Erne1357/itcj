// static/js/admin/home_bars.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminDashboard || {};
  const piesUrl = cfg.piesUrl || "/api/agendatec/v1/admin/stats/coordinators";

  let chBarsGlobal = null;
  let chBarsCoord  = null;

  const STATUS_ORDER = [
    "PENDING",
    "RESOLVED_SUCCESS",
    "RESOLVED_NOT_COMPLETED",
    "ATTENDED_OTHER_SLOT",
    "NO_SHOW",
    "CANCELED",
  ];
  const STATUS_LABEL = {
    PENDING: "Pendientes",
    RESOLVED_SUCCESS: "Resueltas",
    RESOLVED_NOT_COMPLETED: "No resueltas",
    ATTENDED_OTHER_SLOT: "Otro horario",
    NO_SHOW: "No asistió",
    CANCELED: "Canceladas",
  };

  function buildQuery() {
    const q = new URLSearchParams();
    const from = $("#fltFrom")?.value;
    const to   = $("#fltTo")?.value;
    if (from) q.set("from", from);
    if (to)   q.set("to", to);
    q.set("states", "1"); // necesitamos desglose por estado
    return q.toString();
  }

  function destroy(ch) { try { ch?.destroy?.(); } catch {} return null; }

  function percSeriesFromStates(statesObj) {
    const total = STATUS_ORDER.reduce((a,k)=>a+Number(statesObj?.[k]||0), 0) || 1;
    return STATUS_ORDER.map(k => Math.round((Number(statesObj?.[k]||0) * 10000) / total)/100);
  }

  function ensureOnce(cb){ let ran=false; return (...a)=>{ if(ran) return; ran=true; cb(...a);} }

  async function loadBars() {
    const r = await fetch(`${piesUrl}?${buildQuery()}`, { credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();

    // ------ GLOBAL ------
    const labels = STATUS_ORDER.map(k => STATUS_LABEL[k]);
    const globalPerc = percSeriesFromStates(j?.overall?.states || {});
    chBarsGlobal = destroy(chBarsGlobal);
    const cvG = $("#chBarsGlobal");
    if (cvG) {
      chBarsGlobal = new Chart(cvG, {
        type: "bar",
        data: { labels, datasets: [{ label: "% del total", data: globalPerc }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { y: { beginAtZero: true, max: 100, ticks: { callback: v => v + "%" } } },
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.parsed.y}%` } } }
        }
      });
    }

    // ------ POR COORDINADOR (apiladas 100%) ------
    const coords = (j.coordinators || []).slice().sort((a,b) =>
      (a.coordinator_name||"").localeCompare(b.coordinator_name||"")
    );
    const coordLabels = coords.map(c => c.coordinator_name || `#${c.coordinator_id}`);

    // Para apilado 100%, cada dataset es un estado con vector por coordinador normalizado a %
    const dataByStatus = {};
    STATUS_ORDER.forEach(k => dataByStatus[k] = []);

    for (const c of coords) {
      const st = (c?.totals?.states) || {};
      const total = STATUS_ORDER.reduce((a,k)=>a+Number(st[k]||0),0) || 1;
      STATUS_ORDER.forEach(k => {
        dataByStatus[k].push(Math.round((Number(st[k]||0)*10000)/total)/100);
      });
    }

    const datasets = STATUS_ORDER.map(k => ({
      label: STATUS_LABEL[k],
      data: dataByStatus[k],
      stack: "pct"
    }));

    chBarsCoord = destroy(chBarsCoord);
    const cvC = $("#chBarsCoord");
    if (cvC) {
      chBarsCoord = new Chart(cvC, {
        type: "bar",
        data: { labels: coordLabels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          indexAxis: 'y',
          scales: {
            x: { beginAtZero: true, max: 100, stacked: true, ticks: { callback: v => v + "%" } },
            y: { stacked: true }
          },
          plugins: { tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.x}%` } } }
        }
      });
    }
  }

  // Carga solo si la pestaña está visible
  const onShowBars = async () => { try { await loadBars(); } catch(e){ console.error(e); } };
  document.getElementById("tabBarsGlobal")?.addEventListener("shown.bs.tab", onShowBars);
  document.getElementById("tabBarsCoord") ?.addEventListener("shown.bs.tab", onShowBars);

  // Si ya están activas al llegar:
  if (document.getElementById("paneBarsGlobal")?.classList.contains("active") ||
      document.getElementById("paneBarsCoord") ?.classList.contains("active")) {
    onShowBars();
  }

  // Integración con rango y realtime
  $("#btnApplyRange")?.addEventListener("click", onShowBars);
  (function wireRealtime() {
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 400);
      const debounced = ((fn, t)=>{let h;return (...a)=>{clearTimeout(h);h=setTimeout(()=>fn(...a),t);};})(onShowBars, 600);
      s.off?.("appointment_created"); s.off?.("drop_created"); s.off?.("request_status_changed");
      s.on("appointment_created", debounced);
      s.on("drop_created", debounced);
      s.on("request_status_changed", debounced);
    };
    tryBind();
  })();

})();
