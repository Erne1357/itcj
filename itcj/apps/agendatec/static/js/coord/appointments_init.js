// static/js/coord/appointments_init.js
// Inicialización de días habilitados para vista de citas

/**
 * Carga los días habilitados del período activo y llena el select
 */
(async () => {
  const apDaySelect = document.getElementById("apDay");

  if (!apDaySelect) {
    console.warn("[appointments_init] No se encontró el select de días");
    return;
  }

  try {
    // Cargar período activo con días habilitados
    const response = await fetch("/api/agendatec/v1/periods/active", {
      credentials: "include"
    });

    if (!response.ok) {
      throw new Error("No hay período activo disponible");
    }

    const data = await response.json();
    const enabledDays = data.enabled_days || [];

    if (enabledDays.length === 0) {
      apDaySelect.innerHTML = '<option value="">No hay días habilitados</option>';
      apDaySelect.disabled = true;
      showToast("No hay días habilitados en el período activo", "warn");
      return;
    }

    // Formatear y ordenar días
    const daysWithFormat = enabledDays.map(dateStr => {
      const date = new Date(dateStr + "T00:00:00");
      return {
        value: dateStr,
        label: formatDayLabelShort(date)
      };
    }).sort((a, b) => a.value.localeCompare(b.value));

    // Llenar select
    apDaySelect.innerHTML = daysWithFormat
      .map(opt => `<option value="${opt.value}">${opt.label}</option>`)
      .join("");

    // Habilitar el select
    apDaySelect.disabled = false;

    // Seleccionar el día actual si está en la lista
    const today = new Date().toISOString().split('T')[0];
    const todayExists = daysWithFormat.some(d => d.value === today);
    if (todayExists) {
      apDaySelect.value = today;
    }

    // Disparar evento personalizado para notificar que los días están listos
    const event = new CustomEvent('appointmentsInitReady', {
      detail: {
        selectedDay: apDaySelect.value,
        enabledDays: daysWithFormat
      }
    });
    document.dispatchEvent(event);

  } catch (error) {
    console.error("[appointments_init] Error al cargar días habilitados:", error);
    apDaySelect.innerHTML = '<option value="">Error al cargar días</option>';
    apDaySelect.disabled = true;
    showToast("Error al cargar los días del período activo", "error");
  }
})();

/**
 * Formatea una fecha como "25 Ago" en español (versión corta)
 */
function formatDayLabelShort(date) {
  const months = [
    "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"
  ];

  const dayNumber = date.getDate();
  const monthName = months[date.getMonth()];

  return `${dayNumber} ${monthName}`;
}
