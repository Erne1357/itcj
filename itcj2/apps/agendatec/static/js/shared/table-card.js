/* =============================================================================
   AgendaTec — Responsive table → card helper
   -----------------------------------------------------------------------------
   Para tablas con data-at-table="card", copia data-at-label de cada <th> a su
   <td> correspondiente para que el CSS de < md lo renderice como label.
   Llamar SyncLabels(table) tras renderizar filas dinámicas.
   Expone window.AgendaTec.TableCard.
   ============================================================================= */
(function () {
  "use strict";

  /**
   * Sincroniza labels de columnas a cada celda de tbody.
   * Lee data-at-label del <th>; cae a textContent del <th> si no hay attr.
   * @param {HTMLTableElement|string} table elemento o selector
   */
  function syncLabels(table) {
    const t = typeof table === "string" ? document.querySelector(table) : table;
    if (!t || t.tagName !== "TABLE") return;
    if (t.dataset.atTable !== "card") return;

    const headers = Array.from(t.querySelectorAll("thead th")).map((th) => {
      const explicit = th.getAttribute("data-at-label");
      return explicit !== null ? explicit : (th.textContent || "").trim();
    });

    if (!headers.length) return;

    t.querySelectorAll("tbody tr").forEach((tr) => {
      Array.from(tr.children).forEach((td, idx) => {
        if (td.tagName !== "TD") return;
        if (!td.hasAttribute("data-at-label")) {
          td.setAttribute("data-at-label", headers[idx] || "");
        }
      });
    });
  }

  /**
   * Auto-sync ante mutaciones del tbody. Útil cuando el render es por JS.
   * Llamar una vez por tabla al cargar la página.
   * @param {HTMLTableElement|string} table
   */
  function observe(table) {
    const t = typeof table === "string" ? document.querySelector(table) : table;
    if (!t || t.tagName !== "TABLE") return null;
    if (t.dataset.atTable !== "card") return null;

    const tbody = t.querySelector("tbody");
    if (!tbody) return null;

    syncLabels(t);
    const mo = new MutationObserver(() => syncLabels(t));
    mo.observe(tbody, { childList: true, subtree: false });
    return mo;
  }

  /** Auto-observa todas las tablas marcadas al DOMContentLoaded. */
  function autoInit() {
    document.querySelectorAll('table[data-at-table="card"]').forEach((t) => observe(t));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit, { once: true });
  } else {
    autoInit();
  }

  window.AgendaTec = window.AgendaTec || {};
  window.AgendaTec.TableCard = { syncLabels, observe };
})();
