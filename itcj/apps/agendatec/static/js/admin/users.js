// static/js/admin/users.js
(() => {
  const $ = (s) => document.querySelector(s);
  const cfg = window.__adminUsersCfg || {};
  const listUrl = cfg.listUrl || "/api/agendatec/v1/admin/users/coordinators";
  const createUrl = cfg.createUrl || "/api/agendatec/v1/admin/users/coordinators";
  const updateBase = cfg.updateBase || "/api/agendatec/v1/admin/users/coordinators/"; // + id
  const programsUrl = cfg.programsUrl || "/api/agendatec/v1/programs";

  // Carga inicial
  loadPrograms();
  reload();

  $("#btnReload")?.addEventListener("click", reload);
  $("#btnNew")?.addEventListener("click", openNewModal);
  $("#txtSearch")?.addEventListener("input", debounce(reload, 300));
  $("#fltProgram")?.addEventListener("change", reload);
  $("#btnSaveCoord")?.addEventListener("click", saveCoord);

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

  function openNewModal() {
    $("#mdlTitle").textContent = "Nuevo coordinador";
    $("#fName").value = "";
    $("#fEmail").value = "";
    $("#fNip").value = "1234";
    $("#fPrograms").value = [];
    $("#btnSaveCoord").dataset.id = ""; // crear
    new bootstrap.Modal($("#mdlCoord")).show();
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-edit]");
    if (!btn) return;
    const id = btn.getAttribute("data-edit");
    await openEditModal(id);
  });

  async function openEditModal(id) {
    // Obtener lista y buscar uno (para no crear endpoint extra)
    try {
      const r = await fetch(`${listUrl}?q=&limit=9999`, { credentials: "include" });
      const j = await r.json();
      const it = (j.items || []).find((x) => String(x.id) === String(id));
      if (!it) throw new Error();
      $("#mdlTitle").textContent = "Editar coordinador";
      $("#fName").value = it.name || "";
      $("#fEmail").value = it.email || "";
      $("#fNip").value = ""; // no mostramos nip actual
      // seleccionar programas
      const sel = $("#fPrograms");
      const ids = new Set((it.programs || []).map((p) => String(p.id)));
      for (const opt of sel.options) opt.selected = ids.has(opt.value);
      $("#btnSaveCoord").dataset.id = String(it.id); // actualizar
      new bootstrap.Modal($("#mdlCoord")).show();
    } catch {
      showToast?.("No se pudo abrir el modal", "error");
    }
  }

  async function saveCoord() {
    const id = $("#btnSaveCoord").dataset.id || "";
    const name = $("#fName").value.trim();
    const email = $("#fEmail").value.trim();
    const nip = $("#fNip").value.trim();
    const programs = Array.from($("#fPrograms").selectedOptions).map((o) => Number(o.value));

    if (!name) {
      showToast?.("Nombre es requerido", "warning");
      return;
    }
    try {
      if (id) {
        // update
        const r = await fetch(`${updateBase}${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ name, email, program_ids: programs }),
        });
        if (!r.ok) throw new Error();
        showToast?.("Coordinador actualizado", "success");
      } else {
        // create
        const payload = { name, email, program_ids: programs };
        if (nip) payload.nip = nip;
        const r = await fetch(createUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error();
        showToast?.("Coordinador creado", "success");
      }
      bootstrap.Modal.getInstance($("#mdlCoord"))?.hide();
      reload();
    } catch {
      showToast?.("No se pudo guardar", "error");
    }
  }

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
