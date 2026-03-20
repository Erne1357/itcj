'use strict';

// Detectar si estamos en un iframe móvil
const inIframe = window.self !== window.top;
if (inIframe) {
    document.body.classList.add('in-mobile-iframe');
    // Ocultar el toggle normal
    const normalToggle = document.getElementById('normalMobileToggle');
    if (normalToggle) normalToggle.style.display = 'none';
}

// Toggle sidebar en movil
function toggleSidebar() {
    const sidebar = document.getElementById('configSidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (sidebar.classList.contains('open')) {
        closeSidebar();
    } else {
        // Forzar repaint antes de abrir
        sidebar.style.display = 'none';
        sidebar.offsetHeight; // Trigger reflow
        sidebar.style.display = '';

        // Pequeño delay para asegurar el repaint
        requestAnimationFrame(() => {
            sidebar.classList.add('open');
            overlay.classList.add('show');
        });
    }
}

function closeSidebar() {
    const sidebar = document.getElementById('configSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
}

// Regresar al dashboard (para iframe móvil)
function goToDashboard() {
    if (inIframe) {
        try {
            window.parent.postMessage({
                type: 'CLOSE_APP',
                source: 'config'
            }, window.location.origin);
        } catch (e) {
            console.warn('No se pudo notificar al parent:', e);
            window.location.href = '/itcj/m/';
        }
    } else {
        window.location.href = '/itcj/m/';
    }
}

// Cerrar sidebar al hacer click en un enlace (móvil)
document.addEventListener('DOMContentLoaded', function() {
    const navLinks = document.querySelectorAll('.config-nav-link');
    navLinks.forEach(link => {
        link.addEventListener('click', function() {
            if (window.innerWidth <= 768) {
                closeSidebar();
            }
        });
    });

    // Forzar repaint inicial del sidebar en móvil
    if (window.innerWidth <= 768) {
        const sidebar = document.getElementById('configSidebar');
        sidebar.style.display = 'none';
        sidebar.offsetHeight;
        sidebar.style.display = '';
    }

    // Bind del botón de regreso al dashboard
    const backBtn = document.getElementById('mobileBackToDashboard');
    if (backBtn) {
        backBtn.addEventListener('click', goToDashboard);
    }
});

// Utilidades de toast
function showSuccess(message) {
    document.getElementById('successMessage').textContent = message;
    new bootstrap.Toast(document.getElementById('successToast')).show();
}

function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    new bootstrap.Toast(document.getElementById('errorToast')).show();
}

// API Base URL
const API_BASE = '/api/core/v2';
