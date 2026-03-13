/**
 * VisteTec - Base (logout handler)
 */
(function () {
    'use strict';

    document.getElementById('btnLogout')?.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/core/v2/auth/logout', {
                method: 'POST',
                credentials: 'include'
            });
            if (res.ok) {
                if (window.self !== window.top) {
                    try {
                        window.parent.postMessage({
                            type: 'LOGOUT',
                            source: 'vistetec',
                            reason: 'manual_logout'
                        }, window.location.origin);
                    } catch (e) { }
                }
                window.location.href = '/itcj/login';
            }
        } catch (error) {
            console.error('Error logging out:', error);
        }
    });

    // Sidebar logout handler
    document.getElementById('sidebarLogout')?.addEventListener('click', function () {
        document.getElementById('btnLogout')?.click();
    });

    // Initialize VisteTec Notification FAB Widget
    document.addEventListener('DOMContentLoaded', function () {
        if (window.AppNotificationFAB) {
            new AppNotificationFAB('vistetec', '/api/core/v2', {
                color: '#8B1538',
                colorDark: '#5C0E24'
            });
        }
    });

})();
