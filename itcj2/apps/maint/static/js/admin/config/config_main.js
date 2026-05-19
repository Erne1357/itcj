/**
 * config_main.js — Router de tabs por hash para la página de Configuración
 * de Mantenimiento (/maint/admin/config).
 *
 * Lógica:
 *  - Al cargar, activa el tab correspondiente a location.hash (o el primero).
 *  - Al cambiar de tab, actualiza location.hash sin recargar la página.
 *  - Coordina la init lazy de sub-módulos: llama a su init() la primera vez
 *    que se muestra el tab correspondiente.
 */

// === CONSTANTES ===
const TAB_DEFAULT = 'categorias';

const VALID_HASHES = new Set([
    'categorias',
    'areas',
    'prioridades',
    'tipos',
    'notif',
    'audit',
]);

/**
 * Mapa hash → función de init lazy.
 * Cada módulo expone window.MaintConfig{Nombre}.init() y se llama
 * exactamente una vez cuando el tab se muestra por primera vez.
 * El flag de "ya inicializado" lo maneja cada módulo internamente.
 */
const TAB_INITS = {
    categorias: function () {
        if (window.MaintConfigCategories) {
            window.MaintConfigCategories.init();
        }
    },
    areas: function () {
        if (window.MaintConfigAreas) {
            window.MaintConfigAreas.init();
        }
    },
    prioridades: function () {
        if (window.MaintConfigPriorities) {
            window.MaintConfigPriorities.init();
        }
    },
    tipos: function () {
        if (window.MaintConfigCatalogs) {
            window.MaintConfigCatalogs.init();
        }
    },
    notif: function () {
        if (window.MaintConfigNotifications) {
            window.MaintConfigNotifications.init();
        }
    },
    audit: function () {
        if (window.MaintConfigAudit) {
            window.MaintConfigAudit.init();
        }
    },
};

// === INICIALIZACIÓN ===
document.addEventListener('DOMContentLoaded', function () {
    // El listener de shown.bs.tab DEBE adjuntarse ANTES de la primera
    // activación: el botón de tab no tiene clase `fade`, por lo que
    // Bootstrap 5.3 dispara `shown.bs.tab` de forma SÍNCRONA dentro de
    // .show(); si el listener no existe aún, el init lazy del tab inicial
    // nunca corre (spinner infinito).
    setupHashSync();
    activateTabFromHash();

    // Navegación vía dropdown "Configuración" (links .../config#frag):
    // estando ya en la página solo cambia el hash, sin recargar. Sin este
    // listener el tab no cambiaría al usar el menú.
    window.addEventListener('hashchange', activateTabFromHash);
});

// === ACTIVACIÓN INICIAL ===
/**
 * Lee location.hash y activa el tab correspondiente.
 * Si el hash no es válido o no existe, activa el tab por defecto.
 */
function activateTabFromHash() {
    const hash = location.hash.replace('#', '').trim();
    const target = VALID_HASHES.has(hash) ? hash : TAB_DEFAULT;

    const tabBtn = document.querySelector(
        `#configTabs button[data-hash="${target}"]`
    );
    if (tabBtn) {
        bootstrap.Tab.getOrCreateInstance(tabBtn).show();
    }
}

// === SINCRONIZACIÓN DE HASH + INIT LAZY ===
/**
 * Escucha el evento `shown.bs.tab` de Bootstrap para:
 *   1. Actualizar location.hash (sin entrada extra en el historial).
 *   2. Llamar al init lazy del módulo correspondiente (si existe).
 */
function setupHashSync() {
    const tabsEl = document.getElementById('configTabs');
    if (!tabsEl) return;

    tabsEl.addEventListener('shown.bs.tab', function (e) {
        const hash = e.target.getAttribute('data-hash');
        if (hash) {
            history.replaceState(null, '', '#' + hash);
            // Init lazy del sub-módulo
            if (typeof TAB_INITS[hash] === 'function') {
                TAB_INITS[hash]();
            }
        }
    });
}
