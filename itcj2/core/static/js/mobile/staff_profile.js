'use strict';

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('logoutBtn').addEventListener('click', async () => {
        if (!confirm('¿Cerrar sesion?')) return;
        try {
            await fetch('/api/core/v2/auth/logout', {
                method: 'POST',
                credentials: 'include'
            });
            window.location.href = '/itcj/login';
        } catch (e) {
            window.location.href = '/itcj/login';
        }
    });
});
