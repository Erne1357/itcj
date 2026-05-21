/**
 * coord/drops.js
 * Página: /coord/drops — Listar bajas y responder vía modal.
 *
 * UX:
 *  - RESOLVED_SUCCESS → ejecución directa + toast con botón Undo (5 s).
 *  - RESOLVED_NOT_COMPLETED / CANCELED → modal de confirmación con nombre del alumno.
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

  const $ = (sel) => document.querySelector(sel);

  /** Estados destructivos (requieren confirmación) */
  const IS_DESTRUCTIVE = new Set(["CANCELED", "RESOLVED_NOT_COMPLETED"]);

  // === ESTADO ===
  let currentCoordinatorId = null;

  // === INICIALIZACIÓN ===
  document.addEventListener("DOMContentLoaded", function () {
    window.AgendaTec.SocketStatus.mount({ anchor: "#currentPeriod" });
    wireSocket();
    loadSharedCoordinators();

    $("#btnLoadDrops")?.addEventListener("click", handleLoadDrops);
    $("#dropStatus")?.addEventListener("change", () => $("#btnLoadDrops")?.click());

    // Carga inicial
    $("#btnLoadDrops")?.click();
  });

  // === COORDINADORES ===
  async function loadSharedCoordinators() {
    try {
      const r = await fetch("/api/agendatec/v2/coord/shared-coordinators", { credentials: "include" });
      if (!r.ok) return;
      const data = await r.json();

      currentCoordinatorId = data.current_coordinator_id;

      if (currentCoordinatorId) {
        window.__reqJoinDrops?.({ coord_id: currentCoordinatorId });
      }

      if (data.has_multiple_coordinators) {
        const filterContainer = document.getElementById("coordFilterContainer");
        const filterSelect    = document.getElementById("coordFilter");
        if (filterContainer && filterSelect) {
          filterContainer.classList.remove("d-none");
          filterSelect.innerHTML = '<option value="ALL">Todas las bajas del programa</option>';
          const coordNames = (data.coordinators || []).map(c => c.name).join(", ");
          const info = document.createElement("small");
          info.className = "text-muted d-block mt-1 coord-info";
          info.textContent = `Coordinadores: ${coordNames}`;
          const existing = filterContainer.parentElement?.querySelector(".coord-info");
          if (existing) existing.remove();
          filterContainer.parentElement?.appendChild(info);
        }
      }
    } catch (e) {
      console.error("[drops] Error cargando coordinadores:", e);
    }
  }

  // === HELPERS DE ESTADO ===
  const mapReqStatusEs = (s) => ({
    PENDING:                "Pendiente",
    RESOLVED_SUCCESS:       "Resuelta",
    RESOLVED_NOT_COMPLETED: "No resuelta",
    CANCELED:               "Cancelada",
  }[s] || s);

  const toneFor = (s) => ({
    PENDING:                "warning",
    RESOLVED_SUCCESS:       "success",
    RESOLVED_NOT_COMPLETED: "secondary",
    CANCELED:               "secondary",
  }[s] || "secondary");

  const fmtDate = (iso) => {
    try {
      return new Date(iso).toLocaleString("es-MX", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return iso || ""; }
  };

  // === CARGA ===
  async function handleLoadDrops() {
    const status  = $("#dropStatus")?.value;
    const dropList = document.getElementById("dropList");

    if (dropList) dropList.innerHTML = Skeleton.tableRows(5, 6);

    const url = new URL("/api/agendatec/v2/coord/drops", window.location.origin);
    if (status) url.searchParams.set("status", status);

    try {
      const r    = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();

      const periodNameEl = document.getElementById("periodName");
      if (data?.period?.name && periodNameEl) periodNameEl.textContent = data.period.name;

      renderDrops(data.items || []);
    } catch {
      showToast("Error al cargar solicitudes de baja.", "error");
    }
  }

  // === RENDER ===
  function renderDrops(items) {
    const el = document.getElementById("dropList");
    if (!items.length) {
      el.innerHTML = `
        <div class="at-empty">
          <i class="bi bi-check2-all at-empty__icon" aria-hidden="true"></i>
          <p class="at-empty__title">Sin solicitudes pendientes</p>
          <p class="at-empty__message">No hay solicitudes de baja con el filtro actual.</p>
        </div>`;
      return;
    }

    let html = `
      <table class="table table-sm table-striped align-middle" data-at-table="card" id="dropsTable">
        <thead>
          <tr>
            <th data-at-label="ID">ID</th>
            <th data-at-label="Alumno">Alumno</th>
            <th data-at-label="Estado">Estado</th>
            <th data-at-label="Descripción">Descripción</th>
            <th data-at-label="Creada">Creada</th>
            <th data-at-label="">Detalle</th>
          </tr>
        </thead><tbody>`;

    for (const it of items) {
      const created  = it.created_at ? fmtDate(it.created_at) : "—";
      const statusEs = mapReqStatusEs(it.status);
      const tone     = toneFor(it.status);
      const desc     = (it.description || "Sin descripción").trim();
      const alumno   = it.student
        ? `${escapeHtml(it.student.full_name || "—")}<br><span class="text-muted small">${escapeHtml(it.student.control_number || it.student.username || "—")}</span>`
        : "—";

      html += `<tr>
        <td data-at-label="ID">#${escapeHtml(String(it.id))}</td>
        <td data-at-label="Alumno">${alumno}</td>
        <td data-at-label="Estado"><span class="badge text-bg-${tone}">${escapeHtml(statusEs)}</span></td>
        <td data-at-label="Descripción">
          <span class="at-desc-truncate" title="${escapeHtml(desc)}">${escapeHtml(desc)}</span>
        </td>
        <td data-at-label="Creada">${escapeHtml(created)}</td>
        <td data-at-label="">
          <button class="btn btn-sm btn-primary" data-open="${escapeHtml(String(it.id))}">
            Ver detalle
          </button>
        </td>
      </tr>`;
    }
    html += `</tbody></table>`;
    el.innerHTML = html;

    const table = el.querySelector("table");
    if (table) TableCard.syncLabels(table);
  }

  // === DELEGACIÓN CLICK ===
  document.addEventListener("click", async (e) => {
    // Abrir detalle
    const openBtn = e.target.closest("button[data-open]");
    if (openBtn) {
      await openDetail(openBtn.getAttribute("data-open"));
      return;
    }

    // Acción de estado
    const act = e.target.closest("button[data-drop][data-st]");
    if (!act) return;

    const id         = act.getAttribute("data-drop");
    const st         = act.getAttribute("data-st");
    const commentEl  = document.getElementById("dropCoordComment");
    const comment    = (commentEl?.value || "").trim();

    // Nombre del alumno del body del modal
    const bodyEl    = document.getElementById("dropDetailBody");
    const alumnoLine = bodyEl?.querySelector("div:nth-child(2)")?.textContent || "";
    const alumnoMatch = alumnoLine.match(/Alumno:\s*(.+)/);
    const studentName = alumnoMatch ? alumnoMatch[1].trim() : `#${id}`;

    if (!IS_DESTRUCTIVE.has(st)) {
      // RESOLVED_SUCCESS → directo + Undo
      await patchDrop(id, st, comment);
      try {
        bootstrap.Modal.getInstance(document.getElementById("dropDetailModal"))?.hide();
      } catch {}

      showUndoToast(`Baja marcada como "${mapReqStatusEs(st)}"`, async () => {
        await patchDrop(id, "PENDING", "");
        $("#btnLoadDrops")?.click();
      });
      $("#btnLoadDrops")?.click();
    } else {
      // Destructivo → confirmación con nombre
      const label = {
        CANCELED:               "Cancelada",
        RESOLVED_NOT_COMPLETED: "No resuelta",
      }[st] || st;

      const confirmed = await showConfirmModal(
        `¿Confirmar marcar como "${label}" la baja de ${studentName}?`
      );
      if (!confirmed) return;

      await patchDrop(id, st, comment);
      try {
        bootstrap.Modal.getInstance(document.getElementById("dropDetailModal"))?.hide();
      } catch {}
      $("#btnLoadDrops")?.click();
    }
  });

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
    const toastId = "at-undo-drop-" + Date.now();
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
    document.body.appendChild(wrapper);

    const toastEl = wrapper.querySelector(".toast");
    const bsToast = new bootstrap.Toast(toastEl);
    bsToast.show();

    let undid = false;
    wrapper.querySelector(`#${toastId}-undo`)?.addEventListener("click", () => {
      if (!undid) { undid = true; onUndo(); bsToast.hide(); }
    });
    toastEl.addEventListener("hidden.bs.toast", () => wrapper.remove());
  }

  // === PATCH ===
  async function patchDrop(id, st, comment) {
    try {
      const body = comment ? { status: st, coordinator_comment: comment } : { status: st };
      const r    = await fetch(`/api/agendatec/v2/coord/requests/${id}/status`, {
        method:      "PATCH",
        headers:     { "Content-Type": "application/json" },
        credentials: "include",
        body:        JSON.stringify(body),
      });
      if (!r.ok) throw new Error();
      if (st !== "PENDING") showToast("Estado actualizado.", "success");
    } catch {
      showToast("No se pudo actualizar el estado.", "error");
    }
  }

  // === DETALLE ===
  async function openDetail(reqId) {
    try {
      const url = new URL("/api/agendatec/v2/coord/drops", window.location.origin);
      url.searchParams.set("request_id", reqId);
      const r    = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const it   = (data.items || [])[0];
      const body    = document.getElementById("dropDetailBody");
      const actions = document.getElementById("dropDetailActions");

      if (!it) {
        body.innerHTML    = `<div class="text-muted">No se encontró la solicitud.</div>`;
        actions.innerHTML = "";
      } else {
        const alumno = it.student
          ? `${escapeHtml(it.student.full_name || "—")} (${escapeHtml(it.student.control_number || it.student.username || "—")})`
          : "—";
        body.innerHTML = `
          <div class="mb-1"><strong>Solicitud #${escapeHtml(String(it.id))}</strong></div>
          <div class="mb-1"><strong>Alumno:</strong> ${alumno}</div>
          <div class="mb-1"><strong>Estado:</strong> ${escapeHtml(mapReqStatusEs(it.status))}</div>
          <div class="mb-1"><strong>Creada:</strong> ${escapeHtml(fmtDate(it.created_at))}</div>
          <div class="mb-2"><strong>Descripción:</strong><br>${escapeHtml(it.description || "Sin descripción")}</div>`;

        actions.innerHTML = `
          <button class="btn btn-outline-success"  data-drop="${escapeHtml(String(it.id))}" data-st="RESOLVED_SUCCESS">Marcar resuelta</button>
          <button class="btn btn-outline-warning"  data-drop="${escapeHtml(String(it.id))}" data-st="RESOLVED_NOT_COMPLETED">No resuelta</button>
          <button class="btn btn-outline-danger"   data-drop="${escapeHtml(String(it.id))}" data-st="CANCELED">Cancelar</button>`;

        const cEl = document.getElementById("dropCoordComment");
        if (cEl) cEl.value = it.coordinator_comment || it.comment || "";
      }

      new bootstrap.Modal(document.getElementById("dropDetailModal")).show();
    } catch {
      showToast("No se pudo abrir el detalle.", "error");
    }
  }

  // === SOCKETS (debounced 250ms) ===
  function wireSocket() {
    const refreshDebounced = debounce(() => $("#btnLoadDrops")?.click(), 250);

    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) { setTimeout(tryBind, 500); return; }
      s.off?.("drop_created");
      s.off?.("request_status_changed");

      s.on("drop_created",           ()  => refreshDebounced());
      s.on("request_status_changed", (p) => {
        if (p?.type !== "DROP") return;
        refreshDebounced();
      });
    };
    tryBind();
  }

})();
