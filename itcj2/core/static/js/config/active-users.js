/* =============================================================================
   Usuarios activos (panel index de config) — módulo del registry ConfigPage.
   Comportamiento IGUAL que el widget previo (socket /system + evento
   active_users) pero con ciclo init/destroy: el socket se crea al entrar a la
   página y se desconecta al salir — sin listeners duplicados en morphs A→B→A.
   F6 reescribe este archivo (presencia real + socket.io vendored).
   ============================================================================= */
(function () {
    'use strict';

    var socket = null;

    function init() {
        // Re-consultar SIEMPRE los nodos: idiomorph recrea el content en revisitas.
        var totalEl = document.getElementById('active-users-total');
        var detailEl = document.getElementById('active-users-detail');
        if (!totalEl || typeof window.io !== 'function') return;

        destroy();  // defensivo: nunca dos sockets

        socket = io('/system', {
            transports: ['websocket', 'polling'],
            withCredentials: true
        });

        socket.on('active_users', function (data) {
            totalEl.textContent = data.total;
            var parts = [];
            if (data.students > 0) parts.push(data.students + ' est.');
            if (data.admins > 0) parts.push(data.admins + ' admin.');
            detailEl.textContent = parts.join(' | ');
        });

        socket.on('connect_error', function () {
            totalEl.textContent = '--';
            detailEl.textContent = 'Sin conexion';
        });
    }

    function destroy() {
        if (socket) {
            try { socket.disconnect(); } catch (e) { /* noop */ }
            socket = null;
        }
    }

    if (window.ConfigPage) {
        window.ConfigPage.register('index', { init: init, destroy: destroy });
    }
})();
