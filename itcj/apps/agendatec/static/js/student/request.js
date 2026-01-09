(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // NOTA: ALLOWED_DAYS eliminado - ahora se obtiene dinámicamente del período activo
  let enabledDays = []; // Se carga desde /api/agendatec/v1/periods/active

  // State
  const state = {
    type: null,            // DROP | APPOINTMENT | BOTH
    program_id: null,
    day: null,
    slot_id: null,
    description: null,
    selectedHour: null,
    currentRoom: null,     // Para trackear la room actual
    periodLoaded: false,   // Para controlar la carga del período
  };

  // Variables globales para sockets
  let btnById = new Map();
  let heldByMe = null;
  let pendingHold = null;
  let countdownInt = null;
  let countdownLeft = 0;
  let holdBar = null;
  let socketEventsRegistered = false;

  // Elements
  const stepType = $("#stepType");
  const stepProgram = $("#stepProgram");
  const stepForms = $("#stepForms");
  const stepCalendar = $("#stepCalendar");
  const programSelect = $("#programSelect");
  const coordCard = $("#coordCard");
  const coordName = $("#coordName");
  const coordEmail = $("#coordEmail");
  const coordHours = $("#coordHours");
  const typeHint = $("#typeHint");

  const altaFields = $("#altaFields");
  const bajaFields = $("#bajaFields");
  const altaMateria = $("#altaMateria");
  const altaNoSe = $("#altaNoSe");
  const altaHorario = $("#altaHorario");
  const bajaMateria = $("#bajaMateria");
  const bajaHorario = $("#bajaHorario");

  const calendarBlock = $("#calendarBlock");
  const slotsWrap = $("#slotsWrap");
  const slotGrid = $("#slotGrid");

  const btnConfirmForms = $("#btnConfirmForms");
  const btnSubmit = $("#btnSubmit");
  const actionBar = $("#actionBar");

  // Helpers para sockets
  const getSocket = () => window.__slotsSocket;
  const emit = (event, payload) => {
    const socket = getSocket();
    if (socket && socket.connected) {
      socket.emit(event, payload);
    } else {
      console.warn(`[WS] No se puede emitir ${event}, socket no disponible`);
    }
  };

  // Función para esperar a que el socket esté conectado
  const waitForSocket = (maxWait = 5000) => {
    return new Promise((resolve, reject) => {
      const socket = getSocket();
      if (socket && socket.connected) {
        resolve(socket);
        return;
      }

      let waited = 0;
      const interval = 100;
      const check = setInterval(() => {
        const socket = getSocket();
        waited += interval;

        if (socket && socket.connected) {
          clearInterval(check);
          resolve(socket);
        } else if (waited >= maxWait) {
          clearInterval(check);
          reject(new Error('Socket no disponible después del tiempo límite'));
        }
      }, interval);
    });
  };

  // Función para hacer join a un día de forma segura
  const joinDay = async (day) => {
    try {
      await waitForSocket();

      // Salir del día anterior si existe
      if (state.currentRoom && state.currentRoom !== day) {
        emit("leave_day", { day: state.currentRoom });
      }

      // Unirse al nuevo día
      emit("join_day", { day });
      state.currentRoom = day;

    } catch (error) {
      console.error("[WS] Error al hacer join:", error);
      showToast("Error de conexión con el servidor", "warn");
    }
  };

  // Helpers para UI de slots
  const getSlotButton = (slotId) => {
    const id = Number(slotId);
    return btnById.get(id) || document.querySelector(`.slot-btn[data-slot="${id}"]`) || null;
  };

  const startCountdown = (ttl) => {
    if (countdownInt) clearInterval(countdownInt);
    countdownLeft = ttl || 0;
    const holdTimerEl = holdBar?.querySelector(".slot-hold-timer");

    const tick = () => {
      if (holdTimerEl) {
        holdTimerEl.textContent = countdownLeft > 0
          ? `Reserva temporal: ${countdownLeft}s`
          : `Reserva expirada`;
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
      b.classList.remove("active", "held", "held-self");
      b.disabled = false;
    }
    heldByMe = null;
    state.slot_id = null;
    if (holdBar) holdBar.hidden = true;
    updateSubmitDisabled();
  };

  // Registrar eventos de socket una sola vez
  const registerSocketEvents = () => {
    if (socketEventsRegistered) return;

    const socket = getSocket();
    if (!socket) return;

    // Limpiar handlers existentes
    socket.off("slots_snapshot");
    socket.off("slot_held");
    socket.off("slot_released");
    socket.off("slot_booked");
    socket.off("hold_slot_ack");
    socket.off("release_hold_ack");

    // Snapshot inicial
    socket.on("slots_snapshot", (snap) => {
      if (!snap || snap.day !== state.day) return;

      // Marca booked
      (snap.booked || []).forEach((id) => {
        const btn = getSlotButton(id);
        if (btn) {
          btn.classList.add("booked");
          btn.disabled = true;
        }
      });

      // Marca held
      (snap.held || []).forEach(({ slot_id }) => {
        const btn = getSlotButton(slot_id);
        if (btn) {
          btn.classList.add("held");
          btn.classList.remove("held-self");
          btn.disabled = true;
        }
      });
    });

    // Alguien puso hold en un slot
    socket.on("slot_held", ({ slot_id, day, ttl }) => {
      if (day !== state.day) return;
      const btn = getSlotButton(slot_id);
      if (!btn) return;
      if (!btn.classList.contains("held-self")) {
        btn.classList.add("held");
        btn.classList.remove("held-self");
      }
      btn.disabled = true;
    });

    // Se liberó un hold
    socket.on("slot_released", ({ slot_id, day }) => {
      if (day !== state.day) return;
      const btn = getSlotButton(slot_id);
      if (!btn) return;
      btn.classList.remove("held", "held-self", "booked");
      btn.disabled = false;
      btn.hidden = false;
      if (heldByMe === Number(slot_id)) {
        releaseLocal();
      }
    });

    socket.on("slots_window_changed", (p) => {
      if (p?.day === state.day) {
        // vuelve a pedir los slots del día
        loadSlots();
      }
    });
    // Slot reservado definitivamente
    socket.on("slot_booked", ({ slot_id, day }) => {
      if (day !== state.day) return;
      const btn = getSlotButton(slot_id);
      if (btn) {
        btn.classList.add("booked");
        btn.disabled = true;
        btn.hidden = true;
      }
      if (heldByMe === Number(slot_id)) {
        releaseLocal();
        showToast("El horario fue reservado con éxito.", "success");
      }
    });

    // Respuesta a MI intento de hold
    socket.on("hold_slot_ack", (resp) => {
      if (!resp) return;
      if (!resp.ok) {
        if (resp.error === "already_held") {
          showToast("Este horario está temporalmente ocupado.", "warn");
        } else if (resp.error === "slot_not_found") {
          showToast("El horario ya no está disponible.", "warn");
        } else {
          showToast("No se pudo seleccionar el horario.", "error");
        }
        return;
      }

      const slotId = Number(resp.slot_id);
      const ttl = Number(resp.ttl || 0);

      // Si tenía otro hold, lo suelto visualmente
      if (heldByMe && heldByMe !== slotId && btnById.has(heldByMe)) {
        const old = btnById.get(heldByMe);
        old.classList.remove("active", "held", "held-self");
        old.disabled = false;
      }

      const btn = btnById.get(slotId);
      if (btn) {
        btn.classList.add("active", "held", "held-self");
        btn.disabled = true;
      }

      heldByMe = slotId;
      state.slot_id = slotId;
      if (holdBar) holdBar.hidden = false;
      startCountdown(ttl);
      updateSubmitDisabled();
    });

    // Respuesta a release
    socket.on("release_hold_ack", (resp) => {
      if (resp?.ok && pendingHold) {
        const next = pendingHold;
        pendingHold = null;
        emit("hold_slot", { slot_id: next });
      }
    });

    socketEventsRegistered = true;
  };

  //Empezar con el botón submit sin mostrarse
  btnSubmit.hidden = true;

  // ------------- Cargar período activo al inicio -------------
  async function loadActivePeriod() {
    try {
      const r = await fetch("/api/agendatec/v1/periods/active", { credentials: "include" });
      if (!r.ok) {
        throw new Error("No hay período activo");
      }
      const data = await r.json();
      enabledDays = (data.enabled_days || []).sort();
      state.periodLoaded = true;

      // Renderizar botones de días dinámicamente
      renderDayButtons();
    } catch (error) {
      console.error("Error al cargar período activo:", error);
      showToast("No hay período activo disponible. Contacta al administrador.", "error");
      // Deshabilitar todo el flujo si no hay período
      state.periodLoaded = false;
    }
  }

  // Renderizar botones de días dinámicamente
  function renderDayButtons() {
    const calendarBlock = $("#calendarBlock");
    const dayButtonsContainer = $(".day-buttons-container");

    if (!dayButtonsContainer || !enabledDays.length) {
      if (dayButtonsContainer) {
        dayButtonsContainer.innerHTML = '<p class="text-muted text-center">No hay días habilitados en el período actual.</p>';
      }
      return;
    }

    dayButtonsContainer.innerHTML = enabledDays.map(day => {
      const d = new Date(day + "T00:00:00");
      const dayName = d.toLocaleDateString("es-MX", { weekday: "short" });
      const dayNum = d.getDate();
      const monthName = d.toLocaleDateString("es-MX", { month: "short" });

      return `
        <button class="btn btn-outline-primary day-btn" data-day="${day}">
          <div class="day-name">${dayName}</div>
          <div class="day-number">${dayNum}</div>
          <div class="month-name">${monthName}</div>
        </button>
      `;
    }).join("");

    // Re-agregar event listeners para los nuevos botones
    $$(".day-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const day = btn.getAttribute("data-day");
        if (!enabledDays.includes(day)) return;
        state.day = day;

        // Hacer join al día seleccionado
        await joinDay(day);

        // Registrar eventos de socket si no están registrados
        registerSocketEvents();

        // Cargar slots después del join
        setTimeout(() => loadSlots(), 500);
      });
    });
  }

  // Cargar período activo al iniciar
  loadActivePeriod();

  // ------------- Paso 1: elegir tipo -------------
  $("[data-type='DROP']").addEventListener("click", () => chooseType("DROP"));
  $("[data-type='APPOINTMENT']").addEventListener("click", () => chooseType("APPOINTMENT"));
  $("[data-type='BOTH']").addEventListener("click", () => chooseType("BOTH"));

  function chooseType(t) {
    state.type = t;
    stepType.hidden = true;
    if (t === "DROP") {
      typeHint.textContent = "Solo se generará la solicitud de baja. Verifica tus créditos.";
    } else {
      typeHint.textContent = "Se agendará una cita con tu coordinador para alta.";
    }

    stepProgram.hidden = false;
    loadPrograms();
    // Mostrar campos según tipo
    altaFields.hidden = (t === "DROP");
    bajaFields.hidden = (t === "APPOINTMENT");

    // Botonera de acción visible ya (en DROP, se permitirá enviar sin slot)
    actionBar.hidden = false;
    updateSubmitDisabled();
    animateEnter(calendarBlock, !stepCalendar.hidden);
  }

  // ------------- Paso 2: programas + coordinador -------------
  $("#btnReloadPrograms").addEventListener("click", loadPrograms);

  async function loadPrograms() {
    try {
      const r = await fetch("/api/agendatec/v1/programs", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();
      programSelect.innerHTML = `<option value="">Selecciona...</option>` +
        (data.items || []).map(p => `<option value="${p.id}">${p.name}</option>`).join("");
    } catch {
      showToast("No se pudieron cargar los programas.", "error");
    }
  }

  programSelect.addEventListener("change", async (e) => {
    stepForms.hidden = false;
    stepProgram.hidden = true;
    btnConfirmForms.hidden = state.type === "DROP";
    const id = parseInt(e.target.value || "0", 10);
    state.program_id = Number.isFinite(id) && id > 0 ? id : null;
    coordCard.hidden = true;

    if (!state.program_id) { updateSubmitDisabled(); return; }
    try {
      const r = await fetch(`/api/agendatec/v1/programs/${state.program_id}/coordinator`, { credentials: "include" });
      if (!r.ok) throw 0;
      const c = await r.json();
      coordName.textContent = c?.coordinators[0].full_name || "Coordinador";
      coordEmail.textContent = c?.coordinators[0].email || "";
      coordHours.textContent = c?.coordinators[0].office_hours || "";
      coordCard.hidden = false;
    } catch {
      showToast("No se pudo obtener el coordinador.", "warn");
    }
    updateSubmitDisabled();
  });

  // ------------- Paso 3: formularios Alta/Baja -------------
  altaNoSe.addEventListener("change", () => {
    altaMateria.disabled = altaNoSe.checked;
    if (altaNoSe.checked) altaMateria.value = "";
  });

  // ------------- Paso 4: calendario + slots -------------
  btnConfirmForms.addEventListener("click", () => {
    state.description = getDescription();
    if (!state.description || state.description === "") return;
    if (state.type != "DROP") {
      stepCalendar.hidden = false;
      stepForms.hidden = true;
      stepProgram.hidden = true;
    }
  });

  // NOTA: Event listeners de .day-btn ahora se agregan dinámicamente en renderDayButtons()

  $("#btnChangeDay").addEventListener("click", () => {
    // "Elegir otro día": resetea slots y vuelve a mostrar botones de día
    if (state.currentRoom) {
      emit("leave_day", { day: state.currentRoom });
      state.currentRoom = null;
    }

    releaseLocal();
    state.day = null;
    state.slot_id = null;
    slotsWrap.hidden = true;
    slotGrid.innerHTML = "";
    updateSubmitDisabled();
  });

  async function loadSlots() {
    if (!state.program_id || !state.day) return;
    try {
      const r = await fetch(`/api/agendatec/v1/availability/program/${state.program_id}/slots?day=${state.day}`, {
        credentials: "include"
      });
      if (!r.ok) throw 0;
      const data = await r.json();
      renderSlots(data.items || []);
      // Animación al mostrar grid
      slotsWrap.hidden = false;
    } catch (error) {
      console.error(error);
      showToast("No se pudieron cargar los horarios.", "error");
    }
  }

  function renderSlots(items) {
    // --- Estado base ---
    state.slot_id = null;
    state.selectedHour = null;
    updateSubmitDisabled();

    const hourTabs = $("#hourTabs");
    slotGrid.innerHTML = "";
    hourTabs.innerHTML = "";
    btnById.clear();

    if (!items.length) {
      slotGrid.innerHTML = `<div class="text-muted">No hay horarios disponibles para este día.</div>`;
      return;
    }

    // Crear barra de control si no existe
    if (!holdBar) {
      holdBar = document.createElement("div");
      holdBar.id = "__slotHoldBar";
      holdBar.className = "d-flex align-items-center slot-hold-controls mt-2";
      holdBar.hidden = true;
      holdBar.innerHTML = `
        <div class="slot-hold-timer me-auto"></div>
        <button class="btn btn-sm btn-outline-secondary" id="btnHoldCancel">Cancelar selección</button>      `;
      slotGrid.after(holdBar);

      // Event listeners para la barra
      holdBar.querySelector("#btnHoldCancel").onclick = () => {
        if (!heldByMe) return;
        emit("release_hold", { slot_id: heldByMe });
      };

    }

    // 1) Agrupar por hora => { "09": [slots...], "10": [slots...] }
    const byHour = {};
    for (const s of items) {
      const hh = (s.start_time || "").slice(0, 2); // "HH:MM" -> "HH"
      if (!byHour[hh]) byHour[hh] = [];
      byHour[hh].push(s);
    }

    // 2) Ordenar horas asc y construir tabs solo para horas con datos
    const hours = Object.keys(byHour).sort((a, b) => Number(a) - Number(b));

    hours.forEach((hh, idx) => {
      const count = byHour[hh].length;
      const li = document.createElement("li");
      li.className = "nav-item";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "nav-link d-flex align-items-center gap-2 py-1 px-2";
      btn.dataset.hour = hh;
      btn.innerHTML = `<span>${hh}:00</span> <span class="badge text-bg-light">${count}</span>`;

      btn.addEventListener("click", () => {
        // Activar tab
        Array.from(hourTabs.querySelectorAll(".nav-link")).forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.selectedHour = hh;

        // Render de los slots de esa hora
        renderHourSlots(byHour[hh]);
      });

      if (idx === 0) {
        // Seleccionar la primera hora por defecto
        btn.classList.add("active");
        state.selectedHour = hh;
      }

      li.appendChild(btn);
      hourTabs.appendChild(li);
    });

    // 3) Pintar slots de la primera hora activa
    if (state.selectedHour) {
      renderHourSlots(byHour[state.selectedHour]);
    }
  }

  // Render de una hora (se llama al cambiar de tab y al inicio)
  function renderHourSlots(slots) {
    slotGrid.innerHTML = "";
    btnById.clear();

    // Botones por slot en la hora seleccionada
    slots.forEach((s) => {
      const btn = document.createElement("button");
      btn.className = "btn btn-outline-secondary slot-btn";
      btn.textContent = `${s.start_time} - ${s.end_time}`;
      btn.dataset.slot = s.slot_id;

      btn.addEventListener("click", () => {
        const newId = Number(btn.dataset.slot);
        // Si tengo otro hold, lo libero primero
        if (heldByMe && heldByMe !== newId) {
          pendingHold = newId;
          emit("release_hold", { slot_id: heldByMe });
          return;
        }
        emit("hold_slot", { slot_id: newId });
      });

      slotGrid.appendChild(btn);
      btnById.set(s.slot_id, btn);
    });
  }

  // ------------- Envío -------------
  btnSubmit.addEventListener("click", async () => {
    if (!state.type) return;

    // Validaciones mínimas
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
        type: "APPOINTMENT",
        program_id: state.program_id,
        slot_id: state.slot_id,
        description: state.description
      };
    }

    try {
      const r = await fetch("/api/agendatec/v1/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body)
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        if (err.error === "already_has_petition") {
          showToast("Ya tienes una solicitud.", "warn");
        } else if (err.error === "already_has_request_in_period") {
          showToast(err.message || "Ya tienes una solicitud activa en este período.", "warn");
        } else if (err.error === "no_active_period") {
          showToast("No hay un período activo disponible.", "error");
        } else if (err.error === "slot_unavailable") {
          showToast("El horario ya no está disponible.", "warn");
        } else if (err.error === "slot_time_passed"){
          showToast("El horario ya pasó.", "warn");
        } else if (err.error === "slot_conflict") {
          showToast("Conflicto al reservar, intenta otro horario.", "warn");
        } else if (err.error === "day_not_enabled") {
          showToast("Ese día no está habilitado en este período.", "warn");
        } else if (err.error === "day_not_allowed") {
          showToast("Ese día no está permitido.", "warn");
        } else {
          showToast("No se pudo crear la solicitud.", "error");
        }
        return;
      }

      // Éxito → redirigir a Mis solicitudes
      showToast("Solicitud creada correctamente.", "success");
      setTimeout(() => { window.location.href = "/student/requests"; }, 500);

    } catch {
      showToast("No se pudo conectar.", "error");
    }
  });

  function updateSubmitDisabled() {
    if (!state.type) { btnSubmit.disabled = true; return; }
    if (!state.program_id) { btnSubmit.disabled = true; return; }
    if (!state.description) { btnSubmit.disabled = true; return; }
    if (state.type === "DROP") {
      btnSubmit.disabled = false;
      btnSubmit.innerHTML = '<i class="bi bi-check2-circle me-1"></i> Confirmar Solicitud';
      return;
    }
    btnSubmit.innerHTML = '<i class="bi bi-check2-circle me-1"></i> Confirmar y Agendar';
    // Appointment / Both → necesita slot
    btnSubmit.disabled = !(state.day && state.slot_id);
    btnSubmit.hidden = btnSubmit.disabled;

  }

  // ------------- Animaciones helpers -------------
  function animateEnter(el, shouldAnimate) {
    if (!el || !shouldAnimate) return;
    el.classList.remove("expand-fade-exit", "expand-fade-exit-active");
    el.classList.add("expand-fade-enter");
    // force reflow
    void el.offsetWidth;
    el.classList.add("expand-fade-enter-active");
    setTimeout(() => {
      el.classList.remove("expand-fade-enter", "expand-fade-enter-active");
    }, 220);
  }

  function getDescription() {
    // Captura valores
    const materiaAlta = altaMateria.value.trim();
    const noSeAlta = altaNoSe.checked;
    const horarioAlta = altaHorario.value.trim();
    const materiaBaja = bajaMateria.value.trim();
    const horarioBaja = bajaHorario.value.trim();

    // DROP: solo baja
    if (state.type === "DROP") {
      if (!materiaBaja || !horarioBaja) {
        showToast("Completa materia y horario para la baja.", "warn");
        return "";
      }
      return `Solicitud de baja de la materia ${materiaBaja} en el horario ${horarioBaja}.`;
    }

    // APPOINTMENT: solo alta
    if (state.type === "APPOINTMENT") {
      if (!noSeAlta && (!materiaAlta || !horarioAlta)) {
        showToast("Completa materia y horario para la alta.", "warn");
        return "";
      }
      if (noSeAlta) {
        return "Solicitud de alta (materia y horario no especificados).";
      }
      return `Solicitud de alta de la materia ${materiaAlta} en el horario ${horarioAlta}.`;
    }

    // BOTH: alta y baja
    if (state.type === "BOTH") {
      let altaTxt = "";
      let bajaTxt = "";
      if (!materiaBaja || !horarioBaja) {
        showToast("Completa materia y horario para la baja.", "warn");
        return "";
      }
      bajaTxt = `baja de la materia ${materiaBaja} en el horario ${horarioBaja}`;
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

  // Event listeners para actualizar descripción
  bajaMateria.addEventListener("change", () => {
    state.description = getDescription();
    btnSubmit.hidden = !state.description || state.description === "";
    updateSubmitDisabled();
  });

  bajaHorario.addEventListener("change", () => {
    state.description = getDescription();
    btnSubmit.hidden = !state.description || state.description === "";
    updateSubmitDisabled();
  });

})();