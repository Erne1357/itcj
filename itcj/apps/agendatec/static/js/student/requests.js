// static/js/student/requests.js
(async () => {
  const panel = document.getElementById("reqPanel");
  const RELEVANT_TYPES = new Set([
    "REQUEST_STATUS_CHANGED",
    "APPOINTMENT_CREATED",
    "APPOINTMENT_CANCELED",
    "DROP_CREATED"
  ]);

  let __reloadTimer = null;
  const scheduleReload = () => {
    clearTimeout(__reloadTimer);
    __reloadTimer = setTimeout(() => load().catch(() => { }), 300);
  };

  document.addEventListener("notif:push", (e) => {
    const t = e?.detail?.type;
    if (RELEVANT_TYPES.has(t)) {
      scheduleReload();
    }
  });

  // --- Helpers de mapeo a español (UI) ---
  const mapType = (t) => ({
    "APPOINTMENT": "CITA",
    "DROP": "BAJA",
    "BOTH": "ALTA Y BAJA"
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
    return `${slot.day} • ${slot.start_time}–${slot.end_time}`;
  };

  const badge = (text, tone = "secondary") =>
    `<span class="badge text-bg-${tone}" style="letter-spacing:.3px">${text}</span>`;

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

      const activeHtml = renderActive(data.active, data.active_period);
      const historyHtml = renderHistory(data.history || [], data.active_period, data.periods || {});

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

  // --- Render "Solicitud activa" ---
  function renderActive(active, activePeriod) {
    if (!active) {
      return `
        <div class="card border-0 shadow-sm">
          <div class="card-body">
            <div class="d-flex align-items-center justify-content-between">
              <h6 class="mb-0">Solicitud activa</h6>
              ${badge("NINGUNA", "secondary")}
            </div>
            <div class="text-muted small mt-2">No tienes solicitud activa en el período actual.</div>
          </div>
        </div>
      `;
    }

    const type = mapType(active.type);
    const reqStatus = mapReqStatus(active.status);
    const created = fmtDate(active.created_at);
    const desc = (active.description || "Sin descripción").trim();

    const hasAppt = !!active.appointment;
    const appt = active.appointment || null;
    const apptStatus = hasAppt ? mapApptStatus(appt.status) : null;
    const apptLine = hasAppt
      ? `<div class="small">
           <i class="bi bi-calendar2 me-1"></i>
           ${dayRange(appt.slot)}
         </div>`
      : "";

    const statusTone = toneForStatus(active.status);
    const typeTone = active.type === "DROP" ? "warning" : "primary";

    // Determine if cancel button should be shown
    const canCancel = canCancelRequest(active, activePeriod);

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

          ${canCancel ? `
          <div class="mt-3 d-flex gap-2">
            ${btn("Cancelar solicitud", {
              id: "btnCancelRequest",
              cls: "btn btn-sm btn-outline-danger",
              attrs: `data-id="${active.id}"`
            })}
          </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  // --- Determinar si se puede cancelar una solicitud ---
  function canCancelRequest(request, activePeriod) {
    // Solo se puede cancelar si el estado es PENDING
    if (request.status !== "PENDING") {
      return false;
    }

    // Verificar que el período esté activo
    const period = request.period;
    if (!period || period.status !== "ACTIVE") {
      return false;
    }

    // Si hay un student_admission_deadline, verificar que no haya pasado
    if (activePeriod && activePeriod.student_admission_deadline) {
      const now = new Date();
      const deadline = new Date(activePeriod.student_admission_deadline);
      if (now > deadline) {
        return false;
      }
    }

    // Si es APPOINTMENT, verificar que la cita no haya pasado
    if (request.type === "APPOINTMENT" && request.appointment) {
      const slot = request.appointment.slot;
      if (slot) {
        const now = new Date();
        const slotDateTime = new Date(`${slot.day}T${slot.start_time}`);
        if (now >= slotDateTime) {
          return false;
        }
      }
    }

    return true;
  }

  // --- Render "Historial" agrupado por período ---
  function renderHistory(items, activePeriod, periods) {
    // Agrupar solicitudes por período
    const groupedByPeriod = {};

    for (const item of items) {
      const periodId = item.period_id || "sin_periodo";
      if (!groupedByPeriod[periodId]) {
        groupedByPeriod[periodId] = [];
      }
      groupedByPeriod[periodId].push(item);
    }

    // Ordenar períodos: primero el activo, luego los demás por ID descendente
    const activePeriodId = activePeriod ? activePeriod.id : null;
    const periodIds = Object.keys(groupedByPeriod).map(id => id === "sin_periodo" ? id : parseInt(id));

    // Ordenar: activo primero, luego descendente
    periodIds.sort((a, b) => {
      if (a === activePeriodId) return -1;
      if (b === activePeriodId) return 1;
      if (a === "sin_periodo") return 1;
      if (b === "sin_periodo") return -1;
      return b - a;
    });

    // Si hay período activo pero no tiene solicitudes en el historial, agregarlo
    if (activePeriodId && !groupedByPeriod[activePeriodId]) {
      periodIds.unshift(activePeriodId);
      groupedByPeriod[activePeriodId] = [];
    }

    let html = `
      <div class="card border-0 shadow-sm">
        <div class="card-body">
          <h6 class="mb-3">Historial</h6>
    `;

    if (periodIds.length === 0) {
      html += `<div class="text-muted small">Sin historial.</div>`;
    } else {
      for (const periodId of periodIds) {
        const period = periodId === "sin_periodo" ? null : periods[periodId];
        const periodName = period ? period.name : "Sin período asignado";
        const isActivePeriod = periodId === activePeriodId;
        const periodItems = groupedByPeriod[periodId] || [];

        // Divisor de período (muy visible)
        html += `
          <div class="period-divider ${isActivePeriod ? 'active' : ''}" style="
            background: ${isActivePeriod ? 'linear-gradient(135deg, #0d6efd 0%, #0a58ca 100%)' : 'linear-gradient(135deg, #6c757d 0%, #495057 100%)'};
            color: white;
            padding: 10px 16px;
            border-radius: 8px;
            margin-bottom: 12px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
          ">
            <i class="bi bi-calendar3"></i>
            <span>${escapeHtml(periodName)}</span>
            ${isActivePeriod ? '<span class="badge bg-light text-primary ms-auto" style="font-size: 0.75rem;">Período actual</span>' : ''}
          </div>
        `;

        // Solicitudes del período
        if (periodItems.length === 0 && isActivePeriod) {
          html += `
            <div class="alert alert-info mb-3" style="font-size: 0.9rem;">
              <i class="bi bi-info-circle me-1"></i> Sin solicitudes en este período.
            </div>
          `;
        } else if (periodItems.length > 0) {
          html += `<ul class="list-group list-group-flush mb-3">`;
          for (const h of periodItems) {
            const t = mapType(h.type);
            const s = mapReqStatus(h.status);
            const when = fmtDate(h.created_at);
            const comment = h.comment;
            const tone = toneForStatus(h.status);
            html += `
              <li class="list-group-item d-flex justify-content-between align-items-start">
                <div class="d-flex flex-column">
                  <span class="fw-semibold">${t}</span>
                  ${comment ? `<span class="small text-muted">Comentarios: ${escapeHtml(comment)}</span>` : ''}
                  <span class="small text-muted">${when}</span>
                </div>
                ${badge(s, tone)}
              </li>
            `;
          }
          html += `</ul>`;
        }
      }
    }

    html += `
        </div>
      </div>
    `;

    return html;
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
        } else if (err.error === "period_closed") {
          showToast(err.message || "El período ya cerró.", "error");
        } else if (err.error === "appointment_time_passed") {
          showToast(err.message || "La cita ya pasó.", "error");
        } else {
          showToast("No se pudo cancelar la solicitud.", "error");
        }
        return;
      }
      showToast("Solicitud cancelada.", "success");
      await load();
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
