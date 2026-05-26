/**
 * coord/slots_init.js
 * Carga los días habilitados del período activo y llena los selects #cfgDay y #cfgDayDel.
 * Usa AgendaTec.Format.formatDayLabel (formato "Lun 25 Ago") del shared.
 */

(async function () {
  "use strict";

  const cfgDaySelect    = document.getElementById("cfgDay");
  const cfgDayDelSelect = document.getElementById("cfgDayDel");

  if (!cfgDaySelect || !cfgDayDelSelect) {
    console.warn("[slots_init] No se encontraron los selects de días");
    return;
  }

  try {
    const response = await fetch("/api/agendatec/v2/periods/active", {
      credentials: "include",
    });

    if (!response.ok) throw new Error("No hay período activo disponible");

    const data        = await response.json();
    const enabledDays = data.enabled_days || [];

    // Actualizar badge del período
    const periodNameEl = document.getElementById("periodName");
    if (periodNameEl && data.name) periodNameEl.textContent = data.name;

    if (enabledDays.length === 0) {
      cfgDaySelect.innerHTML    = '<option value="">No hay días habilitados</option>';
      cfgDayDelSelect.innerHTML = '<option value="">No hay días habilitados</option>';
      cfgDaySelect.disabled     = true;
      cfgDayDelSelect.disabled  = true;
      showToast("No hay días habilitados en el período activo", "warn");
      return;
    }

    // Usar formatDayLabel del shared ("Lun 25 Ago")
    const fmt = window.AgendaTec.Format.formatDayLabel;

    const daysWithFormat = enabledDays
      .map(dateStr => ({ value: dateStr, label: fmt(dateStr) }))
      .sort((a, b) => a.value.localeCompare(b.value));

    fillSelect(cfgDaySelect,    daysWithFormat);
    fillSelect(cfgDayDelSelect, daysWithFormat);

    cfgDaySelect.disabled    = false;
    cfgDayDelSelect.disabled = false;

    // Verificar si hay día en el hash de la URL
    const hashDay = window.location.hash.replace("#", "");
    if (hashDay) {
      const dayExists = daysWithFormat.some(d => d.value === hashDay);
      if (dayExists) {
        cfgDaySelect.value    = hashDay;
        cfgDayDelSelect.value = hashDay;
      }
    }

    document.dispatchEvent(new CustomEvent("slotsInitReady", {
      detail: { selectedDay: cfgDaySelect.value, enabledDays: daysWithFormat },
    }));
  } catch (error) {
    console.error("[slots_init] Error:", error);
    cfgDaySelect.innerHTML    = '<option value="">Error al cargar días</option>';
    cfgDayDelSelect.innerHTML = '<option value="">Error al cargar días</option>';
    cfgDaySelect.disabled     = true;
    cfgDayDelSelect.disabled  = true;
    const periodNameEl = document.getElementById("periodName");
    if (periodNameEl) periodNameEl.textContent = "Error al cargar";
    showToast("Error al cargar los días del período activo", "error");
  }
})();

function fillSelect(selectElement, options) {
  selectElement.innerHTML = options
    .map(opt => `<option value="${opt.value}">${opt.label}</option>`)
    .join("");
}
