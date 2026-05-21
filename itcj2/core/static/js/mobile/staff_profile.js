'use strict';

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('logoutBtn').addEventListener('click', async () => {
        const ok = await AppModal.confirm({
            title: 'Cerrar sesión',
            message: '¿Cerrar sesión actual?',
            confirmText: 'Cerrar sesión',
            confirmVariant: 'danger',
            variant: 'warning',
        });
        if (!ok) return;
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
