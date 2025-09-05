// static/js/student/requests.js (REEMPLAZO COMPLETO)
(async () => {
  const panel = document.getElementById("reqPanel");
  const RELEVANT_TYPES = new Set([
    "REQUEST_STATUS_CHANGED",    // cambio de estado por coordinador
    "APPOINTMENT_CREATED",       // cuando se agenda la cita
    "APPOINTMENT_CANCELED",      // cancelación
    "DROP_CREATED"               // solicitud de baja creada
  ]);
  let __reloadTimer = null;
  const scheduleReload = () => {
    clearTimeout(__reloadTimer);
    __reloadTimer = setTimeout(() => load().catch(() => { }), 300); // debounced
  };
  document.addEventListener("notif:push", (e) => {
    const t = e?.detail?.type;
    if (RELEVANT_TYPES.has(t)) {
      // Opcional: feedback mínimo en consola
      console.log("[Mis solicitudes] notif -> reload:", t, e.detail);
      scheduleReload();
    }
  });
  // --- Helpers de mapeo a español (UI) ---
  const mapType = (t) => ({
    "APPOINTMENT": "CITA",
    "DROP": "BAJA",
    "BOTH": "ALTA Y BAJA" // por si en el futuro muestran combinadas
  }[t] || t);

  const mapReqStatus = (s) => ({
    "PENDING": "PENDIENTE",
    "RESOLVED_SUCCESS": "ATENDIDA Y RESUELTA",
    "RESOLVED_NOT_COMPLETED": "ATENDIDA NO RESUELTA",
    "NO_SHOW": "NO ASISTIÓ",
    "ATTENDED_OTHER_SLOT": "ASISTIÓ EN OTRO HORARIO",
    "CANCELED": "CANCELADA"
  }[s] || s);

  const mapApptStatus = (s) => ({
    "SCHEDULED": "PROGRAMADA",
    "DONE": "CONCLUIDA",
    "NO_SHOW": "NO ASISTIÓ",
    "CANCELED": "CANCELADA"
  }[s] || s);

  const fmtDate = (iso) => {
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit"
      });
    } catch { return iso || ""; }
  };

  const dayRange = (slot) => {
    if (!slot) return "";
    // slot.day ya suele venir YYYY-MM-DD; start_time/end_time tipo HH:MM
    return `${slot.day} • ${slot.start_time}–${slot.end_time}`;
  };

  // Render badge minimalista
  const badge = (text, tone = "secondary") =>
    `<span class="badge text-bg-${tone}" style="letter-spacing:.3px">${text}</span>`;

  // Botón primario minimalista
  const btn = (label, { id = "", cls = "btn btn-sm btn-outline-danger", attrs = "" } = {}) =>
    `<button ${id ? `id="${id}"` : ""} class="${cls}" ${attrs}>${label}</button>`;

  // --- Carga inicial ---
  await load();

  // --- Función principal de carga + render ---
  async function load() {
    try {
      panel.innerHTML = skeleton();
      const r = await fetch("/api/agendatec/v1/requests/mine", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();

      const activeHtml = renderActive(data.active);
      const historyHtml = renderHistory(data.history || []);
      panel.innerHTML = `
        <div class="d-flex flex-column gap-3">
          ${activeHtml}
          ${historyHtml}
        </div>
      `;

      // Wire cancelar si existe botón
      const cancelBtn = document.getElementById("btnCancelRequest");
      if (cancelBtn) {
        cancelBtn.addEventListener("click", async () => {
          const reqId = cancelBtn.getAttribute("data-id");
          // Confirm mínimo viable, puedes cambiarlo por un modal bootstrap si prefieres
          const ok = window.confirm("¿Seguro que deseas cancelar tu solicitud? Esta acción no se puede deshacer.");
          if (!ok) return;
          await doCancel(reqId);
        });
      }
    } catch (e) {
      panel.innerHTML = `<div class="text-muted">No se pudieron cargar tus solicitudes.</div>`;
      console.error("Error al cargar solicitudes:", e);
    }
  }

  // --- Render “Solicitud activa” ---
  function renderActive(active) {
    if (!active) {
      return `
        <div class="card border-0 shadow-sm">
          <div class="card-body">
            <div class="d-flex align-items-center justify-content-between">
              <h6 class="mb-0">Solicitud activa</h6>
              ${badge("NINGUNA", "secondary")}
            </div>
            <div class="text-muted small mt-2">No tienes solicitud activa.</div>
          </div>
        </div>
      `;
    }

    const type = mapType(active.type);
    const reqStatus = mapReqStatus(active.status);
    const created = fmtDate(active.created_at);
    const desc = (active.description || "Sin descripción").trim();

    // Si tiene cita asociada, mostramos datos de la cita
    const hasAppt = !!active.appointment;
    const appt = active.appointment || null;
    const apptStatus = hasAppt ? mapApptStatus(appt.status) : null;
    const apptLine = hasAppt
      ? `<div class="small">
           <i class="bi bi-calendar2 me-1"></i>
           ${dayRange(appt.slot)}
         </div>`
      : "";

    // Elegimos tono del estatus
    const statusTone = toneForStatus(active.status);
    const typeTone = active.type === "DROP" ? "warning" : "primary";

    // Elegibilidad para cancelar:
    // - Request PENDING
    // - Si trae cita: que la cita esté SCHEDULED (programada)
    const canCancel =
      active.status === "PENDING" &&
      (!hasAppt || (hasAppt && appt.status === "SCHEDULED"));

    return `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
            <h6 class="mb-0">Solicitud activa</h6>
            <div class="d-flex align-items-center gap-2">
              ${badge(type, typeTone)}
              ${badge(reqStatus, statusTone)}
              ${hasAppt ? badge(`Cita: ${apptStatus}`, "info") : ""}
            </div>
          </div>

          <div class="mt-2">
            ${apptLine}
            <div class="small text-muted">
              <i class="bi bi-clock me-1"></i> Creada: ${created}
            </div>
            <div class="small mt-1">${escapeHtml(desc)}</div>
          </div>

          <div class="mt-3 d-flex gap-2">
            ${canCancel ? btn("Cancelar solicitud", {
      id: "btnCancelRequest",
      cls: "btn btn-sm btn-outline-danger",
      attrs: `data-id="${active.id}"`
    }) : ""}
          </div>
        </div>
      </div>
    `;
  }

  // --- Render “Historial” ---
  function renderHistory(items) {
    if (!items.length) {
      return `
        <div class="card border-0 shadow-sm">
          <div class="card-body">
            <h6 class="mb-2">Historial</h6>
            <div class="text-muted small">Sin historial.</div>
          </div>
        </div>
      `;
    }

    // Ordenar descendente por fecha de creación (asumiendo created_at ISO)
    items.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    const lis = items.map(h => {
      const t = mapType(h.type);
      const s = mapReqStatus(h.status);
      const when = fmtDate(h.created_at);
      const comment = h.comment;
      const tone = toneForStatus(h.status);
      return `
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <div class="d-flex flex-column">
            <span class="fw-semibold">${t}</span>
            <span class="small text-muted">${comment ? "Comentarios : " + comment : ""}</span>
            <span class="small text-muted">${when}</span>
          </div>
          ${badge(s, tone)}
        </li>
      `;
    }).join("");

    return `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <h6 class="mb-2">Historial</h6>
          <ul class="list-group list-group-flush">
            ${lis}
          </ul>
        </div>
      </div>
    `;
  }

  // --- Cancelar solicitud ---
  async function doCancel(reqId) {
    try {
      const r = await fetch(`/api/agendatec/v1/requests/${reqId}/cancel`, {
        method: "PATCH",
        credentials: "include"
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (err.error === "not_pending") {
          showToast("La solicitud ya no está pendiente.", "warn");
        } else if (err.error === "request_not_found") {
          showToast("Solicitud no encontrada.", "warn");
        } else {
          showToast("No se pudo cancelar la solicitud.", "error");
        }
        return;
      }
      showToast("Solicitud cancelada.", "success");
      await load(); // recargar vista
    } catch (e) {
      console.error(e);
      showToast("No se pudo conectar.", "error");
    }
  }

  // --- Tonos por estatus (Bootstrap) ---
  function toneForStatus(status) {
    switch (status) {
      case "PENDING": return "warning";
      case "RESOLVED_SUCCESS": return "success";
      case "RESOLVED_NOT_COMPLETED": return "secondary";
      case "NO_SHOW": return "danger";
      case "ATTENDED_OTHER_SLOT": return "info";
      case "CANCELED": return "secondary";
      default: return "secondary";
    }
  }

  // --- Skeleton mínimo mientras carga ---
  function skeleton() {
    return `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <div class="placeholder-glow">
            <span class="placeholder col-3"></span>
            <div class="mt-2">
              <span class="placeholder col-6"></span>
              <span class="placeholder col-4"></span>
              <span class="placeholder col-8"></span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // --- Escape básico para texto ---
  function escapeHtml(str) {
    return (str || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
