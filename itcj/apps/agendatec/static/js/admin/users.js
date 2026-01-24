// static/js/admin/users.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminUsersCfg || {};
  const listUrl = cfg.listUrl || "/api/agendatec/v1/admin/users/coordinators";
  const createUrl = cfg.createUrl || "/api/agendatec/v1/admin/users/coordinators";
  const updateBase = cfg.updateBase || "/api/agendatec/v1/admin/users/coordinators/";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v1/programs";
  const searchUsersUrl = cfg.searchUsersUrl || "/api/agendatec/v1/admin/users/search";

  // Estado del modal
  let currentMode = "new"; // "new" o "existing"
  let selectedUserId = null;
  let isEditMode = false;

  // Carga inicial
  loadPrograms();
  reload();

  // Event listeners principales
  $("#btnReload")?.addEventListener("click", reload);
  $("#btnNew")?.addEventListener("click", openNewModal);
  $("#txtSearch")?.addEventListener("input", debounce(reload, 300));
  $("#fltProgram")?.addEventListener("change", reload);
  $("#btnSaveCoord")?.addEventListener("click", saveCoord);

  // Event listeners para el modo de creacion
  $('input[name="coordMode"]')?.forEach?.((radio) => {
    radio.addEventListener("change", handleModeChange);
  });
  document.querySelectorAll('input[name="coordMode"]').forEach((radio) => {
    radio.addEventListener("change", handleModeChange);
  });

  // Event listeners para busqueda de usuarios
  $("#fUserSearch")?.addEventListener("input", debounce(searchUsers, 300));
  $("#fUserSearch")?.addEventListener("focus", () => {
    const val = $("#fUserSearch").value.trim();
    if (val.length >= 2) searchUsers();
  });
  $("#btnClearUser")?.addEventListener("click", clearSelectedUser);

  // Cerrar dropdown al hacer clic fuera
  document.addEventListener("click", (e) => {
    const searchBox = $("#fUserSearch");
    const results = $("#userSearchResults");
    if (searchBox && results && !searchBox.contains(e.target) && !results.contains(e.target)) {
      results.classList.add("d-none");
    }
  });

  // ========== Funciones principales ==========

  async function reload() {
    const qs = new URLSearchParams();
    const q = $("#txtSearch")?.value?.trim();
    const pid = $("#fltProgram")?.value;
    if (q) qs.set("q", q);
    if (pid) qs.set("program_id", pid);

    try {
      const r = await fetch(`${listUrl}?${qs.toString()}`, { credentials: "include" });
      if (!r.ok) throw new Error();
      const j = await r.json();
      renderTable(j.items || []);
    } catch {
      showToast?.("Error al cargar coordinadores", "error");
    }
  }

  function renderTable(items) {
    const tb = $("#tblCoordsBody");
    if (!items.length) {
      tb.innerHTML = `<tr><td colspan="4" class="text-muted">Sin resultados.</td></tr>`;
      return;
    }
    tb.innerHTML = items
      .map((c) => {
        const progs = (c.programs || []).map((p) => escapeHtml(p.name)).join(", ") || "—";
        return `<tr>
          <td>${escapeHtml(c.name || "—")}</td>
          <td>${escapeHtml(c.email || "—")}</td>
          <td>${progs}</td>
          <td class="text-end">
            <button class="btn btn-sm btn-outline-primary" data-edit="${c.id}">
              <i class="bi bi-pencil-square"></i>
            </button>
          </td>
        </tr>`;
      })
      .join("");
  }

  // ========== Modal: Nuevo coordinador ==========

  function openNewModal() {
    isEditMode = false;
    selectedUserId = null;
    currentMode = "new";

    // Reset UI
    $("#mdlTitle").textContent = "Nuevo coordinador";
    $("#modeSelector").classList.remove("d-none");
    $("#modeNew").checked = true;

    // Mostrar seccion de usuario nuevo, ocultar existente
    $("#newUserSection").classList.remove("d-none");
    $("#existingUserSection").classList.add("d-none");

    // Limpiar campos
    $("#fName").value = "";
    $("#fEmail").value = "";
    $("#fUsername").value = "";
    $("#fUserSearch").value = "";
    $("#fUserId").value = "";
    $("#selectedUserCard").classList.add("d-none");
    $("#userSearchResults").classList.add("d-none");

    // Limpiar programas
    const sel = $("#fPrograms");
    for (const opt of sel.options) opt.selected = false;

    $("#btnSaveCoord").dataset.id = "";
    new bootstrap.Modal($("#mdlCoord")).show();
  }

  // ========== Modal: Editar coordinador ==========

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-edit]");
    if (!btn) return;
    const id = btn.getAttribute("data-edit");
    await openEditModal(id);
  });

  async function openEditModal(id) {
    try {
      const r = await fetch(`${listUrl}?q=&limit=9999`, { credentials: "include" });
      const j = await r.json();
      const it = (j.items || []).find((x) => String(x.id) === String(id));
      if (!it) throw new Error();

      isEditMode = true;
      selectedUserId = it.user_id;
      currentMode = "existing"; // En edicion siempre es usuario existente

      $("#mdlTitle").textContent = "Editar coordinador";

      // Ocultar selector de modo en edicion
      $("#modeSelector").classList.add("d-none");

      // Mostrar seccion de usuario nuevo (para mostrar nombre/email editables)
      $("#newUserSection").classList.remove("d-none");
      $("#existingUserSection").classList.add("d-none");

      // Llenar campos
      $("#fName").value = it.name || "";
      $("#fEmail").value = it.email || "";
      $("#fUsername").value = ""; // No mostramos el username en edicion

      // Seleccionar programas
      const sel = $("#fPrograms");
      const ids = new Set((it.programs || []).map((p) => String(p.id)));
      for (const opt of sel.options) opt.selected = ids.has(opt.value);

      $("#btnSaveCoord").dataset.id = String(it.id);
      new bootstrap.Modal($("#mdlCoord")).show();
    } catch {
      showToast?.("No se pudo abrir el modal", "error");
    }
  }

  // ========== Cambio de modo (nuevo/existente) ==========

  function handleModeChange(e) {
    currentMode = e.target.value;

    if (currentMode === "new") {
      $("#newUserSection").classList.remove("d-none");
      $("#existingUserSection").classList.add("d-none");
      clearSelectedUser();
    } else {
      $("#newUserSection").classList.add("d-none");
      $("#existingUserSection").classList.remove("d-none");
      // Limpiar campos de usuario nuevo
      $("#fName").value = "";
      $("#fEmail").value = "";
      $("#fUsername").value = "";
    }
  }

  // ========== Busqueda de usuarios existentes ==========

  async function searchUsers() {
    const q = $("#fUserSearch")?.value?.trim() || "";
    const resultsDiv = $("#userSearchResults");

    if (q.length < 2) {
      resultsDiv.classList.add("d-none");
      return;
    }

    try {
      const r = await fetch(`${searchUsersUrl}?q=${encodeURIComponent(q)}`, { credentials: "include" });
      if (!r.ok) throw new Error();
      const j = await r.json();
      const items = j.items || [];

      if (items.length === 0) {
        resultsDiv.innerHTML = `<div class="p-2 text-muted small">No se encontraron usuarios</div>`;
      } else {
        resultsDiv.innerHTML = items.map((u) => `
          <div class="p-2 border-bottom user-search-item" style="cursor: pointer;"
               data-user-id="${u.id}"
               data-user-name="${escapeHtml(u.full_name)}"
               data-user-email="${escapeHtml(u.email || '')}">
            <div class="fw-semibold">${escapeHtml(u.full_name)}</div>
            <small class="text-muted">${escapeHtml(u.email || u.username || "Sin correo")}</small>
          </div>
        `).join("");

        // Event listeners para seleccionar usuario
        resultsDiv.querySelectorAll(".user-search-item").forEach((item) => {
          item.addEventListener("click", () => selectUser(item));
        });
      }
      resultsDiv.classList.remove("d-none");
    } catch (err) {
      console.error("Error buscando usuarios:", err);
      resultsDiv.innerHTML = `<div class="p-2 text-danger small">Error al buscar</div>`;
      resultsDiv.classList.remove("d-none");
    }
  }

  function selectUser(item) {
    const userId = item.dataset.userId;
    const userName = item.dataset.userName;
    const userEmail = item.dataset.userEmail;

    selectedUserId = parseInt(userId, 10);
    $("#fUserId").value = userId;
    $("#selectedUserName").textContent = userName;
    $("#selectedUserEmail").textContent = userEmail || "Sin correo";

    // Ocultar busqueda, mostrar card de seleccion
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

  // ========== Guardar coordinador ==========

  async function saveCoord() {
    const id = $("#btnSaveCoord").dataset.id || "";
    const programs = Array.from($("#fPrograms").selectedOptions).map((o) => Number(o.value));

    try {
      if (id) {
        // ===== ACTUALIZAR =====
        const name = $("#fName").value.trim();
        const email = $("#fEmail").value.trim();

        if (!name) {
          showToast?.("Nombre es requerido", "warning");
          return;
        }

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
        // ===== CREAR =====
        let payload = { program_ids: programs };

        if (currentMode === "existing") {
          // Modo: Usuario existente
          if (!selectedUserId) {
            showToast?.("Debes seleccionar un usuario", "warning");
            return;
          }
          payload.user_id = selectedUserId;
        } else {
          // Modo: Usuario nuevo
          const name = $("#fName").value.trim();
          const email = $("#fEmail").value.trim();
          const username = $("#fUsername").value.trim();

          if (!name) {
            showToast?.("Nombre es requerido", "warning");
            return;
          }

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
          if (err.error === "already_coordinator") {
            showToast?.("Este usuario ya es coordinador", "warning");
          } else if (err.error === "username_exists") {
            showToast?.("El nombre de usuario ya existe", "warning");
          } else if (err.error === "user_not_found") {
            showToast?.("Usuario no encontrado", "error");
          } else {
            showToast?.(err.message || "Error al crear coordinador", "error");
          }
          return;
        }

        const result = await r.json();
        if (result.created_new_user) {
          showToast?.("Coordinador y usuario creados exitosamente", "success");
        } else {
          showToast?.("Coordinador creado exitosamente", "success");
        }
      }

      bootstrap.Modal.getInstance($("#mdlCoord"))?.hide();
      reload();
    } catch (err) {
      showToast?.(err.message || "No se pudo guardar", "error");
    }
  }

  // ========== Cargar programas ==========

  async function loadPrograms() {
    try {
      const r = await fetch(programsUrl, { credentials: "include" });
      if (!r.ok) throw new Error();
      const data = await r.json();
      const arr = Array.isArray(data) ? data : (data.items || data.programs || []);
      fillSelect($("#fltProgram"), [{ id: "", name: "Todos los programas" }, ...arr]);
      fillSelect($("#fPrograms"), arr, { multiple: true });
    } catch {
      console.warn("No se pudieron cargar programas");
    }
  }

  // ========== Utilidades ==========

  function fillSelect(sel, items, opts = {}) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items
      .map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`)
      .join("");
    if (opts.multiple) sel.multiple = true;
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function debounce(fn, t) {
    let h;
    return (...a) => {
      clearTimeout(h);
      h = setTimeout(() => fn(...a), t);
    };
  }
})();
