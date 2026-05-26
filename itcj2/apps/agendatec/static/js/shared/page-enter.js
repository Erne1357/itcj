/**
 * AgendaTec - page-enter.js
 * Al DOMContentLoaded añade .at-fade-in al <main> de cualquier página
 * agendatec si aún no tiene la clase (ni .at-stagger).
 * Se carga desde base.html después de base.js.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var main = document.querySelector('main');
    if (!main) return;
    if (!main.classList.contains('at-fade-in') && !main.classList.contains('at-stagger')) {
      main.classList.add('at-fade-in');
    }
  });
})();
