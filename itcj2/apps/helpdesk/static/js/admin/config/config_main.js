/**
 * config_main.js
 * Punto de entrada de la pestaña de Configuración (Fase 1: esqueleto).
 *
 * Responsabilidades:
 *  - Activar el tab indicado por el hash de la URL (#categorias, #prioridades, ...).
 *  - Mantener sincronizado el hash al cambiar de tab.
 *  - Punto de extensión para inicializar lazy cada módulo de tab en fases siguientes.
 */
(function () {
    'use strict';

    const TAB_BUTTON_BY_HASH = {
        '#categorias': 'tab-categorias-btn',
        '#inv-cat': 'tab-inv-cat-btn',
        '#prioridades': 'tab-prioridades-btn',
        '#estados': 'tab-estados-btn',
        '#areas': 'tab-areas-btn',
        '#notif': 'tab-notif-btn',
        '#audit': 'tab-audit-btn',
    };

    function activateTabFromHash() {
        const hash = window.location.hash || '#categorias';
        const buttonId = TAB_BUTTON_BY_HASH[hash];
        if (!buttonId) return;

        const btn = document.getElementById(buttonId);
        if (!btn || !window.bootstrap) return;

        const tab = bootstrap.Tab.getOrCreateInstance(btn);
        tab.show();
    }

    function bindHashSync() {
        document.querySelectorAll('#configTabs button[data-bs-toggle="tab"]').forEach((btn) => {
            btn.addEventListener('shown.bs.tab', (e) => {
                const target = e.target.getAttribute('data-bs-target');
                if (target && window.location.hash !== target) {
                    history.replaceState(null, '', target);
                }
                document.dispatchEvent(new CustomEvent('config:tab-shown', {
                    detail: { tab: target },
                }));
            });
        });

        window.addEventListener('hashchange', activateTabFromHash);
    }

    document.addEventListener('DOMContentLoaded', () => {
        bindHashSync();
        activateTabFromHash();
    });
})();
