// static/js/admin/periods.js
// === ESTADO GLOBAL DEL MÓDULO ===
const cfg = window.__adminPeriodsCfg;
let currentPeriods = [];
let editingId = null;

let mdlPeriod, mdlDetails, mdlConfirm;

// === MODAL DE CONFIRMACIÓN ===
function showConfirm(title, message, onConfirm) {
  document.getElementById("mdlConfirmTitle").textContent = title;
  document.getElementById("mdlConfirmBody").innerHTML = message.replace(/\n/g, "<br>");

  const btnConfirm = document.getElementById("btnConfirmAction");
  const newBtn = btnConfirm.cloneNode(true);
  btnConfirm.parentNode.replaceChild(newBtn, btnConfirm);
  newBtn.addEventListener("click", () => { mdlConfirm.hide(); if (onConfirm) onConfirm(); });
  mdlConfirm.show();
}

// === VALIDACIÓN INLINE ===
function setFieldError(id, message) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add("is-invalid");
  let fb = el.nextElementSibling;
  if (!fb || !fb.classList.contains("invalid-feedback")) {
    fb = document.createElement("div");
    fb.className = "invalid-feedback";
    el.after(fb);
  }
  fb.textContent = message;
}

function clearFieldError(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("is-invalid");
  const fb = el.nextElementSibling;
  if (fb && fb.classList.contains("invalid-feedback")) fb.remove();
}

function clearAllErrors() {
  ["fCode", "fName", "fStartDate", "fEndDate", "fAdmissionStartDate",
   "fAdmissionStartTime", "fDeadlineDate", "fDeadlineTime"].forEach(clearFieldError);
}

// === INICIALIZACIÓN ===
document.addEventListener("DOMContentLoaded", () => {
  mdlPeriod  = new bootstrap.Modal(document.getElementById("mdlPeriod"));
  mdlDetails = new bootstrap.Modal(document.getElementById("mdlDetails"));
  mdlConfirm = new bootstrap.Modal(document.getElementById("mdlConfirm"));

  document.getElementById("btnReload").addEventListener("click", loadPeriods);
  document.getElementById("btnNew").addEventListener("click", () => openModal(null));
  document.getElementById("btnSavePeriod").addEventListener("click", savePeriod);
  document.getElementById("fltStatus").addEventListener("change", loadPeriods);

  // Limpiar errores al escribir
  ["fCode", "fName", "fStartDate", "fEndDate", "fAdmissionStartDate",
   "fAdmissionStartTime", "fDeadlineDate", "fDeadlineTime"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => clearFieldError(id));
    document.getElementById(id)?.addEventListener("change", () => clearFieldError(id));
  });

  loadPeriods();
});

// === CARGA DE PERÍODOS ===
async function loadPeriods() {
  const tbody = document.getElementById("tblPeriodsBody");

  // Skeleton durante carga
  if (window.AgendaTec?.Skeleton) {
    tbody.innerHTML = window.AgendaTec.Skeleton.tableRows(4, 8, { withActions: true });
  }

  try {
    const status = document.getElementById("fltStatus").value;
    let url = cfg.listUrl;
    if (status) url += `?status=${status}`;

    const resp = await fetch(url, { credentials: "same-origin" });
    if (!resp.ok) throw new Error("Error al cargar períodos");

    const data = await resp.json();
    currentPeriods = data.items || [];
    renderPeriods();
  } catch (err) {
    console.error(err);
    showToast("Error al cargar períodos: " + err.message, "error");
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger small py-3">
      <i class="bi bi-exclamation-triangle me-1"></i>Error al cargar datos</td></tr>`;
  }
}

// === RENDER TABLA ===
function renderPeriods() {
  const tbody = document.getElementById("tblPeriodsBody");

  if (!currentPeriods.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8">
          <div class="at-empty py-4">
            <i class="bi bi-calendar-x fs-3" aria-hidden="true"></i>
            <p class="mt-2 mb-0">No hay períodos registrados</p>
          </div>
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = currentPeriods.map((p, idx) => {
    const statusClass = { ACTIVE: "success", INACTIVE: "secondary", ARCHIVED: "warning" }[p.status] || "secondary";
    const statusText  = { ACTIVE: "Activo",  INACTIVE: "Inactivo",  ARCHIVED: "Archivado" }[p.status] || p.status;

    const deadline      = p.agendatec_config?.student_admission_deadline || "-";
    const admissionStart = p.agendatec_config?.student_admission_start   || "-";
    const windowDisplay  = (admissionStart !== "-" && deadline !== "-")
      ? `${formatDateTime(admissionStart)}<br><small class="text-muted">a</small><br>${formatDateTime(deadline)}`
      : "-";

    const staggerClass = idx < 8 ? ` at-stagger` : "";

    return `
      <tr class="${staggerClass}" style="animation-delay:${idx * 40}ms">
        <td><code>${escapeHtml(p.code || "-")}</code></td>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td>${formatDate(p.start_date)}</td>
        <td>${formatDate(p.end_date)}</td>
        <td class="small">${windowDisplay}</td>
        <td><span class="badge text-bg-${statusClass}">${statusText}</span></td>
        <td>${p.request_count || 0}</td>
        <td>
          <div class="btn-group btn-group-sm">
            <button class="btn btn-outline-primary" onclick="viewDetails(${p.id})" title="Ver detalles" aria-label="Ver detalles">
              <i class="bi bi-eye" aria-hidden="true"></i>
            </button>
            <button class="btn btn-outline-primary" onclick="configureDays(${p.id})" title="Configurar días" aria-label="Configurar días">
              <i class="bi bi-calendar-week" aria-hidden="true"></i>
            </button>
            ${p.status !== "ACTIVE" ? `
            <button class="btn btn-outline-success" onclick="activatePeriod(${p.id})" title="Activar" aria-label="Activar período">
              <i class="bi bi-check-circle" aria-hidden="true"></i>
            </button>` : ""}
            <button class="btn btn-outline-secondary" onclick="openModal(${p.id})" title="Editar" aria-label="Editar período">
              <i class="bi bi-pencil" aria-hidden="true"></i>
            </button>
            ${p.request_count === 0 ? `
            <button class="btn btn-outline-danger" onclick="deletePeriod(${p.id})" title="Eliminar" aria-label="Eliminar período">
              <i class="bi bi-trash" aria-hidden="true"></i>
            </button>` : ""}
          </div>
        </td>
      </tr>`;
  }).join("");

  // Sincronizar labels para responsividad mobile
  if (window.AgendaTec?.TableCard) {
    window.AgendaTec.TableCard.syncLabels(document.querySelector("#tblPeriodsBody")?.closest("table"));
  }
}

// === MODAL NUEVO/EDITAR ===
function openModal(periodId) {
  editingId = periodId;
  clearAllErrors();

  if (periodId) {
    document.getElementById("mdlTitle").textContent = "Editar Período";
    const period = currentPeriods.find((p) => p.id === periodId);
    if (!period) return;

    document.getElementById("fCode").value     = period.code || "";
    document.getElementById("fName").value     = period.name;
    document.getElementById("fStartDate").value = period.start_date;
    document.getElementById("fEndDate").value   = period.end_date;

    if (period.agendatec_config?.student_admission_start) {
      const admStart = new Date(period.agendatec_config.student_admission_start);
      document.getElementById("fAdmissionStartDate").value = admStart.toISOString().split("T")[0];
      document.getElementById("fAdmissionStartTime").value = admStart.toTimeString().slice(0, 5);
    } else {
      document.getElementById("fAdmissionStartDate").value = "";
      document.getElementById("fAdmissionStartTime").value = "00:00";
    }

    if (period.agendatec_config?.student_admission_deadline) {
      const deadline = new Date(period.agendatec_config.student_admission_deadline);
      document.getElementById("fDeadlineDate").value = deadline.toISOString().split("T")[0];
      document.getElementById("fDeadlineTime").value = deadline.toTimeString().slice(0, 5);
    } else {
      document.getElementById("fDeadlineDate").value = "";
      document.getElementById("fDeadlineTime").value = "18:00";
    }

    document.getElementById("fStatus").value = period.status;
  } else {
    document.getElementById("mdlTitle").textContent = "Nuevo Período";
    ["fCode","fName","fStartDate","fEndDate","fAdmissionStartDate","fDeadlineDate"].forEach(
      (id) => { document.getElementById(id).value = ""; }
    );
    document.getElementById("fAdmissionStartTime").value = "00:00";
    document.getElementById("fDeadlineTime").value       = "18:00";
    document.getElementById("fStatus").value             = "INACTIVE";
  }

  mdlPeriod.show();
}

// === GUARDAR PERÍODO ===
async function savePeriod() {
  const code                = document.getElementById("fCode").value.trim();
  const name                = document.getElementById("fName").value.trim();
  const startDate           = document.getElementById("fStartDate").value;
  const endDate             = document.getElementById("fEndDate").value;
  const admissionStartDate  = document.getElementById("fAdmissionStartDate").value;
  const admissionStartTime  = document.getElementById("fAdmissionStartTime").value;
  const deadlineDate        = document.getElementById("fDeadlineDate").value;
  const deadlineTime        = document.getElementById("fDeadlineTime").value;
  const status              = document.getElementById("fStatus").value;

  clearAllErrors();
  let hasError = false;

  if (!code) { setFieldError("fCode", "El código es obligatorio"); hasError = true; }
  if (!name) { setFieldError("fName", "El nombre es obligatorio"); hasError = true; }
  if (!startDate) { setFieldError("fStartDate", "La fecha de inicio es obligatoria"); hasError = true; }
  if (!endDate)   { setFieldError("fEndDate",   "La fecha de fin es obligatoria"); hasError = true; }
  if (!admissionStartDate) { setFieldError("fAdmissionStartDate", "Obligatorio"); hasError = true; }
  if (!admissionStartTime) { setFieldError("fAdmissionStartTime", "Obligatorio"); hasError = true; }
  if (!deadlineDate) { setFieldError("fDeadlineDate", "Obligatorio"); hasError = true; }
  if (!deadlineTime) { setFieldError("fDeadlineTime", "Obligatorio"); hasError = true; }
  if (hasError) return;

  const admissionStartISO = `${admissionStartDate}T${admissionStartTime}:00-07:00`;
  const deadlineISO       = `${deadlineDate}T${deadlineTime}:00-07:00`;

  if (new Date(deadlineISO) <= new Date(admissionStartISO)) {
    setFieldError("fDeadlineDate", "La fecha límite debe ser posterior al inicio de admisión");
    return;
  }

  const payload = {
    code, name,
    start_date: startDate, end_date: endDate,
    student_admission_start:    admissionStartISO,
    student_admission_deadline: deadlineISO,
    status,
  };

  // Estado de carga en botón
  const btn = document.getElementById("btnSavePeriod");
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Guardando...';

  try {
    const url    = editingId ? cfg.update.replace("{id}", editingId) : cfg.createUrl;
    const method = editingId ? "PATCH" : "POST";

    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

    const data = await resp.json();

    if (!resp.ok) {
      // Para errores 4xx, mostrar como validación inline en el primer campo
      const msg = data.detail || data.message || data.error || "Error al guardar";
      setFieldError("fCode", msg);
      return;
    }

    mdlPeriod.hide();
    loadPeriods();
    showToast(editingId ? "Período actualizado correctamente" : "Período creado correctamente", "success");
  } catch (err) {
    // Errores 5xx o de red → toast
    console.error(err);
    showToast("Error de conexión al guardar el período", "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

// === ACTIVAR PERÍODO ===
async function activatePeriod(periodId) {
  const period = currentPeriods.find((p) => p.id === periodId);
  showConfirm(
    "Activar período",
    `¿Desactivar el período activo actual y activar "${period.name}"?`,
    async () => {
      try {
        const resp = await fetch(cfg.activate.replace("{id}", periodId), {
          method: "POST", credentials: "same-origin",
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.message || data.error || "Error al activar");
        showToast("Período activado correctamente", "success");
        loadPeriods();
      } catch (err) {
        showToast("Error al activar: " + err.message, "error");
      }
    }
  );
}

// === ELIMINAR PERÍODO ===
async function deletePeriod(periodId) {
  const period = currentPeriods.find((p) => p.id === periodId);
  showConfirm(
    "Eliminar período",
    `¿Eliminar el período "${period.name}"?\n\nEsta acción no se puede deshacer.`,
    async () => {
      try {
        const resp = await fetch(cfg.delete.replace("{id}", periodId), {
          method: "DELETE", credentials: "same-origin",
        });
        if (!resp.ok) {
          const data = await resp.json();
          throw new Error(data.message || data.error || "Error al eliminar");
        }
        showToast("Período eliminado correctamente", "success");
        loadPeriods();
      } catch (err) {
        showToast("Error al eliminar: " + err.message, "error");
      }
    }
  );
}

// === VER DETALLES ===
async function viewDetails(periodId) {
  try {
    const [periodResp, statsResp] = await Promise.all([
      fetch(cfg.detail.replace("{id}", periodId), { credentials: "same-origin" }),
      fetch(cfg.stats.replace("{id}", periodId),  { credentials: "same-origin" }),
    ]);
    if (!periodResp.ok || !statsResp.ok) throw new Error("Error al cargar detalles");

    const period = await periodResp.json();
    const stats  = await statsResp.json();

    const admissionStartDisplay = period.agendatec_config?.student_admission_start
      ? formatDateTime(period.agendatec_config.student_admission_start) : "-";
    const deadlineDisplay = period.agendatec_config?.student_admission_deadline
      ? formatDateTime(period.agendatec_config.student_admission_deadline) : "-";

    document.getElementById("detailsContent").innerHTML = `
      <div class="row g-3">
        <div class="col-12">
          <h6>Información General</h6>
          <table class="table table-sm">
            <tr><th>Código:</th><td><code>${escapeHtml(period.code || "-")}</code></td></tr>
            <tr><th>Nombre:</th><td>${escapeHtml(period.name)}</td></tr>
            <tr><th>Estado:</th><td><span class="badge text-bg-${period.status === "ACTIVE" ? "success" : "secondary"}">${period.status}</span></td></tr>
            <tr><th>Fecha Inicio:</th><td>${formatDate(period.start_date)}</td></tr>
            <tr><th>Fecha Fin:</th><td>${formatDate(period.end_date)}</td></tr>
          </table>
        </div>
        <div class="col-12">
          <h6>Ventana de Admisión</h6>
          <table class="table table-sm">
            <tr><th>Inicio Admisión:</th><td>${admissionStartDisplay}</td></tr>
            <tr><th>Fin Admisión:</th><td>${deadlineDisplay}</td></tr>
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
            ${stats.enabled_days.map((d) => `<span class="badge text-bg-primary">${formatDate(d)}</span>`).join("")}
          </div>
        </div>` : ""}
      </div>`;

    mdlDetails.show();
  } catch (err) {
    showToast("Error al cargar detalles del período: " + err.message, "error");
  }
}

function configureDays(periodId) {
  window.location.href = cfg.daysPage.replace("{id}", periodId);
}

// === UTILIDADES ===
function formatDate(dateStr) {
  if (!dateStr) return "-";
  return new Date(dateStr + "T00:00:00").toLocaleDateString("es-MX", {
    year: "numeric", month: "short", day: "numeric",
  });
}

function formatDateTime(dateTimeStr) {
  if (!dateTimeStr) return "-";
  return new Date(dateTimeStr).toLocaleString("es-MX", {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });
}

function escapeHtml(text) {
  if (!text) return "";
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
  return String(text).replace(/[&<>"']/g, (m) => map[m]);
}
