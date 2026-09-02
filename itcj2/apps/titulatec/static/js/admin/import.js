/* ===========================================================================
   import.js — wizard de importación CSV (Convocatorias → tab Importar).

   Mantiene sincronizados los DOS campos ocultos que llevan todo el estado
   editable del preview: `excluded` (índices desmarcados) y `overrides` (celdas
   corregidas a mano). La tabla vive FUERA del <form> y sus inputs no tienen
   `name`, así que el payload es constante: token + 5 map_* + estos dos.

   Antes cada fila emitía 6 inputs con `name` y el commit/revalidate mandaba el
   preview entero: pasada la fila 165, `FormParser` de Starlette (max_fields=1000)
   respondía 400 y el asistente era inutilizable para una convocatoria real.

   `overrides` solo lleva lo que difiere de `data-tt-initial` — el valor que el
   servidor sacó del CSV con el mapeo vigente — así que cambiar un select de
   mapeo no borra lo que el admin ya corrigió, y el ciclo es estable.

   Morph-safe: listeners delegados en `document` (que nunca entra al swap) y
   guarda de doble carga. No asume que el wizard exista al cargar la página.
   =========================================================================== */
(function () {
  'use strict';

  if (window.TitulaTecImport) return;

  function sync(wizard) {
    if (!wizard) return;
    var excluded = [];
    var overrides = {};

    wizard.querySelectorAll('[data-tt-row]').forEach(function (row) {
      var idx = row.getAttribute('data-tt-row');
      var include = row.querySelector('[data-tt-include]');
      if (include && !include.checked) excluded.push(idx);

      row.querySelectorAll('[data-tt-field]').forEach(function (el) {
        var initial = el.getAttribute('data-tt-initial') || '';
        var value = el.value || '';
        if (value !== initial) {
          if (!overrides[idx]) overrides[idx] = {};
          overrides[idx][el.getAttribute('data-tt-field')] = value;
        }
      });
    });

    var excludedInput = wizard.querySelector('[data-tt-excluded]');
    var overridesInput = wizard.querySelector('[data-tt-overrides]');
    if (excludedInput) excludedInput.value = excluded.join(',');
    if (overridesInput) {
      overridesInput.value = Object.keys(overrides).length
        ? JSON.stringify(overrides) : '';
    }
  }

  function onEdit(e) {
    var target = e.target;
    if (!target || !target.closest) return;
    if (!target.closest('[data-tt-row]')) return;
    sync(target.closest('[data-tt-import]'));
  }

  // Captura: el `change` del checkbox y el `input` de las celdas de texto van
  // al mismo sitio, y hay que haber escrito los ocultos ANTES de que htmx
  // serialice el form (el commit y el revalidate salen de dentro del wizard).
  document.addEventListener('input', onEdit, true);
  document.addEventListener('change', onEdit, true);

  window.TitulaTecImport = { sync: sync };
})();
