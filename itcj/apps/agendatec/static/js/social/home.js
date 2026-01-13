// static/js/social/home.js
(() => {
  const $ = (sel) => document.querySelector(sel);

  // Estado para controlar a qué sala estamos unidos
  let lastJoin = { day: null, program_id: null };

  // Cargar lista de carreras (programas)
  async function loadPrograms() {
    try {
      const r = await fetch("/api/agendatec/v1/programs", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();
      const sel = $("#ssProgram");
      const opts = ['<option value="">Todas</option>'].concat(
        (data.items || []).map(p => `<option value="${p.id}">${p.name}</option>`)
      );
      sel.innerHTML = opts.join("");
    } catch {
      showToast?.("No se pudieron cargar las carreras.", "error");
    }
  }

  async function loadAppointments() {
    const day = $("#ssDay").value;
    const programId = $("#ssProgram").value;

    // Unirse a la sala correcta de sockets (día + programa opcional)
    try {
      if (lastJoin.day) {
        window.__socialLeaveApDay?.({ day: lastJoin.day, program_id: lastJoin.program_id || null });
      }
      window.__socialJoinApDay?.({ day, program_id: programId || null });
      lastJoin = { day, program_id: programId || null };
    } catch {}

    const url = new URL("/api/agendatec/v1/social/appointments", window.location.origin);
    url.searchParams.set("day", day);
    if (programId) url.searchParams.set("program_id", programId);

    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();
      renderTable(data.items || []);
    } catch {
      showToast?.("Error al cargar citas.", "error");
    }
  }

  function renderTable(items) {
    const el = $("#ssList");
    if (!items.length) {
      el.innerHTML = `<div class="text-muted">Sin citas.</div>`;
      return;
    }
    let html = `<table class="table table-sm table-striped align-middle">
      <thead>
        <tr>
          <th style="width:160px">Horario</th>
          <th>Nombre</th>
        </tr>
      </thead>
      <tbody>`;
    for (const it of items) {
      html += `<tr>
        <td>${it.time}</td>
        <td>${escapeHtml(it.student_name || "—")}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
  }

  function escapeHtml(str) {
    return (str || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // Realtime: refrescar ante eventos relevantes
  (function wireRealtime(){
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 500);

      s.off?.("appointment_created");
      s.off?.("request_status_changed");

      const matchesFilter = (payload) => {
        const day = $("#ssDay").value;
        const programId = $("#ssProgram").value;
        if (payload?.type === "APPOINTMENT") {
          if (payload.day && payload.day !== day) return false;
          if (programId && Number(payload.program_id || 0) !== Number(programId)) return false;
          return true;
        }
        return false;
      };

      s.on("appointment_created", (p) => {
        // Se emite con: slot_day, program_id
        const payload = { type: "APPOINTMENT", day: p?.slot_day, program_id: p?.program_id };
        if (matchesFilter(payload)) $("#btnLoadSS")?.click();
      });

      s.on("request_status_changed", (p) => {
        // Solo nos interesan cambios en APPOINTMENT (cancel/resuelto) para “limpiar”/actualizar vista
        if (p?.type === "APPOINTMENT" && matchesFilter(p)) {
          $("#btnLoadSS")?.click();
        }
      });
    };
    tryBind();
  })();

  // Listeners UI
  $("#btnLoadSS").addEventListener("click", loadAppointments);
  $("#ssDay").addEventListener("change", () => $("#btnLoadSS").click());
  $("#ssProgram").addEventListener("change", () => $("#btnLoadSS").click());

  // Esperar a que home_init.js termine de cargar los días
  document.addEventListener('socialHomeInitReady', (e) => {
    const selectedDay = e.detail?.selectedDay;
    if (selectedDay) {
      // Solo cargar si hay un día seleccionado
      $("#btnLoadSS").click();
    }
  });

  // Cargar programas al inicio
  loadPrograms();
})();
