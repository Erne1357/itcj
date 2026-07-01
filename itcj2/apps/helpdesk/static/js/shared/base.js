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

    // --- Morph-safety: preservar widgets inyectados por JS en runtime ---
    // El FAB de notificaciones (#notifFab-/#notifPanel-) se inserta en <body> en
    // runtime y NO existe en el HTML del servidor. Con hx-swap="morph:innerHTML"
    // sobre <body>, idiomorph difea contra la respuesta del server (sin FAB) y lo
    // eliminaría en la 1ª navegación boosteada. Cancelamos su remoción.
    // (En iframe el FAB se autosuprime, así que esto solo aplica standalone.)
    if (window.Idiomorph && Idiomorph.defaults && Idiomorph.defaults.callbacks &&
            !Idiomorph.defaults.callbacks._hdFabPatched) {
        var _hdPrevBeforeRemoved = Idiomorph.defaults.callbacks.beforeNodeRemoved;
        Idiomorph.defaults.callbacks.beforeNodeRemoved = function (node) {
            if (node && node.nodeType === 1 && node.id && /^notif(Fab|Panel)-/.test(node.id)) {
                return false; // preservar: no remover el widget inyectado
            }
            if (typeof _hdPrevBeforeRemoved === 'function') return _hdPrevBeforeRemoved(node);
        };
        Idiomorph.defaults.callbacks._hdFabPatched = true;
    }

    var registry = {};
    var currentKey = null;
    var loadedModules = {};   // src -> true (evita recargar/re-declarar módulos)

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

    // Carga secuencial (orden = deps CDN antes que el módulo app) y dedup por src.
    // Al terminar de cargar, cada módulo llama HelpdeskPage.page(key, ...) y, si su
    // página sigue activa, register() dispara el init. Por eso no llamamos setup()
    // aquí: evita doble-init. En revisitas (módulo ya cargado) activate() hace setup().
    function loadModules(attr) {
        var srcs = (attr || '').split('|').filter(Boolean);
        var i = 0;
        function next() {
            if (i >= srcs.length) return;
            var src = srcs[i++];
            if (loadedModules[src]) { next(); return; }
            loadedModules[src] = true;
            var s = document.createElement('script');
            s.src = src;
            s.onload = next;
            s.onerror = function () { console.error('[HelpdeskPage] fallo módulo ' + src); next(); };
            document.head.appendChild(s);
        }
        next();
    }

    function activate() {
        var root = document.querySelector('[data-hd-page]');
        var key = root ? (root.getAttribute('data-hd-page') || null) : null;
        if (key === currentKey) return;          // mismo destino → no-op
        teardown();                              // destruye la página saliente
        currentKey = key;
        if (!key) return;
        if (registry[key]) { setup(); return; }  // módulo ya cargado → re-init directo
        var mods = root.getAttribute('data-hd-modules');
        if (!mods) { setup(); return; }          // página migrada sin JS (ej. categorías)
        loadModules(mods);                       // 1ª visita → carga; register() hará setup()
    }

    function register(key, hooks) {
        if (!key) return;
        registry[key] = hooks || {};
        // Si el módulo se registra mientras su página está activa (carga diferida),
        // inicialízala ahora.
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
    // Solo en requests boosteados (navegación real); evita parpadeo si en el
    // futuro se agregan hx-get/hx-post in-page que no son navegación.
    function navStart(evt) {
        if (evt && evt.detail && evt.detail.boosted) document.body.classList.add('hd-navigating');
    }
    function navEnd() { document.body.classList.remove('hd-navigating'); }

    // --- Navegación morph desde JS (contraparte de hx-boost en templates) ---
    // Los enlaces internos viven en templates con {{ hd_boost(url) }}; cuando la
    // navegación se dispara desde JS (redirects tras guardar, quick-view, botones
    // "generar reporte"…) se usa HelpdeskPage.navigate(url) para morfear igual que
    // la navbar en vez de recargar. Whitelist de cliente que espeja las páginas
    // /help-desk/ migradas (todas registradas en este controller).
    function isBoostableClient(url) {
        if (!url) return false;
        try {
            var u = new URL(url, window.location.origin);
            if (u.origin !== window.location.origin) return false;   // cross-app → recarga
            return /^\/help-desk\//.test(u.pathname);                // página helpdesk migrada
        } catch (e) {
            return false;
        }
    }

    // navigate(url): morfea hacia una página helpdesk migrada (como el boost del
    // nav) o recarga si no es boosteable / falta htmx.
    //
    // History: se delega ENTERAMENTE en htmx montando una fuente efímera DENTRO
    // de <body> con hx-push-url="true". Así htmx (1) hereda hx-ext="morph,
    // head-support" del <body> (getExtensions() resuelve la extensión de swap
    // desde el elemento fuente → el morph y el merge de <head> funcionan), y
    // (2) hace el pushState con marcador htmx + snapshot de la página saliente en
    // cache ANTES del swap → back/forward funcionan por su popstate SIN pushState
    // manual (= sin doble push). HX-Boosted:true fuerza al endpoint a devolver la
    // PÁGINA completa (no el fragmento de la rama HX-Request). El morph elimina la
    // fuente al swappear (igual que a los enlaces del nav); un finally la limpia
    // si la petición falla y no hubo swap.
    function navigate(url) {
        if (!url) return;
        var htmx = window.htmx;
        if (!isBoostableClient(url) || !htmx || typeof htmx.ajax !== 'function') {
            window.location.href = url;      // fallback: cross-app / no migrada / sin htmx
            return;
        }
        var src = document.createElement('span');
        src.setAttribute('hx-push-url', 'true');
        src.style.display = 'none';
        document.body.appendChild(src);
        var cleanup = function () { if (src.parentNode) src.parentNode.removeChild(src); };
        try {
            var done = htmx.ajax('GET', url, {
                source: src,
                target: 'body',
                swap: 'morph:innerHTML',
                headers: { 'HX-Boosted': 'true' }
            });
            if (done && typeof done.finally === 'function') {
                done.finally(cleanup);
            } else {
                setTimeout(cleanup, 5000);
            }
        } catch (e) {
            cleanup();
            window.location.href = url;      // fallback duro si htmx.ajax lanza
        }
    }

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

    window.HelpdeskPage = { register: register, page: register, navigate: navigate };
})();
