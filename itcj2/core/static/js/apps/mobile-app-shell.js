/**
 * Mobile App Shell - Sidebar & Back Button Handler
 * Script compartido para apps en iframe móvil
 */

(function() {
    'use strict';

    // Detectar si estamos en un iframe móvil
    const inIframe = window.self !== window.top;
    
    // Agregar clase al body si está en iframe
    if (inIframe) {
        document.body.classList.add('in-mobile-iframe');
    }

    /**
     * Clase para manejar el sidebar y navegación móvil
     */
    class MobileAppShell {
        constructor() {
            this.sidebar = document.getElementById('appSidebar');
            this.overlay = document.getElementById('appSidebarOverlay');
            this.trigger = document.getElementById('sidebarTrigger');
            this.closeBtn = document.getElementById('sidebarClose');
            this.backBtn = document.getElementById('mobileBackToDashboard');
            
            this.isOpen = false;
            
            this.init();
        }

        init() {
            this.bindEvents();
            this.setupBackButton();
        }

        /**
         * Abre el sidebar con animación
         */
        open() {
            if (!this.sidebar || !this.overlay) return;
            
            this.sidebar.classList.add('active');
            this.overlay.classList.add('active');
            document.body.classList.add('sidebar-open');
            this.isOpen = true;
            
            // Focus trap
            this.sidebar.focus();
        }

        /**
         * Cierra el sidebar con animación
         */
        close() {
            if (!this.sidebar || !this.overlay) return;
            
            this.sidebar.classList.remove('active');
            this.overlay.classList.remove('active');
            document.body.classList.remove('sidebar-open');
            this.isOpen = false;
        }

        /**
         * Toggle del sidebar
         */
        toggle() {
            if (this.isOpen) {
                this.close();
            } else {
                this.open();
            }
        }

        /**
         * Configura el botón de regreso al dashboard
         */
        setupBackButton() {
            if (!this.backBtn) return;
            
            this.backBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.goToDashboard();
            });
        }

        /**
         * Regresa al dashboard (notifica al parent si está en iframe)
         */
        goToDashboard() {
            if (inIframe) {
                try {
                    window.parent.postMessage({
                        type: 'CLOSE_APP',
                        source: this.getAppName()
                    }, window.location.origin);
                } catch (e) {
                    console.warn('[MobileAppShell] No se pudo notificar al parent:', e);
                    window.location.href = '/itcj/m/';
                }
            } else {
                window.location.href = '/itcj/m/';
            }
        }

        /**
         * Obtiene el nombre de la app actual
         */
        getAppName() {
            const path = window.location.pathname;
            if (path.includes('/agendatec')) return 'agendatec';
            if (path.includes('/helpdesk')) return 'helpdesk';
            if (path.includes('/vistetec')) return 'vistetec';
            return 'app';
        }

        /**
         * Bind de eventos
         */
        bindEvents() {
            // Trigger (hamburger button)
            this.trigger?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggle();
            });

            // Close button
            this.closeBtn?.addEventListener('click', (e) => {
                e.preventDefault();
                this.close();
            });

            // Overlay click
            this.overlay?.addEventListener('click', () => {
                this.close();
            });

            // ESC key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.isOpen) {
                    this.close();
                }
            });

            // Swipe to close (básico)
            let touchStartX = 0;
            this.sidebar?.addEventListener('touchstart', (e) => {
                touchStartX = e.touches[0].clientX;
            }, { passive: true });

            this.sidebar?.addEventListener('touchmove', (e) => {
                const touchX = e.touches[0].clientX;
                const diff = touchX - touchStartX;
                
                // Si desliza hacia la derecha más de 50px, cerrar
                if (diff > 50) {
                    this.close();
                }
            }, { passive: true });

            // Items del sidebar (cerrar al hacer click)
            this.sidebar?.querySelectorAll('.app-sidebar-item').forEach(item => {
                item.addEventListener('click', () => {
                    // Pequeño delay para mostrar feedback visual
                    setTimeout(() => this.close(), 150);
                });
            });
        }
    }

    // Inicializar cuando el DOM esté listo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.mobileAppShell = new MobileAppShell();
        });
    } else {
        window.mobileAppShell = new MobileAppShell();
    }

})();
