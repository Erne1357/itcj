/* =============================================================================
   AgendaTec — MultiSelect touch-friendly
   -----------------------------------------------------------------------------
   Reemplaza <select multiple> con un dropdown Bootstrap de checkboxes.
   Sincroniza la selección con el <select> original (mantiene compatibilidad
   con el backend).
   Expone window.AgendaTec.MultiSelect.
   ============================================================================= */
(function () {
  "use strict";

  /**
   * Crea un MultiSelect sobre el <select multiple> dado.
   * @param {string|HTMLElement} selector  El <select multiple> original
   * @param {object}             opts
   *   - placeholder  {string}  Texto cuando no hay selección (default "Seleccionar…")
   *   - searchPlaceholder {string}  Placeholder del input de búsqueda
   */
  function create(selector, opts = {}) {
    const select = typeof selector === "string"
      ? document.querySelector(selector)
      : selector;
    if (!select || select.tagName !== "SELECT") return null;

    const placeholder       = opts.placeholder       || "Seleccionar…";
    const searchPlaceholder = opts.searchPlaceholder || "Buscar…";

    // Ocultar el <select> original (se mantiene en DOM para compatibilidad)
    select.hidden = true;
    select.setAttribute("aria-hidden", "true");

    // Wrapper del componente
    const wrapper = document.createElement("div");
    wrapper.className = "dropdown at-multiselect";
    wrapper.setAttribute("role", "group");
    wrapper.setAttribute("aria-label", select.getAttribute("aria-label") || placeholder);
    select.insertAdjacentElement("beforebegin", wrapper);

    // Botón de trigger
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "btn btn-sm btn-outline-secondary w-100 dropdown-toggle text-start d-flex justify-content-between align-items-center at-multiselect__trigger";
    trigger.setAttribute("data-bs-toggle", "dropdown");
    trigger.setAttribute("data-bs-auto-close", "outside");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-haspopup", "listbox");
    wrapper.appendChild(trigger);

    const triggerLabel = document.createElement("span");
    triggerLabel.className = "at-multiselect__label";
    trigger.appendChild(triggerLabel);

    // Menú dropdown
    const menu = document.createElement("div");
    menu.className = "dropdown-menu p-2 at-multiselect__menu";
    menu.style.minWidth = "220px";
    menu.style.maxHeight = "280px";
    menu.style.overflowY = "auto";
    wrapper.appendChild(menu);

    // Input de búsqueda
    const searchWrap = document.createElement("div");
    searchWrap.className = "mb-2";
    const searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.className = "form-control form-control-sm";
    searchInput.placeholder = searchPlaceholder;
    searchInput.setAttribute("aria-label", searchPlaceholder);
    searchWrap.appendChild(searchInput);
    menu.appendChild(searchWrap);

    // Contenedor de checkboxes
    const checkList = document.createElement("ul");
    checkList.className = "list-unstyled mb-0";
    checkList.setAttribute("role", "listbox");
    checkList.setAttribute("aria-multiselectable", "true");
    menu.appendChild(checkList);

    // Construir checkboxes desde las <option> del select
    function buildOptions() {
      checkList.innerHTML = "";
      const query = searchInput.value.toLowerCase().trim();
      const options = Array.from(select.options);

      options.forEach((opt) => {
        if (query && !opt.text.toLowerCase().includes(query)) return;

        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", opt.selected ? "true" : "false");

        const label = document.createElement("label");
        label.className = "dropdown-item d-flex align-items-center gap-2 py-1 rounded user-select-none";
        label.style.cursor = "pointer";

        const cb = document.createElement("input");
        cb.type    = "checkbox";
        cb.className = "form-check-input m-0 flex-shrink-0";
        cb.value   = opt.value;
        cb.checked = opt.selected;
        cb.setAttribute("aria-label", opt.text);

        const txt = document.createElement("span");
        txt.className = "flex-grow-1 text-wrap";
        txt.textContent = opt.text;

        label.appendChild(cb);
        label.appendChild(txt);
        li.appendChild(label);
        checkList.appendChild(li);

        // Touch / click
        cb.addEventListener("change", () => {
          opt.selected = cb.checked;
          li.setAttribute("aria-selected", cb.checked ? "true" : "false");
          syncTriggerLabel();
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
      });

      if (!checkList.children.length) {
        const li = document.createElement("li");
        li.className = "px-2 py-1 text-muted small";
        li.textContent = "Sin resultados";
        checkList.appendChild(li);
      }
    }

    function syncTriggerLabel() {
      const selected = Array.from(select.options).filter((o) => o.selected);
      if (!selected.length) {
        triggerLabel.textContent = placeholder;
        trigger.classList.remove("fw-semibold");
      } else if (selected.length === 1) {
        triggerLabel.textContent = selected[0].text;
        trigger.classList.add("fw-semibold");
      } else {
        triggerLabel.textContent = `${selected.length} seleccionados`;
        trigger.classList.add("fw-semibold");
      }
    }

    // Debounce en búsqueda
    let searchTimer;
    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(buildOptions, 150);
    });

    // Al abrir el dropdown, reconstruir opciones y enfocar búsqueda
    wrapper.addEventListener("shown.bs.dropdown", () => {
      searchInput.value = "";
      buildOptions();
      searchInput.focus();
    });

    // Método público para refrescar opciones (p.ej. tras cargar datos)
    const api = {
      refresh: () => { buildOptions(); syncTriggerLabel(); },
      getSelected: () => Array.from(select.options).filter((o) => o.selected).map((o) => o.value),
    };

    buildOptions();
    syncTriggerLabel();
    return api;
  }

  window.AgendaTec = window.AgendaTec || {};
  window.AgendaTec.MultiSelect = { create };
})();
