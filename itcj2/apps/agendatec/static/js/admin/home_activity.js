// static/js/admin/home_activity.js
(() => {
  if (window.__homeActivityMounted) return;
  window.__homeActivityMounted = true;

  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminDashboard || {};
  const activityUrl = cfg.activityUrl || "/api/agendatec/v2/admin/stats/activity";
  const palette = window.AgendaTec?.ChartPalette;

  let chActGlobal = null;
  let chActCoord  = null;
  let lastData    = null;

  const barColor = palette?.statusColors?.PENDING
    || getComputedStyle(document.documentElement).getPropertyValue("--at-primary").trim();

  function buildQuery() {
    const q = new URLSearchParams();
    const from = $("#fltFrom")?.value;
    const to   = $("#fltTo")?.value;
    if (from) q.set("from", from);
    if (to)   q.set("to", to);
    return q.toString();
  }

  function getHost(canvas) {
    const host = canvas.closest(".actHost") || canvas.parentElement || canvas;
    return host;
  }

  function destroy(ch) { try { ch?.destroy?.(); } catch {} return null; }

  // === EMPTY STATE ===
  function renderEmpty(host, message) {
    // Usar clases CSS (sin inline styles)
    host.classList.add("at-chart-host", "at-chart-host--empty");
    if (!host.querySelector(".at-empty--chart")) {
      const el = document.createElement("div");
      el.className = "at-empty--chart d-flex flex-column align-items-center justify-content-center h-100 py-4";
      el.innerHTML = `<i class="bi bi-bar-chart fs-2 text-muted opacity-50" aria-hidden="true"></i>
        <p class="mt-2 text-muted small mb-0">${message || "Sin datos"}</p>`;
      host.appendChild(el);
    }
  }

  function clearEmpty(host) {
    host.querySelector(".at-empty--chart")?.remove();
    host.classList.remove("at-chart-host--empty");
  }

  function drawGlobal(labels, values) {
    const cv = $("#chActGlobal");
    if (!cv) return;
    const host = getHost(cv);
    clearEmpty(host);
    chActGlobal = destroy(chActGlobal);

    const allZero = values.every((v) => v === 0);
    if (allZero) {
      renderEmpty(host, "Sin actividad para el rango seleccionado");
      return;
    }

    chActGlobal = new Chart(cv, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "Solicitudes actualizadas",
          data: values,
          backgroundColor: barColor,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 150,
        animation: { duration: 200 },
        scales: { y: { beginAtZero: true, grace: "5%" } },
        plugins: { legend: { display: false } },
      },
    });
  }

  function drawCoord(labels, values, title) {
    const cv = $("#chActCoord");
    if (!cv) return;
    const host = getHost(cv);
    clearEmpty(host);
    chActCoord = destroy(chActCoord);

    const allZero = values.every((v) => v === 0);
    if (allZero) {
      renderEmpty(host, "Sin actividad para este coordinador");
      return;
    }

    chActCoord = new Chart(cv, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: title || "Coordinador",
          data: values,
          backgroundColor: palette?.coordColors?.[1] || barColor,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 150,
        animation: { duration: 200 },
        scales: { y: { beginAtZero: true, grace: "5%" } },
        plugins: { legend: { display: false } },
      },
    });
  }

  function fillSelector(coordinators) {
    const sel = $("#selActCoord");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = `<option value="">(Selecciona)</option>` +
      (coordinators || []).map((c) => `<option value="${c.id}">${escapeHtml(c.name || "")}</option>`).join("");
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  }

  async function loadActivity() {
    const r = await fetch(`${activityUrl}?${buildQuery()}`, { credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    lastData = j;

    const labels = j.labels || Array.from({ length: 24 }, (_, i) => `${i.toString().padStart(2, "0")}:00`);
    drawGlobal(labels, j.overall || []);

    fillSelector(j.coordinators);
    const sel    = $("#selActCoord");
    const chosen = sel?.value;
    if (chosen) {
      const c = (j.coordinators || []).find((x) => String(x.id) === String(chosen));
      drawCoord(labels, c?.hours || [], c?.name || "Coordinador");
    } else {
      drawCoord(labels, [], "(Selecciona)");
    }
  }

  $("#selActCoord")?.addEventListener("change", () => {
    if (!lastData) return;
    const labels = lastData.labels || [];
    const sel    = $("#selActCoord");
    const c      = (lastData.coordinators || []).find((x) => String(x.id) === String(sel.value));
    drawCoord(labels, c?.hours || [], c?.name || "Coordinador");
  });

  const onShow = async () => { try { await loadActivity(); } catch (e) { console.error(e); } };
  document.getElementById("tabActivity")?.addEventListener("shown.bs.tab", onShow);
  if (document.getElementById("paneActivity")?.classList.contains("active")) onShow();

  if (!window.__homeActivityBound) {
    $("#btnApplyRange")?.addEventListener("click", onShow);
    (function wireRealtime() {
      const tryBind = () => {
        const s = window.__reqSocket;
        if (!s) return setTimeout(tryBind, 400);
        const debounced = ((fn, t) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), t); }; })(onShow, 600);
        s.on("appointment_created", debounced);
        s.on("drop_created", debounced);
        s.on("request_status_changed", debounced);
      };
      tryBind();
    })();
    window.__homeActivityBound = true;
  }

  function escapeHtml(s) {
    return (s || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }
})();
