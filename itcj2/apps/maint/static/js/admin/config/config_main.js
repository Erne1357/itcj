/**
 * config_main.js — Router de tabs por hash para la página de Configuración
 * de Mantenimiento (/maint/admin/config).
 *
 * Lógica:
 *  - Al cargar, activa el tab correspondiente a location.hash (o el primero).
 *  - Al cambiar de tab, actualiza location.hash sin recargar la página.
 * Sin lógica de datos — esqueleto navegable (Fase 1).
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

// === INICIALIZACIÓN ===
document.addEventListener('DOMContentLoaded', function () {
    activateTabFromHash();
    setupHashSync();
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

// === SINCRONIZACIÓN DE HASH ===
/**
 * Escucha el evento `shown.bs.tab` de Bootstrap para actualizar
 * location.hash cada vez que el usuario cambia de tab.
 * Se usa replaceState para no generar entradas de historial extra.
 */
function setupHashSync() {
    const tabsEl = document.getElementById('configTabs');
    if (!tabsEl) return;

    tabsEl.addEventListener('shown.bs.tab', function (e) {
        const hash = e.target.getAttribute('data-hash');
        if (hash) {
            history.replaceState(null, '', '#' + hash);
        }
    });
}
