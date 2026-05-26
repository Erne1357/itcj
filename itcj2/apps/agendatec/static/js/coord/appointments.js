/**
 * coord/appointments.js
 * Página: /coord/appointments — Listar y cambiar estado de citas.
 *
 * UX:
 *  - RESOLVED_SUCCESS → ejecución directa + toast con botón Undo (5 s).
 *  - CANCELED / NO_SHOW / RESOLVED_NOT_COMPLETED → modal de confirmación
 *    con nombre del alumno en el mensaje.
 *  - Socket debounced 250 ms.
 *  - Skeleton durante fetch.
 *  - Table→card en mobile (data-at-table="card").
 *  - SocketStatus indicator montado en #currentPeriod.
 */

(function () {
  "use strict";

  const escapeHtml = window.AgendaTec.Format.escapeHtml;
  const debounce   = window.AgendaTec.Format.debounce;
  const Skeleton   = window.AgendaTec.Skeleton;
  const TableCard  = window.AgendaTec.TableCard;

  // === ESTADO ===
  let useTable              = true;
  let sharedCoordinators    = [];
  let currentCoordinatorId  = null;

  const $ = (sel) => document.querySelector(sel);

  // === HELPERS ESTADO ===
  const statusTone = (s) => ({
    PENDING:                "warning",
    RESOLVED_SUCCESS:       "success",
    RESOLVED_NOT_COMPLETED: "secondary",
    NO_SHOW:                "danger",
    ATTENDED_OTHER_SLOT:    "info",
    CANCELED:               "secondary",
  }[s] || "secondary");

  const statusES = (s) => ({
    PENDING:                "Pendiente",
    RESOLVED_SUCCESS:       "Resuelta",
    RESOLVED_NOT_COMPLETED: "No resuelta",
    NO_SHOW:                "No asistió",
    ATTENDED_OTHER_SLOT:    "Asistió en otro horario",
    CANCELED:               "Cancelada",
  }[s] || s);

  /** Estados destructivos (requieren confirmación) */
  const IS_DESTRUCTIVE = new Set(["CANCELED", "NO_SHOW", "RESOLVED_NOT_COMPLETED"]);

  // === INICIALIZACIÓN ===
  document.addEventListener("DOMContentLoaded", function () {
    window.AgendaTec.SocketStatus.mount({ anchor: "#currentPeriod" });
    wireViewToggle();
    wireSocket();
    loadSharedCoordinators();

    $("#apDay")?.addEventListener("change", () => loadBtn());
    $("#reqStatus")?.addEventListener("change", () => loadBtn());
    $("#btnLoadAppointments")?.addEventListener("click", handleLoadAppointments);
  });

  // === COORDINADORES COMPARTIDOS ===
  async function loadSharedCoordinators() {
    try {
      const r = await fetch("/api/agendatec/v2/coord/shared-coordinators", { credentials: "include" });
      if (!r.ok) return;
      const data = await r.json();

      currentCoordinatorId = data.current_coordinator_id;
      sharedCoordinators   = data.coordinators || [];

      const daySelect = document.getElementById("apDay");
      if (currentCoordinatorId && daySelect?.value) {
        window.__lastApJoin && window.__reqLeaveApDay?.({ coord_id: currentCoordinatorId, day: window.__lastApJoin });
        window.__reqJoinApDay?.({ coord_id: currentCoordinatorId, day: daySelect.value });
        window.__lastApJoin = daySelect.value;
      }

      if (data.has_multiple_coordinators) {
        const filterContainer = document.getElementById("coordFilterContainer");
        const filterSelect    = document.getElementById("coordFilter");
        if (filterContainer && filterSelect) {
          filterContainer.classList.remove("d-none");
          filterSelect.innerHTML  = '<option value="ALL">Todos los coordinadores</option>';
          filterSelect.innerHTML += '<option value="MINE">Solo mis citas</option>';
          sharedCoordinators.forEach(coord => {
            if (!coord.is_me) {
              const opt = document.createElement("option");
              opt.value       = coord.id;
              opt.textContent = coord.name;
              filterSelect.appendChild(opt);
            }
          });
          filterSelect.addEventListener("change", () => {
            if (document.getElementById("apDay")?.value) loadBtn();
          });
        }
      }
    } catch (e) {
      console.error("[appointments] Error cargando coordinadores:", e);
    }
  }

  // === CARGA ===
  function loadBtn() {
    $("#btnLoadAppointments")?.click();
  }

  async function handleLoadAppointments() {
    const day        = $("#apDay")?.value;
    const reqStatus  = $("#reqStatus")?.value;
    const coordFilter = $("#coordFilter")?.value || "ALL";

    const apList = document.getElementById("apList");
    if (apList) apList.innerHTML = Skeleton.tableRows(5, useTable ? 6 : 7);

    const url = new URL("/api/agendatec/v2/coord/appointments", window.location.origin);
    url.searchParams.set("day", day);
    if (reqStatus && reqStatus !== "ALL") url.searchParams.set("req_status", reqStatus);
    if (coordFilter === "MINE" && currentCoordinatorId) {
      url.searchParams.set("coordinator_id", currentCoordinatorId);
    } else if (coordFilter !== "ALL" && coordFilter !== "MINE") {
      url.searchParams.set("coordinator_id", coordFilter);
    }
    url.searchParams.set("include_empty", useTable ? "1" : "0");

    const coordId = currentCoordinatorId;
    if (coordId && day) {
      window.__lastApJoin && window.__reqLeaveApDay?.({ coord_id: coordId, day: window.__lastApJoin });
      window.__reqJoinApDay?.({ coord_id: coordId, day });
      window.__lastApJoin = day;
    }

    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();

      const periodNameEl = document.getElementById("periodName");
      if (data?.period?.name && periodNameEl) periodNameEl.textContent = data.period.name;

      if (useTable) renderTable(data.slots || []);
      else          renderList(data.items  || []);
    } catch {
      showToast("Error al cargar citas.", "error");
    }
  }

  // === RENDER LISTA ===
  function renderList(items) {
    const el = document.getElementById("apList");
    if (!items.length) {
      el.innerHTML = `
        <div class="at-empty">
          <i class="bi bi-calendar-x at-empty__icon" aria-hidden="true"></i>
          <p class="at-empty__title">Sin citas</p>
          <p class="at-empty__message">No hay citas para este día y filtro.</p>
        </div>`;
      return;
    }

    const showCoord = sharedCoordinators.length > 1;
    let html = `
      <table class="table table-sm table-striped align-middle" data-at-table="card" id="apListTable">
        <thead>
          <tr>
            <th data-at-label="Hora">Hora</th>
            <th data-at-label="Alumno">Alumno</th>
            <th data-at-label="Carrera">Carrera</th>
            ${showCoord ? '<th data-at-label="Coordinador">Coordinador</th>' : ""}
            <th data-at-label="Estado">Estado (solicitud)</th>
            <th data-at-label="Descripción">Descripción</th>
            <th data-at-label="">Acciones</th>
          </tr>
        </thead><tbody>`;

    for (const it of items) {
      const alumno    = it.student
        ? `${escapeHtml(it.student.full_name || "—")}<br><span class="text-muted small">${escapeHtml(it.student.control_number || it.student.username || "—")}</span>`
        : "—";
      const st         = it.request_status;
      const coordBadge = showCoord
        ? `<td data-at-label="Coordinador"><span class="badge bg-secondary">${escapeHtml(it.assigned_coordinator?.name || "—")}</span></td>`
        : "";

      html += `<tr>
        <td data-at-label="Hora">${escapeHtml(it.slot?.start_time || "—")}–${escapeHtml(it.slot?.end_time || "—")}</td>
        <td data-at-label="Alumno">${alumno}</td>
        <td data-at-label="Carrera">${escapeHtml(it.program?.name || "—")}</td>
        ${coordBadge}
        <td data-at-label="Estado"><span class="badge text-bg-${statusTone(st)}">${statusES(st)}</span></td>
        <td data-at-label="Descripción">
          <span class="at-desc-truncate" title="${escapeHtml(it.description || "Sin descripción")}">
            ${escapeHtml(it.description || "Sin descripción")}
          </span>
        </td>
        <td data-at-label="">
          <button class="btn btn-sm btn-primary ms-1" data-open="${escapeHtml(String(it.request_id))}">
            Ver detalles
          </button>
        </td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
    const table = el.querySelector("table");
    if (table) TableCard.syncLabels(table);
  }

  // === RENDER TABLA ===
  function renderTable(slots) {
    const el = document.getElementById("apList");
    if (!slots.length) {
      el.innerHTML = `
        <div class="at-empty">
          <i class="bi bi-calendar-x at-empty__icon" aria-hidden="true"></i>
          <p class="at-empty__title">Sin horarios configurados para este día</p>
        </div>`;
      return;
    }

    const showCoord = sharedCoordinators.length > 1;
    let html = `
      <table class="table table-sm table-bordered align-middle" data-at-table="card" id="apListTable">
        <thead>
          <tr>
            <th class="at-col-actions" data-at-label="Hora">Hora</th>
            <th data-at-label="Alumno">Alumno</th>
            <th data-at-label="Carrera">Carrera</th>
            ${showCoord ? '<th data-at-label="Coordinador">Coordinador</th>' : ""}
            <th data-at-label="Solicitud">Solicitud</th>
            <th data-at-label="">Acciones</th>
          </tr>
        </thead><tbody>`;

    for (const s of slots) {
      const slotCoordBadge = showCoord
        ? `<td data-at-label="Coordinador"><span class="badge bg-info text-dark">${escapeHtml(s.coordinator_name || "—")}</span></td>`
        : "";

      if (!s.appointment) {
        html += `<tr>
          <td data-at-label="Hora">${escapeHtml(s.start)}–${escapeHtml(s.end)}</td>
          <td data-at-label="Alumno" class="text-muted">Libre</td>
          <td data-at-label="Carrera" class="text-muted">—</td>
          ${slotCoordBadge}
          <td data-at-label="Solicitud" class="text-muted">—</td>
          <td data-at-label="" class="text-end text-muted small">—</td>
        </tr>`;
        continue;
      }

      const it = s.appointment;
      const alumno = it.student
        ? `${escapeHtml(it.student.full_name || "—")}<br><span class="text-muted small">${escapeHtml(it.student.control_number || it.student.username || "—")}</span>`
        : "—";
      const coordName  = it.assigned_coordinator?.name || s.coordinator_name;
      const coordCell  = showCoord
        ? `<td data-at-label="Coordinador"><span class="badge bg-secondary">${escapeHtml(coordName || "—")}</span></td>`
        : "";
      const st = it.request_status;

      html += `<tr>
        <td data-at-label="Hora">${escapeHtml(s.start)}–${escapeHtml(s.end)}</td>
        <td data-at-label="Alumno">${alumno}</td>
        <td data-at-label="Carrera">${escapeHtml(it.program?.name || "—")}</td>
        ${coordCell}
        <td data-at-label="Solicitud">
          <div><span class="badge text-bg-${statusTone(st)}">${statusES(st)}</span></div>
          <div>
            <span class="at-desc-truncate" title="${escapeHtml(it.description || "Sin descripción")}">
              ${escapeHtml(it.description || "Sin descripción")}
            </span>
          </div>
        </td>
        <td data-at-label="">
          <button class="btn btn-sm btn-primary ms-1" data-open="${escapeHtml(String(it.request_id))}">Ver detalles</button>
        </td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;
    const table = el.querySelector("table");
    if (table) TableCard.syncLabels(table);
  }

  // === BOTONES DE ACCIÓN ===
  function actionBtns(requestId) {
    return `
      <div class="btn-group btn-group-sm flex-wrap" role="group">
        <button class="btn btn-outline-success"   data-req="${requestId}" data-st="RESOLVED_SUCCESS">Resuelta</button>
        <button class="btn btn-outline-warning"   data-req="${requestId}" data-st="RESOLVED_NOT_COMPLETED">No resuelta</button>
        <button class="btn btn-outline-secondary" data-req="${requestId}" data-st="NO_SHOW">No asistió</button>
        <button class="btn btn-outline-info"      data-req="${requestId}" data-st="ATTENDED_OTHER_SLOT">Otro horario</button>
        <button class="btn btn-outline-danger"    data-req="${requestId}" data-st="CANCELED">Cancelar</button>
      </div>`;
  }

  // === MODAL CONFIRMACIÓN ===
  function showConfirmModal(message) {
    return new Promise((resolve) => {
      const modal      = document.getElementById("confirmActionModal");
      const messageEl  = document.getElementById("confirmMessage");
      const confirmBtn = document.getElementById("confirmActionBtn");

      messageEl.textContent = message;

      const bsModal = new bootstrap.Modal(modal);
      bsModal.show();

      const newBtn = confirmBtn.cloneNode(true);
      confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);

      newBtn.addEventListener("click", () => { bsModal.hide(); resolve(true); });
      modal.addEventListener("hidden.bs.modal", () => resolve(false), { once: true });
    });
  }

  // === TOAST CON UNDO ===
  function showUndoToast(message, onUndo) {
    // Crear elemento toast manualmente para incluir el botón Undo
    const toastContainer = document.getElementById("toastContainer") || document.body;
    const toastId = "at-undo-toast-" + Date.now();
    const wrapper = document.createElement("div");
    wrapper.className = "position-fixed bottom-0 end-0 p-3 at-toast-container";
    wrapper.innerHTML = `
      <div id="${toastId}" class="toast align-items-center text-bg-success border-0" role="alert"
           aria-live="assertive" aria-atomic="true" data-bs-delay="5000">
        <div class="d-flex">
          <div class="toast-body d-flex align-items-center gap-2">
            <i class="bi bi-check-circle" aria-hidden="true"></i>
            ${escapeHtml(message)}
            <span class="at-toast-undo">
              <button type="button" class="at-toast-undo__btn" id="${toastId}-undo">Deshacer</button>
            </span>
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
        </div>
      </div>`;
    toastContainer.appendChild(wrapper);

    const toastEl  = wrapper.querySelector(".toast");
    const bsToast  = new bootstrap.Toast(toastEl);
    bsToast.show();

    let undid = false;
    wrapper.querySelector(`#${toastId}-undo`)?.addEventListener("click", () => {
      if (!undid) { undid = true; onUndo(); bsToast.hide(); }
    });

    toastEl.addEventListener("hidden.bs.toast", () => wrapper.remove());
  }

  // === DELEGACIÓN CLICK ===
  document.addEventListener("click", async (e) => {
    // Acción de estado (dentro del modal)
    const act = e.target.closest("button[data-req][data-st]");
    if (act) {
      const id         = act.getAttribute("data-req");
      const st         = act.getAttribute("data-st");
      const commentEl  = document.getElementById("reqCoordComment");
      const comment    = (commentEl?.value || "").trim();

      // Obtener nombre del alumno del body del modal si está disponible
      const bodyEl     = document.getElementById("reqDetailBody");
      const alumnoLine = bodyEl?.querySelector("div:first-child")?.textContent || "";
      // "Alumno: Nombre (control)" → extraer la parte después de "Alumno: "
      const alumnoMatch = alumnoLine.match(/Alumno:\s*(.+)/);
      const studentName = alumnoMatch ? alumnoMatch[1].trim() : `#${id}`;

      if (!IS_DESTRUCTIVE.has(st)) {
        // RESOLVED_SUCCESS (y ATTENDED_OTHER_SLOT) → directo + Undo
        await patchRequest(id, st, comment);

        // Cerrar modal de detalle
        try {
          bootstrap.Modal.getInstance(document.getElementById("reqDetailModal"))?.hide();
        } catch {}

        // Toast con Undo (revertir a PENDING)
        showUndoToast(`Cita marcada como "${statusES(st)}"`, async () => {
          await patchRequest(id, "PENDING", "");
          loadBtn();
        });
        loadBtn();
      } else {
        // Destructivo → confirmación con nombre
        const label = {
          CANCELED:               "Cancelada",
          NO_SHOW:                "No asistió",
          RESOLVED_NOT_COMPLETED: "No resuelta",
        }[st] || st;

        const confirmed = await showConfirmModal(
          `¿Confirmar marcar como "${label}" la cita de ${studentName}?`
        );
        if (!confirmed) return;

        await patchRequest(id, st, comment);
        try {
          bootstrap.Modal.getInstance(document.getElementById("reqDetailModal"))?.hide();
        } catch {}
        loadBtn();
      }
      return;
    }

    // Abrir detalle
    const openBtn = e.target.closest("button[data-open]");
    if (openBtn) {
      openDetail(openBtn.getAttribute("data-open"));
    }
  });

  // === PATCH ===
  async function patchRequest(reqId, newStatus, coordComment) {
    try {
      const body = coordComment ? { status: newStatus, coordinator_comment: coordComment } : { status: newStatus };
      const r = await fetch(`/api/agendatec/v2/coord/requests/${reqId}/status`, {
        method:      "PATCH",
        headers:     { "Content-Type": "application/json" },
        credentials: "include",
        body:        JSON.stringify(body),
      });
      if (!r.ok) throw new Error();
      if (newStatus !== "PENDING") showToast("Estado de solicitud actualizado.", "success");
    } catch {
      showToast("No se pudo actualizar el estado.", "error");
    }
  }

  // === DETALLE ON-DEMAND ===
  async function openDetail(reqId) {
    try {
      const url = new URL("/api/agendatec/v2/coord/appointments", window.location.origin);
      url.searchParams.set("request_id", reqId);
      url.searchParams.set("day", $("#apDay")?.value || "");
      const r    = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const it   = (data.items || []).find(x => String(x.request_id) === String(reqId));
      const body    = document.getElementById("reqDetailBody");
      const actions = document.getElementById("reqDetailActions");

      if (!it) {
        body.innerHTML    = `<div class="text-muted">No se encontró la solicitud.</div>`;
        actions.innerHTML = "";
      } else {
        const alumno = it.student
          ? `${escapeHtml(it.student.full_name || "—")} (${escapeHtml(it.student.control_number || it.student.username || "—")})`
          : "—";
        body.innerHTML = `
          <div class="mb-1"><strong>Alumno:</strong> ${alumno}</div>
          <div class="mb-1"><strong>Carrera:</strong> ${escapeHtml(it.program?.name || "—")}</div>
          <div class="mb-1"><strong>Horario:</strong> ${escapeHtml(it.slot?.start_time || "—")}–${escapeHtml(it.slot?.end_time || "—")}</div>
          <div class="mb-1"><strong>Estado solicitud:</strong> ${statusES(it.request_status)}</div>
          <div class="mb-2"><strong>Descripción:</strong><br>${escapeHtml(it.description || "Sin descripción")}</div>`;
        actions.innerHTML = actionBtns(it.request_id);
        const commentEl = document.getElementById("reqCoordComment");
        if (commentEl) commentEl.value = it.coordinator_comment || "";
      }

      new bootstrap.Modal(document.getElementById("reqDetailModal")).show();
    } catch {
      showToast("No se pudo abrir el detalle.", "error");
    }
  }

  // === TOGGLE LISTA / TABLA ===
  function wireViewToggle() {
    const btnList  = $("#btnViewList");
    const btnTable = $("#btnViewTable");

    if (btnList) {
      btnList.addEventListener("click", () => {
        useTable = false;
        btnList.classList.add("active");
        btnList.setAttribute("aria-pressed", "true");
        btnTable?.classList.remove("active");
        btnTable?.setAttribute("aria-pressed", "false");
        loadBtn();
      });
    }
    if (btnTable) {
      btnTable.addEventListener("click", () => {
        useTable = true;
        btnTable.classList.add("active");
        btnTable.setAttribute("aria-pressed", "true");
        btnList?.classList.remove("active");
        btnList?.setAttribute("aria-pressed", "false");
        loadBtn();
      });
    }
  }

  // === SOCKETS (debounced 250ms) ===
  function wireSocket() {
    const refreshDebounced = debounce(() => loadBtn(), 250);

    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) { setTimeout(tryBind, 500); return; }
      s.off?.("appointment_created");
      s.off?.("request_status_changed");

      s.on("appointment_created", (p) => {
        const selectedDay = document.getElementById("apDay")?.value;
        if (p?.slot_day === selectedDay) refreshDebounced();
      });
      s.on("request_status_changed", (p) => {
        const selectedDay = document.getElementById("apDay")?.value;
        if (!selectedDay) return;
        if (p?.type === "APPOINTMENT" && p?.day === selectedDay) refreshDebounced();
      });
    };
    tryBind();
  }

  // === EVENTO DE INIT ===
  document.addEventListener("appointmentsInitReady", (e) => {
    if (e.detail?.selectedDay) loadBtn();
  });

})();
