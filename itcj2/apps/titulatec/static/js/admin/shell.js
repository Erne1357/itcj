/* ===========================================================================
   TitulaTec · Admin shell — comportamiento del layout de escritorio.
   Cargado UNA vez en el bloque scripts de base_admin (persiste entre swaps
   morph del menú). El sidebar/topbar NO entran al swap, así que basta enlazar
   los listeners en la carga inicial; el estado activo se recalcula en cada
   navegación HTMX (htmx:afterSettle).
   El toast de errores HTMX vive ahora en titulatec-utils.js (compartido).
   =========================================================================== */
(function () {
  'use strict';

  // En iframe (shell embebido) no mostramos "Volver a ITCJ" ni en desktop:
  // quitamos d-lg-block para que el d-none lo mantenga oculto en todos los tamaños.
  if (window.self !== window.top) {
    var back = document.getElementById('ttBackItcj');
    if (back) back.classList.remove('d-lg-block');
  }

  // Activo del menú: el sidebar no entra al swap, así que lo actualizamos por JS
  // según la URL actual tras cada navegación HTMX (estilo wire:navigate).
  function ttSetActive() {
    var path = (location.pathname || '').replace(/\/$/, '');
    document.querySelectorAll('#ttSide a[hx-get]').forEach(function (a) {
      var url = (a.getAttribute('hx-get') || '').replace(/\/$/, '');
      var on = url && url !== '#' &&
        (url === path || (url !== '/titulatec/admin' && path.indexOf(url) === 0));
      a.classList.toggle('active', !!on);
    });
  }
  document.body.addEventListener('htmx:afterSettle', ttSetActive);
  document.addEventListener('DOMContentLoaded', ttSetActive);

  // Drawer del sidebar admin en móvil/tablet (<992px).
  (function () {
    var admin = document.getElementById('ttAdmin');
    if (!admin) return;
    function open()  { admin.classList.add('side-open'); document.body.classList.add('tt-admin-locked'); }
    function close() { admin.classList.remove('side-open'); document.body.classList.remove('tt-admin-locked'); }
    var burger = document.getElementById('ttAdminBurger');
    var closeBtn = document.getElementById('ttAdminClose');
    var overlay = document.getElementById('ttAdminOverlay');
    if (burger) burger.addEventListener('click', open);
    if (closeBtn) closeBtn.addEventListener('click', close);
    if (overlay) overlay.addEventListener('click', close);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    // Al navegar por un item del menú, cierra el drawer.
    admin.querySelectorAll('.side a').forEach(function (a) { a.addEventListener('click', close); });
  })();
})();
