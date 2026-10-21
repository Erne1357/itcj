/* ===========================================================================
   TitulaTec · Admin — Pestaña «Sinodales» (fase 4).

   Spec 2026-10-21-titulatec-fase4-sinodales §9. Lo que el servidor no puede
   hacer solo en el detalle (`partials/sinodales/_detalle.html`):

     - en «Asignar sinodales», apaga en cada select a los docentes que ya se
       eligieron en otra posición (los 4 deben ser personas distintas; el
       servidor lo vuelve a exigir con 400 + `X-Tt-Error`);
     - «Sustituir» por fila (`data-tt-sin-toggle`): despliega/pliega el
       formulario de esa posición y enfoca su primer campo.

   Las confirmaciones son `hx-confirm` + `data-tt-confirm-ok`: el puente de
   `titulatec-utils.js` las convierte en `confirmDialog` (nunca el diálogo
   nativo del navegador).

   Contrato (igual que `titulacion.js`): se carga UNA vez desde
   `admin/base_admin.html`; clics y cambios por delegación en `document.body`
   leyendo el DOM VIGENTE; el contenido de `#tt-sin-body` se reemplaza en cada
   swap y el estado se recalcula en `htmx:afterSettle` y
   `htmx:historyRestore`. Sin raíz (`#tt-sin-assign`), no hace nada.

   Expone solo `window.TitulaTecSinodales = { init() }`.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecSinodales) return;   // doble carga del <script>

  function $(id) { return document.getElementById(id); }

  // ————————————————————————————————— selects de «Asignar»
  function selects() {
    var form = $('tt-sin-assign');
    return form ? Array.prototype.slice.call(form.querySelectorAll('select.tt-sin-pick')) : [];
  }

  // Cada docente elegido en una posición queda deshabilitado en las otras.
  function syncPicks() {
    var lista = selects();
    if (!lista.length) return;
    lista.forEach(function (sel) {
      var otros = lista.filter(function (s) { return s !== sel && s.value; })
        .map(function (s) { return s.value; });
      Array.prototype.forEach.call(sel.options, function (opt) {
        opt.disabled = !!opt.value && otros.indexOf(opt.value) !== -1;
      });
    });
  }

  // ————————————————————————————————— delegación (una sola vez)
  document.body.addEventListener('change', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('#tt-sin-assign select.tt-sin-pick')) syncPicks();
  });

  document.body.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var toggle = t.closest('[data-tt-sin-toggle]');
    if (!toggle) return;
    var id = toggle.getAttribute('data-tt-sin-toggle');
    var bloque = $(id);
    if (!bloque) return;
    bloque.hidden = !bloque.hidden;
    document.querySelectorAll('[data-tt-sin-toggle="' + id + '"][aria-expanded]').forEach(function (b) {
      b.setAttribute('aria-expanded', bloque.hidden ? 'false' : 'true');
    });
    if (!bloque.hidden) {
      var primero = bloque.querySelector('select, textarea, input:not([type="hidden"])');
      if (primero) primero.focus();
    }
  });

  // ————————————————————————————————— init
  function init() {
    syncPicks();
  }

  document.body.addEventListener('htmx:afterSettle', init);
  // Back/Forward: htmx restaura el body desde un snapshot (nodos nuevos).
  document.body.addEventListener('htmx:historyRestore', init);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.TitulaTecSinodales = { init: init };
})();
