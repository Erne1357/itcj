// static/js/coord_home.js
// Página: /coord/home  → Configurar horario y generar slots
window.addEventListener("DOMContentLoaded", () => {
  const daySelect = document.getElementById("cfgDay");
  const hashDay = window.location.hash.replace("#", "");
  if (hashDay) {
    for (const opt of daySelect.options) {
      if (opt.value === hashDay) {
        daySelect.value = hashDay;
        break;
      }
    }
  }
});
(() => {
  const $ = (sel) => document.querySelector(sel);
  const cfgForm = $("#dayConfigForm");
  const btnSave = $("#btnSaveCfg");
  const cfgRes = $("#cfgResult");

  cfgForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    btnSave.disabled = true;
    cfgRes.textContent = "";

    const body = {
      day: $("#cfgDay").value,
      start: $("#cfgStart").value,
      end: $("#cfgEnd").value,
      slot_minutes: parseInt($("#cfgMinutes").value, 10)
    };

    try {
      const r = await fetch("/api/agendatec/v1/coord/day-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body)
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (err.error === "booked_slots_exist") {
          showToast(`No se puede cambiar: ya hay ${err.booked_count} slots reservados ese día.`, "warn");
        } else if (err.error === "cannot_modify_today_or_past") {
          showToast("No puedes modificar el día actual o pasado.", "warn");
        } else if (err.error === "day_not_allowed") {
          showToast("El día no está permitido.", "warn");
        } else if (err.error === "slot_time_passed") {
          showToast("El horario inicial ya pasó");
        } else if (err.error === "invalid_time_range_or_slot_size") {
          showToast("Rango de horario inválido o tamaño de slot incompatible.", "warn");
        } else if (err.error === "overlap_booked_slots_exist") {
          showToast(`No se puede cambiar ese tramo: hay ${err.booked_count} slots reservados dentro del rango seleccionado.`, "warn");
        } else {
          showToast("Error al guardar configuración.", "error");
        }
        return;
      }
      const data = await r.json();
      cfgRes.textContent =
        `Ventanas borradas: ${data.windows_deleted} | ` +
        `Horarios borrados: ${data.slots_deleted} | ` +
        `Horarios creados: ${data.slots_created}`;
      showToast("Configuración guardada y slots generados.", "success");
    } catch (e) {
      showToast("No se pudo conectar.", "error");
    } finally {
      btnSave.disabled = false;
    }
  });
})();
