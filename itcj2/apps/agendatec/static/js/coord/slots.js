/**
 * coord/slots.js
 * Formulario "Configurar horario": guarda la configuración de slots del día.
 * Al éxito, muestra at-alert-inline con auto-dismiss 4s y llama __slotsRefresh.
 */

(function () {
  "use strict";

  const cfgForm = document.getElementById("dayConfigForm");
  const btnSave = document.getElementById("btnSaveCfg");
  const cfgRes  = document.getElementById("cfgResult");

  if (!cfgForm) return;

  let dismissTimer = null;

  function showSuccessAlert(msg) {
    if (!cfgRes) return;
    clearTimeout(dismissTimer);
    cfgRes.innerHTML = `
      <span class="at-alert-inline at-alert-inline--success">
        <i class="bi bi-check-circle" aria-hidden="true"></i>
        ${msg}
      </span>`;
    dismissTimer = setTimeout(() => {
      if (cfgRes) cfgRes.innerHTML = "";
    }, 4000);
  }

  cfgForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    btnSave.disabled = true;
    if (cfgRes) cfgRes.innerHTML = "";

    const body = {
      day:          document.getElementById("cfgDay").value,
      start:        document.getElementById("cfgStart").value,
      end:          document.getElementById("cfgEnd").value,
      slot_minutes: parseInt(document.getElementById("cfgMinutes").value, 10),
    };

    try {
      const r = await fetch("/api/agendatec/v2/coord/day-config", {
        method:      "POST",
        headers:     { "Content-Type": "application/json" },
        credentials: "include",
        body:        JSON.stringify(body),
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
          showToast("El horario inicial ya pasó.", "warn");
        } else if (err.error === "invalid_time_range_or_slot_size") {
          showToast("Rango de horario inválido o tamaño de slot incompatible.", "warn");
        } else if (err.error === "overlap_booked_slots_exist") {
          showToast(`No se puede cambiar ese tramo: hay ${err.booked_count} slots reservados dentro del rango.`, "warn");
        } else {
          showToast("Error al guardar configuración.", "error");
        }
        return;
      }

      const data = await r.json();
      showSuccessAlert(
        `Configuración guardada — Ventanas: ${data.windows_deleted} eliminadas | ` +
        `Horarios: ${data.slots_deleted} eliminados, ${data.slots_created} creados`
      );
      showToast("Configuración guardada y slots generados.", "success");

      // Auto-refresh de la vista (expuesto por slots_view.js)
      const day = document.getElementById("cfgDay").value;
      if (typeof window.__slotsRefresh === "function" && day) {
        window.__slotsRefresh(day);
      }
    } catch (e) {
      showToast("No se pudo conectar.", "error");
    } finally {
      btnSave.disabled = false;
    }
  });

})();
