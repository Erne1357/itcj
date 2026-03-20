/**
 * AgendaTec - Base (sidebar logout + notification FAB init)
 */
(function () {
    'use strict';

    // Sidebar logout handler
    document.getElementById('sidebarLogout')?.addEventListener('click', function () {
        document.getElementById('btnLogout')?.click();
    });

    // Initialize AgendaTec Notification FAB Widget
    document.addEventListener('DOMContentLoaded', function () {
        if (window.AppNotificationFAB) {
            new AppNotificationFAB('agendatec', '/api/core/v2', {
                color: '#0d6efd',
                colorDark: '#0a58ca'
            });
        }
    });

})();
