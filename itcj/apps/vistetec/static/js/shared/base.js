/**
 * VisteTec - Base (logout handler)
 */
(function () {
    'use strict';

    document.getElementById('btnLogout')?.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/core/v1/auth/logout', {
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

})();
