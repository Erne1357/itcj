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

// Nota: el shim jQuery de cierre de modales (BS4) se eliminó en el cierre del
// bloque E-G. Bootstrap 5 maneja data-bs-dismiss, tecla ESC y click en backdrop
// de forma nativa, así que este bloque era no-op. Ver docs/auditoria_ui_helpdesk.md §8.4.

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
    var boostUrlsRe = null;   // RegExp de páginas migradas (data-hd-boost-urls)

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

    // Whitelist de páginas migradas que emite el server (nav.py boost_urls_regex).
    // Se re-lee en cada activate() porque el morph reemplaza el <main> que la trae.
    function syncBoostUrls(root) {
        var raw = root ? (root.getAttribute('data-hd-boost-urls') || '') : '';
        try { boostUrlsRe = raw ? new RegExp(raw) : null; }
        catch (e) { boostUrlsRe = null; }
    }

    function activate() {
        var root = document.querySelector('[data-hd-page]');
        syncBoostUrls(root);
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
            // Whitelist estricta del server: SOLO páginas registradas en
            // HD_PAGE_MODULES. /help-desk/ a secas incluía páginas NO migradas
            // (admin/categories, inventory/reports/*) que al morfearse quedan sin
            // su JS. Sin el atributo (página fuera del base) se cae al criterio
            // amplio de antes para no romper navigate().
            if (boostUrlsRe) return boostUrlsRe.test(u.pathname);
            return /^\/help-desk\//.test(u.pathname);
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
    // opts.push === false → no toca el historial (lo usa refresh()).
    function navigate(url, opts) {
        if (!url) return;
        var htmx = window.htmx;
        if (!isBoostableClient(url) || !htmx || typeof htmx.ajax !== 'function') {
            window.location.href = url;      // fallback: cross-app / no migrada / sin htmx
            return;
        }
        var src = document.createElement('span');
        src.setAttribute('hx-push-url', (opts && opts.push === false) ? 'false' : 'true');
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

    // refresh(): re-morfea la página ACTUAL con HTML fresco del server, sin tocar
    // el historial. Sustituto de location.reload() tras una mutación: mismo
    // resultado sin el flash en blanco ni perder el scroll.
    function refresh() { navigate(window.location.href, { push: false }); }

    // --- Boost delegado de los links de CONTENIDO -----------------------------
    // Los <a> de los templates llevan {{ hd_boost(url) }}, pero los que inyectan
    // los módulos por innerHTML (tarjetas de ticket, tablas de inventario, árbol
    // de predecesores…) nunca pasaron por htmx: recargaban la página entera.
    // Un único listener en document los cubre a todos — vive fuera del árbol
    // morfeado y no necesita htmx.process() por cada render.
    // Se cede el click cuando el usuario pidió otra cosa: ctrl/cmd/shift/alt,
    // botón no primario, target (_blank de los "ver en pestaña nueva"), download,
    // o un ancla que ya declare hx-* (el nav, o hx-boost="false" como opt-out).
    var NON_HTTP_SCHEME = /^(?!https?:)[a-z][a-z0-9+.-]*:/i;

    function onDocumentClick(e) {
        if (e.defaultPrevented || e.button !== 0) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        // Regla de isla, igual que el server (htmx_boost_enabled): ORIGEN y
        // destino migrados. Saliendo de una página NO migrada se recarga como
        // hasta ahora — sus scripts no están en el registry y nadie los destruye.
        if (!currentKey || !isBoostableClient(window.location.href)) return;
        var a = e.target && e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        if (a.hasAttribute('download')) return;
        var target = a.getAttribute('target');
        if (target && target !== '_self') return;
        if (a.closest('[hx-boost], [hx-get], [hx-post]')) return;  // lo maneja htmx
        var href = a.getAttribute('href');
        if (!href || href.charAt(0) === '#' || NON_HTTP_SCHEME.test(href)) return;
        if (!isBoostableClient(a.href)) return;      // whitelist data-hd-boost-urls
        e.preventDefault();
        navigate(a.href);
    }

    document.addEventListener('click', onDocumentClick);

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

    window.HelpdeskPage = { register: register, page: register, navigate: navigate, refresh: refresh };
})();
