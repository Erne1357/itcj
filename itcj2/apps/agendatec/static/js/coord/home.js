/**
 * coord/home.js
 * Panel de inicio del coordinador.
 * Carga KPIs del dashboard, recordatorios de slots sin configurar,
 * conecta al socket y monta indicador de conexión.
 */

// === ESTADO DEL MÓDULO ===
let _lastCoordId = 0;
let _lastDays = [];
let _roomsBound = false;

const escapeHtml = window.AgendaTec.Format.escapeHtml;
const debounce   = window.AgendaTec.Format.debounce;
const Skeleton   = window.AgendaTec.Skeleton;

// === INICIALIZACIÓN ===
document.addEventListener("DOMContentLoaded", function () {
  // Skeleton KPIs inmediato
  const kpisEl = document.getElementById("dashKpis");
  if (kpisEl) kpisEl.innerHTML = Skeleton.kpis(2);

  loadDashboard();

  // Indicador de conexión socket
  window.AgendaTec.SocketStatus.mount({ anchor: "#currentPeriod" });
});

// === CARGA DE DATOS ===
async function loadDashboard() {
  try {
    const r = await fetch("/api/agendatec/v2/coord/dashboard", { credentials: "include" });
    if (!r.ok) throw new Error("error");
    const data = await r.json();

    // Período
    const periodNameEl = document.getElementById("periodName");
    if (data?.period?.name && periodNameEl) {
      periodNameEl.textContent = data.period.name;
    }

    // Render KPIs
    renderKpis(data);

    // Recordatorios
    renderReminders(data?.missing_slots || []);

    // Sockets
    tryJoinRoomsOnce(data?.days_allowed || [], data?.current_coordinator_id);
  } catch (e) {
    console.error("[home] error load", e);
    const periodNameEl = document.getElementById("periodName");
    if (periodNameEl) periodNameEl.textContent = "Error al cargar";
    renderKpisError();
  }
}

// === RENDER KPIs ===
function renderKpis(data) {
  const kpisEl = document.getElementById("dashKpis");
  if (!kpisEl) return;

  const apTotal   = data?.appointments?.total   ?? "0";
  const apPending = data?.appointments?.pending  ?? "0";
  const drTotal   = data?.drops?.total           ?? "0";
  const drPending = data?.drops?.pending         ?? "0";

  kpisEl.innerHTML = `
    <div class="col-12 col-md-6">
      <div class="at-kpi at-kpi--accent h-100">
        <div class="at-kpi__label">
          <a href="/agendatec/coord/appointments" class="text-decoration-none text-reset">
            <i class="bi bi-calendar-check me-1" aria-hidden="true"></i> Citas
          </a>
        </div>
        <div class="d-flex gap-3 mt-1">
          <div class="flex-fill">
            <div class="at-stat-label">Total</div>
            <div class="at-kpi__value" id="kpiApTotal">${escapeHtml(String(apTotal))}</div>
          </div>
          <div class="flex-fill">
            <div class="at-stat-label">Pendientes</div>
            <div class="at-kpi__value ${Number(apPending) > 0 ? 'at-kpi__value--warning' : ''}" id="kpiApPending">${escapeHtml(String(apPending))}</div>
          </div>
        </div>
      </div>
    </div>
    <div class="col-12 col-md-6">
      <div class="at-kpi at-kpi--success h-100">
        <div class="at-kpi__label">
          <a href="/agendatec/coord/drops" class="text-decoration-none text-reset">
            <i class="bi bi-arrow-down-circle me-1" aria-hidden="true"></i> Bajas
          </a>
        </div>
        <div class="d-flex gap-3 mt-1">
          <div class="flex-fill">
            <div class="at-stat-label">Total</div>
            <div class="at-kpi__value" id="kpiDropTotal">${escapeHtml(String(drTotal))}</div>
          </div>
          <div class="flex-fill">
            <div class="at-stat-label">Pendientes</div>
            <div class="at-kpi__value ${Number(drPending) > 0 ? 'at-kpi__value--warning' : ''}" id="kpiDropPending">${escapeHtml(String(drPending))}</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderKpisError() {
  const kpisEl = document.getElementById("dashKpis");
  if (!kpisEl) return;
  kpisEl.innerHTML = `
    <div class="col-12">
      <div class="at-empty">
        <i class="bi bi-exclamation-triangle at-empty__icon" aria-hidden="true"></i>
        <p class="at-empty__message">No se pudieron cargar los datos del panel.</p>
      </div>
    </div>`;
}

// === RENDER RECORDATORIOS ===
function renderReminders(missingDays) {
  const el = document.getElementById("reminderList");
  if (!el) return;

  if (!missingDays.length) {
    el.className = "";
    el.innerHTML = `
      <div class="at-empty py-3">
        <i class="bi bi-check2-circle at-empty__icon" aria-hidden="true"></i>
        <p class="at-empty__message">Todo configurado</p>
      </div>`;
    return;
  }

  el.className = "at-stagger at-reminder-list";
  const items = missingDays.slice(0, 5).map(d => `
    <div class="at-reminder-item">
      <div class="at-reminder-item__text">
        <i class="bi bi-exclamation-triangle text-warning" aria-hidden="true"></i>
        <span>Falta configurar horario para <strong>${escapeHtml(d)}</strong></span>
      </div>
      <a class="btn btn-sm btn-outline-primary" href="/agendatec/coord/slots#${encodeURIComponent(d)}">
        <i class="bi bi-gear me-1" aria-hidden="true"></i>Configurar
      </a>
    </div>
  `).join("");
  el.innerHTML = items;
}

// === SOCKETS ===
const scheduleReload = debounce(() => loadDashboard(), 250);

function joinRooms(coordId, daysAllowed) {
  window.__reqJoinDrops?.({ coord_id: coordId });
  (daysAllowed || []).forEach(day => {
    window.__reqJoinApDay?.({ coord_id: coordId, day });
  });
}

function tryJoinRoomsOnce(daysAllowed, coordEntityId) {
  const coordId = coordEntityId || 0;
  const s = window.__reqSocket;
  if (!coordId || !s) return;

  _lastCoordId = coordId;
  _lastDays    = daysAllowed || [];
  joinRooms(coordId, daysAllowed);

  if (!_roomsBound) {
    s.off?.("appointment_created");
    s.off?.("drop_created");
    s.off?.("request_status_changed");
    s.on("appointment_created",    () => scheduleReload());
    s.on("drop_created",           () => scheduleReload());
    s.on("request_status_changed", () => scheduleReload());
    s.on("connect", () => {
      if (_lastCoordId) joinRooms(_lastCoordId, _lastDays);
    });
    _roomsBound = true;
  }
}
