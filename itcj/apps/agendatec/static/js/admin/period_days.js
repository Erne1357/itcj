// static/js/admin/period_days.js
const cfg = window.__periodDaysCfg;
const periodId = window.__periodId;

let flatpickrInstance;
let selectedDates = [];
let periodData = null;
let hasUnsavedChanges = false;
let mdlConfirm;

// Toast notification helper
function showToast(message, type = "info") {
  // Si existe Toastify (librería global)
  if (window.Toastify) {
    const bgColors = {
      success: "linear-gradient(to right, #00b09b, #96c93d)",
      error: "linear-gradient(to right, #ff5f6d, #ffc371)",
      warn: "linear-gradient(to right, #f09819, #ff512f)",
      info: "linear-gradient(to right, #4facfe, #00f2fe)"
    };

    Toastify({
      text: message,
      duration: 3000,
      gravity: "top",
      position: "right",
      background: bgColors[type] || bgColors.info,
      stopOnFocus: true
    }).showToast();
  } else {
    // Fallback a alert si no hay Toastify
    alert(message);
  }
}

// Confirmation modal helper
function showConfirm(title, message, onConfirm) {
  const titleEl = document.getElementById("mdlConfirmTitle");
  const body = document.getElementById("mdlConfirmBody");

  titleEl.textContent = title;
  body.innerHTML = message.replace(/\n/g, "<br>");

  const btnConfirm = document.getElementById("btnConfirmAction");
  const newBtn = btnConfirm.cloneNode(true);
  btnConfirm.parentNode.replaceChild(newBtn, btnConfirm);

  newBtn.addEventListener("click", () => {
    mdlConfirm.hide();
    if (onConfirm) onConfirm();
  });

  mdlConfirm.show();
}

document.addEventListener("DOMContentLoaded", () => {
  // Initialize modals
  mdlConfirm = new bootstrap.Modal(document.getElementById("mdlConfirm"));

  // Event listeners
  document.getElementById("btnReload").addEventListener("click", loadData);
  document.getElementById("btnSave").addEventListener("click", saveDays);
  document.getElementById("btnClearAll").addEventListener("click", clearAllDays);

  // Warn before leaving with unsaved changes
  window.addEventListener("beforeunload", (e) => {
    if (hasUnsavedChanges) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  loadData();
});

async function loadData() {
  try {
    // Cargar período y días habilitados en paralelo
    const [periodResp, daysResp, statsResp] = await Promise.all([
      fetch(cfg.periodDetailUrl, { credentials: "same-origin" }),
      fetch(cfg.enabledDaysUrl, { credentials: "same-origin" }),
      fetch(cfg.statsUrl, { credentials: "same-origin" })
    ]);

    if (!periodResp.ok || !daysResp.ok || !statsResp.ok) {
      throw new Error("Error al cargar datos");
    }

    periodData = await periodResp.json();
    const daysData = await daysResp.json();
    const statsData = await statsResp.json();

    // Actualizar nombre del período
    document.getElementById("periodName").innerHTML =
      `Período: <span class="fw-bold">${escapeHtml(periodData.name)}</span>`;

    // Cargar días seleccionados
    selectedDates = (daysData.days || []).map(d => d.day);

    // Inicializar Flatpickr
    initFlatpickr();

    // Actualizar UI
    renderSelectedDays();
    renderStats(statsData);

    hasUnsavedChanges = false;
  } catch (err) {
    console.error(err);
    showToast("Error al cargar datos: " + err.message, "error");
  }
}

function initFlatpickr() {
  if (flatpickrInstance) {
    flatpickrInstance.destroy();
  }

  const container = document.getElementById("calendarContainer");
  container.innerHTML = '<input id="flatpickrInput" type="text" style="display:none;">';

  flatpickrInstance = flatpickr("#flatpickrInput", {
    mode: "multiple",
    inline: true,
    locale: "es",
    dateFormat: "Y-m-d",
    defaultDate: selectedDates,
    minDate: periodData.start_date,
    maxDate: periodData.end_date,
    appendTo: container,
    onChange: (selectedDatesObj, dateStr, instance) => {
      selectedDates = selectedDatesObj.map(d => formatDateISO(d));
      renderSelectedDays();
      hasUnsavedChanges = true;
      // Reaplicar estilos después de seleccionar/deseleccionar
      setTimeout(() => fixFlatpickrStyles(instance), 10);
    },
    static: true,
    onReady: function(selectedDates, dateStr, instance) {
      // Aplicar estilos forzados después de que Flatpickr renderiza
      fixFlatpickrStyles(instance);
    },
    onMonthChange: function(selectedDates, dateStr, instance) {
      // Reaplicar estilos cuando cambia el mes
      fixFlatpickrStyles(instance);
    },
    onYearChange: function(selectedDates, dateStr, instance) {
      // Reaplicar estilos cuando cambia el año
      fixFlatpickrStyles(instance);
    }
  });
}

function fixFlatpickrStyles(instance) {
  // Esperar un momento para que Flatpickr termine de renderizar
  setTimeout(() => {
    const calendar = instance.calendarContainer;

    // Arreglar el dayContainer para usar grid
    const dayContainer = calendar.querySelector('.dayContainer');
    if (dayContainer) {
      dayContainer.style.display = 'grid';
      dayContainer.style.gridTemplateColumns = 'repeat(7, 1fr)';
      dayContainer.style.width = '100%';
      dayContainer.style.gap = '5px';
    }

    // Arreglar los días individuales
    const days = calendar.querySelectorAll('.flatpickr-day');
    days.forEach(day => {
      // Aplicar solo los estilos de layout necesarios
      day.style.float = 'none';
      day.style.height = '38px';
      day.style.lineHeight = '38px';
      day.style.width = '100%';
      day.style.maxWidth = '100%';
      day.style.flex = 'none';
      day.style.margin = '0';
      day.style.padding = '0';
      day.style.display = 'flex';
      day.style.alignItems = 'center';
      day.style.justifyContent = 'center';
      day.style.borderRadius = '0.375rem';

      // IMPORTANTE: Limpiar estilos inline de Flatpickr que bloquean el hover
      // Solo para días normales (no seleccionados, no deshabilitados, no de otros meses)
      if (!day.classList.contains('selected') &&
          !day.classList.contains('flatpickr-disabled') &&
          !day.classList.contains('prevMonthDay') &&
          !day.classList.contains('nextMonthDay')) {
        // Remover estilos inline para que el CSS funcione
        day.style.removeProperty('background-color');
        day.style.removeProperty('border');
        day.style.removeProperty('border-color');
      }
    });

    // Arreglar el contenedor principal
    const rContainer = calendar.querySelector('.flatpickr-rContainer');
    if (rContainer) {
      rContainer.style.display = 'block';
      rContainer.style.width = '100%';
    }

    const innerContainer = calendar.querySelector('.flatpickr-innerContainer');
    if (innerContainer) {
      innerContainer.style.display = 'block';
      innerContainer.style.width = '100%';
    }

    const daysContainer = calendar.querySelector('.flatpickr-days');
    if (daysContainer) {
      daysContainer.style.width = '100%';
    }

    // Arreglar los nombres de los días de la semana
    const weekdays = calendar.querySelectorAll('.flatpickr-weekday');
    weekdays.forEach(weekday => {
      weekday.style.fontSize = '0.85rem';
      weekday.style.fontWeight = '700';
      weekday.style.color = '#212529';
      weekday.style.textTransform = 'uppercase';
      weekday.style.letterSpacing = '0.5px';
    });
  }, 10);
}

function renderSelectedDays() {
  const list = document.getElementById("selectedDaysList");
  const emptyMsg = document.getElementById("emptyMessage");
  const count = document.getElementById("selectedCount");

  count.textContent = selectedDates.length;

  if (selectedDates.length === 0) {
    list.style.display = "none";
    emptyMsg.style.display = "block";
    return;
  }

  list.style.display = "block";
  emptyMsg.style.display = "none";

  // Ordenar fechas
  const sorted = [...selectedDates].sort();

  list.innerHTML = sorted.map(dateStr => `
    <div class="list-group-item d-flex justify-content-between align-items-center">
      <span>
        <i class="bi bi-calendar-check text-primary"></i>
        ${formatDateReadable(dateStr)}
      </span>
      <button class="btn btn-sm btn-outline-danger" onclick="removeDay('${dateStr}')">
        <i class="bi bi-trash"></i>
      </button>
    </div>
  `).join("");
}

function renderStats(stats) {
  const container = document.getElementById("statsContent");
  container.innerHTML = `
    <div class="row g-2 text-center">
      <div class="col-6">
        <div class="p-2 bg-light rounded">
          <div class="fs-4 fw-bold text-primary">${stats.total_requests || 0}</div>
          <div class="small text-muted">Total Solicitudes</div>
        </div>
      </div>
      <div class="col-6">
        <div class="p-2 bg-light rounded">
          <div class="fs-4 fw-bold text-warning">${stats.pending_requests || 0}</div>
          <div class="small text-muted">Pendientes</div>
        </div>
      </div>
      <div class="col-6">
        <div class="p-2 bg-light rounded">
          <div class="fs-4 fw-bold text-success">${stats.resolved_requests || 0}</div>
          <div class="small text-muted">Resueltas</div>
        </div>
      </div>
      <div class="col-6">
        <div class="p-2 bg-light rounded">
          <div class="fs-4 fw-bold text-info">${selectedDates.length}</div>
          <div class="small text-muted">Días Habilitados</div>
        </div>
      </div>
    </div>
  `;
}

function removeDay(dateStr) {
  selectedDates = selectedDates.filter(d => d !== dateStr);
  flatpickrInstance.setDate(selectedDates);
  renderSelectedDays();
  hasUnsavedChanges = true;
}

function clearAllDays() {
  showConfirm(
    "Limpiar días",
    "¿Deseas limpiar todos los días seleccionados?",
    () => {
      selectedDates = [];
      flatpickrInstance.clear();
      renderSelectedDays();
      hasUnsavedChanges = true;
    }
  );
}

async function saveDays() {
  if (!hasUnsavedChanges) {
    showToast("No hay cambios para guardar", "info");
    return;
  }

  if (selectedDates.length === 0) {
    showConfirm(
      "Advertencia",
      "⚠️ Vas a eliminar TODOS los días habilitados.\n\nLos estudiantes NO podrán crear solicitudes en este período.\n\n¿Continuar?",
      async () => {
        await performSave();
      }
    );
  } else {
    await performSave();
  }
}

async function performSave() {
  try {
    const resp = await fetch(cfg.saveEnabledDaysUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ days: selectedDates })
    });

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.message || data.error || "Error al guardar");
    }

    showToast(`Días guardados correctamente (${data.enabled_days_count} días habilitados)`, "success");
    hasUnsavedChanges = false;
    loadData(); // Recargar para actualizar stats
  } catch (err) {
    console.error(err);
    showToast("Error al guardar: " + err.message, "error");
  }
}

// Utilidades
function formatDateISO(date) {
  const d = new Date(date);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDateReadable(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("es-MX", {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
}
