// static/js/admin/periods.js
const cfg = window.__adminPeriodsCfg;
let currentPeriods = [];
let editingId = null;

// Bootstrap modals
let mdlPeriod, mdlDetails, mdlMessage;

// Modal helper functions
function showMessage(type, title, message) {
  const header = document.getElementById("mdlMessageHeader");
  const titleEl = document.getElementById("mdlMessageTitle");
  const icon = document.getElementById("mdlMessageIcon");
  const body = document.getElementById("mdlMessageBody");
  const footer = document.getElementById("mdlMessageFooter");

  // Reset header classes
  header.className = "modal-header";

  // Configure based on type
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
  mdlPeriod = new bootstrap.Modal(document.getElementById("mdlPeriod"));
  mdlDetails = new bootstrap.Modal(document.getElementById("mdlDetails"));
  mdlMessage = new bootstrap.Modal(document.getElementById("mdlMessage"));

  // Event listeners
  document.getElementById("btnReload").addEventListener("click", loadPeriods);
  document.getElementById("btnNew").addEventListener("click", () => openModal(null));
  document.getElementById("btnSavePeriod").addEventListener("click", savePeriod);
  document.getElementById("fltStatus").addEventListener("change", loadPeriods);

  loadPeriods();
});

async function loadPeriods() {
  try {
    const status = document.getElementById("fltStatus").value;
    let url = cfg.listUrl;
    if (status) {
      url += `?status=${status}`;
    }

    const resp = await fetch(url, { credentials: "same-origin" });
    if (!resp.ok) throw new Error("Error al cargar períodos");

    const data = await resp.json();
    currentPeriods = data.items || [];
    renderPeriods();
  } catch (err) {
    console.error(err);
    showMessage("error", "Error al cargar", "No se pudieron cargar los períodos: " + err.message);
  }
}

function renderPeriods() {
  const tbody = document.getElementById("tblPeriodsBody");
  if (!currentPeriods.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">No hay períodos registrados</td></tr>`;
    return;
  }

  tbody.innerHTML = currentPeriods.map(p => {
    const statusClass = {
      ACTIVE: "success",
      INACTIVE: "secondary",
      ARCHIVED: "warning"
    }[p.status] || "secondary";

    const statusText = {
      ACTIVE: "Activo",
      INACTIVE: "Inactivo",
      ARCHIVED: "Archivado"
    }[p.status] || p.status;

    return `
      <tr>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td>${formatDate(p.start_date)}</td>
        <td>${formatDate(p.end_date)}</td>
        <td>${formatDateTime(p.student_admission_deadline)}</td>
        <td><span class="badge bg-${statusClass}">${statusText}</span></td>
        <td>${p.request_count || 0}</td>
        <td>
          <div class="btn-group btn-group-sm">
            <button class="btn btn-outline-primary" onclick="viewDetails(${p.id})" title="Ver detalles">
              <i class="bi bi-eye"></i>
            </button>
            <button class="btn btn-outline-primary" onclick="configureDays(${p.id})" title="Configurar días">
              <i class="bi bi-calendar-week"></i>
            </button>
            ${p.status !== 'ACTIVE' ? `
            <button class="btn btn-outline-success" onclick="activatePeriod(${p.id})" title="Activar">
              <i class="bi bi-check-circle"></i>
            </button>
            ` : ''}
            <button class="btn btn-outline-secondary" onclick="openModal(${p.id})" title="Editar">
              <i class="bi bi-pencil"></i>
            </button>
            ${p.request_count === 0 ? `
            <button class="btn btn-outline-danger" onclick="deletePeriod(${p.id})" title="Eliminar">
              <i class="bi bi-trash"></i>
            </button>
            ` : ''}
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function openModal(periodId) {
  editingId = periodId;
  const title = document.getElementById("mdlTitle");

  if (periodId) {
    title.textContent = "Editar Período";
    const period = currentPeriods.find(p => p.id === periodId);
    if (!period) return;

    document.getElementById("fName").value = period.name;
    document.getElementById("fStartDate").value = period.start_date;
    document.getElementById("fEndDate").value = period.end_date;

    // Parse deadline
    const deadline = new Date(period.student_admission_deadline);
    document.getElementById("fDeadlineDate").value = deadline.toISOString().split('T')[0];
    document.getElementById("fDeadlineTime").value = deadline.toTimeString().slice(0, 5);

    document.getElementById("fStatus").value = period.status;
  } else {
    title.textContent = "Nuevo Período";
    document.getElementById("fName").value = "";
    document.getElementById("fStartDate").value = "";
    document.getElementById("fEndDate").value = "";
    document.getElementById("fDeadlineDate").value = "";
    document.getElementById("fDeadlineTime").value = "18:00";
    document.getElementById("fStatus").value = "INACTIVE";
  }

  mdlPeriod.show();
}

async function savePeriod() {
  const name = document.getElementById("fName").value.trim();
  const startDate = document.getElementById("fStartDate").value;
  const endDate = document.getElementById("fEndDate").value;
  const deadlineDate = document.getElementById("fDeadlineDate").value;
  const deadlineTime = document.getElementById("fDeadlineTime").value;
  const status = document.getElementById("fStatus").value;

  if (!name || !startDate || !endDate || !deadlineDate || !deadlineTime) {
    showMessage("warning", "Campos incompletos", "Por favor completa todos los campos obligatorios");
    return;
  }

  // Construir deadline con timezone
  const deadlineISO = `${deadlineDate}T${deadlineTime}:00-07:00`;

  const payload = {
    name,
    start_date: startDate,
    end_date: endDate,
    student_admission_deadline: deadlineISO,
    status
  };

  try {
    let url, method;
    if (editingId) {
      url = cfg.updateBase + editingId;
      method = "PATCH";
    } else {
      url = cfg.createUrl;
      method = "POST";
    }

    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload)
    });

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.message || data.error || "Error al guardar");
    }

    mdlPeriod.hide();
    loadPeriods();
    showMessage("success", "Operación exitosa", editingId ? "Período actualizado correctamente" : "Período creado correctamente");
  } catch (err) {
    console.error(err);
    showMessage("error", "Error al guardar", err.message);
  }
}

async function activatePeriod(periodId) {
  const period = currentPeriods.find(p => p.id === periodId);
  showConfirm(
    "Activar período",
    `¿Desactivar el período activo actual y activar "${period.name}"?`,
    async () => {
      try {
        const resp = await fetch(cfg.activateBase + periodId, {
          method: "POST",
          credentials: "same-origin"
        });

        const data = await resp.json();

        if (!resp.ok) {
          throw new Error(data.message || data.error || "Error al activar");
        }

        showMessage("success", "Período activado", "Período activado correctamente");
        loadPeriods();
      } catch (err) {
        console.error(err);
        showMessage("error", "Error al activar", err.message);
      }
    }
  );
}

async function deletePeriod(periodId) {
  const period = currentPeriods.find(p => p.id === periodId);
  showConfirm(
    "Eliminar período",
    `¿Eliminar el período "${period.name}"?\n\nEsta acción no se puede deshacer.`,
    async () => {
      try {
        const resp = await fetch(cfg.deleteBase + periodId, {
          method: "DELETE",
          credentials: "same-origin"
        });

        if (!resp.ok) {
          const data = await resp.json();
          throw new Error(data.message || data.error || "Error al eliminar");
        }

        showMessage("success", "Período eliminado", "Período eliminado correctamente");
        loadPeriods();
      } catch (err) {
        console.error(err);
        showMessage("error", "Error al eliminar", err.message);
      }
    }
  );
}

async function viewDetails(periodId) {
  try {
    const [periodResp, statsResp] = await Promise.all([
      fetch(cfg.detailBase + periodId, { credentials: "same-origin" }),
      fetch(cfg.statsBase + periodId, { credentials: "same-origin" })
    ]);

    if (!periodResp.ok || !statsResp.ok) throw new Error("Error al cargar detalles");

    const period = await periodResp.json();
    const stats = await statsResp.json();

    const content = document.getElementById("detailsContent");
    content.innerHTML = `
      <div class="row g-3">
        <div class="col-12">
          <h6>Información General</h6>
          <table class="table table-sm">
            <tr><th>Nombre:</th><td>${escapeHtml(period.name)}</td></tr>
            <tr><th>Estado:</th><td><span class="badge bg-${period.status === 'ACTIVE' ? 'success' : 'secondary'}">${period.status}</span></td></tr>
            <tr><th>Fecha Inicio:</th><td>${formatDate(period.start_date)}</td></tr>
            <tr><th>Fecha Fin:</th><td>${formatDate(period.end_date)}</td></tr>
            <tr><th>Fecha Límite Admisión:</th><td>${formatDateTime(period.student_admission_deadline)}</td></tr>
          </table>
        </div>
        <div class="col-12">
          <h6>Estadísticas</h6>
          <table class="table table-sm">
            <tr><th>Total Solicitudes:</th><td>${stats.total_requests}</td></tr>
            <tr><th>Solicitudes Pendientes:</th><td>${stats.pending_requests}</td></tr>
            <tr><th>Solicitudes Resueltas:</th><td>${stats.resolved_requests}</td></tr>
            <tr><th>Días Habilitados:</th><td>${stats.enabled_days_count}</td></tr>
          </table>
        </div>
        ${stats.enabled_days && stats.enabled_days.length > 0 ? `
        <div class="col-12">
          <h6>Días Habilitados</h6>
          <div class="d-flex flex-wrap gap-1">
            ${stats.enabled_days.map(d => `<span class="badge bg-primary">${formatDate(d)}</span>`).join('')}
          </div>
        </div>
        ` : ''}
      </div>
    `;

    mdlDetails.show();
  } catch (err) {
    console.error(err);
    showMessage("error", "Error al cargar detalles", "No se pudieron cargar los detalles del período: " + err.message);
  }
}

function configureDays(periodId) {
  window.location.href = cfg.daysPageBase + periodId;
}

// Utilidades
function formatDate(dateStr) {
  if (!dateStr) return "-";
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("es-MX", { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(dateTimeStr) {
  if (!dateTimeStr) return "-";
  const d = new Date(dateTimeStr);
  return d.toLocaleString("es-MX", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short"
  });
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, m => map[m]);
}
