/**
 * coord/slots_view.js
 * Vista visual del día en /coord/slots (KPIs + tira + tabla) con refresh en vivo.
 * Mapea estados de slot a at-slot-chip--{estado} (5 estados semánticos).
 * Expone window.__slotsRefresh para que slots.js llame tras guardar config.
 */

(function () {
  "use strict";

  const escapeHtml   = window.AgendaTec.Format.escapeHtml;
  const Skeleton     = window.AgendaTec.Skeleton;
  const TableCard    = window.AgendaTec.TableCard;

  // === ELEMENTOS ===
  const daySel   = document.getElementById("cfgDay");
  const dayDel   = document.getElementById("cfgDayDel");
  const kpiTotal = document.getElementById("kpiTotal");
  const kpiFree  = document.getElementById("kpiFree");
  const kpiBooked = document.getElementById("kpiBooked");
  const kpiWins  = document.getElementById("kpiWindows");
  const strip    = document.getElementById("dayStrip");
  const tbody    = document.getElementById("dayTableBody");
  const titleView = document.getElementById("titleView");

  if (!daySel || !strip || !tbody) return;

  // Modal de detalle de slot
  const slotDetailBody  = document.getElementById("slotDetailBody");
  const slotDetailModal = document.getElementById("slotDetailModal")
    ? new bootstrap.Modal(document.getElementById("slotDetailModal"))
    : null;

  // Helper sockets
  const slotsSock = () => window.__slotsSocket;

  // === HELPERS ===
  function fmtName(stu) {
    if (!stu) return "—";
    const n = stu.full_name || "—";
    const c = stu.control_number || stu.username || "";
    return c ? `${escapeHtml(n)} (${escapeHtml(c)})` : escapeHtml(n);
  }

  /**
   * Determina el estado semántico del chip a partir de los datos del slot.
   * Devuelve una de: available | reserved | taken | no-show | disabled
   */
  function resolveChipState(slot) {
    // Slot sin cita
    if (!slot.appointment) {
      if (slot.status === "DISABLED") return "disabled";
      // hold de Redis se indica con slot.is_held o appointment_id sin datos completos
      if (slot.is_held) return "reserved";
      return "available";
    }
    const st = slot.appointment.request_status || "";
    if (st === "RESOLVED_SUCCESS")        return "taken";
    if (st === "NO_SHOW" || st === "RESOLVED_NOT_COMPLETED") return "no-show";
    if (st === "CANCELED")                return "available";
    // PENDING / ASSIGNED / IN_PROGRESS / VALIDATED → reservado
    return "reserved";
  }

  // === SKELETON EN STRIP + TABLA ===
  function showLoadingSkeleton() {
    if (strip) {
      strip.innerHTML = Array.from({ length: 8 }, () =>
        `<div class="at-slot-chip at-slot-chip--available">
           <span class="at-skeleton at-skeleton--line" style="width:80px"></span>
         </div>`
      ).join("");
    }
    if (tbody) {
      tbody.innerHTML = Skeleton.tableRows(4, 4);
    }
  }

  // === CARGA Y RENDER ===
  async function loadAndRender(day) {
    if (!day) return;
    showLoadingSkeleton();
    await loadWindowsKpi(day);
    if (titleView) {
      titleView.textContent = "Vista del día — " + window.AgendaTec.Format.formatDayLabel(day);
    }
    const slots = await loadSlotsWithAppointments(day);
    render(slots);
  }

  async function loadWindowsKpi(day) {
    try {
      const url = new URL("/api/agendatec/v2/coord/day-config", window.location.origin);
      url.searchParams.set("day", day);
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      if (kpiWins) kpiWins.textContent = (data.items || []).length;
    } catch {
      if (kpiWins) kpiWins.textContent = "—";
    }
  }

  async function loadSlotsWithAppointments(day) {
    try {
      const url = new URL("/api/agendatec/v2/coord/appointments", window.location.origin);
      url.searchParams.set("day", day);
      url.searchParams.set("include_empty", "1");
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      return data.slots || [];
    } catch {
      return [];
    }
  }

  function render(slots) {
    const total  = slots.length;
    const booked = slots.filter(s => !!s.appointment).length;
    const free   = total - booked;

    if (kpiTotal)  kpiTotal.textContent  = total;
    if (kpiBooked) kpiBooked.textContent = booked;
    if (kpiFree)   kpiFree.textContent   = free;

    renderStrip(slots);
    renderTable(slots);
  }

  // === TIRA DE CHIPS ===
  function renderStrip(slots) {
    if (!strip) return;
    strip.innerHTML = "";

    if (!slots.length) {
      strip.innerHTML = `
        <div class="at-empty py-3">
          <i class="bi bi-grid at-empty__icon" aria-hidden="true"></i>
          <p class="at-empty__title">No hay slots configurados para este día</p>
          <div class="at-empty__cta">
            <a href="#dayConfigForm" class="btn btn-sm btn-outline-primary"
               onclick="document.getElementById('dayConfigForm').scrollIntoView({behavior:'smooth'});return false;">
              Configurar horario
            </a>
          </div>
        </div>`;
      return;
    }

    for (const s of slots) {
      const state = resolveChipState(s);
      const who   = s.appointment
        ? (s.appointment.student?.full_name || "Reservado")
        : (state === "disabled" ? "No disponible" : "Libre");

      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `at-slot-chip at-slot-chip--${state} at-slot-chip--interactive`;
      chip.setAttribute("data-slot-id", s.id || "");
      chip.setAttribute("title", `${s.start}–${s.end} · ${who}`);
      chip.setAttribute("aria-label", `Horario ${s.start} a ${s.end} — ${who}`);

      chip.innerHTML = `<span class="at-slot-chip__time">${escapeHtml(s.start)}–${escapeHtml(s.end)}</span>`;

      // Click → mini-modal con detalle
      chip.addEventListener("click", () => openSlotDetail(s));
      strip.appendChild(chip);
    }
  }

  // === TABLA ===
  function renderTable(slots) {
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!slots.length) return;

    const table = document.getElementById("dayTable");

    for (const s of slots) {
      const ap     = s.appointment;
      const state  = resolveChipState(s);
      const who    = ap ? fmtName(ap.student) : "—";
      const prog   = ap ? escapeHtml(ap.program?.name || "—") : "—";

      const stateLabels = {
        available: '<span class="badge text-bg-secondary">Libre</span>',
        reserved:  '<span class="badge text-bg-primary">Reservado</span>',
        taken:     '<span class="badge text-bg-success">Atendida</span>',
        "no-show": '<span class="badge text-bg-danger">No asistió</span>',
        disabled:  '<span class="badge text-bg-light text-muted">No disponible</span>',
      };

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(s.start)}–${escapeHtml(s.end)}</td>
        <td>${stateLabels[state] || ""}</td>
        <td>${who}</td>
        <td>${prog}</td>
      `;
      tbody.appendChild(tr);
    }

    // Sincronizar labels para table→card en mobile
    if (table) TableCard.syncLabels(table);
  }

  // === MINI-MODAL DETALLE DE SLOT ===
  function openSlotDetail(slot) {
    if (!slotDetailBody || !slotDetailModal) return;

    const ap = slot.appointment;
    if (!ap) {
      slotDetailBody.innerHTML = `
        <div class="mb-1"><strong>Horario:</strong> ${escapeHtml(slot.start)}–${escapeHtml(slot.end)}</div>
        <div class="text-muted">Sin cita asignada.</div>`;
    } else {
      const alumno = fmtName(ap.student);
      const prog   = escapeHtml(ap.program?.name || "—");
      const estado = escapeHtml(ap.request_status || "—");
      slotDetailBody.innerHTML = `
        <div class="mb-1"><strong>Horario:</strong> ${escapeHtml(slot.start)}–${escapeHtml(slot.end)}</div>
        <div class="mb-1"><strong>Alumno:</strong> ${alumno}</div>
        <div class="mb-1"><strong>Carrera:</strong> ${prog}</div>
        <div class="mb-1"><strong>Estado:</strong> ${estado}</div>
        ${ap.description ? `<div class="mb-1"><strong>Desc:</strong> ${escapeHtml(ap.description)}</div>` : ""}
      `;
    }
    slotDetailModal.show();
  }

  // === CAMBIO DE DÍA ===
  function currentDay() { return daySel.value; }

  function onDayChange() {
    const d = currentDay();
    if (!d) return;
    joinDayRoomsWhenSocketReady(d);
    loadAndRender(d);
    if (dayDel) dayDel.value = d;
  }

  // === SOCKETS ===
  function joinDayRooms(day) {
    if (typeof window.__joinDay === "function") window.__joinDay(day);
  }

  function joinDayRoomsWhenSocketReady(day) {
    function tryJoin() {
      const s = slotsSock();
      if (s && s.connected) joinDayRooms(day);
      else setTimeout(tryJoin, 400);
    }
    tryJoin();
  }

  (function wireSocketRefresh() {
    const s = slotsSock();
    if (!s) { setTimeout(wireSocketRefresh, 500); return; }

    s.off?.("slots_window_changed");
    s.off?.("slot_booked");
    s.off?.("slot_released");

    const refreshIfDay = (payloadDay) => {
      const d = currentDay();
      if (!d || payloadDay !== d) return;
      loadAndRender(d);
    };

    s.on("slots_window_changed", (p) => refreshIfDay(p?.day));
    s.on("slot_booked",          (p) => refreshIfDay(p?.day));
    s.on("slot_released",        (p) => refreshIfDay(p?.day));
  })();

  // === EVENT LISTENERS ===
  daySel.addEventListener("change", onDayChange);

  // Evento de slots_init.js cuando los días están listos
  document.addEventListener("slotsInitReady", (e) => {
    const d = e.detail?.selectedDay;
    if (d) {
      joinDayRoomsWhenSocketReady(d);
      loadAndRender(d);
      if (dayDel) dayDel.value = d;
    }
  });

  // === EXPOSICIÓN GLOBAL para que slots.js llame tras guardar ===
  window.__slotsRefresh = loadAndRender;

})();
