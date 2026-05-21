/**
 * social/home_init.js — Inicialización de días habilitados.
 *
 * Carga los días del período activo, llena el select #ssDay y dispara
 * el evento 'socialHomeInitReady' cuando está listo.
 *
 * Depende de: AgendaTec.Format (format.js, cargado antes en el template).
 * Usa Format.formatDayLabel(iso) → "Lun 25 Ago" (formato unificado con coord).
 */
(async () => {
  "use strict";

  const ssDaySelect = document.getElementById("ssDay");

  if (!ssDaySelect) {
    console.warn("[social_home_init] No se encontró el select de días (#ssDay)");
    return;
  }

  try {
    const response = await fetch("/api/agendatec/v2/periods/active", {
      credentials: "include",
    });

    if (!response.ok) {
      throw new Error("No hay período activo disponible");
    }

    const data = await response.json();
    const enabledDays = data.enabled_days || [];

    if (enabledDays.length === 0) {
      ssDaySelect.innerHTML = '<option value="">No hay días habilitados</option>';
      ssDaySelect.disabled = true;
      showToast?.("No hay días habilitados en el período activo", "warning");
      return;
    }

    // Formatear y ordenar días usando Format.formatDayLabel (Fase 2+)
    const formatLabel = window.AgendaTec?.Format?.formatDayLabel
      || ((iso) => iso); // fallback trivial si el script no cargó

    const daysWithFormat = enabledDays
      .map((dateStr) => ({
        value: dateStr,
        label: formatLabel(dateStr),
      }))
      .sort((a, b) => a.value.localeCompare(b.value));

    ssDaySelect.innerHTML = daysWithFormat
      .map((opt) => `<option value="${opt.value}">${opt.label}</option>`)
      .join("");

    ssDaySelect.disabled = false;

    // Seleccionar hoy si está disponible
    const today = new Date().toISOString().split("T")[0];
    if (daysWithFormat.some((d) => d.value === today)) {
      ssDaySelect.value = today;
    }

    document.dispatchEvent(
      new CustomEvent("socialHomeInitReady", {
        detail: {
          selectedDay:  ssDaySelect.value,
          enabledDays:  daysWithFormat,
        },
      })
    );
  } catch (error) {
    console.error("[social_home_init] Error al cargar días habilitados:", error);
    ssDaySelect.innerHTML = '<option value="">Error al cargar días</option>';
    ssDaySelect.disabled = true;
    showToast?.("Error al cargar los días del período activo", "danger");
  }
})();
