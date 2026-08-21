/* =============================================================================
   AgendaTec — Skeleton helper
   -----------------------------------------------------------------------------
   Genera placeholders animados (shimmer) para insertar durante fetch.
   Respeta prefers-reduced-motion vía CSS (regla global en base.css).
   Expone window.AgendaTec.Skeleton.
   ============================================================================= */
(function () {
  "use strict";

  /**
   * Filas de tabla con N celdas placeholder.
   * @param {number} rows   filas a generar (default 3)
   * @param {number} cols   columnas (default 4)
   * @param {object} opts   { withActions: boolean }
   * @returns {string} HTML para insertar en tbody
   */
  function tableRows(rows = 3, cols = 4, opts = {}) {
    const cells = Array.from({ length: cols }, (_, i) => {
      const isLast = opts.withActions && i === cols - 1;
      const w = isLast ? "80px" : `${40 + ((i * 13) % 50)}%`;
      return `<td><span class="at-skeleton at-skeleton--line" style="width:${w}"></span></td>`;
    }).join("");
    return Array.from({ length: rows }, () => `<tr>${cells}</tr>`).join("");
  }

  /**
   * Cards apilados (vista list-group / mobile).
   */
  function cards(n = 3) {
    const block = `
      <div class="at-card at-card--bordered mb-2 p-3">
        <span class="at-skeleton at-skeleton--title"></span>
        <span class="at-skeleton at-skeleton--line" style="width:80%"></span>
        <span class="at-skeleton at-skeleton--line" style="width:55%"></span>
      </div>`;
    return Array.from({ length: n }, () => block).join("");
  }

  /**
   * KPI tiles placeholder.
   */
  function kpis(n = 4) {
    const block = `
      <div class="col">
        <div class="at-kpi">
          <span class="at-skeleton at-skeleton--line" style="width:60%"></span>
          <span class="at-skeleton" style="height:1.8rem;width:40%"></span>
        </div>
      </div>`;
    return Array.from({ length: n }, () => block).join("");
  }

  /**
   * Placeholders con la silueta de los chips de horario (.at-slot).
   *
   * `cards()` NO sirve para el grid de slots: ese contenedor es
   * `d-flex flex-wrap gap-2`, asi que cada `.at-card` se vuelve un flex item
   * que encoge a su contenido y las lineas internas (width en %) quedan como
   * palitos finos. Estos comparten alto y ancho con el chip real, de modo que
   * al llegar los datos el layout no salta.
   *
   * `aria-hidden`: son decorativos. Quien anuncia el estado es el
   * `aria-busy` del contenedor, no cada bloque.
   */
  function slots(n = 6) {
    const block = `<span class="at-skeleton at-skeleton--slot" aria-hidden="true"></span>`;
    return Array.from({ length: n }, () => block).join("");
  }

  /**
   * Línea simple (un placeholder).
   */
  function line(width = "100%") {
    return `<span class="at-skeleton at-skeleton--line" style="width:${width}"></span>`;
  }

  window.AgendaTec = window.AgendaTec || {};
  window.AgendaTec.Skeleton = { tableRows, cards, kpis, line, slots };
})();
