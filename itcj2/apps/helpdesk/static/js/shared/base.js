// itcj2/apps/helpdesk/static/js/shared/base.js

// Logout handler function
async function performLogout() {
    try {
        const res = await fetch('/api/core/v2/auth/logout', {
            method: 'POST',
            credentials: 'include'
        });

        if (res.ok) {
            // Si estamos en iframe, notificar al parent (dashboard)
            if (window.self !== window.top) {
                try {
                    window.parent.postMessage({
                        type: 'LOGOUT',
                        source: 'helpdesk',
                        reason: 'manual_logout'
                    }, window.location.origin);
                } catch (e) {
                    console.warn('No se pudo notificar logout al parent:', e);
                }
            }

            // Redirigir al login
            window.location.href = '/itcj/login';
        }
    } catch (error) {
        console.error('Error logging out:', error);
    }
}

// Sidebar logout handler
document.getElementById('sidebarLogout')?.addEventListener('click', performLogout);

// Initialize Helpdesk Notification FAB Widget
document.addEventListener('DOMContentLoaded', () => {
    if (window.AppNotificationFAB) {
        const helpdeskNotifications = new AppNotificationFAB('helpdesk');
        console.log('[Helpdesk] Notification FAB widget initialized');
    } else {
        console.error('[Helpdesk] AppNotificationFAB not loaded');
    }
});

// Compatibilidad de cierre de modales en iframe
$(document).ready(function() {
    // Detectar si estamos en iframe
    const inIframe = window.self !== window.top;

    // Configurar modales para cerrar correctamente
    $('.modal').each(function() {
        const $modal = $(this);

        // Botones de cerrar
        $modal.find('[data-dismiss="modal"], .close').on('click', function(e) {
            e.preventDefault();
            $modal.modal('hide');
        });

        // Cerrar con ESC
        $modal.on('shown.bs.modal', function() {
            $(document).on('keydown.modal', function(e) {
                if (e.key === 'Escape') {
                    $modal.modal('hide');
                }
            });
        });

        $modal.on('hidden.bs.modal', function() {
            $(document).off('keydown.modal');
        });

        // Click en backdrop
        $modal.on('click', function(e) {
            if (e.target === this) {
                $modal.modal('hide');
            }
        });
    });
});
