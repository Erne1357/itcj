// static/js/admin/period_days.js
const cfg = window.__periodDaysCfg;
const periodId = window.__periodId;

let flatpickrInstance;
let selectedDates = [];
let periodData = null;
let hasUnsavedChanges = false;
let mdlMessage;

// Modal helper functions
function showMessage(type, title, message) {
  const header = document.getElementById("mdlMessageHeader");
  const titleEl = document.getElementById("mdlMessageTitle");
  const icon = document.getElementById("mdlMessageIcon");
  const body = document.getElementById("mdlMessageBody");
  const footer = document.getElementById("mdlMessageFooter");

  header.className = "modal-header";

  const configs = {
    success: {
      headerClass: "bg-success text-white",
      icon: '<i class="bi bi-check-circle-fill text-success"></i>',
      btnClass: "btn-success"
    },
    error: {
      headerClass: "bg-danger text-white",
      icon: '<i class="bi bi-x-circle-fill text-danger"></i>',
      btnClass: "btn-danger"
    },
    warning: {
      headerClass: "bg-warning text-dark",
      icon: '<i class="bi bi-exclamation-triangle-fill text-warning"></i>',
      btnClass: "btn-warning"
    },
    info: {
      headerClass: "bg-info text-white",
      icon: '<i class="bi bi-info-circle-fill text-info"></i>',
      btnClass: "btn-info"
    }
  };

  const config = configs[type] || configs.info;
  header.classList.add(...config.headerClass.split(" "));
  titleEl.textContent = title;
  icon.innerHTML = config.icon;
  body.innerHTML = message.replace(/\n/g, "<br>");
  footer.innerHTML = `<button type="button" class="btn ${config.btnClass}" data-bs-dismiss="modal">Cerrar</button>`;

  mdlMessage.show();
}

function showConfirm(title, message, onConfirm) {
  const header = document.getElementById("mdlMessageHeader");
  const titleEl = document.getElementById("mdlMessageTitle");
  const icon = document.getElementById("mdlMessageIcon");
  const body = document.getElementById("mdlMessageBody");
  const footer = document.getElementById("mdlMessageFooter");

  header.className = "modal-header bg-warning text-dark";
  titleEl.textContent = title;
  icon.innerHTML = '<i class="bi bi-question-circle-fill text-warning"></i>';
  body.innerHTML = message.replace(/\n/g, "<br>");

  footer.innerHTML = `
    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
    <button type="button" class="btn btn-warning" id="btnConfirmAction">Confirmar</button>
  `;

  document.getElementById("btnConfirmAction").addEventListener("click", () => {
    mdlMessage.hide();
    if (onConfirm) onConfirm();
  });

  mdlMessage.show();
}

document.addEventListener("DOMContentLoaded", () => {
  // Initialize modals
  mdlMessage = new bootstrap.Modal(document.getElementById("mdlMessage"));

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
    showMessage("error", "Error al cargar", "No se pudieron cargar los datos: " + err.message);
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
    onChange: (selectedDatesObj) => {
      selectedDates = selectedDatesObj.map(d => formatDateISO(d));
      renderSelectedDays();
      hasUnsavedChanges = true;
    }
  });
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
    showMessage("info", "Sin cambios", "No hay cambios para guardar");
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

    showMessage("success", "Días guardados", `Días guardados correctamente\n\nDías habilitados: ${data.enabled_days_count}`);
    hasUnsavedChanges = false;
    loadData(); // Recargar para actualizar stats
  } catch (err) {
    console.error(err);
    showMessage("error", "Error al guardar", err.message);
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
