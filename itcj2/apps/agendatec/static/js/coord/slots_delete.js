/**
 * coord/slots_delete.js
 * Elimina un rango de horarios del día.
 * Antes de mostrar el modal, consulta los slots del rango y muestra
 * cuántos se eliminarán (libres) y cuántos se conservarán (reservados).
 */

(function () {
  "use strict";

  const escapeHtml = window.AgendaTec.Format.escapeHtml;

  const dayEl    = document.getElementById("cfgDayDel");
  const sEl      = document.getElementById("delStart");
  const eEl      = document.getElementById("delEnd");
  const btn      = document.getElementById("btnDeleteRange");

  if (!btn) return;

  const modalEl      = document.getElementById("modalDeleteSlots");
  const modal        = new bootstrap.Modal(modalEl);
  const modalMsg     = document.getElementById("modalDeleteSlotsMsg");
  const btnConfirm   = document.getElementById("btnConfirmDeleteSlots");

  let pendingDelete = null;

  // Confirmar eliminar
  btnConfirm?.addEventListener("click", async () => {
    modal.hide();
    if (pendingDelete) {
      await executeDelete(pendingDelete.day, pendingDelete.start, pendingDelete.end);
      pendingDelete = null;
    }
  });

  // Click en "Eliminar"
  btn.addEventListener("click", async () => {
    const day   = (dayEl?.value  || "").trim();
    const start = (sEl?.value    || "").trim();
    const end   = (eEl?.value    || "").trim();

    if (!day || !start || !end) {
      showToast("Completa día, inicio y fin.", "warn");
      return;
    }
    if (end <= start) {
      showToast("El rango es inválido.", "warn");
      return;
    }

    // Consultar slots del día para calcular el preview
    let freeCount     = 0;
    let reservedCount = 0;

    try {
      const url = new URL("/api/agendatec/v2/coord/appointments", window.location.origin);
      url.searchParams.set("day", day);
      url.searchParams.set("include_empty", "1");
      const r = await fetch(url, { credentials: "include" });
      if (r.ok) {
        const data  = await r.json();
        const slots = (data.slots || []).filter(s => s.start >= start && s.end <= end);
        freeCount     = slots.filter(s => !s.appointment).length;
        reservedCount = slots.filter(s => !!s.appointment).length;
      }
    } catch {
      // Si falla la consulta, mostramos el modal sin preview
    }

    // Armar mensaje del modal
    let msgHtml;
    if (freeCount === 0 && reservedCount === 0) {
      msgHtml = `<span>No hay horarios en el rango <strong>${escapeHtml(start)}–${escapeHtml(end)}</strong> del día <strong>${escapeHtml(day)}</strong>.</span>`;
    } else {
      msgHtml = `
        <p class="mb-2">Rango: <strong>${escapeHtml(start)}–${escapeHtml(end)}</strong> del día <strong>${escapeHtml(day)}</strong></p>
        <ul class="mb-1">
          <li>Se eliminarán <strong>${freeCount} horario${freeCount !== 1 ? "s" : ""} libre${freeCount !== 1 ? "s" : ""}</strong>.</li>
          ${reservedCount > 0
            ? `<li class="text-warning"><strong>${reservedCount} horario${reservedCount !== 1 ? "s" : ""} reservado${reservedCount !== 1 ? "s" : ""}</strong> se conservará${reservedCount !== 1 ? "n" : ""}.</li>`
            : ""}
        </ul>`;
    }
    if (modalMsg) modalMsg.innerHTML = msgHtml;

    // Deshabilitar confirmar si no hay nada que eliminar
    if (btnConfirm) btnConfirm.disabled = (freeCount === 0);

    pendingDelete = { day, start, end };
    modal.show();
  });

  async function executeDelete(day, start, end) {
    try {
      const r = await fetch("/api/agendatec/v2/coord/day-config", {
        method:      "DELETE",
        headers:     { "Content-Type": "application/json" },
        credentials: "include",
        body:        JSON.stringify({ day, start, end }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (err?.error === "overlap_booked_slots_exist") {
          showToast(`No se puede eliminar: hay ${err.booked_count} horario(s) ya reservados.`, "warn");
        } else if (err?.error === "cannot_modify_today_or_past") {
          showToast("No se puede modificar hoy o días pasados.", "warn");
        } else {
          showToast("No se pudo eliminar el rango.", "error");
        }
        return;
      }
      showToast("Rango eliminado.", "success");
      // Refrescar vista
      const cfgDay = document.getElementById("cfgDay")?.value;
      if (typeof window.__slotsRefresh === "function" && cfgDay) {
        window.__slotsRefresh(cfgDay);
      }
    } catch (e) {
      console.error(e);
      showToast("No se pudo conectar.", "error");
    }
  }

})();
