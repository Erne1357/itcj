/**
 * coord/slots.js
 * Formulario "Configurar horario".
 *
 * Flujo: preview → (si toca a alguien) modal de confirmación → POST.
 * El endpoint ya no rechaza rangos con reservas: acorta las citas conservando
 * su hora de inicio, así que el coordinador tiene que ver a quién afecta antes
 * de aplicar.
 *
 * Depende de window.AgendaTecSlotScope (slots_scope.js, cargado antes).
 */

(function () {
  "use strict";

  const cfgForm = document.getElementById("dayConfigForm");
  const btnSave = document.getElementById("btnSaveCfg");
  const cfgRes  = document.getElementById("cfgResult");

  if (!cfgForm) return;

  const Scope = window.AgendaTecSlotScope || {};
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

  // El select ofrece las duraciones frecuentes; "Otra..." revela un input para
  // cualquier entero de 5 a 60. Antes solo se aceptaba el conjunto fijo.
  const selMinutes = document.getElementById("cfgMinutes");
  const inpMinutes = document.getElementById("cfgMinutesCustom");

  if (selMinutes && inpMinutes) {
    selMinutes.addEventListener("change", () => {
      const custom = selMinutes.value === "custom";
      inpMinutes.hidden = !custom;
      if (custom) inpMinutes.focus();
    });
  }

  function readMinutes() {
    if (selMinutes && selMinutes.value === "custom" && inpMinutes) {
      return parseInt(inpMinutes.value, 10);
    }
    return parseInt(selMinutes.value, 10);
  }

  function readBody() {
    return {
      day:          document.getElementById("cfgDay").value,
      start:        document.getElementById("cfgStart").value,
      end:          document.getElementById("cfgEnd").value,
      slot_minutes: readMinutes(),
      programs:     Scope.getSelectedPrograms ? Scope.getSelectedPrograms() : null,
    };
  }

  function reportError(payload, fallback) {
    const { code, detail } = Scope.readApiError
      ? Scope.readApiError(payload)
      : { code: payload && payload.error, detail: payload || {} };

    switch (code) {
      case "misaligned_booked_slots":
        showToast(
          "No se puede dividir a esa duración: hay citas que no caen en la nueva " +
          "rejilla — " + (Scope.describeOffenders ? Scope.describeOffenders(detail.offenders) : ""),
          "warn"
        );
        break;
      case "overlap_booked_slots_exist":
        showToast(
          `No se puede cambiar ese tramo: hay ${detail.booked_count} horario(s) reservado(s) dentro del rango.`,
          "warn"
        );
        break;
      case "overlapping_slots_in_range":
        showToast("Hay horarios encimados en ese rango. Repórtalo a soporte.", "error");
        break;
      case "coordinator_has_no_programs":
        showToast("No tienes carreras asignadas. Pide a un administrador que te las asigne.", "warn");
        break;
      case "invalid_programs":
        showToast("Seleccionaste una carrera que no coordinas.", "warn");
        break;
      case "day_not_allowed":
        showToast("El día no está permitido en el período activo.", "warn");
        break;
      case "day_in_past":
        showToast("No puedes configurar un día que ya pasó.", "warn");
        break;
      case "range_fully_in_past":
        showToast("Ese rango ya pasó por completo.", "warn");
        break;
      case "invalid_time_range_or_slot_size":
        showToast("Rango de horario inválido o duración de cita no permitida.", "warn");
        break;
      case "slot_booked_during_split":
        showToast("Un alumno reservó mientras confirmabas. Vuelve a intentarlo.", "warn");
        break;
      default:
        showToast(fallback, "error");
    }
  }

  cfgForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    btnSave.disabled = true;
    if (cfgRes) cfgRes.innerHTML = "";

    const body = readBody();

    if (!Number.isInteger(body.slot_minutes) || body.slot_minutes < 5 || body.slot_minutes > 60) {
      showToast("La duración de la cita debe ser un número entero entre 5 y 60 minutos.", "warn");
      btnSave.disabled = false;
      return;
    }

    try {
      // 1) Preview: sin efectos, dice a quién afecta el cambio.
      const pRes = await fetch("/api/agendatec/v2/coord/day-config/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      const preview = await pRes.json().catch(() => ({}));

      if (!pRes.ok) {
        reportError(preview, "No se pudo validar la configuración.");
        return;
      }

      if (preview.blocked) {
        showToast(
          "No se puede dividir a " + body.slot_minutes + " min: hay citas que no caen " +
          "en la nueva rejilla — " + Scope.describeOffenders(preview.offenders),
          "warn"
        );
        return;
      }

      // 2) Confirmación explícita solo si el cambio toca a alguien.
      const touchesSomeone =
        (preview.appointments_affected || []).length ||
        (preview.out_of_scope_appointments || []).length;

      if (touchesSomeone && Scope.renderPreviewModal) {
        const ok = await Scope.renderPreviewModal(preview);
        if (!ok) return;
      }

      // 3) POST definitivo. Puede devolver 409 aunque el preview dijera que no:
      //    entre ambos un alumno pudo reservar.
      const r = await fetch("/api/agendatec/v2/coord/day-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        reportError(err, "Error al guardar configuración.");
        return;
      }

      const data = await r.json();
      const partes = [`${data.slots_created} horario(s) creado(s)`];
      if (data.slots_deleted) partes.push(`${data.slots_deleted} eliminado(s)`);
      if (data.slots_shortened) partes.push(`${data.slots_shortened} cita(s) ajustada(s)`);
      showSuccessAlert("Configuración guardada — " + partes.join(", "));

      if (data.appointments_notified) {
        showToast(`Se notificó a ${data.appointments_notified} alumno(s) del cambio.`, "success");
      } else {
        showToast("Configuración guardada y horarios generados.", "success");
      }

      // Auto-refresh de la vista (expuesto por slots_view.js)
      if (typeof window.__slotsRefresh === "function" && body.day) {
        window.__slotsRefresh(body.day);
      }
    } catch (e) {
      showToast("No se pudo conectar.", "error");
    } finally {
      btnSave.disabled = false;
    }
  });

})();
