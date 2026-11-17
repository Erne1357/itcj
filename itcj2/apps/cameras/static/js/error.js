/**
 * Página de error de Cámaras.
 * El botón que SALE de la app (403 sin acceso) avisa al parent para cerrar la
 * ventana del escritorio en vez de recargarlo; fuera de iframe navega normal.
 */
document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('errorActionBtn');
    if (!btn || !document.getElementById('mobileBackToDashboard')) return;
    if (window.self === window.top) return;
    btn.addEventListener('click', function (e) {
        e.preventDefault();
        try {
            window.parent.postMessage({ type: 'CLOSE_APP', source: 'error-page' }, window.location.origin);
        } catch (_) {
            window.location.href = btn.getAttribute('href');
        }
    });
});
