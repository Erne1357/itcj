/**
 * Formato B del alumno — única lógica de cliente: habilitar «Enviar Formato B»
 * solo con la casilla «Confirmo que mis datos son correctos» marcada.
 *
 * Morph-safe: delegación en `document` (una sola vez, guarda `data-tt-bound`)
 * y re-sincronización tras cada swap de HTMX, porque la pantalla de revisión
 * llega por `hx-swap="outerHTML"` y el botón nace deshabilitado en el servidor.
 */
(function () {
  'use strict';

  function sync() {
    var box = document.getElementById('fb-confirm');
    var btn = document.getElementById('fb-submit');
    if (!box || !btn) return;
    btn.disabled = !box.checked;
  }

  function init() {
    sync();
    if (document.documentElement.getAttribute('data-tt-fb-bound')) return;
    document.documentElement.setAttribute('data-tt-fb-bound', '1');
    document.addEventListener('change', function (ev) {
      if (ev.target && ev.target.matches && ev.target.matches('[data-fb-confirm]')) sync();
    });
    document.body.addEventListener('htmx:afterSettle', sync);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
