/**
 * AgendaTec — Student / requests.js
 * Lista y gestión de solicitudes del alumno.
 * Usa: Skeleton.cards(), .at-period-divider, .at-empty, .at-stagger.
 * Sin inline styles — todo por clases CSS.
 */

(async () => {
  "use strict";

  // === HELPERS ===
  const escapeHtml = (s) => window.AgendaTec.Format.escapeHtml(s);
  const Skeleton   = window.AgendaTec.Skeleton;

  const panel = document.getElementById("reqPanel");

  const RELEVANT_TYPES = new Set([
    "REQUEST_STATUS_CHANGED",
    "APPOINTMENT_CREATED",
    "APPOINTMENT_CANCELED",
    "DROP_CREATED",
  ]);

  let __reloadTimer = null;
  const scheduleReload = () => {
    clearTimeout(__reloadTimer);
    __reloadTimer = setTimeout(() => load().catch(() => {}), 300);
  };

  document.addEventListener("notif:push", (e) => {
    if (RELEVANT_TYPES.has(e?.detail?.type)) scheduleReload();
  });

  // === MAPEOS ===
  const mapType = (t) => ({
    APPOINTMENT: "CITA",
    DROP       : "BAJA",
    BOTH       : "ALTA Y BAJA",
  }[t] || t);

  const mapReqStatus = (s) => ({
    PENDING                 : "PENDIENTE",
    RESOLVED_SUCCESS        : "ATENDIDA Y RESUELTA",
    RESOLVED_NOT_COMPLETED  : "ATENDIDA NO RESUELTA",
    NO_SHOW                 : "NO ASISTIÓ",
    ATTENDED_OTHER_SLOT     : "ASISTIÓ EN OTRO HORARIO",
    CANCELED                : "CANCELADA",
  }[s] || s);

  const mapApptStatus = (s) => ({
    SCHEDULED: "PROGRAMADA",
    DONE     : "CONCLUIDA",
    NO_SHOW  : "NO ASISTIÓ",
    CANCELED : "CANCELADA",
  }[s] || s);

  const fmtDate = (iso) => {
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return iso || ""; }
  };

  const dayRange = (slot) => {
    if (!slot) return "";
    return `${slot.day} • ${slot.start_time}–${slot.end_time}`;
  };

  const badge = (text, tone = "secondary") =>
    `<span class="badge text-bg-${tone}">${escapeHtml(text)}</span>`;

  const btnHtml = (label, { id = "", cls = "btn btn-sm btn-outline-danger", attrs = "" } = {}) =>
    `<button ${id ? `id="${id}"` : ""} class="${cls}" type="button" ${attrs}>${label}</button>`;

  // === CARGA INICIAL ===
  await load();

  // === CARGA + RENDER ===
  async function load() {
    try {
      panel.innerHTML = Skeleton.cards(3);

      const r = await fetch("/api/agendatec/v2/requests/mine", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();

      const activeHtml  = renderActive(data.active, data.active_period);
      const historyHtml = renderHistory(data.history || [], data.active_period, data.periods || {});

      panel.innerHTML = `<div class="d-flex flex-column gap-3">${activeHtml}${historyHtml}</div>`;

      // Wire botón cancelar
      const cancelBtn = document.getElementById("btnCancelRequest");
      if (cancelBtn) {
        const modalEl  = document.getElementById("modalCancelRequest");
        const modal    = new bootstrap.Modal(modalEl);
        const btnConfirm = document.getElementById("btnConfirmCancelRequest");

        cancelBtn.addEventListener("click", () => {
          btnConfirm.setAttribute("data-pending-id", cancelBtn.getAttribute("data-id"));
          modal.show();
        });

        btnConfirm?.addEventListener("click", async () => {
          const reqId = btnConfirm.getAttribute("data-pending-id");
          modal.hide();
          if (reqId) await doCancel(reqId);
        });
      }

    } catch (e) {
      panel.innerHTML = `
        <div class="at-empty">
          <div class="at-empty__icon" aria-hidden="true"><i class="bi bi-exclamation-circle"></i></div>
          <p class="at-empty__title">No se pudieron cargar tus solicitudes</p>
          <div class="at-empty__cta">
            <button type="button" class="btn btn-outline-secondary btn-sm" id="btnRetry">
              <i class="bi bi-arrow-repeat me-1"></i> Reintentar
            </button>
          </div>
        </div>
      `;
      document.getElementById("btnRetry")?.addEventListener("click", () => load());
      console.error("Error al cargar solicitudes:", e);
    }
  }

  // === RENDER SOLICITUD ACTIVA ===
  function renderActive(active, activePeriod) {
    if (!active) {
      return `
        <section class="at-section">
          <div class="at-section__head">
            <h6 class="at-section__title mb-0">Solicitud activa</h6>
            ${badge("NINGUNA", "secondary")}
          </div>
          <div class="at-empty">
            <div class="at-empty__icon" aria-hidden="true"><i class="bi bi-inbox"></i></div>
            <p class="at-empty__title">Sin solicitud activa</p>
            <p class="at-empty__message">No tienes solicitud activa en el período actual.</p>
            <div class="at-empty__cta">
              <a href="/agendatec/student/request" class="btn btn-primary">
                <i class="bi bi-plus-circle me-1" aria-hidden="true"></i> Crear solicitud
              </a>
            </div>
          </div>
        </section>
      `;
    }

    const type      = mapType(active.type);
    const reqStatus = mapReqStatus(active.status);
    const created   = fmtDate(active.created_at);
    const desc      = (active.description || "Sin descripción").trim();

    const hasAppt    = !!active.appointment;
    const appt       = active.appointment || null;
    const apptStatus = hasAppt ? mapApptStatus(appt.status) : null;
    const apptLine   = hasAppt
      ? `<div class="small mt-1"><i class="bi bi-calendar2 me-1" aria-hidden="true"></i>${dayRange(appt.slot)}</div>`
      : "";

    const statusTone = toneForStatus(active.status);
    const typeTone   = active.type === "DROP" ? "warning" : "primary";
    const canCancel  = canCancelRequest(active, activePeriod);

    return `
      <section class="at-section at-section--accent">
        <div class="at-section__head flex-wrap gap-2">
          <h6 class="at-section__title mb-0">Solicitud activa</h6>
          <div class="d-flex align-items-center gap-2 flex-wrap">
            ${badge(type, typeTone)}
            ${badge(reqStatus, statusTone)}
            ${hasAppt ? badge(`Cita: ${apptStatus}`, "info") : ""}
          </div>
        </div>
        <div class="at-section__body">
          ${apptLine}
          <div class="small text-muted">
            <i class="bi bi-clock me-1" aria-hidden="true"></i> Creada: ${created}
          </div>
          <div class="small mt-2">${escapeHtml(desc)}</div>
          ${canCancel ? `
          <div class="mt-3 d-flex gap-2">
            ${btnHtml("Cancelar solicitud", {
              id   : "btnCancelRequest",
              cls  : "btn btn-sm btn-outline-danger",
              attrs: `data-id="${active.id}"`,
            })}
          </div>
          ` : ""}
        </div>
      </section>
    `;
  }

  // === PUEDE CANCELAR ===
  function canCancelRequest(request, activePeriod) {
    if (request.status !== "PENDING") return false;
    const period = request.period;
    if (!period || period.status !== "ACTIVE") return false;
    if (activePeriod?.student_admission_deadline) {
      if (new Date() > new Date(activePeriod.student_admission_deadline)) return false;
    }
    if (request.type === "APPOINTMENT" && request.appointment?.slot) {
      const slotDT = new Date(`${request.appointment.slot.day}T${request.appointment.slot.start_time}`);
      if (new Date() >= slotDT) return false;
    }
    return true;
  }

  // === RENDER HISTORIAL AGRUPADO POR PERÍODO ===
  function renderHistory(items, activePeriod, periods) {
    const groupedByPeriod = {};
    for (const item of items) {
      const pid = item.period_id || "sin_periodo";
      if (!groupedByPeriod[pid]) groupedByPeriod[pid] = [];
      groupedByPeriod[pid].push(item);
    }

    const activePeriodId = activePeriod ? activePeriod.id : null;
    const periodIds = Object.keys(groupedByPeriod).map((id) =>
      id === "sin_periodo" ? id : parseInt(id)
    );

    periodIds.sort((a, b) => {
      if (a === activePeriodId) return -1;
      if (b === activePeriodId) return 1;
      if (a === "sin_periodo")  return 1;
      if (b === "sin_periodo")  return -1;
      return b - a;
    });

    if (activePeriodId && !groupedByPeriod[activePeriodId]) {
      periodIds.unshift(activePeriodId);
      groupedByPeriod[activePeriodId] = [];
      if (!periods[activePeriodId] && activePeriod) {
        periods[activePeriodId] = {
          id    : activePeriod.id,
          name  : activePeriod.name,
          status: activePeriod.status,
        };
      }
    }

    let html = `<section class="at-section"><div class="at-section__head"><h6 class="at-section__title mb-0">Historial</h6></div><div class="at-section__body">`;

    if (periodIds.length === 0) {
      html += `
        <div class="at-empty">
          <div class="at-empty__icon" aria-hidden="true"><i class="bi bi-inbox"></i></div>
          <p class="at-empty__title">Sin historial</p>
          <p class="at-empty__message">Aún no tienes solicitudes cerradas.</p>
          <div class="at-empty__cta">
            <a href="/agendatec/student/request" class="btn btn-primary btn-sm">
              <i class="bi bi-plus-circle me-1" aria-hidden="true"></i> Crear solicitud
            </a>
          </div>
        </div>
      `;
    } else {
      for (const periodId of periodIds) {
        const period       = periodId === "sin_periodo" ? null : periods[periodId];
        const periodName   = period ? period.name : "Sin período asignado";
        const isActivePeriod = periodId === activePeriodId;
        const periodItems  = groupedByPeriod[periodId] || [];

        // Divisor de período — clases CSS, sin inline styles
        const dividerMod = isActivePeriod ? "" : " at-period-divider--past";
        html += `
          <div class="at-period-divider${dividerMod}">
            <div class="d-flex align-items-center gap-2">
              <i class="bi bi-calendar3" aria-hidden="true"></i>
              <span>${escapeHtml(periodName)}</span>
            </div>
            ${isActivePeriod
              ? '<span class="at-period-divider__badge">Período actual</span>'
              : ""}
          </div>
        `;

        if (periodItems.length === 0 && isActivePeriod) {
          html += `
            <div class="alert alert-info mb-3 small">
              <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
              No tienes solicitudes cerradas en este período.
            </div>
          `;
        } else if (periodItems.length === 0) {
          html += `
            <div class="alert alert-secondary mb-3 small">
              <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
              Solicitudes cerradas.
            </div>
          `;
        } else {
          // at-stagger para animar la entrada por período
          html += `<ul class="list-group list-group-flush mb-3 at-stagger">`;
          for (const h of periodItems) {
            const t       = mapType(h.type);
            const s       = mapReqStatus(h.status);
            const when    = fmtDate(h.created_at);
            const comment = h.comment;
            const tone    = toneForStatus(h.status);
            html += `
              <li class="list-group-item d-flex justify-content-between align-items-start">
                <div class="d-flex flex-column">
                  <span class="fw-semibold">${t}</span>
                  ${comment ? `<span class="small text-muted">Comentarios: ${escapeHtml(comment)}</span>` : ""}
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

    html += `</div></section>`;
    return html;
  }

  // === CANCELAR SOLICITUD ===
  async function doCancel(reqId) {
    try {
      const r = await fetch(`/api/agendatec/v2/requests/${reqId}/cancel`, {
        method     : "PATCH",
        credentials: "include",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const msgs = {
          not_pending           : "La solicitud ya no está pendiente.",
          request_not_found     : "Solicitud no encontrada.",
          period_closed         : err.message || "El período ya cerró.",
          appointment_time_passed: err.message || "La cita ya pasó.",
        };
        showToast(msgs[err.error] || "No se pudo cancelar la solicitud.", "error");
        return;
      }
      showToast("Solicitud cancelada.", "success");
      await load();
    } catch (e) {
      console.error(e);
      showToast("No se pudo conectar.", "error");
    }
  }

  // === TONOS POR ESTATUS ===
  function toneForStatus(status) {
    return {
      PENDING               : "warning",
      RESOLVED_SUCCESS      : "success",
      RESOLVED_NOT_COMPLETED: "secondary",
      NO_SHOW               : "danger",
      ATTENDED_OTHER_SLOT   : "info",
      CANCELED              : "secondary",
    }[status] || "secondary";
  }

})();
