/**
 * active-users.js — widget "En Línea" de la página index de /itcj/config.
 *
 * Suscriptor PURO del namespace /system (broadcast-only): pinta el payload
 * `active_users` {total, students, staff, admins} (contrato C5). La presencia
 * real se registra en /notify (presence-client.js del shell + widgets de apps);
 * este widget ya no se cuenta a sí mismo.
 *
 * Módulo del registry ConfigPage (C2): init crea el socket /system al entrar a
 * la página index; destroy lo cierra al navegar a otra pestaña del shell.
 */
(function () {
    'use strict';

    var socket = null;

    function render(data) {
        var totalEl = document.getElementById('active-users-total');
        var detailEl = document.getElementById('active-users-detail');
        if (!totalEl) return;
        totalEl.textContent = (data && typeof data.total === 'number') ? String(data.total) : '--';
        if (!detailEl) return;
        var parts = [];
        if (data && data.students > 0) parts.push(data.students + ' est.');
        if (data && data.staff > 0) parts.push(data.staff + ' staff');
        if (data && data.admins > 0) parts.push(data.admins + ' admin.');
        detailEl.textContent = parts.join(' | ');
    }

    function renderError() {
        var totalEl = document.getElementById('active-users-total');
        var detailEl = document.getElementById('active-users-detail');
        if (totalEl) totalEl.textContent = '--';
        if (detailEl) detailEl.textContent = 'Sin conexión';
    }

    function init() {
        if (!document.getElementById('active-users-total')) return; // markup ausente
        if (!window.io) { renderError(); return; }                   // vendored no cargó
        socket = window.io('/system', {
            transports: ['websocket', 'polling'],
            withCredentials: true
        });
        socket.on('active_users', render);
        socket.on('connect_error', renderError);
    }

    function destroy() {
        if (socket) {
            try { socket.off(); socket.disconnect(); } catch (e) { /* noop */ }
            socket = null;
        }
    }

    window.ConfigPage.register('index', { init: init, destroy: destroy });
})();
