/* =============================================================================
   ConfigShell — shell del panel /itcj/config (sidebar, iframe móvil, toasts).
   IIFE morph-safe: handlers DELEGADOS en document (sobreviven a los swaps de
   idiomorph; los botones se recrean, el listener no vive en ellos).
   Expone window.ConfigShell + window.ConfigUtils y mantiene los alias legacy
   showSuccess/showError que consumen los page-JS pre-F3.
   ============================================================================= */
(function () {
    'use strict';
    if (window.ConfigShell) return; // singleton

    var inIframe = window.self !== window.top;

    // ---- Sidebar ------------------------------------------------------------
    function sidebarEl() { return document.getElementById('configSidebar'); }
    function overlayEl() { return document.getElementById('sidebarOverlay'); }

    // El off-canvas móvil se cierra SOLO por transform (ver config-base.css
    // ~L602): sin visibility:hidden el sidebar sigue teniendo bounding box y
    // Playwright (gotoCore) lo ve "visible". Para no romper eso pero sacar los
    // ~8 links del tab order / árbol de accesibilidad mientras está cerrado en
    // móvil, togglear inert + aria-hidden desde JS (no cambian visibilidad
    // computada ni el bounding box).
    var mobileMql = window.matchMedia('(max-width: 768px)');

    function lockSidebarA11y(sidebar) {
        sidebar.setAttribute('inert', '');
        sidebar.setAttribute('aria-hidden', 'true');
    }

    function unlockSidebarA11y(sidebar) {
        sidebar.removeAttribute('inert');
        sidebar.removeAttribute('aria-hidden');
    }

    // Sincroniza inert/aria-hidden según breakpoint + estado open/closed actual.
    function syncSidebarA11y() {
        var sidebar = sidebarEl();
        if (!sidebar) return;
        if (mobileMql.matches && !sidebar.classList.contains('open')) {
            lockSidebarA11y(sidebar);
        } else {
            unlockSidebarA11y(sidebar);
        }
    }

    function openSidebar() {
        var sidebar = sidebarEl();
        var overlay = overlayEl();
        if (!sidebar) return;
        sidebar.classList.add('open');
        if (overlay) overlay.classList.add('show');
        unlockSidebarA11y(sidebar);
    }

    function closeSidebar() {
        var sidebar = sidebarEl();
        var overlay = overlayEl();
        if (sidebar) sidebar.classList.remove('open');
        if (overlay) overlay.classList.remove('show');
        if (sidebar && mobileMql.matches) lockSidebarA11y(sidebar);
    }

    function toggleSidebar() {
        var sidebar = sidebarEl();
        if (sidebar && sidebar.classList.contains('open')) closeSidebar();
        else openSidebar();
    }

    // Regreso al dashboard móvil (shell iframe del core)
    function goToDashboard() {
        if (inIframe) {
            try {
                window.parent.postMessage({ type: 'CLOSE_APP', source: 'config' }, window.location.origin);
                return;
            } catch (e) {
                console.warn('No se pudo notificar al parent:', e);
            }
        }
        window.location.href = '/itcj/m/';
    }

    // Delegación única (sustituye los onclick="" del template)
    document.addEventListener('click', function (e) {
        if (e.target.closest('.config-mobile-toggle')) { toggleSidebar(); return; }
        if (e.target.closest('#sidebarOverlay')) { closeSidebar(); return; }
        if (e.target.closest('#mobileBackToDashboard')) { goToDashboard(); return; }
        // En rail/off-canvas (≤992px), navegar desde el sidebar lo cierra
        if (e.target.closest('.config-nav-link') && window.innerWidth <= 992) closeSidebar();
    });

    // Estado inicial (carga directa en móvil con sidebar cerrado) + reacción a
    // cambios de breakpoint (rotación, resize de ventana/DevTools).
    syncSidebarA11y();
    if (typeof mobileMql.addEventListener === 'function') {
        mobileMql.addEventListener('change', syncSidebarA11y);
    } else if (typeof mobileMql.addListener === 'function') {
        mobileMql.addListener(syncSidebarA11y); // Safari <14
    }

    // body es el target del morph:innerHTML: sus ATRIBUTOS no se morfean,
    // así que la clase de iframe puesta aquí persiste entre navegaciones.
    if (inIframe) document.body.classList.add('in-mobile-iframe');
    // (#normalMobileToggle se oculta por CSS: body.in-mobile-iframe #normalMobileToggle)

    // ---- Toasts + helpers compartidos ----------------------------------------
    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // type: 'success' (default) | 'error' | 'danger'
    function showToast(message, type) {
        var isError = type === 'error' || type === 'danger';
        var msgEl = document.getElementById(isError ? 'errorMessage' : 'successMessage');
        var toastEl = document.getElementById(isError ? 'errorToast' : 'successToast');
        if (!msgEl || !toastEl || !window.bootstrap) return;
        msgEl.textContent = message;
        bootstrap.Toast.getOrCreateInstance(toastEl).show();
    }

    function showSuccess(message) { showToast(message, 'success'); }
    function showError(message) { showToast(message, 'error'); }

    window.ConfigShell = {
        toggleSidebar: toggleSidebar,
        closeSidebar: closeSidebar,
        goToDashboard: goToDashboard,
        inIframe: inIframe
    };
    window.ConfigUtils = { showToast: showToast, escapeHtml: escapeHtml };
    // Alias legacy (page-JS pre-F3); se retiran cuando F3-F5 reescriban cada página.
    window.showSuccess = showSuccess;
    window.showError = showError;
    window.API_BASE = window.API_BASE || '/api/core/v2';
})();
