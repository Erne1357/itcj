// static/js/coord/slots_delete.js
(() => {
  const $ = (sel) => document.querySelector(sel);

  const dayEl = $("#cfgDayDel");
  const sEl = $("#delStart");
  const eEl = $("#delEnd");
  const btn = $("#btnDeleteRange");

  if (!btn) return;

  // Modal de confirmación
  const modal = new bootstrap.Modal($("#modalDeleteSlots"));
  const modalMsg = $("#modalDeleteSlotsMsg");
  const btnConfirm = $("#btnConfirmDeleteSlots");

  let pendingDelete = null;

  btnConfirm?.addEventListener("click", async () => {
    modal.hide();
    if (pendingDelete) {
      await executeDelete(pendingDelete.day, pendingDelete.start, pendingDelete.end);
      pendingDelete = null;
    }
  });

  btn.addEventListener("click", () => {
    const day = (dayEl?.value || "").trim();
    const start = (sEl?.value || "").trim();
    const end = (eEl?.value || "").trim();
    if (!day || !start || !end) {
      showToast("Completa día, inicio y fin.", "warn");
      return;
    }
    if (end <= start) {
      showToast("El rango es inválido.", "warn");
      return;
    }

    // Mostrar modal de confirmación
    pendingDelete = { day, start, end };
    modalMsg.textContent = `¿Eliminar horarios de ${start} a ${end} del ${day}?`;
    modal.show();
  });

  async function executeDelete(day, start, end) {
    try {
      const r = await fetch("/api/agendatec/v1/coord/day-config", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ day, start, end })
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
      // Si tu página tiene un recargador de la configuración del día:
      try { window.reloadDay?.(day); } catch {}
    } catch (e) {
      console.error(e);
      showToast("No se pudo conectar.", "error");
    }
  }
})();
