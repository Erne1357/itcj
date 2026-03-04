(function () {
    'use strict';

    var totalEl = document.getElementById('active-users-total');
    var detailEl = document.getElementById('active-users-detail');

    if (!totalEl) return;

    var socket = io('/system', {
        transports: ['websocket', 'polling'],
        withCredentials: true
    });

    socket.on('active_users', function (data) {
        totalEl.textContent = data.total;

        if (data.students > 0 || data.admins > 0) {
            var parts = [];
            if (data.students > 0) {
                parts.push(data.students + ' est.');
            }
            if (data.admins > 0) {
                parts.push(data.admins + ' admin.');
            }
            detailEl.textContent = parts.join(' | ');
        } else {
            detailEl.textContent = '';
        }
    });

    socket.on('connect_error', function () {
        totalEl.textContent = '--';
        detailEl.textContent = 'Sin conexion';
    });
})();
