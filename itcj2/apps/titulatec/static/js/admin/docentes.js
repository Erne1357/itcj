/* ===========================================================================
   TitulaTec · Admin — Pestaña «Docentes» (fase 4).

   Spec 2026-10-21-titulatec-fase4-sinodales §8. Lo que el servidor no puede
   hacer solo:

     - botones `data-tt-doc-toggle="<id>"`: despliegan/pliegan el formulario
       (`data-tt-doc-panel`) de una fila o el de «Crear nuevo»;
     - tras cada swap de `#tt-doc-body`, el mensaje de validación
       (`#tt-doc-error`) se trae a la vista.

   Las confirmaciones son `hx-confirm` + `data-tt-confirm-ok`: el puente de
   `titulatec-utils.js` las convierte en `confirmDialog` (nunca el diálogo
   nativo del navegador).

   Contrato (igual que `titulacion.js`): se carga UNA vez desde
   `admin/base_admin.html`; clics por delegación en `document.body` leyendo el
   DOM VIGENTE (el contenido de `#tt-doc-body` se reemplaza en cada swap).

   Expone solo `window.TitulaTecDocentes = { init() }`.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecDocentes) return;   // doble carga del <script>

  function onToggle(e) {
    var btn = e.target.closest ? e.target.closest('[data-tt-doc-toggle]') : null;
    if (!btn) return;
    var panel = document.getElementById(btn.getAttribute('data-tt-doc-toggle'));
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      var first = panel.querySelector('input:not([type="hidden"])');
      if (first) first.focus();
    }
  }

  function revealError() {
    var err = document.getElementById('tt-doc-error');
    if (err && err.scrollIntoView) err.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function onSettle(e) {
    var t = e && e.target;
    if (t && (t.id === 'tt-doc-body' || (t.closest && t.closest('#tt-doc-body')))) revealError();
  }

  function init() {
    if (document.body._ttDocBound) return;   // expando: sobrevive al morph
    document.body._ttDocBound = true;
    document.body.addEventListener('click', onToggle);
    document.body.addEventListener('htmx:afterSettle', onSettle);
  }

  window.TitulaTecDocentes = { init: init };
  init();
})();
