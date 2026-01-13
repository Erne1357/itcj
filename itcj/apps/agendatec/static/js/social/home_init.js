// static/js/social/home_init.js
// Inicialización de días habilitados para vista de servicio social

/**
 * Carga los días habilitados del período activo y llena el select
 */
(async () => {
  const ssDaySelect = document.getElementById("ssDay");

  if (!ssDaySelect) {
    console.warn("[social_home_init] No se encontró el select de días");
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
      ssDaySelect.innerHTML = '<option value="">No hay días habilitados</option>';
      ssDaySelect.disabled = true;
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
    ssDaySelect.innerHTML = daysWithFormat
      .map(opt => `<option value="${opt.value}">${opt.label}</option>`)
      .join("");

    // Habilitar el select
    ssDaySelect.disabled = false;

    // Seleccionar el día actual si está en la lista
    const today = new Date().toISOString().split('T')[0];
    const todayExists = daysWithFormat.some(d => d.value === today);
    if (todayExists) {
      ssDaySelect.value = today;
    }

    // Disparar evento personalizado para notificar que los días están listos
    const event = new CustomEvent('socialHomeInitReady', {
      detail: {
        selectedDay: ssDaySelect.value,
        enabledDays: daysWithFormat
      }
    });
    document.dispatchEvent(event);

  } catch (error) {
    console.error("[social_home_init] Error al cargar días habilitados:", error);
    ssDaySelect.innerHTML = '<option value="">Error al cargar días</option>';
    ssDaySelect.disabled = true;
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
