/**
 * config_main.js
 * Punto de entrada de la pestaña de Configuración — navegación HTMX.
 *
 * Responsabilidades:
 *  - Activar el tab indicado por el hash de la URL (#categorias, #prioridades, ...).
 *  - Mantener sincronizado el hash al cambiar de tab.
 *  - Disparar config:tab-shown para que cada módulo de tab se lazy-inite.
 *  - Al destruir (navigate away): emitir config:teardown para que cada tab
 *    limpie su estado y quede listo para reinicializarse en la próxima visita.
 *
 * Registra window.HelpdeskPage.page('admin_config', { init, destroy }).
 */
(function () {
    'use strict';

    const TAB_BUTTON_BY_HASH = {
        '#categorias':  'tab-categorias-btn',
        '#inv-cat':     'tab-inv-cat-btn',
        '#prioridades': 'tab-prioridades-btn',
        '#estados':     'tab-estados-btn',
        '#areas':       'tab-areas-btn',
        '#notif':       'tab-notif-btn',
        '#audit':       'tab-audit-btn',
    };

    // Listeners propios de esta instancia para poder quitarlos en destroy()
    let _tabListeners   = [];  // [{btn, listener}]
    let _hashListener   = null;

    // === ACTIVAR TAB POR HASH ===
    function activateTabFromHash() {
        const hash     = window.location.hash || '#categorias';
        const buttonId = TAB_BUTTON_BY_HASH[hash];
        if (!buttonId) return;

        const btn = document.getElementById(buttonId);
        if (!btn || !window.bootstrap) return;

        const tab = bootstrap.Tab.getOrCreateInstance(btn);
        tab.show();
    }

    // === BIND TABS + HASH SYNC ===
    function bindHashSync() {
        document.querySelectorAll('#configTabs button[data-bs-toggle="tab"]').forEach(function (btn) {
            function onShown(e) {
                const target = e.target.getAttribute('data-bs-target');
                if (target && window.location.hash !== target) {
                    history.replaceState(null, '', target);
                }
                document.dispatchEvent(new CustomEvent('config:tab-shown', {
                    detail: { tab: target },
                }));
            }
            btn.addEventListener('shown.bs.tab', onShown);
            _tabListeners.push({ btn: btn, listener: onShown });
        });

        _hashListener = function () { activateTabFromHash(); };
        window.addEventListener('hashchange', _hashListener);
    }

    // === DISPATCH INITIAL TAB ===
    function dispatchInitialTab() {
        // Encuentra el tab activo en el DOM y emite el evento para que el módulo
        // correspondiente se lazy-inite inmediatamente.
        const hash     = window.location.hash || '#categorias';
        const buttonId = TAB_BUTTON_BY_HASH[hash];
        const target   = buttonId ? ('#' + (document.getElementById(buttonId) || {}).getAttribute?.('data-bs-target')?.slice(1) || hash.slice(1)) : hash;

        // Forma más directa: simplemente emitir con el hash como tab
        document.dispatchEvent(new CustomEvent('config:tab-shown', {
            detail: { tab: hash },
        }));
    }

    // === INIT ===
    function init() {
        bindHashSync();
        activateTabFromHash();
        dispatchInitialTab();
    }

    // === DESTROY ===
    function destroy() {
        // 1. Avisar a todos los tabs para que hagan teardown
        document.dispatchEvent(new CustomEvent('config:teardown'));

        // 2. Quitar los listeners de tab de Bootstrap
        _tabListeners.forEach(function (item) {
            item.btn.removeEventListener('shown.bs.tab', item.listener);
        });
        _tabListeners = [];

        // 3. Quitar listener de hashchange
        if (_hashListener) {
            window.removeEventListener('hashchange', _hashListener);
            _hashListener = null;
        }

        // 4. Cerrar el modal field-builder si está abierto (evita orphan modals)
        const builderModalEl = document.getElementById('modal-field-builder');
        if (builderModalEl) {
            const inst = bootstrap.Modal.getInstance(builderModalEl);
            if (inst) {
                try { inst.hide(); } catch (_) {}
            }
        }
    }

    // === REGISTRO ===
    if (window.HelpdeskPage && typeof window.HelpdeskPage.page === 'function') {
        window.HelpdeskPage.page('admin_config', { init: init, destroy: destroy });
    }

})();
