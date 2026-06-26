/* ===========================================================================
   TitulaTec · Shell del alumno — FAB de notificaciones + cierre de sesión.
   El drawer/appbar los maneja el shell core (mobile-app-shell.js). Las vistas
   del alumno usan navegación completa (no morph), así que basta enlazar en la
   carga. El toast de errores HTMX es global (titulatec-utils.js).
   =========================================================================== */
(function () {
  'use strict';

  // FAB de notificaciones por-app (se autosuprime dentro del iframe del shell).
  if (window.AppNotificationFAB) {
    try { new AppNotificationFAB('titulatec', '/api/core/v2', { color: '#0F172A', colorDark: '#0B1220' }); } catch (e) {}
  }

  function ttLogout() {
    fetch('/api/core/v2/auth/logout', { method: 'POST', credentials: 'include' })
      .catch(function () {})
      .finally(function () {
        if (window.self !== window.top) {
          try { window.parent.postMessage({ type: 'LOGOUT', reason: 'titulatec' }, window.location.origin); } catch (e) {}
        } else {
          window.location.href = '/itcj/login';
        }
      });
  }

  var logoutBtn = document.getElementById('sidebarLogout');
  if (logoutBtn) logoutBtn.addEventListener('click', ttLogout);
  document.querySelectorAll('[data-tt-logout]').forEach(function (b) { b.addEventListener('click', ttLogout); });
})();
