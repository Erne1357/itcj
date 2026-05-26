/**
 * coord/appointments_init.js
 * Carga los días habilitados del período activo y llena el select #apDay.
 * Usa AgendaTec.Format.formatDayLabel (formato "Lun 25 Ago") del shared.
 */

(async function () {
  "use strict";

  const apDaySelect = document.getElementById("apDay");

  if (!apDaySelect) {
    console.warn("[appointments_init] No se encontró el select de días");
    return;
  }

  try {
    const response = await fetch("/api/agendatec/v2/periods/active", {
      credentials: "include",
    });

    if (!response.ok) throw new Error("No hay período activo disponible");

    const data        = await response.json();
    const enabledDays = data.enabled_days || [];

    if (enabledDays.length === 0) {
      apDaySelect.innerHTML = '<option value="">No hay días habilitados</option>';
      apDaySelect.disabled  = true;
      showToast("No hay días habilitados en el período activo", "warn");
      return;
    }

    // Usar formatDayLabel del shared ("Lun 25 Ago")
    const fmt = window.AgendaTec.Format.formatDayLabel;

    const daysWithFormat = enabledDays
      .map(dateStr => ({ value: dateStr, label: fmt(dateStr) }))
      .sort((a, b) => a.value.localeCompare(b.value));

    apDaySelect.innerHTML = daysWithFormat
      .map(opt => `<option value="${opt.value}">${opt.label}</option>`)
      .join("");
    apDaySelect.disabled = false;

    // Seleccionar hoy si está en la lista
    const today     = new Date().toISOString().split("T")[0];
    const todayExists = daysWithFormat.some(d => d.value === today);
    if (todayExists) apDaySelect.value = today;

    document.dispatchEvent(new CustomEvent("appointmentsInitReady", {
      detail: { selectedDay: apDaySelect.value, enabledDays: daysWithFormat },
    }));
  } catch (error) {
    console.error("[appointments_init] Error:", error);
    apDaySelect.innerHTML = '<option value="">Error al cargar días</option>';
    apDaySelect.disabled  = true;
    showToast("Error al cargar los días del período activo", "error");
  }
})();
