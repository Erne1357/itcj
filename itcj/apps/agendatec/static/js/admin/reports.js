// static/js/admin/reports.js
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const cfg = window.__adminReportsCfg || {};
  const xlsxUrl = cfg.xlsxUrl || "/api/agendatec/v1/admin/reports/requests.xlsx";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v1/programs";
  const coordsUrl = cfg.coordsUrl || "/api/agendatec/v1/admin/users/coordinators";
  const periodsUrl = cfg.periodsUrl || "/api/agendatec/v1/periods";

  let activePeriodId = null;

  initDates();
  initMultiSelects();
  initDropdownAutoPosition();
  loadProgramsAndCoords();
  initColumnConfig();

  $("#btnXlsx")?.addEventListener("click", exportXlsx);

  function initDates() {
    const to = new Date();
    const from = new Date(Date.now() - 30 * 86400000);
    $("#repTo").value = to.toISOString().slice(0, 10);
    $("#repFrom").value = from.toISOString().slice(0, 10);
  }

  // ==================== MULTI-SELECT ====================

  function initMultiSelects() {
    // Configurar listeners para los dropdowns multi-select existentes
    setupMultiSelectListeners("#repStatusMenu");
    setupMultiSelectListeners("#repAppStatusMenu");
    setupMultiSelectListeners("#repProgramMenu");
    setupMultiSelectListeners("#repCoordMenu");
  }

  /**
   * Ajusta automáticamente la posición del dropdown si se sale del viewport
   */
  function initDropdownAutoPosition() {
    document.querySelectorAll(".multi-select-dropdown").forEach((dropdown) => {
      dropdown.addEventListener("shown.bs.dropdown", () => {
        const menu = dropdown.querySelector(".dropdown-menu");
        if (!menu) return;

        // Reset para medir correctamente
        menu.classList.remove("dropdown-menu-end");
        menu.style.left = "";
        menu.style.right = "";

        const rect = menu.getBoundingClientRect();
        const viewportWidth = window.innerWidth;

        // Si el menú se sale por la derecha, alinearlo a la derecha
        if (rect.right > viewportWidth - 10) {
          menu.classList.add("dropdown-menu-end");
        }
      });
    });
  }

  function setupMultiSelectListeners(menuSelector) {
    const menu = $(menuSelector);
    if (!menu) return;

    menu.addEventListener("change", (e) => {
      if (e.target.type === "checkbox") {
        updateMultiSelectLabel(menu);
      }
    });
  }

  function updateMultiSelectLabel(menu) {
    const dropdown = menu.closest(".multi-select-dropdown");
    if (!dropdown) return;

    const label = dropdown.querySelector(".multi-select-label");
    const defaultText = label?.dataset.default || "Todos";
    const checkboxes = menu.querySelectorAll('input[type="checkbox"]');
    const checked = [...checkboxes].filter((cb) => cb.checked);

    if (checked.length === 0) {
      label.textContent = defaultText;
      label.classList.remove("fw-semibold");
    } else if (checked.length === 1) {
      // Mostrar el nombre de la opción seleccionada
      const labelText = checked[0].closest("label")?.textContent?.trim() || checked[0].value;
      label.textContent = labelText;
      label.classList.add("fw-semibold");
    } else {
      label.textContent = `${checked.length} seleccionados`;
      label.classList.add("fw-semibold");
    }
  }

  function getMultiSelectValues(menuSelector) {
    const menu = $(menuSelector);
    if (!menu) return [];
    const checkboxes = menu.querySelectorAll('input[type="checkbox"]:checked');
    return [...checkboxes].map((cb) => cb.value);
  }

  function fillMultiSelectMenu(menuSelector, items) {
    const menu = $(menuSelector);
    if (!menu || !Array.isArray(items)) return;

    menu.innerHTML = items
      .map(
        (item) => `
        <li><label class="dropdown-item d-flex align-items-center gap-2 py-1">
          <input type="checkbox" class="form-check-input m-0" value="${item.id}"> ${escapeHtml(item.name)}
        </label></li>
      `
      )
      .join("");

    // Re-attach listeners
    setupMultiSelectListeners(menuSelector);
  }

  // ==================== COLUMN CONFIG ====================

  function initColumnConfig() {
    // Configurar drag-and-drop para ambas listas
    setupDragAndDrop("#citasColumns");
    setupDragAndDrop("#bajasColumns");

    // Botones de seleccionar todas/ninguna
    $("#selectAllCitas")?.addEventListener("click", () => toggleAllChecks("#citasColumns", true));
    $("#selectNoneCitas")?.addEventListener("click", () => toggleAllChecks("#citasColumns", false));
    $("#selectAllBajas")?.addEventListener("click", () => toggleAllChecks("#bajasColumns", true));
    $("#selectNoneBajas")?.addEventListener("click", () => toggleAllChecks("#bajasColumns", false));

    // Toggle del chevron al abrir/cerrar
    const collapseEl = $("#columnsConfig");
    if (collapseEl) {
      collapseEl.addEventListener("show.bs.collapse", () => {
        $("#columnsChevron")?.classList.remove("bi-chevron-down");
        $("#columnsChevron")?.classList.add("bi-chevron-up");
      });
      collapseEl.addEventListener("hide.bs.collapse", () => {
        $("#columnsChevron")?.classList.remove("bi-chevron-up");
        $("#columnsChevron")?.classList.add("bi-chevron-down");
      });
    }
  }

  function toggleAllChecks(listSelector, checked) {
    const list = $(listSelector);
    if (!list) return;
    list.querySelectorAll(".col-check").forEach((cb) => {
      cb.checked = checked;
    });
  }

  function setupDragAndDrop(listSelector) {
    const list = $(listSelector);
    if (!list) return;

    let draggedItem = null;

    list.querySelectorAll(".list-group-item").forEach((item) => {
      item.setAttribute("draggable", "true");

      item.addEventListener("dragstart", (e) => {
        draggedItem = item;
        item.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", item.dataset.col);
      });

      item.addEventListener("dragend", () => {
        item.classList.remove("dragging");
        list.querySelectorAll(".list-group-item").forEach((i) => {
          i.classList.remove("drag-over");
        });
        draggedItem = null;
      });

      item.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (draggedItem && draggedItem !== item) {
          item.classList.add("drag-over");
        }
      });

      item.addEventListener("dragleave", () => {
        item.classList.remove("drag-over");
      });

      item.addEventListener("drop", (e) => {
        e.preventDefault();
        item.classList.remove("drag-over");
        if (draggedItem && draggedItem !== item) {
          const allItems = [...list.querySelectorAll(".list-group-item")];
          const draggedIndex = allItems.indexOf(draggedItem);
          const targetIndex = allItems.indexOf(item);

          if (draggedIndex < targetIndex) {
            item.parentNode.insertBefore(draggedItem, item.nextSibling);
          } else {
            item.parentNode.insertBefore(draggedItem, item);
          }
        }
      });
    });
  }

  function getColumnsConfig(listSelector) {
    const list = $(listSelector);
    if (!list) return [];
    const columns = [];
    list.querySelectorAll(".list-group-item").forEach((item) => {
      const checkbox = item.querySelector(".col-check");
      if (checkbox?.checked) {
        columns.push(item.dataset.col);
      }
    });
    return columns;
  }

  // ==================== DATA LOADING ====================

  async function loadProgramsAndCoords() {
    try {
      const [rp, rc, rper] = await Promise.all([
        fetch(programsUrl, { credentials: "include" }),
        fetch(coordsUrl, { credentials: "include" }),
        fetch(periodsUrl, { credentials: "include" }),
      ]);
      const pj = await rp.json();
      const cj = await rc.json();
      const perj = await rper.json();

      const progs = Array.isArray(pj) ? pj : pj.items || pj.programs || [];
      const coords = cj.items || [];
      const periods = Array.isArray(perj) ? perj : perj.items || perj.periods || [];

      // Llenar multi-selects de programas y coordinadores
      fillMultiSelectMenu("#repProgramMenu", progs.map((p) => ({ id: p.id, name: p.name })));
      fillMultiSelectMenu("#repCoordMenu", coords.map((c) => ({ id: c.id, name: c.name })));

      // Find active period
      const activePeriod = periods.find((p) => p.status === "ACTIVE");
      if (activePeriod) {
        activePeriodId = activePeriod.id;
      }

      // Fill periods select with "Todos" as first option and active period preselected
      const periodOptions = [{ id: "", name: "Todos los períodos" }, ...periods.map((p) => ({ id: p.id, name: p.name }))];
      fillSelect($("#repPeriod"), periodOptions);

      // Set active period as default
      if (activePeriodId) {
        $("#repPeriod").value = activePeriodId;
      }
    } catch {
      /* silent */
    }
  }

  // ==================== QUERY STRING & EXPORT ====================

  function buildQs() {
    const q = new URLSearchParams();
    const from = $("#repFrom")?.value;
    const to = $("#repTo")?.value;
    const type = $("#repType")?.value;
    const period = $("#repPeriod")?.value;
    const text = $("#repQ")?.value?.trim();
    const orderBy = $("#repOrderBy")?.value;
    const orderDir = $("#repOrderDir")?.value;
    const fileName = $("#repFileName")?.value?.trim();

    // Multi-selects
    const statuses = getMultiSelectValues("#repStatusMenu");
    const appStatuses = getMultiSelectValues("#repAppStatusMenu");
    const programs = getMultiSelectValues("#repProgramMenu");
    const coords = getMultiSelectValues("#repCoordMenu");

    // Obtener configuración de columnas
    const citasCols = getColumnsConfig("#citasColumns");
    const bajasCols = getColumnsConfig("#bajasColumns");

    if (from) q.set("from", from);
    if (to) q.set("to", to);
    if (type) q.set("type", type);
    if (period) q.set("period_id", period);
    if (text) q.set("q", text);
    if (orderBy) q.set("order_by", orderBy);
    if (orderDir) q.set("order_dir", orderDir);
    if (fileName) q.set("filename", fileName);

    // Multi-valores (separados por coma)
    if (statuses.length > 0) q.set("status", statuses.join(","));
    if (appStatuses.length > 0) q.set("appointment_status", appStatuses.join(","));
    if (programs.length > 0) q.set("program_id", programs.join(","));
    if (coords.length > 0) q.set("coordinator_id", coords.join(","));

    // Agregar columnas seleccionadas y su orden
    if (citasCols.length > 0) q.set("citas_cols", citasCols.join(","));
    if (bajasCols.length > 0) q.set("bajas_cols", bajasCols.join(","));

    return q.toString();
  }

  function getFileName() {
    const custom = $("#repFileName")?.value?.trim();
    if (custom) {
      // Sanitizar nombre de archivo
      return custom.replace(/[<>:"/\\|?*]/g, "_") + ".xlsx";
    }
    return `reporte_agendatec_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.xlsx`;
  }

  async function exportXlsx() {
    const btn = $("#btnXlsx");
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Generando...';

    try {
      const r = await fetch(`${xlsxUrl}?${buildQs()}`, {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) throw new Error();
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = getFileName();
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast?.("Reporte generado correctamente", "success");
    } catch {
      showToast?.("No se pudo generar el reporte", "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalText;
    }
  }

  // ==================== HELPERS ====================

  function fillSelect(sel, items) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items.map((x) => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join("");
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
