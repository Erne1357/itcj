/**
 * AgendaTec — Student / request.js
 * Wizard de nueva solicitud: tipo → carrera → detalles → horario.
 * Usa .at-slot, .at-stepper, Skeleton.cards(), at-empty, ARIA, hold countdown.
 */

(() => {
  "use strict";

  // === ALIAS LOCALES ===
  const escapeHtml = (s) => window.AgendaTec.Format.escapeHtml(s);
  const Skeleton   = window.AgendaTec.Skeleton;

  // === ESTADO ===
  let enabledDays = [];

  const state = {
    type        : null,   // DROP | APPOINTMENT | BOTH
    program_id  : null,
    day         : null,
    slot_id     : null,
    description : null,
    selectedHour: null,
    currentRoom : null,
    periodLoaded: false,
  };

  // Variables de socket / hold
  let btnById            = new Map();
  let heldByMe           = null;
  let pendingHold        = null;
  let countdownInt       = null;
  let countdownLeft      = 0;
  let holdBar            = null;
  let socketEventsRegistered = false;

  // === ELEMENTOS DEL DOM ===
  const stepType      = document.getElementById("stepType");
  const stepProgram   = document.getElementById("stepProgram");
  const stepForms     = document.getElementById("stepForms");
  const stepCalendar  = document.getElementById("stepCalendar");
  const stepConfirm   = document.getElementById("stepConfirm");
  const programSelect = document.getElementById("programSelect");
  const coordCard     = document.getElementById("coordCard");
  const coordName     = document.getElementById("coordName");
  const coordEmail    = document.getElementById("coordEmail");
  const coordHours    = document.getElementById("coordHours");
  const careerName    = document.getElementById("careerName");
  const typeHint      = document.getElementById("typeHint");
  const confirmSummary= document.getElementById("confirmSummary");
  const confirmStepTitle = document.getElementById("confirmStepTitle");
  const calendarNextWrap = document.getElementById("calendarNextWrap");
  const btnNextFromCalendar = document.getElementById("btnNextFromCalendar");
  const btnBackFromConfirm  = document.getElementById("btnBackFromConfirm");
  const wizardSteps   = document.getElementById("wizardSteps");

  // === FLOW (orden de stages por tipo) ===
  const FLOW_DEFAULT = [
    { id: "type",    label: "Tipo" },
    { id: "program", label: "Carrera" },
    { id: "forms",   label: "Detalles" },
    { id: "confirm", label: "Confirmar" },
  ];
  const FLOW_APPT = [
    { id: "type",    label: "Tipo" },
    { id: "program", label: "Carrera" },
    { id: "forms",   label: "Detalles" },
    { id: "calendar",label: "Horario" },
    { id: "confirm", label: "Confirmar" },
  ];
  const getFlow = () => (state.type && state.type !== "DROP" ? FLOW_APPT : FLOW_DEFAULT);

  // Mapa id → elemento card
  const stageEl = {
    type:     stepType,
    program:  stepProgram,
    forms:    stepForms,
    calendar: stepCalendar,
    confirm:  stepConfirm,
  };

  let currentStageIdx = 0;

  // Smooth scroll a un elemento (respeta prefers-reduced-motion).
  const scrollToEl = (el) => {
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
  };

  const altaFields  = document.getElementById("altaFields");
  const bajaFields  = document.getElementById("bajaFields");
  const altaMateria = document.getElementById("altaMateria");
  const altaNoSe    = document.getElementById("altaNoSe");
  const altaHorario = document.getElementById("altaHorario");
  const bajaMateria = document.getElementById("bajaMateria");
  const bajaHorario = document.getElementById("bajaHorario");

  const calendarBlock = document.getElementById("calendarBlock");
  const slotsWrap     = document.getElementById("slotsWrap");
  const slotGrid      = document.getElementById("slotGrid");

  const btnConfirmForms = document.getElementById("btnConfirmForms");
  const btnSubmit       = document.getElementById("btnSubmit");
  const actionBar       = document.getElementById("actionBar");
  const btnBack         = document.getElementById("btnBack");

  // === STEPPER DINAMICO ===

  /**
   * Reconstruye el stepper segun el flow vigente (depende del tipo).
   * Marca activo el stage en indice `activeIdx` y previos como done.
   */
  function renderStepper(activeIdx) {
    const flow = getFlow();
    const frag = document.createDocumentFragment();

    flow.forEach((stage, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "at-stepper__step";
      btn.dataset.stageIdx = String(i);
      btn.dataset.stageId  = stage.id;
      btn.disabled = true;

      if (i < activeIdx) {
        btn.classList.add("at-stepper__step--done", "at-stepper__step--clickable");
        btn.disabled = false;
        btn.addEventListener("click", () => goToStage(i));
      } else if (i === activeIdx) {
        btn.classList.add("at-stepper__step--active");
        btn.setAttribute("aria-current", "step");
      }

      btn.innerHTML = `
        <span class="at-stepper__bullet">${i + 1}</span>
        <span class="at-stepper__label">${stage.label}</span>
      `;
      frag.appendChild(btn);

      if (i < flow.length - 1) {
        const conn = document.createElement("span");
        conn.className = "at-stepper__connector";
        conn.setAttribute("aria-hidden", "true");
        if (i < activeIdx) conn.classList.add("at-stepper__connector--done");
        frag.appendChild(conn);
      }
    });

    wizardSteps.innerHTML = "";
    wizardSteps.appendChild(frag);
  }

  /**
   * Muestra el stage indicado (por indice en el flow vigente).
   * Oculta los demas cards y actualiza el stepper.
   */
  function showStage(targetIdx) {
    const flow = getFlow();
    if (targetIdx < 0) targetIdx = 0;
    if (targetIdx >= flow.length) targetIdx = flow.length - 1;
    currentStageIdx = targetIdx;

    const targetId = flow[targetIdx].id;

    // Ocultar todos los cards de stage.
    Object.values(stageEl).forEach((el) => { if (el) el.hidden = true; });

    // Mostrar el target con animacion.
    const el = stageEl[targetId];
    if (el) {
      el.hidden = false;
      el.classList.remove("at-step-enter");
      void el.offsetWidth;
      el.classList.add("at-step-enter");
      scrollToEl(el);
    }

    // Renderizar stepper con el indice activo.
    renderStepper(targetIdx);

    // ActionBar / next-from-calendar segun stage.
    if (actionBar) actionBar.hidden = targetId !== "confirm";
    if (calendarNextWrap) calendarNextWrap.hidden = targetId !== "calendar" || !heldByMe;

    // Cuando entramos a "confirm" generamos el resumen y habilitamos submit.
    if (targetId === "confirm") {
      buildSummary();
      const flowIdx = flow.findIndex(f => f.id === "confirm");
      if (confirmStepTitle) confirmStepTitle.textContent = `${flowIdx + 1}) Revisa y confirma`;
    }
    updateSubmitDisabled();
  }

  /**
   * Navega a un stage previo (al hacer click en stepper).
   * Limpia datos posteriores y libera hold si corresponde.
   */
  function goToStage(targetIdx) {
    const flow = getFlow();
    const targetId = flow[targetIdx].id;

    // Si retrocedemos antes del calendar, liberar hold.
    if (targetId !== "calendar" && targetId !== "confirm" && heldByMe) {
      emitSocket("release_hold", { slot_id: heldByMe });
      releaseLocal();
    }

    // Resetear estado segun el stage destino.
    if (targetId === "type") {
      state.type        = null;
      state.program_id  = null;
      state.description = null;
      state.day         = null;
      state.slot_id     = null;
      if (programSelect) programSelect.value = "";
      if (coordCard) coordCard.hidden = true;
      document.querySelectorAll(".at-type-card[data-type]").forEach((c) => {
        c.classList.remove("at-type-card--active");
        c.setAttribute("aria-pressed", "false");
      });
      if (typeHint) typeHint.textContent = "";
    } else if (targetId === "program") {
      state.program_id  = null;
      state.description = null;
      state.day         = null;
      state.slot_id     = null;
      if (programSelect) programSelect.value = "";
      if (coordCard) coordCard.hidden = true;
    } else if (targetId === "forms") {
      state.description = null;
      state.day         = null;
      state.slot_id     = null;
    }

    showStage(targetIdx);
  }

  // Render inicial del stepper (flow default, stage 0 activo).
  renderStepper(0);

  // Inicialmente ocultar btnSubmit
  btnSubmit.hidden = true;

  // === BOTÓN REGRESAR CON CONFIRMACIÓN ===
  btnBack.addEventListener("click", async () => {
    const hasDatos = state.type || state.program_id || state.description;
    const dest = btnBack.dataset.href ||
      document.querySelector('a[href*="student_home"]')?.href || "/agendatec/student/home";
    if (!hasDatos) {
      window.location.href = dest;
      return;
    }
    const ok = await AppModal.confirm({
      title: "Salir sin guardar",
      message: "Perderás los datos ingresados en esta solicitud. ¿Continuar?",
      confirmText: "Sí, salir",
      confirmVariant: "danger",
      cancelText: "Permanecer",
      variant: "warning",
    });
    if (ok) {
      if (heldByMe) emitSocket("release_hold", { slot_id: heldByMe });
      window.location.href = dest;
    }
  });

  // === SOCKET HELPERS ===
  const getSocket = () => window.__slotsSocket;

  const emitSocket = (event, payload) => {
    const socket = getSocket();
    if (socket && socket.connected) {
      socket.emit(event, payload);
    } else {
      console.warn(`[WS] No se puede emitir ${event}, socket no disponible`);
    }
  };

  const waitForSocket = (maxWait = 5000) => {
    return new Promise((resolve, reject) => {
      const socket = getSocket();
      if (socket && socket.connected) { resolve(socket); return; }
      let waited = 0;
      const interval = setInterval(() => {
        const s = getSocket();
        waited += 100;
        if (s && s.connected) { clearInterval(interval); resolve(s); }
        else if (waited >= maxWait) { clearInterval(interval); reject(new Error("Socket timeout")); }
      }, 100);
    });
  };

  const joinDay = async (day) => {
    try {
      await waitForSocket();
      if (state.currentRoom && state.currentRoom !== day) {
        emitSocket("leave_day", { day: state.currentRoom });
      }
      emitSocket("join_day", { day });
      state.currentRoom = day;
    } catch (error) {
      console.error("[WS] Error al hacer join:", error);
      showToast("Error de conexión con el servidor", "warn");
    }
  };

  // === COUNTDOWN Y HOLD ===

  const getSlotButton = (slotId) => {
    const id = Number(slotId);
    return btnById.get(id) || document.querySelector(`.at-slot[data-slot="${id}"]`) || null;
  };

  /**
   * Inicia el countdown visual: actualiza el badge .at-slot__countdown dentro del chip
   * y el timer en el holdBar como redundancia.
   */
  const startCountdown = (ttl) => {
    if (countdownInt) clearInterval(countdownInt);
    countdownLeft = ttl || 0;

    const tick = () => {
      // Actualizar holdBar
      const holdTimerEl = holdBar?.querySelector(".slot-hold-timer");
      if (holdTimerEl) {
        holdTimerEl.textContent = countdownLeft > 0
          ? `Reserva temporal: ${countdownLeft}s`
          : "Reserva expirada";
      }

      // Actualizar countdown dentro del chip held-self
      if (heldByMe && btnById.has(heldByMe)) {
        const chip = btnById.get(heldByMe);
        let span = chip.querySelector(".at-slot__countdown");
        if (span && countdownLeft > 0) {
          span.textContent = `${countdownLeft}s`;
        } else if (span && countdownLeft <= 0) {
          span.textContent = "";
        }
      }

      if (countdownLeft <= 0) {
        clearInterval(countdownInt);
        releaseLocal();
      }
      countdownLeft -= 1;
    };

    tick();
    countdownInt = setInterval(tick, 1000);
  };

  const releaseLocal = () => {
    if (heldByMe && btnById.has(heldByMe)) {
      const b = btnById.get(heldByMe);
      b.classList.remove("at-slot--held-self", "at-slot--reserved", "at-slot--taken");
      b.disabled = false;
      // quitar countdown span
      const span = b.querySelector(".at-slot__countdown");
      if (span) span.remove();
      // restaurar aria-label de disponible
      const label = b.querySelector(".at-slot__label")?.textContent || "";
      if (label) b.setAttribute("aria-label", `${label} — disponible`);
    }
    heldByMe = null;
    state.slot_id = null;
    if (holdBar) holdBar.hidden = true;
    if (calendarNextWrap) calendarNextWrap.hidden = true;
    updateSubmitDisabled();
  };

  // === REGISTRO DE EVENTOS SOCKET ===
  const registerSocketEvents = () => {
    if (socketEventsRegistered) return;
    const socket = getSocket();
    if (!socket) return;

    socket.off("slots_snapshot");
    socket.off("slot_held");
    socket.off("slot_released");
    socket.off("slot_booked");
    socket.off("hold_slot_ack");
    socket.off("release_hold_ack");
    socket.off("slots_window_changed");

    socket.on("slots_snapshot", (snap) => {
      if (!snap || snap.day !== state.day) return;
      (snap.booked || []).forEach((id) => {
        const btn = getSlotButton(id);
        if (btn) { btn.classList.add("at-slot--taken"); btn.disabled = true; }
      });
      (snap.held || []).forEach(({ slot_id }) => {
        const btn = getSlotButton(slot_id);
        if (btn && !btn.classList.contains("at-slot--held-self")) {
          btn.classList.add("at-slot--reserved");
          btn.disabled = true;
        }
      });
    });

    socket.on("slot_held", ({ slot_id, day }) => {
      if (day !== state.day) return;
      const btn = getSlotButton(slot_id);
      if (!btn || btn.classList.contains("at-slot--held-self")) return;
      btn.classList.add("at-slot--reserved");
      btn.disabled = true;
    });

    socket.on("slot_released", ({ slot_id, day }) => {
      if (day !== state.day) return;
      const btn = getSlotButton(slot_id);
      if (!btn) return;
      btn.classList.remove("at-slot--reserved", "at-slot--held-self", "at-slot--taken");
      btn.disabled = false;
      btn.hidden = false;
      if (heldByMe === Number(slot_id)) releaseLocal();
    });

    socket.on("slots_window_changed", (p) => {
      if (p?.day === state.day) loadSlots();
    });

    socket.on("slot_booked", ({ slot_id, day }) => {
      if (day !== state.day) return;
      const btn = getSlotButton(slot_id);
      if (btn) { btn.classList.add("at-slot--taken"); btn.disabled = true; btn.hidden = true; }
      if (heldByMe === Number(slot_id)) {
        releaseLocal();
        showToast("El horario fue reservado con éxito.", "success");
      }
    });

    socket.on("hold_slot_ack", (resp) => {
      if (!resp) return;
      if (!resp.ok) {
        const msgs = {
          already_held    : "Este horario está temporalmente ocupado.",
          slot_not_found  : "El horario ya no está disponible.",
        };
        showToast(msgs[resp.error] || "No se pudo seleccionar el horario.", "error");
        return;
      }
      const slotId = Number(resp.slot_id);
      const ttl    = Number(resp.ttl || 0);

      // Liberar hold anterior visualmente
      if (heldByMe && heldByMe !== slotId && btnById.has(heldByMe)) {
        const old = btnById.get(heldByMe);
        old.classList.remove("at-slot--held-self");
        old.disabled = false;
        const oldSpan = old.querySelector(".at-slot__countdown");
        if (oldSpan) oldSpan.remove();
      }

      const btn = btnById.get(slotId);
      if (btn) {
        btn.classList.add("at-slot--held-self");
        btn.disabled = true;
        // Añadir countdown badge dentro del chip
        let span = btn.querySelector(".at-slot__countdown");
        if (!span) {
          span = document.createElement("span");
          span.className = "at-slot__countdown";
          span.setAttribute("aria-live", "off");
          btn.appendChild(span);
        }
        span.textContent = `${ttl}s`;
        // Actualizar aria-label
        const label = btn.querySelector(".at-slot__label")?.textContent || "";
        if (label) btn.setAttribute("aria-label", `${label} — seleccionado`);
      }

      heldByMe = slotId;
      state.slot_id = slotId;
      if (holdBar) holdBar.hidden = false;
      // Slot reservado → mostrar boton "Continuar" para avanzar al confirm.
      if (calendarNextWrap) calendarNextWrap.hidden = false;
      startCountdown(ttl);
      updateSubmitDisabled();
    });

    socket.on("release_hold_ack", (resp) => {
      if (resp?.ok && pendingHold) {
        const next = pendingHold;
        pendingHold = null;
        emitSocket("hold_slot", { slot_id: next });
      }
    });

    socketEventsRegistered = true;
  };

  // === CARGA DE PERÍODO ACTIVO ===
  async function loadActivePeriod() {
    try {
      const r = await fetch("/api/agendatec/v2/periods/active", { credentials: "include" });
      if (!r.ok) throw new Error("No hay período activo");
      const data = await r.json();
      enabledDays = (data.enabled_days || []).sort();
      state.periodLoaded = true;
      renderDayButtons();
    } catch (error) {
      console.error("Error al cargar período activo:", error);
      showToast("No hay período activo disponible. Contacta al administrador.", "error");
      state.periodLoaded = false;
    }
  }

  // === RENDER BOTONES DE DÍAS ===
  function renderDayButtons() {
    const container = document.querySelector(".day-buttons-container");
    if (!container) return;

    if (!enabledDays.length) {
      container.innerHTML = '<p class="text-muted text-center">No hay días habilitados en el período actual.</p>';
      return;
    }

    container.innerHTML = enabledDays.map((day) => {
      const d = new Date(day + "T00:00:00");
      const dayName  = d.toLocaleDateString("es-MX", { weekday: "short" });
      const dayNum   = d.getDate();
      const monthName = d.toLocaleDateString("es-MX", { month: "short" });
      const label = `${dayName} ${dayNum} ${monthName}`;

      return `
        <button class="btn btn-outline-primary day-btn" type="button"
                data-day="${day}"
                aria-pressed="false"
                aria-label="${label}">
          <div class="day-name" aria-hidden="true">${dayName}</div>
          <div class="day-number" aria-hidden="true">${dayNum}</div>
          <div class="month-name" aria-hidden="true">${monthName}</div>
        </button>
      `;
    }).join("");

    container.querySelectorAll(".day-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const day = btn.getAttribute("data-day");
        if (!enabledDays.includes(day)) return;

        // Actualizar aria-pressed
        container.querySelectorAll(".day-btn").forEach((b) => {
          b.setAttribute("aria-pressed", "false");
          b.classList.remove("active");
        });
        btn.setAttribute("aria-pressed", "true");
        btn.classList.add("active");

        state.day = day;
        await joinDay(day);
        registerSocketEvents();

        // Mostrar skeleton mientras espera el join (500ms)
        slotGrid.innerHTML = Skeleton.cards(2);
        slotsWrap.hidden = false;

        setTimeout(() => loadSlots(), 500);
      });
    });
  }

  loadActivePeriod();

  // === PASO 1: ELEGIR TIPO ===
  document.querySelectorAll(".at-type-card[data-type]").forEach((card) => {
    card.addEventListener("click", () => chooseType(card.dataset.type));
  });

  function chooseType(t) {
    state.type = t;
    const hints = {
      DROP        : "Solo se generará la solicitud de baja. Verifica tus créditos.",
      APPOINTMENT : "Se agendará una cita con tu coordinador para alta.",
      BOTH        : "Se solicitará alta y baja. Deberás agendar una cita.",
    };
    typeHint.textContent = hints[t] || "";

    // Marcar activa la card del tipo elegido (feedback visual antes de pasar).
    document.querySelectorAll(".at-type-card[data-type]").forEach((c) => {
      const isActive = c.dataset.type === t;
      c.classList.toggle("at-type-card--active", isActive);
      c.setAttribute("aria-pressed", isActive ? "true" : "false");
    });

    // Mostrar campos según tipo
    altaFields.hidden = (t === "DROP");
    bajaFields.hidden = (t === "APPOINTMENT");

    actionBar.hidden = true;
    updateSubmitDisabled();
    loadPrograms();

    // Delay para que el usuario alcance a ver el check verde antes de la
    // transicion al paso siguiente. Respeta prefers-reduced-motion.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const delay = reduced ? 0 : 320;

    setTimeout(() => showStage(1), delay); // program stage (indice 1 en cualquier flow)
  }

  // === PASO 2: PROGRAMAS + COORDINADOR ===
  document.getElementById("btnReloadPrograms").addEventListener("click", loadPrograms);

  async function loadPrograms() {
    programSelect.disabled = true;
    programSelect.innerHTML = '<option value="">Cargando…</option>';
    try {
      const r = await fetch("/api/agendatec/v2/programs", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();
      programSelect.innerHTML = '<option value="">Selecciona...</option>' +
        (data.items || []).map((p) =>
          `<option value="${p.id}">${escapeHtml(p.name)}</option>`
        ).join("");
    } catch {
      showToast("No se pudieron cargar los programas.", "error");
      programSelect.innerHTML = '<option value="">Error al cargar</option>';
    } finally {
      programSelect.disabled = false;
    }
  }

  programSelect.addEventListener("change", async (e) => {
    const id = parseInt(e.target.value || "0", 10);
    state.program_id = Number.isFinite(id) && id > 0 ? id : null;
    coordCard.hidden = true;

    if (!state.program_id) { updateSubmitDisabled(); return; }

    // Capturar nombre legible de la carrera para mostrar en paso 3 + resumen.
    const programLabel = e.target.options[e.target.selectedIndex]?.textContent?.trim() || "";
    if (careerName) careerName.textContent = programLabel || "—";
    state.program_label = programLabel;

    // Avanzar a stage forms (indice 2 en cualquier flow).
    btnConfirmForms.hidden = false; // siempre visible; validacion en click
    showStage(2);

    try {
      const r = await fetch(
        `/api/agendatec/v2/programs/${state.program_id}/coordinator`,
        { credentials: "include" }
      );
      if (!r.ok) throw 0;
      const c = await r.json();
      const coord = c?.coordinators?.[0];
      if (coord) {
        coordName.textContent  = coord.full_name || "Coordinador";
        coordEmail.textContent = coord.email || "";
        coordHours.textContent = coord.office_hours || "";
        state.coord_label = coord.full_name || "";
        state.coord_email = coord.email || "";
      } else {
        coordName.textContent  = "Sin coordinador asignado";
        coordEmail.textContent = "";
        coordHours.textContent = "";
        state.coord_label = "Sin coordinador asignado";
        state.coord_email = "";
      }
      // Siempre mostrar el info card; carrera ya fue puesta y si no hay
      // coordinador igual conviene que el usuario vea que su carrera fue tomada.
      coordCard.hidden = false;
    } catch {
      showToast("No se pudo obtener el coordinador.", "warn");
      coordCard.hidden = false;
    }
    updateSubmitDisabled();
  });

  // === PASO 3: FORMULARIOS ALTA/BAJA ===
  altaNoSe.addEventListener("change", () => {
    altaMateria.disabled = altaNoSe.checked;
    if (altaNoSe.checked) altaMateria.value = "";
  });

  btnConfirmForms.addEventListener("click", () => {
    // Siempre visible; valida al click. getDescription() ya muestra toast
    // si falta materia / horario.
    state.description = getDescription();
    if (!state.description) return;

    // DROP omite stage calendar y va directo a confirm.
    const flow = getFlow();
    const nextId = state.type === "DROP" ? "confirm" : "calendar";
    const nextIdx = flow.findIndex(f => f.id === nextId);
    showStage(nextIdx);
  });

  // === PASO 4: CALENDARIO + SLOTS ===
  document.getElementById("btnChangeDay").addEventListener("click", () => {
    if (state.currentRoom) {
      emitSocket("leave_day", { day: state.currentRoom });
      state.currentRoom = null;
    }
    releaseLocal();
    state.day    = null;
    state.slot_id = null;
    slotsWrap.hidden = true;
    slotGrid.innerHTML = "";

    // Resetear aria-pressed de día
    document.querySelectorAll(".day-btn").forEach((b) => {
      b.setAttribute("aria-pressed", "false");
      b.classList.remove("active");
    });

    updateSubmitDisabled();
  });

  async function loadSlots() {
    if (!state.program_id || !state.day) return;
    slotGrid.innerHTML = Skeleton.cards(2);

    try {
      const r = await fetch(
        `/api/agendatec/v2/availability/program/${state.program_id}/slots?day=${state.day}`,
        { credentials: "include" }
      );
      if (!r.ok) throw 0;
      const data = await r.json();
      renderSlots(data.items || []);
      slotsWrap.hidden = false;
    } catch (error) {
      console.error(error);
      showToast("No se pudieron cargar los horarios.", "error");
      slotGrid.innerHTML = renderEmptySlots();
    }
  }

  function renderEmptySlots() {
    return `
      <div class="at-empty">
        <div class="at-empty__icon" aria-hidden="true"><i class="bi bi-calendar-x"></i></div>
        <p class="at-empty__title">Sin horarios disponibles</p>
        <p class="at-empty__message">No hay horarios para este día.</p>
        <div class="at-empty__cta">
          <button type="button" class="btn btn-outline-secondary btn-sm" id="btnEmptyChangeDay">
            <i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i> Elegir otro día
          </button>
        </div>
      </div>
    `;
  }

  function renderSlots(items) {
    state.slot_id     = null;
    state.selectedHour = null;
    updateSubmitDisabled();

    const hourTabs = document.getElementById("hourTabs");
    slotGrid.innerHTML = "";
    hourTabs.innerHTML = "";
    btnById.clear();

    if (!items.length) {
      slotGrid.innerHTML = renderEmptySlots();
      // wire CTA del empty state
      const emptyBtn = document.getElementById("btnEmptyChangeDay");
      if (emptyBtn) {
        emptyBtn.addEventListener("click", () => {
          document.getElementById("btnChangeDay").click();
        });
      }
      return;
    }

    // Crear holdBar si no existe
    if (!holdBar) {
      holdBar = document.createElement("div");
      holdBar.id = "__slotHoldBar";
      holdBar.className = "slot-hold-controls mt-2";
      holdBar.hidden = true;
      holdBar.innerHTML = `
        <div class="slot-hold-timer me-auto"></div>
        <button class="btn btn-sm btn-outline-secondary" id="btnHoldCancel" type="button">
          Cancelar selección
        </button>
      `;
      slotGrid.after(holdBar);
      holdBar.querySelector("#btnHoldCancel").addEventListener("click", () => {
        if (!heldByMe) return;
        emitSocket("release_hold", { slot_id: heldByMe });
      });
    }

    // Agrupar por hora
    const byHour = {};
    for (const s of items) {
      const hh = (s.start_time || "").slice(0, 2);
      if (!byHour[hh]) byHour[hh] = [];
      byHour[hh].push(s);
    }

    const hours = Object.keys(byHour).sort((a, b) => Number(a) - Number(b));
    let firstActive = true;

    hours.forEach((hh, idx) => {
      const count = byHour[hh].length;
      const li  = document.createElement("li");
      li.className = "nav-item";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "nav-link d-flex align-items-center gap-2 py-1 px-2";
      btn.dataset.hour = hh;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", idx === 0 ? "true" : "false");
      btn.setAttribute("aria-controls", `slotGrid`);
      btn.id = `hourTab-${hh}`;
      btn.innerHTML = `<span>${hh}:00</span> <span class="badge text-bg-light">${count}</span>`;

      btn.addEventListener("click", () => {
        hourTabs.querySelectorAll("[role='tab']").forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        state.selectedHour = hh;
        renderHourSlots(byHour[hh]);
      });

      if (firstActive) {
        btn.classList.add("active");
        state.selectedHour = hh;
        firstActive = false;
      }

      li.appendChild(btn);
      hourTabs.appendChild(li);
    });

    if (state.selectedHour) {
      renderHourSlots(byHour[state.selectedHour]);
    }
  }

  function renderHourSlots(slots) {
    slotGrid.innerHTML = "";
    btnById.clear();

    slots.forEach((s) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "at-slot";
      btn.dataset.slot = s.slot_id;

      const timeLabel = `${s.start_time} - ${s.end_time}`;
      btn.innerHTML = `<span class="at-slot__label">${timeLabel}</span>`;

      // aria-label descriptivo
      btn.setAttribute("aria-label", `${timeLabel} — disponible`);

      btn.addEventListener("click", () => {
        const newId = Number(btn.dataset.slot);
        if (heldByMe && heldByMe !== newId) {
          pendingHold = newId;
          emitSocket("release_hold", { slot_id: heldByMe });
          return;
        }
        emitSocket("hold_slot", { slot_id: newId });
      });

      slotGrid.appendChild(btn);
      btnById.set(s.slot_id, btn);
    });
  }

  // === NAVEGACION CONFIRM ===
  if (btnNextFromCalendar) {
    btnNextFromCalendar.addEventListener("click", () => {
      if (!state.slot_id) {
        showToast("Selecciona un horario primero.", "warn");
        return;
      }
      const flow = getFlow();
      const idx = flow.findIndex(f => f.id === "confirm");
      showStage(idx);
    });
  }

  if (btnBackFromConfirm) {
    btnBackFromConfirm.addEventListener("click", () => {
      const flow = getFlow();
      const prevId = state.type === "DROP" ? "forms" : "calendar";
      const idx = flow.findIndex(f => f.id === prevId);
      goToStage(idx);
    });
  }

  // === RESUMEN (paso Confirmar) ===
  function buildSummary() {
    if (!confirmSummary) return;

    const typeMap = {
      DROP        : "Baja",
      APPOINTMENT : "Alta",
      BOTH        : "Alta y Baja",
    };
    const tipo    = typeMap[state.type] || "—";
    const carrera = state.program_label || "—";
    const coord   = state.coord_label || (state.type === "DROP" ? "No aplica" : "—");

    const materiaAlta = altaMateria.value.trim();
    const horarioAlta = altaHorario.value.trim();
    const noSeAlta    = altaNoSe.checked;
    const materiaBaja = bajaMateria.value.trim();
    const horarioBaja = bajaHorario.value.trim();

    const rows = [];
    rows.push({ dt: "Tipo",     dd: escapeHtml(tipo) });
    rows.push({ dt: "Carrera",  dd: escapeHtml(carrera) });
    if (state.type !== "DROP") {
      rows.push({ dt: "Coordinador", dd: escapeHtml(coord) });
    }

    if (state.type === "DROP" || state.type === "BOTH") {
      rows.push({
        dt: "Materia a baja",
        dd: `${escapeHtml(materiaBaja || "—")}<span class="at-summary__meta">${escapeHtml(horarioBaja || "")}</span>`,
      });
    }
    if (state.type === "APPOINTMENT" || state.type === "BOTH") {
      const altaTxt = noSeAlta ? "No especificada" : (materiaAlta || "—");
      const altaHoraTxt = noSeAlta ? "" : horarioAlta;
      rows.push({
        dt: "Materia a alta",
        dd: `${escapeHtml(altaTxt)}<span class="at-summary__meta">${escapeHtml(altaHoraTxt)}</span>`,
      });
    }

    if (state.type !== "DROP" && state.day) {
      // Buscar el slot seleccionado para mostrar hora amable.
      const slotBtn = state.slot_id ? btnById.get(state.slot_id) : null;
      const slotLabel = slotBtn?.querySelector(".at-slot__label")?.textContent || "";
      const d = new Date(state.day + "T00:00:00");
      const fechaLeg = d.toLocaleDateString("es-MX", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
      rows.push({
        dt: "Cita",
        dd: `${escapeHtml(fechaLeg)}<span class="at-summary__meta">${escapeHtml(slotLabel)}</span>`,
      });
    }

    confirmSummary.innerHTML = rows.map(r => `<dt>${r.dt}</dt><dd>${r.dd}</dd>`).join("");
  }

  // === ENVÍO ===
  btnSubmit.addEventListener("click", async () => {
    if (!state.type) return;
    if (!state.program_id) { showToast("Selecciona tu carrera.", "warn"); return; }

    let body;
    if (state.type === "DROP") {
      body = { type: "DROP", program_id: state.program_id, description: state.description };
    } else {
      if (!state.day || !state.slot_id) {
        showToast("Selecciona un día y un horario.", "warn");
        return;
      }
      body = {
        type       : "APPOINTMENT",
        program_id : state.program_id,
        slot_id    : state.slot_id,
        description: state.description,
      };
    }

    btnSubmit.disabled = true;
    btnSubmit.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span> Enviando…';

    try {
      const r = await fetch("/api/agendatec/v2/requests", {
        method : "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body   : JSON.stringify(body),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const msgs = {
          already_has_petition             : "Ya tienes una solicitud.",
          already_has_request_in_period    : err.message || "Ya tienes una solicitud activa en este período.",
          no_active_period                 : "No hay un período activo disponible.",
          slot_unavailable                 : "El horario ya no está disponible.",
          slot_time_passed                 : "El horario ya pasó.",
          slot_conflict                    : "Conflicto al reservar, intenta otro horario.",
          day_not_enabled                  : "Ese día no está habilitado en este período.",
          day_not_allowed                  : "Ese día no está permitido.",
        };
        showToast(msgs[err.error] || "No se pudo crear la solicitud.", "error");
        return;
      }

      showToast("Solicitud creada correctamente.", "success");
      setTimeout(() => { window.location.href = "/agendatec/student/requests"; }, 500);

    } catch {
      showToast("No se pudo conectar.", "error");
    } finally {
      btnSubmit.disabled = false;
      btnSubmit.innerHTML = '<i class="bi bi-check2-circle me-1" aria-hidden="true"></i> Confirmar solicitud';
    }
  });

  // === ESTADO DEL BOTÓN SUBMIT ===
  function updateSubmitDisabled() {
    // Submit solo es relevante en stage confirm; ahi es donde actionBar esta visible.
    btnSubmit.hidden = false;

    const baseOk =
      !!state.type &&
      !!state.program_id &&
      !!state.description;

    const needsSlot = state.type !== "DROP";
    const slotOk    = !needsSlot || (!!state.day && !!state.slot_id);

    btnSubmit.disabled = !(baseOk && slotOk);
    btnSubmit.innerHTML = needsSlot
      ? '<i class="bi bi-check2-circle me-1" aria-hidden="true"></i> Confirmar y Agendar'
      : '<i class="bi bi-check2-circle me-1" aria-hidden="true"></i> Confirmar Solicitud';
  }

  // === DESCRIPCIÓN ===
  function getDescription() {
    const materiaAlta  = altaMateria.value.trim();
    const noSeAlta     = altaNoSe.checked;
    const horarioAlta  = altaHorario.value.trim();
    const materiaBaja  = bajaMateria.value.trim();
    const horarioBaja  = bajaHorario.value.trim();

    if (state.type === "DROP") {
      if (!materiaBaja || !horarioBaja) {
        showToast("Completa materia y horario para la baja.", "warn");
        return "";
      }
      return `Solicitud de baja de la materia ${materiaBaja} en el horario ${horarioBaja}.`;
    }

    if (state.type === "APPOINTMENT") {
      if (!noSeAlta && (!materiaAlta || !horarioAlta)) {
        showToast("Completa materia y horario para la alta.", "warn");
        return "";
      }
      if (noSeAlta) return "Solicitud de alta (materia y horario no especificados).";
      return `Solicitud de alta de la materia ${materiaAlta} en el horario ${horarioAlta}.`;
    }

    if (state.type === "BOTH") {
      if (!materiaBaja || !horarioBaja) {
        showToast("Completa materia y horario para la baja.", "warn");
        return "";
      }
      const bajaTxt = `baja de la materia ${materiaBaja} en el horario ${horarioBaja}`;
      let altaTxt;
      if (noSeAlta) {
        altaTxt = "alta (materia y horario no especificados)";
      } else {
        if (!materiaAlta || !horarioAlta) {
          showToast("Completa materia y horario para la alta.", "warn");
          return "";
        }
        altaTxt = `alta de la materia ${materiaAlta} en el horario ${horarioAlta}`;
      }
      return `Se solicita ${bajaTxt} y ${altaTxt}.`;
    }
    return "";
  }

})();
