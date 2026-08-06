/* =============================================================================
   ConfigPage — controller de navegación HTMX del panel /itcj/config (C2).
   Clon adaptado de itcj2/apps/helpdesk/static/js/shared/base.js:
     · registro por página ([data-cfg-page] en #cfgMain) con init/destroy
     · carga secuencial de módulos (data-cfg-modules) con dedup por src;
       los módulos se cargan UNA vez y se re-inicializan en cada visita
     · navigate(url): morph programático; config es CRUD-por-modal, así que
       CUALQUIER navegación morph cierra modales y limpia backdrops ANTES
       del swap (morph:innerHTML no sabe de body.modal-open ni .modal-backdrop)
     · boost delegado: un click listener en document manda por navigate() TODO
       <a> de contenido cuyo href caiga en la whitelist (data-cfg-boost-urls),
       incluidos los que inyectan los módulos por innerHTML. El sidebar sigue
       con hx-boost server-side y se le cede el click a htmx.
     · morph-safety: preserva #appModal-* (inyectados en runtime por AppModal)
       y cualquier nodo marcado con data-cfg-preserve
   Activación: DOMContentLoaded + htmx:afterSettle + htmx:historyRestore.
   ============================================================================= */
(function () {
    'use strict';
    if (window.ConfigPage) return;   // singleton

    // --- Morph-safety: widgets inyectados por JS en runtime -------------------
    if (window.Idiomorph && Idiomorph.defaults && Idiomorph.defaults.callbacks &&
            !Idiomorph.defaults.callbacks._cfgPreservePatched) {
        var _prevBeforeRemoved = Idiomorph.defaults.callbacks.beforeNodeRemoved;
        Idiomorph.defaults.callbacks.beforeNodeRemoved = function (node) {
            if (node && node.nodeType === 1) {
                if (node.id && /^appModal-/.test(node.id)) return false;
                if (node.hasAttribute && node.hasAttribute('data-cfg-preserve')) return false;
            }
            if (typeof _prevBeforeRemoved === 'function') return _prevBeforeRemoved(node);
        };
        Idiomorph.defaults.callbacks._cfgPreservePatched = true;
    }

    var registry = {};
    var currentKey = null;
    var loadedModules = {};   // src -> true (no recargar/re-declarar módulos)
    var boostUrlsRe = null;   // RegExp de URLs migradas (data-cfg-boost-urls)

    function root() { return document.getElementById('cfgMain'); }

    function teardown() {
        var hooks = currentKey && registry[currentKey];
        if (hooks && typeof hooks.destroy === 'function') {
            try { hooks.destroy(); }
            catch (e) { console.error('[ConfigPage] destroy ' + currentKey + ':', e); }
        }
    }

    function setup() {
        var hooks = currentKey && registry[currentKey];
        if (hooks && typeof hooks.init === 'function') {
            try { hooks.init(); }
            catch (e) { console.error('[ConfigPage] init ' + currentKey + ':', e); }
        }
    }

    // Carga secuencial (deps CDN antes que el módulo app), dedup por src.
    // No llama setup(): cada módulo termina con ConfigPage.register(key, ...)
    // y register() dispara init solo si su página sigue activa (anti doble-init).
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
            s.onerror = function () { console.error('[ConfigPage] fallo módulo ' + src); next(); };
            document.head.appendChild(s);
        }
        next();
    }

    function syncBoostUrls(el) {
        var raw = el ? (el.getAttribute('data-cfg-boost-urls') || '') : '';
        try { boostUrlsRe = raw ? new RegExp(raw) : null; }
        catch (e) { boostUrlsRe = null; }
    }

    function activate() {
        var el = root();
        syncBoostUrls(el);
        var key = el ? (el.getAttribute('data-cfg-page') || null) : null;
        if (key === currentKey) return;          // mismo destino → no-op
        teardown();
        currentKey = key;
        if (!key) return;
        if (registry[key]) { setup(); return; }  // módulo ya cargado → re-init
        var mods = el.getAttribute('data-cfg-modules');
        if (!mods) { setup(); return; }          // página migrada sin JS
        loadModules(mods);
    }

    function register(key, hooks) {
        if (!key) return;
        registry[key] = hooks || {};
        if (key === currentKey) setup();
    }

    // --- Modales: limpieza previa a CUALQUIER navegación morph ----------------
    function closeOpenModals() {
        document.querySelectorAll('.modal.show').forEach(function (el) {
            if (window.bootstrap) {
                var inst = bootstrap.Modal.getInstance(el);
                // dispose (no hide): hide es async por el fade y el backdrop
                // moriría DESPUÉS del swap; dispose corta la instancia ya.
                if (inst) { try { inst.dispose(); } catch (e) { /* ya dispuesto */ } }
            }
            el.classList.remove('show');
            el.style.display = 'none';
            el.setAttribute('aria-hidden', 'true');
        });
        document.querySelectorAll('.modal-backdrop').forEach(function (b) { b.remove(); });
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }

    function isBoostableClient(url) {
        if (!url || !boostUrlsRe) return false;
        try {
            var u = new URL(url, window.location.origin);
            if (u.origin !== window.location.origin) return false;
            return boostUrlsRe.test(u.pathname);
        } catch (e) {
            return false;
        }
    }

    // navigate(url, opts): morph programático hacia una página migrada, o recarga.
    // History delegado a htmx via fuente efímera con hx-push-url (hereda el
    // hx-ext del body → morph + head-support funcionan; sin doble pushState).
    // opts.push === false → no toca el historial (lo usa refresh()).
    function navigate(url, opts) {
        if (!url) return;
        var htmx = window.htmx;
        if (!isBoostableClient(url) || !htmx || typeof htmx.ajax !== 'function') {
            window.location.href = url;      // no migrada / cross-app / sin htmx
            return;
        }
        closeOpenModals();
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
            if (done && typeof done.finally === 'function') done.finally(cleanup);
            else setTimeout(cleanup, 5000);
        } catch (e) {
            cleanup();
            window.location.href = url;
        }
    }

    // refresh(): re-morfea la página ACTUAL con HTML fresco del servidor, sin
    // tocar el historial. Sustituto de location.reload() tras una mutación:
    // mismo resultado sin el flash en blanco ni perder el scroll.
    function refresh() { navigate(window.location.href, { push: false }); }

    // --- Boost delegado de los links de CONTENIDO -----------------------------
    // El sidebar lleva hx-boost server-side (cfg_boost_attr), pero los links del
    // contenido (nav-cards del index, breadcrumbs, "ver detalle", y los que
    // renderizan los módulos por innerHTML) no: hacían full-reload y parpadeaba
    // todo el shell. Un ÚNICO listener en document los captura — vive fuera del
    // árbol morfeado, así que sobrevive a los swaps y cubre también el HTML
    // inyectado por JS (que htmx nunca procesó).
    // Se cede el click a htmx/al navegador cuando el usuario pidió otra cosa:
    // ctrl/cmd/shift/alt-click, botón central, target, download, o cualquier
    // ancla que ya declare hx-* (incluido hx-boost="false" como opt-out).
    var NON_HTTP_SCHEME = /^(?!https?:)[a-z][a-z0-9+.-]*:/i;

    function onDocumentClick(e) {
        if (e.defaultPrevented || e.button !== 0) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        if (!currentKey) return;                     // shell fuera del island
        var a = e.target && e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        if (a.hasAttribute('download')) return;
        var target = a.getAttribute('target');
        if (target && target !== '_self') return;
        if (a.closest('[hx-boost], [hx-get], [hx-post]')) return;  // lo maneja htmx
        var href = a.getAttribute('href');
        if (!href || href.charAt(0) === '#' || NON_HTTP_SCHEME.test(href)) return;
        if (!isBoostableClient(a.href)) return;      // whitelist data-cfg-boost-urls
        e.preventDefault();
        navigate(a.href);
    }

    document.addEventListener('click', onDocumentClick);

    function boot() { activate(); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    document.body.addEventListener('htmx:afterSettle', activate);
    document.body.addEventListener('htmx:historyRestore', activate);
    // Links boosteados del sidebar: cerrar modales ANTES del request/swap.
    document.body.addEventListener('htmx:beforeRequest', function (evt) {
        if (evt && evt.detail && evt.detail.boosted) closeOpenModals();
    });

    window.ConfigPage = { register: register, navigate: navigate, refresh: refresh };
    Object.defineProperty(window.ConfigPage, 'page', {
        get: function () { return currentKey; }
    });
})();
