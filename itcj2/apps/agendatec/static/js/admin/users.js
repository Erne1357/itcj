// static/js/admin/users.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg          = window.__adminUsersCfg || {};
  const listUrl      = cfg.listUrl      || "/api/agendatec/v2/admin/users/coordinators";
  const createUrl    = cfg.createUrl    || "/api/agendatec/v2/admin/users/coordinators";
  const updateBase   = cfg.updateBase   || "/api/agendatec/v2/admin/users/coordinators/";
  const programsUrl  = cfg.programsUrl  || "/api/agendatec/v2/programs";
  const searchUsersUrl = cfg.searchUsersUrl || "/api/agendatec/v2/admin/users/search";

  // === ESTADO DEL MÓDULO ===
  let currentMode    = "new"; // "new" | "existing"
  let selectedUserId = null;
  let isEditMode     = false;
  let multiSelectApi = null; // instancia del MultiSelect

  // === INICIALIZACIÓN ===
  loadPrograms();
  reload();

  $("#btnReload")?.addEventListener("click", reload);
  $("#btnNew")?.addEventListener("click", openNewModal);
  $("#txtSearch")?.addEventListener("input", debounce(reload, 300));
  $("#fltProgram")?.addEventListener("change", reload);
  $("#btnSaveCoord")?.addEventListener("click", saveCoord);

  document.querySelectorAll('input[name="coordMode"]').forEach((radio) => {
    radio.addEventListener("change", handleModeChange);
  });

  $("#fUserSearch")?.addEventListener("input", debounce(searchUsers, 300));
  $("#fUserSearch")?.addEventListener("focus", () => {
    if (($("#fUserSearch").value.trim()).length >= 2) searchUsers();
  });
  $("#btnClearUser")?.addEventListener("click", clearSelectedUser);

  document.addEventListener("click", (e) => {
    const searchBox = $("#fUserSearch");
    const results   = $("#userSearchResults");
    if (searchBox && results && !searchBox.contains(e.target) && !results.contains(e.target)) {
      results.classList.add("d-none");
    }
  });

  // === CARGA PRINCIPAL ===
  async function reload() {
    const tb = $("#tblCoordsBody");
    if (!tb) return;

    // Skeleton
    if (window.AgendaTec?.Skeleton) {
      tb.innerHTML = window.AgendaTec.Skeleton.tableRows(4, 4, { withActions: true });
    }

    const qs = new URLSearchParams();
    const q   = $("#txtSearch")?.value?.trim();
    const pid = $("#fltProgram")?.value;
    if (q)   qs.set("q", q);
    if (pid) qs.set("program_id", pid);

    try {
      const r = await fetch(`${listUrl}?${qs.toString()}`, { credentials: "include" });
      if (!r.ok) throw new Error();
      const j = await r.json();
      renderTable(j.items || []);
    } catch {
      showToast?.("Error al cargar coordinadores", "error");
      tb.innerHTML = `<tr><td colspan="4" class="text-center text-danger small py-3">
        <i class="bi bi-exclamation-triangle me-1"></i>Error al cargar datos</td></tr>`;
    }
  }

  function renderTable(items) {
    const tb = $("#tblCoordsBody");
    if (!items.length) {
      tb.innerHTML = `
        <tr>
          <td colspan="4">
            <div class="at-empty py-4">
              <i class="bi bi-person-x fs-3" aria-hidden="true"></i>
              <p class="mt-2 mb-1">Sin coordinadores</p>
              <button type="button" class="btn btn-sm btn-primary" id="btnNewFromEmpty">
                <i class="bi bi-person-plus me-1"></i>Crear coordinador
              </button>
            </div>
          </td>
        </tr>`;
      document.getElementById("btnNewFromEmpty")?.addEventListener("click", openNewModal);
      return;
    }
    tb.innerHTML = items.map((c) => {
      const progs = (c.programs || []).map((p) => escapeHtml(p.name)).join(", ") || "—";
      return `<tr>
        <td data-at-label="Nombre">${escapeHtml(c.name || "—")}</td>
        <td data-at-label="Correo">${escapeHtml(c.email || "—")}</td>
        <td data-at-label="Programas">${progs}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-outline-primary" data-edit="${c.id}" aria-label="Editar coordinador ${escapeHtml(c.name || '')}">
            <i class="bi bi-pencil-square" aria-hidden="true"></i>
          </button>
        </td>
      </tr>`;
    }).join("");

    if (window.AgendaTec?.TableCard) {
      window.AgendaTec.TableCard.syncLabels(tb.closest("table"));
    }
  }

  // === MODAL NUEVO ===
  function openNewModal() {
    isEditMode     = false;
    selectedUserId = null;
    currentMode    = "new";

    $("#mdlTitle").textContent = "Nuevo coordinador";
    $("#modeSelector").classList.remove("d-none");
    $("#modeNew").checked = true;
    $("#newUserSection").classList.remove("d-none");
    $("#existingUserSection").classList.add("d-none");
    $("#fName").value = "";
    $("#fEmail").value = "";
    $("#fUsername").value = "";
    $("#fUserSearch").value = "";
    $("#fUserId").value = "";
    $("#selectedUserCard").classList.add("d-none");
    $("#userSearchResults").classList.add("d-none");

    // Reset multiselect
    if (multiSelectApi) {
      Array.from($("#fPrograms").options).forEach((o) => { o.selected = false; });
      multiSelectApi.refresh();
    }

    $("#btnSaveCoord").dataset.id = "";
    new bootstrap.Modal($("#mdlCoord")).show();
  }

  // === MODAL EDITAR ===
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-edit]");
    if (!btn) return;
    await openEditModal(btn.getAttribute("data-edit"));
  });

  async function openEditModal(id) {
    try {
      const r  = await fetch(`${listUrl}?q=&limit=9999`, { credentials: "include" });
      const j  = await r.json();
      const it = (j.items || []).find((x) => String(x.id) === String(id));
      if (!it) throw new Error();

      isEditMode     = true;
      selectedUserId = it.user_id;
      currentMode    = "existing";

      $("#mdlTitle").textContent = "Editar coordinador";
      $("#modeSelector").classList.add("d-none");
      $("#newUserSection").classList.remove("d-none");
      $("#existingUserSection").classList.add("d-none");
      $("#fName").value  = it.name  || "";
      $("#fEmail").value = it.email || "";
      $("#fUsername").value = "";

      // Seleccionar programas
      const ids = new Set((it.programs || []).map((p) => String(p.id)));
      Array.from($("#fPrograms").options).forEach((o) => { o.selected = ids.has(o.value); });
      if (multiSelectApi) multiSelectApi.refresh();

      $("#btnSaveCoord").dataset.id = String(it.id);
      new bootstrap.Modal($("#mdlCoord")).show();
    } catch {
      showToast?.("No se pudo abrir el modal", "error");
    }
  }

  // === CAMBIO DE MODO ===
  function handleModeChange(e) {
    currentMode = e.target.value;
    if (currentMode === "new") {
      $("#newUserSection").classList.remove("d-none");
      $("#existingUserSection").classList.add("d-none");
      clearSelectedUser();
    } else {
      $("#newUserSection").classList.add("d-none");
      $("#existingUserSection").classList.remove("d-none");
      $("#fName").value = "";
      $("#fEmail").value = "";
      $("#fUsername").value = "";
    }
  }

  // === BÚSQUEDA DE USUARIOS EXISTENTES ===
  async function searchUsers() {
    const q = $("#fUserSearch")?.value?.trim() || "";
    const resultsDiv = $("#userSearchResults");
    if (q.length < 2) { resultsDiv.classList.add("d-none"); return; }

    try {
      const r = await fetch(`${searchUsersUrl}?q=${encodeURIComponent(q)}`, { credentials: "include" });
      if (!r.ok) throw new Error();
      const j = await r.json();
      const items = j.items || [];

      if (!items.length) {
        resultsDiv.innerHTML = `<div class="p-2 text-muted small">No se encontraron usuarios</div>`;
      } else {
        resultsDiv.innerHTML = items.map((u) => `
          <div class="p-2 border-bottom user-search-item" data-user-id="${u.id}"
               data-user-name="${escapeHtml(u.full_name)}"
               data-user-email="${escapeHtml(u.email || '')}"
               style="cursor:pointer;" tabindex="0" role="button"
               aria-label="Seleccionar ${escapeHtml(u.full_name)}">
            <div class="fw-semibold">${escapeHtml(u.full_name)}</div>
            <small class="text-muted">${escapeHtml(u.email || u.username || "Sin correo")}</small>
          </div>`).join("");

        resultsDiv.querySelectorAll(".user-search-item").forEach((item) => {
          item.addEventListener("click",   () => selectUser(item));
          item.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") selectUser(item); });
        });
      }
      resultsDiv.classList.remove("d-none");
    } catch {
      resultsDiv.innerHTML = `<div class="p-2 text-danger small">Error al buscar</div>`;
      resultsDiv.classList.remove("d-none");
    }
  }

  function selectUser(item) {
    selectedUserId = parseInt(item.dataset.userId, 10);
    $("#fUserId").value  = item.dataset.userId;
    $("#selectedUserName").textContent  = item.dataset.userName;
    $("#selectedUserEmail").textContent = item.dataset.userEmail || "Sin correo";
    $("#fUserSearch").value = "";
    $("#userSearchResults").classList.add("d-none");
    $("#selectedUserCard").classList.remove("d-none");
  }

  function clearSelectedUser() {
    selectedUserId = null;
    $("#fUserId").value = "";
    $("#selectedUserCard").classList.add("d-none");
    $("#fUserSearch").value = "";
  }

  // === GUARDAR COORDINADOR ===
  async function saveCoord() {
    const id       = $("#btnSaveCoord").dataset.id || "";
    const programs = Array.from($("#fPrograms").selectedOptions).map((o) => Number(o.value));

    const btn          = $("#btnSaveCoord");
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Guardando...';

    try {
      if (id) {
        // ACTUALIZAR
        const name  = $("#fName").value.trim();
        const email = $("#fEmail").value.trim();
        if (!name) { showToast?.("Nombre es requerido", "warning"); return; }

        const r = await fetch(`${updateBase}${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ name, email, program_ids: programs }),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          throw new Error(err.message || "Error al actualizar");
        }
        showToast?.("Coordinador actualizado", "success");
      } else {
        // CREAR
        let payload = { program_ids: programs };

        if (currentMode === "existing") {
          if (!selectedUserId) { showToast?.("Debes seleccionar un usuario", "warning"); return; }
          payload.user_id = selectedUserId;
        } else {
          const name     = $("#fName").value.trim();
          const email    = $("#fEmail").value.trim();
          const username = $("#fUsername").value.trim();
          if (!name) { showToast?.("Nombre es requerido", "warning"); return; }
          payload.name = name;
          payload.email = email;
          payload.username = username;
        }

        const r = await fetch(createUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          const errMap = {
            already_coordinator: "Este usuario ya es coordinador",
            username_exists:     "El nombre de usuario ya existe",
            user_not_found:      "Usuario no encontrado",
          };
          showToast?.(errMap[err.error] || err.message || "Error al crear coordinador",
            err.error ? "warning" : "error");
          return;
        }
        const result = await r.json();
        showToast?.(result.created_new_user
          ? "Coordinador y usuario creados exitosamente"
          : "Coordinador creado exitosamente", "success");
      }

      bootstrap.Modal.getInstance($("#mdlCoord"))?.hide();
      reload();
    } catch (err) {
      showToast?.(err.message || "No se pudo guardar", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }

  // === CARGAR PROGRAMAS ===
  async function loadPrograms() {
    try {
      const r = await fetch(programsUrl, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const arr  = Array.isArray(data) ? data : (data.items || data.programs || []);

      fillSelect($("#fltProgram"), [{ id: "", name: "Todos los programas" }, ...arr]);
      fillSelect($("#fPrograms"), arr, { multiple: true });

      // Inicializar MultiSelect sobre #fPrograms
      if (window.AgendaTec?.MultiSelect && document.getElementById("fPrograms")) {
        multiSelectApi = window.AgendaTec.MultiSelect.create("#fPrograms", {
          placeholder:       "Seleccionar programas…",
          searchPlaceholder: "Buscar programa…",
        });
      }
    } catch {
      console.warn("No se pudieron cargar programas");
    }
  }

  // === UTILIDADES ===
  function fillSelect(sel, items, opts = {}) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items.map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("");
    if (opts.multiple) sel.multiple = true;
  }

  function escapeHtml(s) {
    return (s || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function debounce(fn, t) {
    let h;
    return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), t); };
  }
})();
