(() => {
  const $ = (sel) => document.querySelector(sel);

  const programSelect = $("#programSelect");
  const numPlazos = $("#numPlazos");
  const justificacion = $("#justificacion");
  const charCount = $("#charCount");
  const btnSubmit = $("#btnSubmit");

  const MAX_CHARS = 900;

  function updateSubmitDisabled() {
    const valid =
      programSelect.value !== "" &&
      numPlazos.value !== "" &&
      justificacion.value.trim().length > 0;
    btnSubmit.disabled = !valid;
  }

  function showToast(message, type = "info") {
    // Reemplaza esto por tu helper de toasts si ya tienes uno global.
    if (window.showToast && window.showToast !== showToast) {
      window.showToast(message, type);
      return;
    }
    alert(message);
  }

  async function loadPrograms() {
    programSelect.disabled = true;
    programSelect.innerHTML = `<option value="">Cargando...</option>`;
    try {
      const r = await fetch("/api/prorrogas/v2/programs", { credentials: "include" });
      if (!r.ok) throw 0;
      const data = await r.json();
      const items = data.items || [];
      programSelect.innerHTML =
        `<option value="">Selecciona tu carrera...</option>` +
        items.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
    } catch {
      programSelect.innerHTML = `<option value="">No se pudieron cargar los programas</option>`;
      showToast("No se pudieron cargar los programas.", "error");
    } finally {
      programSelect.disabled = false;
      updateSubmitDisabled();
    }
  }

  programSelect.addEventListener("change", updateSubmitDisabled);
  numPlazos.addEventListener("change", updateSubmitDisabled);

  justificacion.addEventListener("input", () => {
    const remaining = MAX_CHARS - justificacion.value.length;
    charCount.textContent = `${remaining} caracteres disponibles`;
    updateSubmitDisabled();
  });

  btnSubmit.addEventListener("click", async () => {
    const program_id = parseInt(programSelect.value, 10);
    const payments_terms = parseInt(numPlazos.value, 10);
    const letter = justificacion.value.trim();

    if (!program_id) {
      showToast("Selecciona tu carrera.", "warn");
      return;
    }
    if (!payments_terms || payments_terms < 1 || payments_terms > 3) {
      showToast("Selecciona un número de plazos válido (máximo 3).", "warn");
      return;
    }
    if (!letter) {
      showToast("Escribe la justificación de tu solicitud.", "warn");
      return;
    }

    btnSubmit.disabled = true;

    try {
      const r = await fetch(`/api/prorrogas/v2/request2`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ program_id, payments_terms, letter }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        console.error("Error al crear solicitud:", r.status, err);
        showToast(err.detail || err.message || `No se pudo crear la solicitud (HTTP ${r.status}).`, "error");
        btnSubmit.disabled = false;
        return;
      }

      showToast("Solicitud creada correctamente.", "success");
      setTimeout(() => {
        window.location.href = "/prorrogas/student/requests";
      }, 500);
    } catch {
      showToast("No se pudo conectar con el servidor.", "error");
      btnSubmit.disabled = false;
    }
  });

  // Carga inicial
  loadPrograms();
  updateSubmitDisabled();
})();