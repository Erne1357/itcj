/**
 * shared/base.js — Mantenimiento
 * Se carga en TODAS las páginas que extienden base_maint.html.
 *
 * Responsabilidades:
 *   - Logout (API + notificación a iframe padre)
 *   - Inicializar el FAB de notificaciones de la app maint
 *   - Listener del botón de logout en el sidebar
 */
'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// LOGOUT
// ─────────────────────────────────────────────────────────────────────────────

async function performLogout() {
    try {
        var res = await fetch('/api/core/v2/auth/logout', {
            method: 'POST',
            credentials: 'include',
        });

        if (res.ok) {
            // Notificar al dashboard padre si estamos en iframe
            if (window.self !== window.top) {
                try {
                    window.parent.postMessage({
                        type: 'LOGOUT',
                        source: 'maint',
                        reason: 'manual_logout',
                    }, window.location.origin);
                } catch (_) {
                    // Silenciar errores cross-origin
                }
            }
            window.location.href = '/itcj/login';
        }
    } catch (err) {
        console.error('[Maint] Error al cerrar sesión:', err);
    }
}

document.getElementById('sidebarLogout')?.addEventListener('click', performLogout);
document.getElementById('navbarLogout')?.addEventListener('click', performLogout);

// ─────────────────────────────────────────────────────────────────────────────
// FAB DE NOTIFICACIONES
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function () {
    if (window.AppNotificationFAB) {
        new AppNotificationFAB('maint');
    } else {
        console.warn('[Maint] AppNotificationFAB no cargado');
    }
});
