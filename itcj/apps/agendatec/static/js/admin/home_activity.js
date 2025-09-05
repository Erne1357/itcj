// static/js/admin/home_activity.js
(() => {
  if (window.__homeActivityMounted) return;
  window.__homeActivityMounted = true;

  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminDashboard || {};
  const activityUrl = cfg.activityUrl || "/api/agendatec/v1/admin/stats/activity";

  let chActGlobal = null;
  let chActCoord  = null;
  let lastData    = null; // cache para cambiar de coordinador sin re-fetch

  function buildQuery() {
    const q = new URLSearchParams();
    const from = $("#fltFrom")?.value;
    const to   = $("#fltTo")?.value;
    if (from) q.set("from", from);
    if (to)   q.set("to", to);
    return q.toString();
  }

  function getHost(canvas) {
    // Usa .actHost si existe; si no, el padre inmediato como fallback
    const host = canvas.closest(".actHost") || canvas.parentElement || canvas;
    // Asegura altura estable si no hay CSS aplicado (por si el HTML no fue editado)
    if (!host.style.height) host.style.height = "280px";
    if (!host.style.position) host.style.position = "relative";
    // Canvas al 100% del host
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    return host;
  }

  function destroy(ch){ try{ ch?.destroy?.(); }catch{} return null; }

  function drawGlobal(labels, values) {
    const cv = $("#chActGlobal");
    if (!cv) return;
    getHost(cv);                   // fija host y tamaño
    chActGlobal = destroy(chActGlobal);
    chActGlobal = new Chart(cv, {
      type: "bar",
      data: { labels, datasets: [{ label: "Solicitudes actualizadas", data: values }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 150,
        animation: { duration: 200 },
        scales: { y: { beginAtZero: true, grace: "5%" } },
        plugins: { legend: { display: false } }
      }
    });
  }

  function drawCoord(labels, values, title) {
    const cv = $("#chActCoord");
    if (!cv) return;
    getHost(cv);                   // fija host y tamaño
    chActCoord = destroy(chActCoord);
    chActCoord = new Chart(cv, {
      type: "bar",
      data: { labels, datasets: [{ label: title || "Coordinador", data: values }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 150,
        animation: { duration: 200 },
        scales: { y: { beginAtZero: true, grace: "5%" } },
        plugins: { legend: { display: false } }
      }
    });
  }

  function fillSelector(coordinators) {
    const sel = $("#selActCoord");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = `<option value="">(Selecciona)</option>` +
      (coordinators||[]).map(c => `<option value="${c.id}">${(c.name||"")}</option>`).join("");
    // conservar si existe
    if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
  }

  async function loadActivity() {
    const r = await fetch(`${activityUrl}?${buildQuery()}`, { credentials: "include" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    lastData = j;

    const labels = j.labels || Array.from({length:24}, (_,i)=>`${i.toString().padStart(2,"0")}:00`);
    drawGlobal(labels, j.overall || []);

    fillSelector(j.coordinators);
    // Si ya hay elegido, pinta; si no, limpia
    const sel = $("#selActCoord");
    const chosen = sel?.value;
    if (chosen) {
      const c = (j.coordinators||[]).find(x=> String(x.id) === String(chosen));
      drawCoord(labels, c?.hours || [], c?.name || "Coordinador");
    } else {
      drawCoord(labels, [], "(Selecciona)");
    }
  }

  $("#selActCoord")?.addEventListener("change", () => {
    if (!lastData) return;
    const labels = lastData.labels || [];
    const sel = $("#selActCoord");
    const c = (lastData.coordinators||[]).find(x=> String(x.id) === String(sel.value));
    drawCoord(labels, c?.hours || [], c?.name || "Coordinador");
  });

  // Cargar solo cuando se muestre la pestaña
  const onShow = async () => { try { await loadActivity(); } catch(e){ console.error(e); } };
  document.getElementById("tabActivity")?.addEventListener("shown.bs.tab", onShow);

  // Si ya está activa, carga
  if (document.getElementById("paneActivity")?.classList.contains("active")) onShow();

  // Integración con rango y realtime — evita desregistrar handlers de otros módulos
  if (!window.__homeActivityBound) {
    $("#btnApplyRange")?.addEventListener("click", onShow);
    (function wireRealtime() {
      const tryBind = () => {
        const s = window.__reqSocket;
        if (!s) return setTimeout(tryBind, 400);
        const debounced = ((fn, t)=>{let h;return (...a)=>{clearTimeout(h);h=setTimeout(()=>fn(...a),t);};})(onShow, 600);
        // ¡NO usamos s.off() sin referencia! Para no romper otros listeners
        s.on("appointment_created", debounced);
        s.on("drop_created", debounced);
        s.on("request_status_changed", debounced);
      };
      tryBind();
    })();
    window.__homeActivityBound = true;
  }
})();
