// static/js/admin/create_request.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__createRequestCfg || {};
  const studentsUrl = cfg.studentsUrl || "/api/agendatec/v1/admin/users/students";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v1/programs";
  const periodsUrl = cfg.periodsUrl || "/api/agendatec/v1/periods/active";
  const createUrl = cfg.createUrl || "/api/agendatec/v1/admin/requests/create";

  let enabledDays = [];
  let activePeriod = null;
  let allSlots = [];
  let selectedProgram = null;
  let allStudents = []; // Almacenar todos los estudiantes para filtrado

  // Cargar datos iniciales
  async function init() {
    try {
      await Promise.all([
        loadStudents(),
        loadPrograms(),
        loadActivePeriod()
      ]);
    } catch (e) {
      console.error("Error initializing:", e);
      showToast?.("Error al cargar datos iniciales", "error");
    }
  }

  // Cargar estudiantes
  async function loadStudents() {
    try {
      const r = await fetch(studentsUrl, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      allStudents = data.items || data.students || [];

      renderStudents(allStudents);
    } catch (e) {
      console.error("Error loading students:", e);
      showToast?.("Error al cargar estudiantes", "error");
    }
  }

  // Renderizar estudiantes en el select
  function renderStudents(students) {
    const select = $("#selStudent");
    select.innerHTML = `<option value="">Seleccionar estudiante...</option>` +
      students.map(s => `<option value="${s.id}">${escapeHtml(s.control_number || s.username)} - ${escapeHtml(s.full_name || s.name)}</option>`).join("");
  }

  // Filtrar estudiantes mientras se escribe
  $("#txtSearchStudent")?.addEventListener("input", (e) => {
    const query = e.target.value.toLowerCase().trim();

    if (!query) {
      // Si no hay búsqueda, mostrar todos
      renderStudents(allStudents);
      return;
    }

    // Filtrar por nombre o número de control
    const filtered = allStudents.filter(s => {
      const name = (s.full_name || s.name || "").toLowerCase();
      const control = (s.control_number || "").toLowerCase();
      const username = (s.username || "").toLowerCase();

      return name.includes(query) || control.includes(query) || username.includes(query);
    });

    renderStudents(filtered);

    // Mostrar mensaje si no hay resultados
    if (filtered.length === 0) {
      $("#selStudent").innerHTML = `<option value="">No se encontraron estudiantes</option>`;
    }
  });

  // Cargar programas
  async function loadPrograms() {
    try {
      const r = await fetch(programsUrl, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const programs = Array.isArray(data) ? data : (data.items || data.programs || []);

      const select = $("#selProgram");
      select.innerHTML = `<option value="">Seleccionar programa...</option>` +
        programs.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
    } catch (e) {
      console.error("Error loading programs:", e);
      showToast?.("Error al cargar programas", "error");
    }
  }

  // Cargar período activo y días habilitados
  async function loadActivePeriod() {
    try {
      const r = await fetch(periodsUrl, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();

      activePeriod = data;
      enabledDays = (data.enabled_days || []).map(d => d);

      // Llenar select de días
      const daySelect = $("#selDay");
      if (enabledDays.length === 0) {
        daySelect.innerHTML = `<option value="">No hay días habilitados</option>`;
        return;
      }

      daySelect.innerHTML = `<option value="">Seleccionar día...</option>` +
        enabledDays.map(day => {
          const d = new Date(day);
          const formatted = d.toLocaleDateString("es-MX", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
          return `<option value="${day}">${formatted}</option>`;
        }).join("");
    } catch (e) {
      console.error("Error loading active period:", e);
      showToast?.("Error al cargar período activo", "error");
    }
  }

  // Cambio de tipo de solicitud
  $("#selType")?.addEventListener("change", (e) => {
    const type = e.target.value;
    const appointmentSection = $("#appointmentSection");
    const detailsSection = $("#detailsSection");
    const altaFields = $("#altaFields");
    const bajaFields = $("#bajaFields");

    // Mostrar/ocultar sección de detalles
    if (type) {
      detailsSection.style.display = "block";
    } else {
      detailsSection.style.display = "none";
    }

    // Mostrar campos según el tipo
    if (type === "APPOINTMENT") {
      // APPOINTMENT = Alta o Alta y Baja (mostrar ambos campos)
      altaFields.style.display = "block";
      bajaFields.style.display = "block";
      appointmentSection.style.display = "block";
      $("#selDay").required = true;
      $("#selSlot").required = true;
    } else if (type === "DROP") {
      // DROP = Solo baja
      altaFields.style.display = "none";
      bajaFields.style.display = "block";
      appointmentSection.style.display = "none";
      $("#selDay").required = false;
      $("#selSlot").required = false;
    } else {
      altaFields.style.display = "none";
      bajaFields.style.display = "none";
      appointmentSection.style.display = "none";
      $("#selDay").required = false;
      $("#selSlot").required = false;
    }
  });

  // Checkbox "No sé qué materia"
  $("#altaNoSe")?.addEventListener("change", (e) => {
    const altaMateria = $("#altaMateria");
    if (e.target.checked) {
      altaMateria.value = "No especificada";
      altaMateria.disabled = true;
    } else {
      if (altaMateria.value === "No especificada") {
        altaMateria.value = "";
      }
      altaMateria.disabled = false;
    }
  });

  // Cambio de programa (para cargar slots del coordinador)
  $("#selProgram")?.addEventListener("change", async (e) => {
    const programId = e.target.value;
    selectedProgram = programId;

    // Si ya hay un día seleccionado, recargar slots
    const day = $("#selDay").value;
    if (day && programId) {
      await loadSlotsForDay(day, programId);
    }
  });

  // Cambio de día
  $("#selDay")?.addEventListener("change", async (e) => {
    const day = e.target.value;
    const programId = $("#selProgram").value;

    if (!programId) {
      showToast?.("Por favor selecciona un programa primero", "warn");
      $("#selSlot").innerHTML = `<option value="">Primero selecciona un programa</option>`;
      return;
    }

    if (day) {
      await loadSlotsForDay(day, programId);
    } else {
      $("#selSlot").innerHTML = `<option value="">Selecciona un día primero</option>`;
    }
  });

  // Cargar slots disponibles para un día y programa
  async function loadSlotsForDay(day, programId) {
    try {
      // Usar el mismo endpoint que usa el estudiante: filtra automáticamente por coordinador del programa
      const url = `/api/agendatec/v1/availability/program/${programId}/slots?day=${day}`;

      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const slots = data.items || data.slots || [];

      // Filtrar solo slots disponibles (no reservados)
      const availableSlots = slots.filter(slot => !slot.is_booked);

      const slotSelect = $("#selSlot");
      if (availableSlots.length === 0) {
        slotSelect.innerHTML = `<option value="">No hay horarios disponibles</option>`;
        showToast?.("No hay horarios disponibles para este día y programa", "warn");
        return;
      }

      slotSelect.innerHTML = `<option value="">Seleccionar horario...</option>` +
        availableSlots.map(slot =>
          `<option value="${slot.slot_id}">${slot.start_time} - ${slot.end_time}</option>`
        ).join("");

      allSlots = availableSlots;
    } catch (e) {
      console.error("Error loading slots:", e);
      showToast?.("Error al cargar horarios disponibles", "error");
      $("#selSlot").innerHTML = `<option value="">Error al cargar horarios</option>`;
    }
  }

  // Construir descripción a partir de los campos estructurados
  // Usa exactamente el mismo formato que el formulario del estudiante
  function buildDescription() {
    const type = $("#selType").value;

    const materiaAlta = $("#altaMateria").value.trim();
    const noSeAlta = $("#altaNoSe").checked;
    const horarioAlta = $("#altaHorario").value.trim();
    const materiaBaja = $("#bajaMateria").value.trim();
    const horarioBaja = $("#bajaHorario").value.trim();

    // DROP: solo baja
    if (type === "DROP") {
      if (!materiaBaja || !horarioBaja) {
        showToast?.("Completa materia y horario para la baja.", "warn");
        return "";
      }
      return `Solicitud de baja de la materia ${materiaBaja} en el horario ${horarioBaja}.`;
    }

    // APPOINTMENT: puede ser solo alta, solo baja, o ambas
    if (type === "APPOINTMENT") {
      const tieneAlta = noSeAlta || (materiaAlta && horarioAlta);
      const tieneBaja = materiaBaja && horarioBaja;

      // Caso 1: Solo alta
      if (tieneAlta && !tieneBaja) {
        if (noSeAlta) {
          return "Solicitud de alta (materia y horario no especificados).";
        }
        return `Solicitud de alta de la materia ${materiaAlta} en el horario ${horarioAlta}.`;
      }

      // Caso 2: Solo baja (aunque sea tipo APPOINTMENT)
      if (!tieneAlta && tieneBaja) {
        return `Solicitud de baja de la materia ${materiaBaja} en el horario ${horarioBaja}.`;
      }

      // Caso 3: Alta y baja (BOTH)
      if (tieneAlta && tieneBaja) {
        let altaTxt = "";
        let bajaTxt = `baja de la materia ${materiaBaja} en el horario ${horarioBaja}`;

        if (noSeAlta) {
          altaTxt = "alta (materia y horario no especificados)";
        } else {
          altaTxt = `alta de la materia ${materiaAlta} en el horario ${horarioAlta}`;
        }

        return `Se solicita ${bajaTxt} y ${altaTxt}.`;
      }

      // Si no llenó nada
      showToast?.("Completa al menos la información de una materia (alta o baja).", "warn");
      return "";
    }

    return "";
  }

  // Submit del formulario
  $("#frmCreateRequest")?.addEventListener("submit", async (e) => {
    e.preventDefault();

    const studentId = $("#selStudent").value;
    const type = $("#selType").value;
    const programId = $("#selProgram").value;

    if (!studentId || !type || !programId) {
      showToast?.("Por favor completa todos los campos obligatorios", "warn");
      return;
    }

    // Validar que se haya llenado al menos un campo de materia
    const description = buildDescription();
    if (!description) {
      showToast?.("Por favor completa la información de la materia", "warn");
      return;
    }

    const payload = {
      student_id: parseInt(studentId),
      type: type,
      program_id: parseInt(programId),
      description: description
    };

    if (type === "APPOINTMENT") {
      const slotId = $("#selSlot").value;
      if (!slotId || slotId === "") {
        showToast?.("Por favor selecciona un horario", "warn");
        return;
      }
      payload.slot_id = parseInt(slotId);
    }

    // Mostrar modal de confirmación
    const studentName = $("#selStudent").selectedOptions[0].text;
    const typeName = type === "APPOINTMENT" ? "cita" : "baja";
    const confirmMsg = `¿Estás seguro de crear una solicitud de ${typeName} para ${studentName}?`;

    const mdlConfirmMessage = $("#mdlConfirmMessage");
    const mdlConfirm = new bootstrap.Modal($("#mdlConfirm"));

    mdlConfirmMessage.textContent = confirmMsg;
    mdlConfirm.show();

    // Guardar payload para usar en el callback del modal
    window.__pendingRequestPayload = payload;
  });

  // Manejar confirmación del modal
  $("#btnConfirmCreate")?.addEventListener("click", async () => {
    const payload = window.__pendingRequestPayload;
    if (!payload) return;

    // Cerrar modal
    const mdlConfirm = bootstrap.Modal.getInstance($("#mdlConfirm"));
    mdlConfirm?.hide();

    // Deshabilitar botón del formulario
    const submitBtn = $("#frmCreateRequest").querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Creando...';

    try {
      const r = await fetch(createUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload)
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.message || "Error al crear solicitud");
      }

      const data = await r.json();
      showToast?.("Solicitud creada exitosamente", "success");

      // Redirigir a solicitudes después de 1 segundo
      setTimeout(() => {
        window.location.href = "/agendatec/admin/requests";
      }, 1000);
    } catch (e) {
      console.error("Error creating request:", e);
      showToast?.(e.message || "Error al crear solicitud", "error");
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalText;
    } finally {
      // Limpiar payload
      window.__pendingRequestPayload = null;
    }
  });

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // Inicializar
  init();
})();
