/**
 * social/home.js — Vista de consulta (solo lectura) de citas del día.
 *
 * Dependencias (cargadas antes en el template):
 *   - AgendaTec.Format   (format.js)
 *   - AgendaTec.Skeleton (skeleton.js)
 *   - AgendaTec.TableCard (table-card.js)
 *   - AgendaTec.SocketStatus (socket-status.js)
 *   - showToast (toast.js, en base.html)
 *
 * NOTE: El endpoint /api/agendatec/v2/social/appointments devuelve actualmente:
 *   { time, student_name, program_id, day }
 * Los campos no_control y carrera (nombre de programa) NO están disponibles en la
 * respuesta actual. Se documentan como TODO para extender el endpoint API.
 * TODO(backend): Extender social.py para incluir:
 *   - no_control (User.username o campo dedicado)
 *   - program_name (Program.name)
 * Mientras tanto, no_control muestra "—" y carrera muestra program_id o "—".
 */

// === ESTADO DEL MÓDULO ===
(function () {
  "use strict";

  const { Format, Skeleton, TableCard, SocketStatus } = window.AgendaTec || {};
  const esc = Format ? Format.escapeHtml : (s) => String(s || "");

  /** Sala socket a la que estamos unidos actualmente */
  let lastJoin = { day: null, program_id: null };

  /** Handler debounced de reload para eventos socket */
  const reloadDebounced = Format
    ? Format.debounce(triggerReload, 250)
    : triggerReload;

  // === MAPEO DE ESTADO → BADGE ===
  const STATUS_BADGE = {
    PENDING:     { cls: "text-bg-warning",   label: "Pendiente"   },
    VALIDATED:   { cls: "text-bg-info",      label: "Validado"    },
    ASSIGNED:    { cls: "text-bg-primary",   label: "Asignado"    },
    IN_PROGRESS: { cls: "text-bg-secondary", label: "En proceso"  },
    RESOLVED:    { cls: "text-bg-success",   label: "Resuelto"    },
    CANCELED:    { cls: "text-bg-danger",    label: "Cancelado"   },
  };

  // === INICIALIZACIÓN ===
  document.addEventListener("DOMContentLoaded", function () {
    setupEventListeners();
    loadPrograms();
    mountSocketStatus();
    wireRealtime();

    // Esperar a que home_init.js cargue los días
    document.addEventListener("socialHomeInitReady", function (e) {
      if (e.detail?.selectedDay) {
        triggerReload();
      }
    });
  });

  // === SETUP ===
  function setupEventListeners() {
    document.getElementById("btnLoadSS")
      .addEventListener("click", loadAppointments);
    document.getElementById("ssDay")
      .addEventListener("change", triggerReload);
    document.getElementById("ssProgram")
      .addEventListener("change", triggerReload);
  }

  function triggerReload() {
    document.getElementById("btnLoadSS").click();
  }

  // === INDICADOR SOCKET ===
  function mountSocketStatus() {
    SocketStatus?.mount({ anchor: "#socialHomeTitle" });
  }

  // === CARGA DE PROGRAMAS ===
  async function loadPrograms() {
    try {
      const r = await fetch("/api/agendatec/v2/programs", { credentials: "include" });
      if (!r.ok) throw new Error("programs_fetch_error");
      const data = await r.json();
      const sel = document.getElementById("ssProgram");
      const opts = ['<option value="">Todas</option>'].concat(
        (data.items || []).map(
          (p) => `<option value="${p.id}">${esc(p.name)}</option>`
        )
      );
      sel.innerHTML = opts.join("");
    } catch {
      showToast?.("No se pudieron cargar las carreras.", "warning");
    }
  }

  // === CARGA DE CITAS ===
  async function loadAppointments() {
    const day       = document.getElementById("ssDay").value;
    const programId = document.getElementById("ssProgram").value;
    const btn       = document.getElementById("btnLoadSS");
    const container = document.getElementById("ssList");

    if (!day) return;

    // Skeleton durante fetch
    btn.disabled = true;
    container.innerHTML = buildSkeletonTable();

    // Gestión de sala socket
    try {
      if (lastJoin.day) {
        window.__socialLeaveApDay?.({ day: lastJoin.day, program_id: lastJoin.program_id || null });
      }
      window.__socialJoinApDay?.({ day, program_id: programId || null });
      lastJoin = { day, program_id: programId || null };
    } catch { /* sala socket no crítica */ }

    const url = new URL("/api/agendatec/v2/social/appointments", window.location.origin);
    url.searchParams.set("day", day);
    if (programId) url.searchParams.set("program_id", programId);

    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      renderTable(data.items || []);
    } catch {
      showToast?.("Error al cargar citas.", "danger");
      container.innerHTML = buildEmptyState("Error al cargar citas. Intenta de nuevo.");
    } finally {
      btn.disabled = false;
    }
  }

  // === SKELETON ===
  function buildSkeletonTable() {
    const rows = Skeleton ? Skeleton.tableRows(5, 5) : "";
    return `
      <table class="table table-sm align-middle"
             data-at-table="card"
             aria-label="Citas del día — cargando">
        <thead>
          <tr>
            <th data-at-label="Horario">Horario</th>
            <th data-at-label="No. Control">No. Control</th>
            <th data-at-label="Nombre">Nombre</th>
            <th data-at-label="Carrera">Carrera</th>
            <th data-at-label="Estado">Estado</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  // === RENDER TABLA ===
  function renderTable(items) {
    const container = document.getElementById("ssList");

    if (!items.length) {
      container.innerHTML = buildEmptyState("Sin citas para este día.");
      return;
    }

    const tbody = items.map((it) => {
      const statusInfo = STATUS_BADGE[it.status] || { cls: "text-bg-secondary", label: esc(it.status || "—") };
      // TODO(backend): no_control y program_name aún no vienen en la respuesta del endpoint.
      // Ver social.py — extender para incluir User.username como no_control y Program.name como program_name.
      const noControl   = it.no_control    ? esc(it.no_control)    : "—";
      const programName = it.program_name  ? esc(it.program_name)  : "—";
      return `
        <tr>
          <td>${esc(it.time || "—")}</td>
          <td>${noControl}</td>
          <td>${esc(it.student_name || "—")}</td>
          <td>${programName}</td>
          <td><span class="badge ${statusInfo.cls}">${statusInfo.label}</span></td>
        </tr>`;
    }).join("");

    container.innerHTML = `
      <table class="table table-sm align-middle"
             data-at-table="card"
             aria-label="Citas del día">
        <thead>
          <tr>
            <th data-at-label="Horario">Horario</th>
            <th data-at-label="No. Control">No. Control</th>
            <th data-at-label="Nombre">Nombre</th>
            <th data-at-label="Carrera">Carrera</th>
            <th data-at-label="Estado">Estado</th>
          </tr>
        </thead>
        <tbody>${tbody}</tbody>
      </table>`;

    // Sincronizar labels para modo card mobile
    const table = container.querySelector("table");
    if (table && TableCard) {
      TableCard.syncLabels(table);
    }
  }

  // === EMPTY STATE ===
  function buildEmptyState(msg) {
    return `
      <div class="at-empty py-4" role="status" aria-live="polite">
        <i class="bi bi-eye-slash at-empty__icon" aria-hidden="true"></i>
        <p class="at-empty__message mb-0">${esc(msg)}</p>
      </div>`;
  }

  // === REALTIME (Socket.IO) ===
  function wireRealtime() {
    const tryBind = () => {
      const s = window.__reqSocket;
      if (!s) return setTimeout(tryBind, 500);

      s.off?.("appointment_created");
      s.off?.("request_status_changed");

      const matchesFilter = (payload) => {
        if (payload?.type !== "APPOINTMENT") return false;
        const day = document.getElementById("ssDay").value;
        const programId = document.getElementById("ssProgram").value;
        if (payload.day && payload.day !== day) return false;
        if (programId && Number(payload.program_id || 0) !== Number(programId)) return false;
        return true;
      };

      s.on("appointment_created", (p) => {
        const payload = { type: "APPOINTMENT", day: p?.slot_day, program_id: p?.program_id };
        if (matchesFilter(payload)) reloadDebounced();
      });

      s.on("request_status_changed", (p) => {
        if (matchesFilter(p)) reloadDebounced();
      });
    };
    tryBind();
  }

})();
