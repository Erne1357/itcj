// static/js/coord/slots_init.js
// Inicialización de días habilitados del período activo

/**
 * Carga los días habilitados del período activo y llena los selects
 */
(async () => {
  const cfgDaySelect = document.getElementById("cfgDay");
  const cfgDayDelSelect = document.getElementById("cfgDayDel");

  if (!cfgDaySelect || !cfgDayDelSelect) {
    console.warn("[slots_init] No se encontraron los selects de días");
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

    // Actualizar el badge del período si existe
    const periodNameEl = document.getElementById("periodName");
    if (periodNameEl && data.name) {
      periodNameEl.textContent = data.name;
    }

    if (enabledDays.length === 0) {
      cfgDaySelect.innerHTML = '<option value="">No hay días habilitados</option>';
      cfgDayDelSelect.innerHTML = '<option value="">No hay días habilitados</option>';
      cfgDaySelect.disabled = true;
      cfgDayDelSelect.disabled = true;
      showToast("No hay días habilitados en el período activo", "warn");
      return;
    }

    // Formatear y ordenar días
    const daysWithFormat = enabledDays.map(dateStr => {
      const date = new Date(dateStr + "T00:00:00");
      return {
        value: dateStr,
        label: formatDayLabel(date)
      };
    }).sort((a, b) => a.value.localeCompare(b.value));

    // Llenar ambos selects
    fillSelect(cfgDaySelect, daysWithFormat);
    fillSelect(cfgDayDelSelect, daysWithFormat);

    // Habilitar los selects después de cargar
    cfgDaySelect.disabled = false;
    cfgDayDelSelect.disabled = false;

    // Verificar si hay un día en el hash de la URL
    const hashDay = window.location.hash.replace("#", "");
    if (hashDay) {
      const dayExists = daysWithFormat.some(d => d.value === hashDay);
      if (dayExists) {
        cfgDaySelect.value = hashDay;
        cfgDayDelSelect.value = hashDay;
      }
    }

    // Disparar evento personalizado para notificar que los días están listos
    const event = new CustomEvent('slotsInitReady', {
      detail: {
        selectedDay: cfgDaySelect.value,
        enabledDays: daysWithFormat
      }
    });
    document.dispatchEvent(event);

  } catch (error) {
    console.error("[slots_init] Error al cargar días habilitados:", error);
    cfgDaySelect.innerHTML = '<option value="">Error al cargar días</option>';
    cfgDayDelSelect.innerHTML = '<option value="">Error al cargar días</option>';
    cfgDaySelect.disabled = true;
    cfgDayDelSelect.disabled = true;

    // Actualizar badge con error
    const periodNameEl = document.getElementById("periodName");
    if (periodNameEl) {
      periodNameEl.textContent = "Error al cargar";
    }

    showToast("Error al cargar los días del período activo", "error");
  }
})();

/**
 * Llena un select con opciones
 */
function fillSelect(selectElement, options) {
  selectElement.innerHTML = options
    .map(opt => `<option value="${opt.value}">${opt.label}</option>`)
    .join("");
}

/**
 * Formatea una fecha como "Lun 25 Ago" en español
 */
function formatDayLabel(date) {
  const days = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
  const months = [
    "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"
  ];

  const dayName = days[date.getDay()];
  const dayNumber = date.getDate();
  const monthName = months[date.getMonth()];

  return `${dayName} ${dayNumber} ${monthName}`;
}
