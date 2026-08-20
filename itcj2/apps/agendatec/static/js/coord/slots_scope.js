/**
 * coord/slots_scope.js
 * Scope por carrera del rango horario + confirmación del split.
 *
 * Se carga ANTES que slots.js, que consume window.AgendaTecSlotScope.
 * IIFE: los scripts clásicos comparten scope global, así que solo se expone
 * el namespace.
 */
(function () {
  "use strict";

  let allPrograms = [];

  // === CARRERAS DEL COORDINADOR ===

  async function loadPrograms() {
    const wrap = document.getElementById("cfgProgramsWrap");
    const sel = document.getElementById("cfgPrograms");
    if (!wrap || !sel) return;

    try {
      const res = await fetch("/api/agendatec/v2/coord/programs", { credentials: "include" });
      if (!res.ok) return;
      const body = await res.json();
      allPrograms = body.data || [];
    } catch (e) {
      return;   // sin el selector, el rango aplica a todas: el default de siempre
    }

    // Con una sola carrera no hay nada que elegir.
    if (allPrograms.length <= 1) {
      wrap.hidden = true;
      return;
    }

    sel.innerHTML = "";
    allPrograms.forEach((p) => {
      const o = document.createElement("option");
      o.value = String(p.id);
      o.textContent = p.name;
      o.selected = true;              // default: todas
      sel.appendChild(o);
    });
    wrap.hidden = false;
  }

  /**
   * Carreras elegidas, o null si están todas.
   * null significa "todas" en el backend, que es también lo que manda una UI
   * sin selector: así el default preserva el comportamiento anterior.
   */
  function getSelectedPrograms() {
    const sel = document.getElementById("cfgPrograms");
    const wrap = document.getElementById("cfgProgramsWrap");
    if (!sel || !wrap || wrap.hidden) return null;
    const picked = Array.from(sel.selectedOptions).map((o) => Number(o.value));
    if (picked.length === 0 || picked.length === allPrograms.length) return null;
    return picked;
  }

  // === LECTURA DE ERRORES DE LA API ===

  /**
   * Normaliza las tres formas en que puede llegar un error.
   *
   * itcj2/main.py envuelve el detail de HTTPException en {"error": <detail>},
   * así que un detail string llega como {"error": "codigo"} y un detail dict
   * como {"error": {"error": "codigo", ...}} — doble anidado. Los endpoints
   * nuevos devuelven JSONResponse plano. Comparar err.error contra un string
   * fallaba silenciosamente en el caso anidado, y el coordinador veía un
   * mensaje genérico en vez del motivo real.
   */
  function readApiError(payload) {
    if (!payload) return { code: "", detail: {} };
    const e = payload.error;
    if (typeof e === "string") return { code: e, detail: payload };
    if (e && typeof e === "object") return { code: e.error || "", detail: e };
    if (typeof payload.detail === "string") return { code: payload.detail, detail: payload };
    if (payload.detail && typeof payload.detail === "object") {
      return { code: payload.detail.error || "", detail: payload.detail };
    }
    return { code: "", detail: payload };
  }

  function escapeHtml(t) {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
    return String(t == null ? "" : t).replace(/[&<>"']/g, (m) => map[m]);
  }

  const OFFENDER_REASONS = {
    not_on_grid: "no cae en la nueva rejilla",
    would_grow:  "se alargaría",
    does_not_fit: "no cabe en el rango",
  };

  function describeOffenders(offenders) {
    return (offenders || [])
      .map((o) => `${escapeHtml(o.start)}–${escapeHtml(o.end)} (${OFFENDER_REASONS[o.reason] || o.reason})`)
      .join(", ");
  }

  // === MODAL DE CONFIRMACIÓN ===

  /** Muestra el preview y resuelve true si el coordinador confirma. */
  function renderPreviewModal(preview) {
    return new Promise((resolve) => {
      const body = document.getElementById("modalSplitConfirmBody");
      const modalEl = document.getElementById("modalSplitConfirm");
      const btn = document.getElementById("btnConfirmSplit");
      if (!body || !modalEl || !btn) { resolve(true); return; }

      const parts = [];

      if (preview.start_efectivo) {
        parts.push(
          `<p class="mb-2">El cambio aplica a partir de las
           <strong>${escapeHtml(preview.start_efectivo)}</strong>.
           Los horarios anteriores no se tocan.</p>`
        );
      }
      parts.push(
        `<p class="mb-3 small text-muted">Se eliminarán
         ${preview.slots_to_delete} horario(s) libre(s) y se crearán
         ${preview.slots_to_create}.</p>`
      );

      if (preview.appointments_affected && preview.appointments_affected.length) {
        parts.push('<p class="mb-1"><strong>Citas que cambian de horario:</strong></p><ul class="small">');
        preview.appointments_affected.forEach((a) => {
          parts.push(
            `<li>${escapeHtml(a.student_name)} <span class="text-muted">(${escapeHtml(a.program)})</span>:
             ${escapeHtml(a.old)} → <strong>${escapeHtml(a.new)}</strong></li>`
          );
        });
        parts.push('</ul><p class="small text-muted">Se les enviará una notificación del cambio.</p>');
      }

      if (preview.out_of_scope_appointments && preview.out_of_scope_appointments.length) {
        parts.push(
          '<div class="alert alert-warning small mb-0"><strong>Ojo:</strong> hay citas de carreras ' +
          'que estás excluyendo. Se conservan, pero no podrás recibir nuevas de esas carreras ' +
          'en este rango.<ul class="mb-0 mt-1">'
        );
        preview.out_of_scope_appointments.forEach((a) => {
          parts.push(`<li>${escapeHtml(a.student_name)} — ${escapeHtml(a.program)}</li>`);
        });
        parts.push("</ul></div>");
      }

      body.innerHTML = parts.join("");

      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

      function cleanup() {
        btn.removeEventListener("click", onConfirm);
        modalEl.removeEventListener("hidden.bs.modal", onHide);
      }
      function onConfirm() { cleanup(); modal.hide(); resolve(true); }
      function onHide() { cleanup(); resolve(false); }

      btn.addEventListener("click", onConfirm);
      modalEl.addEventListener("hidden.bs.modal", onHide);
      modal.show();
    });
  }

  document.addEventListener("DOMContentLoaded", loadPrograms);

  window.AgendaTecSlotScope = {
    getSelectedPrograms,
    renderPreviewModal,
    readApiError,
    describeOffenders,
  };
})();
