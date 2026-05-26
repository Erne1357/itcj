/**
 * AgendaTec Admin — Crear Solicitud por Estudiante
 * Formulario guiado para crear solicitudes en nombre de un estudiante.
 */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const cfg = window.__createRequestCfg || {};
  const studentsUrl = cfg.studentsUrl || "/api/agendatec/v2/admin/users/students";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v2/programs";
  const periodsUrl  = cfg.periodsUrl  || "/api/agendatec/v2/periods/active";
  const createUrl   = cfg.createUrl   || "/api/agendatec/v2/admin/requests/create";

  // === ESTADO (module-scoped, sin globales) ===
  let enabledDays = [];
  let activePeriod = null;
  let allSlots = [];
  let allStudents = [];
  let pendingPayload = null;   // payload del modal de confirmación (scoped, sin global)
  let mdlConfirmInst = null;

  // === INICIALIZACIÓN ===
  document.addEventListener("DOMContentLoaded", function () {
    init();
    setupEventListeners();
  });

  async function init() {
    showInitSkeleton();
    try {
      await Promise.all([loadStudents(), loadPrograms(), loadActivePeriod()]);
    } catch (e) {
      console.error("Error initializing:", e);
      showToast?.("Error al cargar datos iniciales", "error");
    } finally {
      hideInitSkeleton();
    }

    mdlConfirmInst = new bootstrap.Modal($("#mdlConfirm"));
  }

  // === SKELETON DURANTE CARGA INICIAL ===
  function showInitSkeleton() {
    const sk = window.AgendaTec?.Skeleton;
    if (!sk) return;
    const studentSel = $("#selStudent");
    const programSel = $("#selProgram");
    if (studentSel) {
      studentSel.innerHTML = `<option disabled>Cargando...</option>`;
      studentSel.disabled = true;
    }
    if (programSel) {
      programSel.innerHTML = `<option disabled>Cargando...</option>`;
      programSel.disabled = true;
    }
  }

  function hideInitSkeleton() {
    const studentSel = $("#selStudent");
    const programSel = $("#selProgram");
    if (studentSel) studentSel.disabled = false;
    if (programSel) programSel.disabled = false;
  }

  // === EVENT LISTENERS ===
  function setupEventListeners() {
    $("#txtSearchStudent")?.addEventListener("input", handleStudentSearch);
    $("#selType")?.addEventListener("change", handleTypeChange);
    $("#altaNoSe")?.addEventListener("change", handleAltaNoSeChange);
    $("#selProgram")?.addEventListener("change", handleProgramChange);
    $("#selDay")?.addEventListener("change", handleDayChange);
    $("#frmCreateRequest")?.addEventListener("submit", handleFormSubmit);
    $("#btnConfirmCreate")?.addEventListener("click", handleConfirmCreate);
    $("#btnCancel")?.addEventListener("click", () => window.history.back());
  }

  // === CARGA DE DATOS ===
  async function loadStudents() {
    const r = await fetch(studentsUrl, { credentials: "include" });
    if (!r.ok) throw new Error("Error al cargar estudiantes");
    const data = await r.json();
    allStudents = data.items || data.students || [];
    renderStudents(allStudents);
  }

  async function loadPrograms() {
    const r = await fetch(programsUrl, { credentials: "include" });
    if (!r.ok) throw new Error("Error al cargar programas");
    const data = await r.json();
    const programs = Array.isArray(data) ? data : (data.items || data.programs || []);
    const select = $("#selProgram");
    if (!select) return;
    select.innerHTML = `<option value="">Seleccionar programa...</option>` +
      programs.map(p => `<option value="${escapeHtml(String(p.id))}">${escapeHtml(p.name)}</option>`).join("");
  }

  async function loadActivePeriod() {
    const r = await fetch(periodsUrl, { credentials: "include" });
    if (!r.ok) throw new Error("Error al cargar período activo");
    const data = await r.json();
    activePeriod = data;
    enabledDays = (data.enabled_days || []).map(d => d);

    const daySelect = $("#selDay");
    if (!daySelect) return;
    if (enabledDays.length === 0) {
      daySelect.innerHTML = `<option value="">No hay días habilitados</option>`;
      return;
    }
    daySelect.innerHTML = `<option value="">Seleccionar día...</option>` +
      enabledDays.map(day => {
        const d = new Date(day + "T00:00:00");
        const formatted = d.toLocaleDateString("es-MX", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
        return `<option value="${escapeHtml(day)}">${formatted}</option>`;
      }).join("");
  }

  async function loadSlotsForDay(day, programId) {
    const slotSelect = $("#selSlot");
    if (!slotSelect) return;
    slotSelect.innerHTML = `<option value="">Cargando horarios...</option>`;
    slotSelect.disabled = true;

    try {
      const url = `/api/agendatec/v2/availability/program/${encodeURIComponent(programId)}/slots?day=${encodeURIComponent(day)}`;
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const slots = data.items || data.slots || [];
      const availableSlots = slots.filter(slot => !slot.is_booked);

      if (availableSlots.length === 0) {
        slotSelect.innerHTML = `<option value="">No hay horarios disponibles</option>`;
        showToast?.("No hay horarios disponibles para este día y programa", "warn");
      } else {
        slotSelect.innerHTML = `<option value="">Seleccionar horario...</option>` +
          availableSlots.map(slot =>
            `<option value="${escapeHtml(String(slot.slot_id))}">${escapeHtml(slot.start_time)} - ${escapeHtml(slot.end_time)}</option>`
          ).join("");
        allSlots = availableSlots;
      }
    } catch (e) {
      slotSelect.innerHTML = `<option value="">Error al cargar horarios</option>`;
      showToast?.("Error al cargar horarios disponibles", "error");
    } finally {
      slotSelect.disabled = false;
    }
  }

  // === RENDER ===
  function renderStudents(students) {
    const select = $("#selStudent");
    if (!select) return;
    if (students.length === 0) {
      select.innerHTML = `<option value="">No se encontraron estudiantes</option>`;
      return;
    }
    select.innerHTML = `<option value="">Seleccionar estudiante...</option>` +
      students.map(s => `<option value="${escapeHtml(String(s.id))}">${escapeHtml(s.control_number || s.username)} - ${escapeHtml(s.full_name || s.name)}</option>`).join("");
  }

  // === HANDLERS ===
  function handleStudentSearch(e) {
    const query = e.target.value.toLowerCase().trim();
    if (!query) {
      renderStudents(allStudents);
      return;
    }
    const filtered = allStudents.filter(s => {
      const name = (s.full_name || s.name || "").toLowerCase();
      const control = (s.control_number || "").toLowerCase();
      const username = (s.username || "").toLowerCase();
      return name.includes(query) || control.includes(query) || username.includes(query);
    });
    renderStudents(filtered);
  }

  function handleTypeChange(e) {
    const type = e.target.value;
    clearFieldError("selType");

    const detailsSection   = $("#detailsSection");
    const altaFields       = $("#altaFields");
    const bajaFields       = $("#bajaFields");
    const appointmentSection = $("#appointmentSection");

    if (type) {
      detailsSection.hidden = false;
    } else {
      detailsSection.hidden = true;
    }

    if (type === "APPOINTMENT") {
      altaFields.hidden = false;
      bajaFields.hidden = false;
      appointmentSection.hidden = false;
      $("#selDay").required = true;
      $("#selSlot").required = true;
    } else if (type === "DROP") {
      altaFields.hidden = true;
      bajaFields.hidden = false;
      appointmentSection.hidden = true;
      $("#selDay").required = false;
      $("#selSlot").required = false;
    } else {
      altaFields.hidden = true;
      bajaFields.hidden = true;
      appointmentSection.hidden = true;
      $("#selDay").required = false;
      $("#selSlot").required = false;
    }
  }

  function handleAltaNoSeChange(e) {
    const altaMateria = $("#altaMateria");
    if (!altaMateria) return;
    if (e.target.checked) {
      altaMateria.value = "No especificada";
      altaMateria.disabled = true;
    } else {
      if (altaMateria.value === "No especificada") altaMateria.value = "";
      altaMateria.disabled = false;
    }
  }

  async function handleProgramChange(e) {
    const programId = e.target.value;
    clearFieldError("selProgram");
    const day = $("#selDay")?.value;
    if (day && programId) {
      await loadSlotsForDay(day, programId);
    }
  }

  async function handleDayChange(e) {
    const day = e.target.value;
    clearFieldError("selDay");
    const programId = $("#selProgram")?.value;
    if (!programId) {
      showToast?.("Por favor selecciona un programa primero", "warn");
      const slotSelect = $("#selSlot");
      if (slotSelect) slotSelect.innerHTML = `<option value="">Primero selecciona un programa</option>`;
      return;
    }
    if (day) {
      await loadSlotsForDay(day, programId);
    } else {
      const slotSelect = $("#selSlot");
      if (slotSelect) slotSelect.innerHTML = `<option value="">Selecciona un día primero</option>`;
    }
  }

  function handleFormSubmit(e) {
    e.preventDefault();
    clearAllErrors();

    const studentId = $("#selStudent")?.value;
    const type      = $("#selType")?.value;
    const programId = $("#selProgram")?.value;

    let hasError = false;

    if (!studentId) {
      setFieldError("selStudent", "Selecciona un estudiante");
      hasError = true;
    }
    if (!type) {
      setFieldError("selType", "Selecciona un tipo de solicitud");
      hasError = true;
    }
    if (!programId) {
      setFieldError("selProgram", "Selecciona un programa");
      hasError = true;
    }

    if (hasError) return;

    const description = buildDescription();
    if (!description) return;   // buildDescription muestra errores inline

    const payload = {
      student_id: parseInt(studentId, 10),
      type: type,
      program_id: parseInt(programId, 10),
      description: description
    };

    if (type === "APPOINTMENT") {
      const slotId = $("#selSlot")?.value;
      if (!slotId) {
        setFieldError("selSlot", "Selecciona un horario");
        return;
      }
      payload.slot_id = parseInt(slotId, 10);
    }

    const studentName = $("#selStudent")?.selectedOptions?.[0]?.text || "el estudiante";
    const typeName = type === "APPOINTMENT" ? "cita" : "baja";
    const confirmMsg = `¿Estás seguro de crear una solicitud de ${typeName} para ${studentName}?`;

    $("#mdlConfirmMessage").textContent = confirmMsg;
    pendingPayload = payload;
    mdlConfirmInst?.show();
  }

  async function handleConfirmCreate() {
    if (!pendingPayload) return;
    const payload = pendingPayload;
    pendingPayload = null;

    mdlConfirmInst?.hide();

    const submitBtn = $("#frmCreateRequest")?.querySelector('button[type="submit"]');
    const originalHtml = submitBtn?.innerHTML;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Creando...';
    }

    try {
      const r = await fetch(createUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload)
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || err.message || `Error HTTP ${r.status}`);
      }

      showToast?.("Solicitud creada exitosamente", "success");
      setTimeout(() => { window.location.href = "/agendatec/admin/requests"; }, 1000);
    } catch (e) {
      showToast?.(e.message || "Error al crear solicitud", "error");
      if (submitBtn && originalHtml) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalHtml;
      }
    }
  }

  // === LÓGICA DE DESCRIPCIÓN ===
  function buildDescription() {
    const type = $("#selType")?.value;
    const materiaAlta  = $("#altaMateria")?.value.trim() || "";
    const noSeAlta     = $("#altaNoSe")?.checked || false;
    const horarioAlta  = $("#altaHorario")?.value.trim() || "";
    const materiaBaja  = $("#bajaMateria")?.value.trim() || "";
    const horarioBaja  = $("#bajaHorario")?.value.trim() || "";

    if (type === "DROP") {
      if (!materiaBaja) { setFieldError("bajaMateria", "Campo obligatorio"); return ""; }
      if (!horarioBaja) { setFieldError("bajaHorario", "Campo obligatorio"); return ""; }
      return `Solicitud de baja de la materia ${materiaBaja} en el horario ${horarioBaja}.`;
    }

    if (type === "APPOINTMENT") {
      const tieneAlta = noSeAlta || (materiaAlta && horarioAlta);
      const tieneBaja = materiaBaja && horarioBaja;

      if (!tieneAlta && !tieneBaja) {
        showToast?.("Completa al menos la información de una materia (alta o baja).", "warn");
        return "";
      }

      if (tieneAlta && !tieneBaja) {
        if (noSeAlta) return "Solicitud de alta (materia y horario no especificados).";
        return `Solicitud de alta de la materia ${materiaAlta} en el horario ${horarioAlta}.`;
      }
      if (!tieneAlta && tieneBaja) {
        return `Solicitud de baja de la materia ${materiaBaja} en el horario ${horarioBaja}.`;
      }
      // ambas
      const altaTxt = noSeAlta ? "alta (materia y horario no especificados)" : `alta de la materia ${materiaAlta} en el horario ${horarioAlta}`;
      const bajaTxt = `baja de la materia ${materiaBaja} en el horario ${horarioBaja}`;
      return `Se solicita ${bajaTxt} y ${altaTxt}.`;
    }

    return "";
  }

  // === INLINE VALIDATION ===
  function setFieldError(fieldId, message) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    el.classList.add("is-invalid");
    let fb = el.nextElementSibling;
    if (!fb || !fb.classList.contains("invalid-feedback")) {
      fb = document.createElement("div");
      fb.className = "invalid-feedback";
      el.insertAdjacentElement("afterend", fb);
    }
    fb.textContent = message;
  }

  function clearFieldError(fieldId) {
    const el = document.getElementById(fieldId);
    if (!el) return;
    el.classList.remove("is-invalid");
    const fb = el.nextElementSibling;
    if (fb?.classList.contains("invalid-feedback")) fb.textContent = "";
  }

  function clearAllErrors() {
    document.querySelectorAll(".is-invalid").forEach(el => el.classList.remove("is-invalid"));
    document.querySelectorAll(".invalid-feedback").forEach(el => { el.textContent = ""; });
  }

  // === UTILIDADES ===
  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
