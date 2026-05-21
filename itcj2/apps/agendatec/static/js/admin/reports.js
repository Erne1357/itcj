/**
 * AgendaTec Admin — Reportes
 * Exportación de reportes Excel con filtros avanzados,
 * configuración de columnas (drag-and-drop + touch), y resúmenes.
 */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const cfg = window.__adminReportsCfg || {};
  const xlsxUrl = cfg.xlsxUrl || "/api/agendatec/v2/admin/reports/requests.xlsx";
  const programsUrl = cfg.programsUrl || "/api/agendatec/v2/programs";
  const coordsUrl = cfg.coordsUrl || "/api/agendatec/v2/admin/users/coordinators";
  const periodsUrl = cfg.periodsUrl || "/api/agendatec/v2/periods";

  let activePeriodId = null;

  // === INICIALIZACIÓN ===
  document.addEventListener("DOMContentLoaded", function () {
    initDates();
    initMultiSelects();
    initDropdownAutoPosition();
    loadProgramsAndCoords();
    initColumnConfig();
    initSummaryConfig();
    initSearchList();
    $("#btnXlsx")?.addEventListener("click", exportXlsx);
  });

  // === FECHAS ===
  function initDates() {
    const to = new Date();
    const from = new Date(Date.now() - 30 * 86400000);
    const toEl = $("#repTo");
    const fromEl = $("#repFrom");
    if (toEl) toEl.value = to.toISOString().slice(0, 10);
    if (fromEl) fromEl.value = from.toISOString().slice(0, 10);
  }

  // === SEARCH LIST ===
  function initSearchList() {
    const textarea = $("#repQ");
    const hint = $("#searchCountHint");
    const countSpan = $("#searchCount");
    const clearBtn = $("#clearSearchList");
    const separatorOptions = $$(".separator-option");

    if (!textarea) return;

    textarea.addEventListener("input", () => updateSearchHint());

    separatorOptions.forEach((opt) => {
      opt.addEventListener("click", (e) => {
        e.preventDefault();
        separatorOptions.forEach((o) => o.classList.remove("active"));
        opt.classList.add("active");
        updateSearchHint();
      });
    });

    clearBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      textarea.value = "";
      updateSearchHint();
      textarea.focus();
    });

    function updateSearchHint() {
      const items = getSearchItems();
      if (hint && countSpan) {
        hint.hidden = items.length === 0;
        countSpan.textContent = items.length;
      }
    }
  }

  function getSelectedSeparator() {
    const active = $(".separator-option.active");
    return active?.dataset.separator || "newline";
  }

  function getSearchItems() {
    const textarea = $("#repQ");
    if (!textarea) return [];
    const text = textarea.value?.trim();
    if (!text) return [];

    const sep = getSelectedSeparator();
    let separator;
    switch (sep) {
      case "comma":     separator = /[,]/; break;
      case "space":     separator = /\s+/; break;
      case "semicolon": separator = /[;]/; break;
      case "tab":       separator = /\t/; break;
      case "newline":
      default:          separator = /[\r\n]+/; break;
    }
    return text.split(separator).map((s) => s.trim()).filter((s) => s.length > 0);
  }

  // === MULTI-SELECT (dropdown con checkboxes, existente en reports) ===
  function initMultiSelects() {
    setupMultiSelectListeners("#repStatusMenu");
    setupMultiSelectListeners("#repAppStatusMenu");
    setupMultiSelectListeners("#repProgramMenu");
    setupMultiSelectListeners("#repCoordMenu");
  }

  function initDropdownAutoPosition() {
    document.querySelectorAll(".multi-select-dropdown").forEach((dropdown) => {
      dropdown.addEventListener("shown.bs.dropdown", () => {
        const menu = dropdown.querySelector(".dropdown-menu");
        if (!menu) return;
        menu.classList.remove("dropdown-menu-end");
        menu.style.left = "";
        menu.style.right = "";
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth - 10) {
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
    return [...menu.querySelectorAll('input[type="checkbox"]:checked')].map((cb) => cb.value);
  }

  function fillMultiSelectMenu(menuSelector, items) {
    const menu = $(menuSelector);
    if (!menu || !Array.isArray(items)) return;
    menu.innerHTML = items.map((item) => `
      <li><label class="dropdown-item d-flex align-items-center gap-2 py-1">
        <input type="checkbox" class="form-check-input m-0" value="${escapeHtml(String(item.id))}"> ${escapeHtml(item.name)}
      </label></li>
    `).join("");
    setupMultiSelectListeners(menuSelector);
  }

  // === COLUMN CONFIG ===
  function initColumnConfig() {
    setupDragAndDrop("#citasColumns");
    setupDragAndDrop("#bajasColumns");

    $("#selectAllCitas")?.addEventListener("click", () => toggleAllChecks("#citasColumns", true));
    $("#selectNoneCitas")?.addEventListener("click", () => toggleAllChecks("#citasColumns", false));
    $("#selectAllBajas")?.addEventListener("click", () => toggleAllChecks("#bajasColumns", true));
    $("#selectNoneBajas")?.addEventListener("click", () => toggleAllChecks("#bajasColumns", false));

    const collapseEl = $("#columnsConfig");
    if (collapseEl) {
      collapseEl.addEventListener("show.bs.collapse", () => {
        $("#columnsChevron")?.classList.replace("bi-chevron-down", "bi-chevron-up");
      });
      collapseEl.addEventListener("hide.bs.collapse", () => {
        $("#columnsChevron")?.classList.replace("bi-chevron-up", "bi-chevron-down");
      });
    }
  }

  function toggleAllChecks(listSelector, checked) {
    $(listSelector)?.querySelectorAll(".col-check").forEach((cb) => { cb.checked = checked; });
  }

  function setupDragAndDrop(listSelector) {
    const list = $(listSelector);
    if (!list) return;

    let draggedItem = null;
    // Touch drag state
    let touchDragItem = null;
    let touchClone = null;
    let touchStartY = 0;

    list.querySelectorAll(".list-group-item").forEach((item) => {
      item.setAttribute("draggable", "true");

      // === Mouse drag events ===
      item.addEventListener("dragstart", (e) => {
        draggedItem = item;
        item.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", item.dataset.col);
      });

      item.addEventListener("dragend", () => {
        item.classList.remove("dragging");
        list.querySelectorAll(".list-group-item").forEach((i) => i.classList.remove("drag-over"));
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

      // === Touch drag events ===
      item.addEventListener("touchstart", (e) => {
        const handle = item.querySelector(".drag-handle");
        if (handle && !handle.contains(e.target) && e.target !== handle) return;

        touchDragItem = item;
        touchStartY = e.touches[0].clientY;
        item.classList.add("dragging");

        // Create floating clone for visual feedback
        touchClone = item.cloneNode(true);
        touchClone.style.position = "fixed";
        touchClone.style.zIndex = "9999";
        touchClone.style.opacity = "0.8";
        touchClone.style.pointerEvents = "none";
        touchClone.style.width = item.offsetWidth + "px";
        const rect = item.getBoundingClientRect();
        touchClone.style.left = rect.left + "px";
        touchClone.style.top = rect.top + "px";
        document.body.appendChild(touchClone);
      }, { passive: true });

      item.addEventListener("touchmove", (e) => {
        if (!touchDragItem || touchDragItem !== item) return;
        e.preventDefault();

        const touch = e.touches[0];
        if (touchClone) {
          touchClone.style.top = (touch.clientY - touchStartY + touchClone.getBoundingClientRect().top + (touch.clientY - e.changedTouches[0].clientY)) + "px";
          // Simpler: track by current touch Y
          touchClone.style.top = (touch.clientY - 20) + "px";
        }

        // Find drop target
        const elementBelow = document.elementFromPoint(touch.clientX, touch.clientY);
        const targetItem = elementBelow?.closest(".list-group-item");
        if (targetItem && targetItem !== touchDragItem && targetItem.closest(listSelector)) {
          list.querySelectorAll(".list-group-item").forEach((i) => i.classList.remove("drag-over"));
          targetItem.classList.add("drag-over");
        }
      }, { passive: false });

      item.addEventListener("touchend", (e) => {
        if (!touchDragItem || touchDragItem !== item) return;

        const touch = e.changedTouches[0];
        const elementBelow = document.elementFromPoint(touch.clientX, touch.clientY);
        const targetItem = elementBelow?.closest(".list-group-item");

        if (targetItem && targetItem !== touchDragItem && targetItem.closest(listSelector)) {
          const allItems = [...list.querySelectorAll(".list-group-item")];
          const draggedIndex = allItems.indexOf(touchDragItem);
          const targetIndex = allItems.indexOf(targetItem);
          if (draggedIndex < targetIndex) {
            targetItem.parentNode.insertBefore(touchDragItem, targetItem.nextSibling);
          } else {
            targetItem.parentNode.insertBefore(touchDragItem, targetItem);
          }
        }

        // Cleanup
        touchDragItem.classList.remove("dragging");
        list.querySelectorAll(".list-group-item").forEach((i) => i.classList.remove("drag-over"));
        touchClone?.remove();
        touchClone = null;
        touchDragItem = null;
      });
    });
  }

  function getColumnsConfig(listSelector) {
    const list = $(listSelector);
    if (!list) return [];
    const columns = [];
    list.querySelectorAll(".list-group-item").forEach((item) => {
      const checkbox = item.querySelector(".col-check");
      if (checkbox?.checked) columns.push(item.dataset.col);
    });
    return columns;
  }

  // === SUMMARY CONFIG ===
  function initSummaryConfig() {
    $("#selectAllCitasSummary")?.addEventListener("click", () => toggleAllSummaryChecks(".citas-summary-check", true));
    $("#selectNoneCitasSummary")?.addEventListener("click", () => toggleAllSummaryChecks(".citas-summary-check", false));
    $("#selectAllBajasSummary")?.addEventListener("click", () => toggleAllSummaryChecks(".bajas-summary-check", true));
    $("#selectNoneBajasSummary")?.addEventListener("click", () => toggleAllSummaryChecks(".bajas-summary-check", false));

    const collapseEl = $("#summaryConfig");
    if (collapseEl) {
      collapseEl.addEventListener("show.bs.collapse", () => {
        $("#summaryChevron")?.classList.replace("bi-chevron-down", "bi-chevron-up");
      });
      collapseEl.addEventListener("hide.bs.collapse", () => {
        $("#summaryChevron")?.classList.replace("bi-chevron-up", "bi-chevron-down");
      });
    }
  }

  function toggleAllSummaryChecks(selector, checked) {
    $$(selector).forEach((cb) => { cb.checked = checked; });
  }

  function getSummaryConfig(selector) {
    return [...$$(selector)].filter((cb) => cb.checked).map((cb) => cb.value);
  }

  // === DATA LOADING ===
  async function loadProgramsAndCoords() {
    // Skeleton en selects dinámicos durante carga
    const programMenu = $("#repProgramMenu");
    const coordMenu = $("#repCoordMenu");
    const periodSel = $("#repPeriod");
    const skLine = window.AgendaTec?.Skeleton?.line;

    if (skLine) {
      const skHtml = `<li class="px-2 py-1">${skLine("80%")}</li>`.repeat(4);
      if (programMenu) programMenu.innerHTML = skHtml;
      if (coordMenu) coordMenu.innerHTML = skHtml;
    }
    if (periodSel) periodSel.innerHTML = '<option value="">Cargando...</option>';

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

      fillMultiSelectMenu("#repProgramMenu", progs.map((p) => ({ id: p.id, name: p.name })));
      fillMultiSelectMenu("#repCoordMenu", coords.map((c) => ({ id: c.id, name: c.name })));

      const activePeriod = periods.find((p) => p.status === "ACTIVE");
      if (activePeriod) activePeriodId = activePeriod.id;

      const periodOptions = [{ id: "", name: "Todos los períodos" }, ...periods.map((p) => ({ id: p.id, name: p.name }))];
      fillSelect(periodSel, periodOptions);
      if (activePeriodId && periodSel) periodSel.value = activePeriodId;
    } catch {
      if (programMenu) programMenu.innerHTML = '<li class="px-2 py-1 text-muted small">Error al cargar</li>';
      if (coordMenu) coordMenu.innerHTML = '<li class="px-2 py-1 text-muted small">Error al cargar</li>';
      if (periodSel) periodSel.innerHTML = '<option value="">Error al cargar</option>';
    }
  }

  // === QUERY STRING & EXPORT ===
  function buildQs() {
    const q = new URLSearchParams();
    const from = $("#repFrom")?.value;
    const to = $("#repTo")?.value;
    const type = $("#repType")?.value;
    const period = $("#repPeriod")?.value;
    const searchItems = getSearchItems();
    const orderBy = $("#repOrderBy")?.value;
    const orderDir = $("#repOrderDir")?.value;
    const fileName = $("#repFileName")?.value?.trim();

    const statuses = getMultiSelectValues("#repStatusMenu");
    const appStatuses = getMultiSelectValues("#repAppStatusMenu");
    const programs = getMultiSelectValues("#repProgramMenu");
    const coords = getMultiSelectValues("#repCoordMenu");
    const citasCols = getColumnsConfig("#citasColumns");
    const bajasCols = getColumnsConfig("#bajasColumns");
    const citasSummary = getSummaryConfig(".citas-summary-check");
    const bajasSummary = getSummaryConfig(".bajas-summary-check");

    if (from) q.set("from", from);
    if (to) q.set("to", to);
    if (type) q.set("type", type);
    if (period) q.set("period_id", period);
    if (searchItems.length > 0) q.set("q", searchItems.join(","));
    if (orderBy) q.set("order_by", orderBy);
    if (orderDir) q.set("order_dir", orderDir);
    if (fileName) q.set("filename", fileName);
    if (statuses.length > 0) q.set("status", statuses.join(","));
    if (appStatuses.length > 0) q.set("appointment_status", appStatuses.join(","));
    if (programs.length > 0) q.set("program_id", programs.join(","));
    if (coords.length > 0) q.set("coordinator_id", coords.join(","));
    if (citasCols.length > 0) q.set("citas_cols", citasCols.join(","));
    if (bajasCols.length > 0) q.set("bajas_cols", bajasCols.join(","));
    if (citasSummary.length > 0) q.set("citas_summary", citasSummary.join(","));
    if (bajasSummary.length > 0) q.set("bajas_summary", bajasSummary.join(","));

    return q.toString();
  }

  function getFileName() {
    const custom = $("#repFileName")?.value?.trim();
    if (custom) return custom.replace(/[<>:"/\\|?*]/g, "_") + ".xlsx";
    return `reporte_agendatec_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.xlsx`;
  }

  async function exportXlsx() {
    const btn = $("#btnXlsx");
    if (!btn) return;
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Generando...';

    try {
      const r = await fetch(`${xlsxUrl}?${buildQs()}`, { method: "POST", credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
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
    } catch (err) {
      showToast?.(`No se pudo generar el reporte: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }

  // === HELPERS ===
  function fillSelect(sel, items) {
    if (!sel || !Array.isArray(items)) return;
    sel.innerHTML = items.map((x) => `<option value="${escapeHtml(String(x.id))}">${escapeHtml(x.name)}</option>`).join("");
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
