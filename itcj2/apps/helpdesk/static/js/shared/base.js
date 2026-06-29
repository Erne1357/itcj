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

/* ===========================================================================
   HelpdeskPage — controller de navegación HTMX (hx-boost + idiomorph morph).
   Corre el init/destroy de cada página según [data-hd-page], en la carga
   inicial y en htmx:afterSettle. Morph-safe: los módulos se cargan UNA vez.
   Spec: docs/superpowers/specs/2026-06-29-helpdesk-htmx-navigation-design.md
   =========================================================================== */
(function () {
    'use strict';
    if (window.HelpdeskPage) return;            // singleton

    var registry = {};
    var currentKey = null;

    function readKey() {
        var root = document.querySelector('[data-hd-page]');
        var key = root ? root.getAttribute('data-hd-page') : null;
        return key || null;
    }

    function teardown() {
        var hooks = currentKey && registry[currentKey];
        if (hooks && typeof hooks.destroy === 'function') {
            try { hooks.destroy(); }
            catch (e) { console.error('[HelpdeskPage] destroy ' + currentKey + ':', e); }
        }
    }

    function setup() {
        var hooks = currentKey && registry[currentKey];
        if (hooks && typeof hooks.init === 'function') {
            try { hooks.init(); }
            catch (e) { console.error('[HelpdeskPage] init ' + currentKey + ':', e); }
        }
    }

    function activate() {
        var key = readKey();
        if (key === currentKey) return;          // mismo destino → no-op
        teardown();                              // destruye la página saliente
        currentKey = key;
        setup();                                 // inicializa la entrante
    }

    function register(key, hooks) {
        if (!key) return;
        registry[key] = hooks || {};
        // Si el módulo se registra DESPUÉS del primer activate (carga diferida)
        // y su página ya está montada, inicialízala ahora.
        if (key === currentKey) setup();
    }

    // Sidebar móvil: cierre delegado (morph-safe) sobre #appSidebar (id estable).
    function bindSidebar() {
        var sidebar = document.getElementById('appSidebar');
        if (sidebar && sidebar.dataset.hdDelegated !== '1') {
            sidebar.dataset.hdDelegated = '1';
            sidebar.addEventListener('click', function (e) {
                if (e.target.closest('.app-sidebar-item')) {
                    setTimeout(function () {
                        if (window.mobileAppShell) window.mobileAppShell.close();
                    }, 150);
                }
            });
        }
    }

    // Barra de progreso de navegación (feedback en cargas lentas).
    function navStart() { document.body.classList.add('hd-navigating'); }
    function navEnd() { document.body.classList.remove('hd-navigating'); }

    function boot() { bindSidebar(); activate(); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    // afterSettle: tras swap boosteado. historyRestore: tras back/forward del browser
    // (htmx restaura el HTML cacheado) → re-sincroniza shell + corre init/destroy de la nueva página.
    document.body.addEventListener('htmx:afterSettle', function () { bindSidebar(); activate(); });
    document.body.addEventListener('htmx:historyRestore', function () { bindSidebar(); activate(); });
    document.body.addEventListener('htmx:beforeRequest', navStart);
    document.body.addEventListener('htmx:afterRequest', navEnd);

    window.HelpdeskPage = { register: register, page: register };
})();
