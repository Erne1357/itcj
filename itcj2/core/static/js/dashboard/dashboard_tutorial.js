/**
 * ========================================
 * TUTORIAL DEL DASHBOARD - Shepherd.js
 * ========================================
 *
 * Tutorial interactivo que guía al usuario a través de las funcionalidades
 * principales del dashboard: aplicaciones, notificaciones, perfil y navegación.
 */

// ==================== CONFIGURACIÓN GLOBAL ====================
const DASHBOARD_TUTORIAL_CONFIG = {
    storageKey: 'dashboard_tutorial_completed',
    tutorialModeKey: 'dashboard_tutorial_mode_active',
    autoStart: true,
    theme: 'light',
    notificationsDataUrl: '/static/core/data/tutorial_notifications.json'
};

// ==================== UTILIDADES DEL TUTORIAL ====================
const DashboardTutorialUtils = {
    /**
     * Guarda datos en localStorage
     */
    setItem(key, value) {
        localStorage.setItem(key, value);
    },

    /**
     * Obtiene datos del localStorage
     */
    getItem(key) {
        return localStorage.getItem(key);
    },

    /**
     * Elimina datos del localStorage
     */
    removeItem(key) {
        localStorage.removeItem(key);
    },

    /**
     * Muestra un mensaje con Bootstrap toast o modal
     */
    showMessage(title, message, type = 'info') {
        // Crear un toast de Bootstrap
        const toastContainer = document.getElementById('toastContainer') || this.createToastContainer();

        const toastId = 'toast-' + Date.now();
        const bgClass = type === 'success' ? 'bg-success' : type === 'error' ? 'bg-danger' : 'bg-info';

        const toastHTML = `
            <div id="${toastId}" class="toast align-items-center text-white ${bgClass} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">
                        <strong>${title}</strong><br>${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;

        toastContainer.insertAdjacentHTML('beforeend', toastHTML);

        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
        toast.show();

        // Remover del DOM después de ocultarse
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    },

    /**
     * Crea el contenedor de toasts si no existe
     */
    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '10000';
        document.body.appendChild(container);
        return container;
    },

    /**
     * Carga las notificaciones de prueba desde JSON
     */
    async loadTutorialNotifications() {
        try {
            const response = await fetch(DASHBOARD_TUTORIAL_CONFIG.notificationsDataUrl);
            if (!response.ok) {
                throw new Error('No se pudieron cargar las notificaciones de prueba');
            }
            const data = await response.json();
            return data.notifications || [];
        } catch (error) {
            console.error('Error cargando notificaciones de prueba:', error);
            return [];
        }
    }
};

// ==================== CLASE PRINCIPAL DEL TUTORIAL ====================
class DashboardTutorial {
    constructor() {
        this.tour = null;
        this.isNavigating = false;
        this.originalInteractiveState = new Map();
        this.tutorialNotifications = [];
        this.isRunning = false; // Nueva variable para prevenir múltiples instancias
    }

    /**
     * Verifica si el usuario ya completó el tutorial
     */
    hasCompletedTutorial() {
        return DashboardTutorialUtils.getItem(DASHBOARD_TUTORIAL_CONFIG.storageKey) === 'true';
    }

    /**
     * Marca el tutorial como completado
     */
    markTutorialComplete() {
        DashboardTutorialUtils.setItem(DASHBOARD_TUTORIAL_CONFIG.storageKey, 'true');
        DashboardTutorialUtils.removeItem(DASHBOARD_TUTORIAL_CONFIG.tutorialModeKey);
    }

    /**
     * Reinicia el tutorial (borra el estado)
     */
    resetTutorial() {
        DashboardTutorialUtils.removeItem(DASHBOARD_TUTORIAL_CONFIG.storageKey);
        DashboardTutorialUtils.removeItem(DASHBOARD_TUTORIAL_CONFIG.tutorialModeKey);
        location.reload();
    }

    /**
     * Activa el modo tutorial
     */
    enableTutorialMode() {
        DashboardTutorialUtils.setItem(DASHBOARD_TUTORIAL_CONFIG.tutorialModeKey, 'true');
    }

    /**
     * Desactiva el modo tutorial
     */
    disableTutorialMode() {
        DashboardTutorialUtils.removeItem(DASHBOARD_TUTORIAL_CONFIG.tutorialModeKey);
    }

    /**
     * Verifica si está en modo tutorial
     */
    isTutorialModeActive() {
        return DashboardTutorialUtils.getItem(DASHBOARD_TUTORIAL_CONFIG.tutorialModeKey) === 'true';
    }

    /**
     * Paso al que se vuelve al reanudar: los pasos que dependen de una ventana
     * o del panel demo (ya cerrados al cancelar) retroceden al paso que los abre.
     */
    getResumeStepId() {
        const back = {
            'window-opened': 'double-click-demo',
            'close-window-demo': 'double-click-demo',
            'notifications-panel': 'notifications-demo',
            'profile-window': 'open-profile-demo'
        };
        return back[this.lastStepId] || this.lastStepId;
    }

    /** Reanuda el tour (tras "Continuar Tutorial" o cerrar el modal de cancelación). */
    resumeTour() {
        if (this.isRunning) return;
        const stepId = this.getResumeStepId();
        this.isNavigating = false;
        this.isRunning = true;
        this.enableTutorialMode();
        this.initializeTour();
        this.getDashboardSteps().forEach(step => this.tour.addStep(step));
        this.installMenuGuard();
        this.tour.start();
        if (stepId) this.tour.show(stepId);
    }

    /**
     * Muestra confirmación de cancelación del tutorial
     */
    showCancelConfirmation() {
        // Crear modal de confirmación si no existe
        let modal = document.getElementById('dashboardTutorialCancelModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'dashboardTutorialCancelModal';
            modal.className = 'modal fade';
            modal.setAttribute('tabindex', '-1');
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important; color: white !important; border-bottom: none;">
                            <h5 class="modal-title" style="color: white !important; font-weight: 600;">
                                <i class="bi bi-box-arrow-right me-2"></i>
                                Salir del Tutorial
                            </h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p class="mb-3">¿Estás seguro de que quieres salir del tutorial?</p>
                            <div class="alert alert-warning mb-0" style="border-left: 4px solid #ffc107;">
                                <i class="bi bi-info-circle me-2"></i>
                                Podrás iniciarlo de nuevo más tarde haciendo click en el botón <strong>"Tutorial"</strong> en la barra inferior.
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                <i class="bi bi-arrow-left me-1"></i>
                                Continuar Tutorial
                            </button>
                            <button type="button" class="btn btn-danger" id="dashboardTutorialCancelConfirm">
                                <i class="bi bi-x-circle me-1"></i>
                                Salir del Tutorial
                            </button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const bsModal = new bootstrap.Modal(modal);
        this.cancelConfirmed = false;
        bsModal.show();

        // Cerrar el modal sin confirmar (X, Esc o "Continuar Tutorial") reanuda el tour
        modal.addEventListener('hidden.bs.modal', () => {
            if (!this.cancelConfirmed) this.resumeTour();
        }, { once: true });

        // Configurar botón de confirmación
        const confirmBtn = document.getElementById('dashboardTutorialCancelConfirm');
        if (confirmBtn) {
            // Remover listeners anteriores
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

            newConfirmBtn.onclick = () => {
                this.cancelConfirmed = true;
                bsModal.hide();

                // IMPORTANTE: Restaurar interfaz antes de marcar como completado
                this.enableAllInteractiveElements();
                this.isRunning = false; // Marcar como no activo

                // Re-habilitar el botón de tutorial
                const tutorialButton = document.getElementById('dashboardTutorialButton');
                if (tutorialButton) {
                    tutorialButton.disabled = false;
                    tutorialButton.style.opacity = '';
                    tutorialButton.style.cursor = '';
                }

                this.markTutorialComplete();

                // Mostrar mensaje de éxito con mejor estilo
                this.showStyledMessage(
                    'Tutorial Omitido',
                    'Puedes reiniciar el tutorial en cualquier momento desde el botón "Tutorial" en la barra inferior.',
                    'info',
                    'info-circle'
                );
            };
        }
    }

    /**
     * Muestra un mensaje estilizado con iconos
     */
    showStyledMessage(title, message, type = 'info', icon = 'info-circle') {
        // Crear un toast estilizado similar a los modales
        const toast = document.createElement('div');
        toast.className = 'position-fixed top-0 start-50 translate-middle-x p-3';
        toast.style.zIndex = '10000';
        toast.style.marginTop = '20px';

        const bgColors = {
            'success': '#28a745',
            'info': '#667eea',
            'warning': '#ffc107',
            'error': '#dc3545'
        };

        toast.innerHTML = `
            <div class="toast show" role="alert" style="min-width: 350px; border: none; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                <div class="toast-header" style="background: ${bgColors[type]}; color: white; border: none;">
                    <i class="bi bi-${icon} me-2"></i>
                    <strong class="me-auto">${title}</strong>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;

        document.body.appendChild(toast);

        // Auto-remover después de 5 segundos
        setTimeout(() => {
            toast.remove();
        }, 5000);
    }

    /**
     * Muestra modal de felicitación al completar el tutorial
     */
    showCompletionModal() {
        // Crear modal de felicitación si no existe
        let modal = document.getElementById('dashboardTutorialCompletionModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'dashboardTutorialCompletionModal';
            modal.className = 'modal fade';
            modal.setAttribute('tabindex', '-1');
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header" style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%) !important; color: white !important; border-bottom: none;">
                            <h5 class="modal-title" style="color: white !important; font-weight: 600;">
                                <i class="bi bi-trophy-fill me-2"></i>
                                ¡Tutorial Completado!
                            </h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body text-center py-4">
                            <div class="mb-4">
                                <i class="bi bi-check-circle-fill" style="font-size: 4rem; color: #28a745;"></i>
                            </div>
                            <h5 class="mb-3">¡Felicitaciones!</h5>
                            <p class="mb-3">Ya conoces las funcionalidades principales del dashboard ITCJ.</p>
                            <div class="alert alert-success mb-0" style="border-left: 4px solid #28a745;">
                                <i class="bi bi-lightbulb-fill me-2"></i>
                                ¡Comienza a explorar y aprovechar todas las herramientas disponibles!
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-success" data-bs-dismiss="modal" style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%) !important; border: none;">
                                <i class="bi bi-rocket-takeoff me-1"></i>
                                ¡Empezar a Usar el Dashboard!
                            </button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    /**
     * Inicializa Shepherd.js con la configuración
     */
    initializeTour() {
        this.tour = new Shepherd.Tour({
            useModalOverlay: true,
            defaultStepOptions: {
                classes: 'dashboard-tutorial-step',
                scrollTo: { behavior: 'smooth', block: 'center' },
                cancelIcon: {
                    enabled: true
                },
                modalOverlayOpeningPadding: 4,
                modalOverlayOpeningRadius: 8,
                popperOptions: {
                    modifiers: [{ name: 'offset', options: { offset: [0, 12] } }]
                }
            }
        });

        // Recordar el paso visible para poder reanudar tras una cancelación
        this.tour.on('show', (evt) => {
            if (evt && evt.step) this.lastStepId = evt.step.id;
        });

        // Evento cuando se completa el tour
        this.tour.on('complete', () => {
            this.removeTutorialNotificationPanel();
            this.removeMenuGuard();
            this.markTutorialComplete();
            this.enableAllInteractiveElements();
            this.isRunning = false; // Marcar como no activo

            // Re-habilitar el botón de tutorial
            const tutorialButton = document.getElementById('dashboardTutorialButton');
            if (tutorialButton) {
                tutorialButton.disabled = false;
                tutorialButton.style.opacity = '';
                tutorialButton.style.cursor = '';
            }

            // Mostrar modal de felicitación estilizado
            this.showCompletionModal();
        });

        // Evento cuando se cancela el tour
        this.tour.on('cancel', () => {
            if (this.isNavigating) {
                return;
            }

            // Restaurar todos los elementos interactivos
            this.removeMenuGuard();
            this.removeTutorialNotificationPanel();
            this.closeDesktopWindows();
            this.closeStartMenu();
            this.disableTutorialMode();
            this.enableAllInteractiveElements();
            this.isRunning = false; // Marcar como no activo

            // Mostrar confirmación
            this.showCancelConfirmation();
        });
    }

    /**
     * Deshabilita todos los elementos interactivos de la página
     */
    disableAllInteractiveElements() {
        const selectors = [
            '.desktop-icon',
            '.start-button',
            '.taskbar-app',
            '.system-icon',
            'button:not(.shepherd-button):not(.shepherd-cancel-icon):not(#dashboardTutorialButton)',
            'a',
            'input',
            'select',
            'textarea'
        ];

        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(element => {
                // Nunca desactivar los controles internos del popover de Shepherd
                if (element.closest('.shepherd-element')) return;
                if (!this.originalInteractiveState.has(element)) {
                    this.originalInteractiveState.set(element, {
                        pointerEvents: element.style.pointerEvents,
                        opacity: element.style.opacity,
                        cursor: element.style.cursor
                    });
                }

                element.style.pointerEvents = 'none';
                element.style.opacity = '0.6';
                element.style.cursor = 'not-allowed';
            });
        });
    }

    /**
     * Re-habilita todos los elementos interactivos
     */
    enableAllInteractiveElements() {
        this.originalInteractiveState.forEach((originalState, element) => {
            element.style.pointerEvents = originalState.pointerEvents;
            element.style.opacity = originalState.opacity;
            element.style.cursor = originalState.cursor;
        });
        this.originalInteractiveState.clear();

        // Llamar a limpieza completa para asegurar que todo quede bien
        this.cleanupTutorialState();
    }

    /**
     * Limpia completamente el estado del tutorial
     * Restaura TODOS los elementos que pudieron ser modificados
     */
    cleanupTutorialState() {
        // Restaurar el menú inicio y sus elementos clave
        const startMenu = document.getElementById('startMenu');
        if (startMenu) {
            startMenu.style.pointerEvents = '';
            startMenu.style.opacity = '';
            startMenu.style.cursor = '';
        }

        ['startMenuUser', 'startMenuSettings', 'startMenuLogout'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.style.pointerEvents = '';
            el.style.opacity = '';
            el.style.cursor = '';
            el.style.position = '';
            el.style.zIndex = '';
            el.classList.remove('tutorial-highlight');
        });

        // Restaurar íconos de aplicaciones
        document.querySelectorAll('.desktop-icon').forEach(icon => {
            icon.style.pointerEvents = '';
            icon.style.opacity = '';
            icon.style.cursor = '';
            icon.style.position = '';
            icon.style.zIndex = '';
        });

        // Restaurar botones de la barra de tareas
        document.querySelectorAll('.start-button, .taskbar-app, .system-icon').forEach(btn => {
            btn.style.pointerEvents = '';
            btn.style.opacity = '';
            btn.style.cursor = '';
        });

        // Restaurar cualquier ventana que haya quedado deshabilitada
        document.querySelectorAll('.app-window').forEach(win => {
            win.style.pointerEvents = '';
            win.style.opacity = '';
        });

        // Restaurar todos los controles de ventana
        document.querySelectorAll('.window-control').forEach(control => {
            control.style.pointerEvents = '';
            control.style.opacity = '';
            control.style.cursor = '';
        });

        // Restaurar todos los botones, enlaces e inputs generales
        document.querySelectorAll('button:not(.shepherd-button), a, input, select, textarea').forEach(element => {
            if (!element.id || element.id !== 'dashboardTutorialButton') {
                element.style.pointerEvents = '';
                element.style.opacity = '';
                element.style.cursor = '';
            }
        });
    }

    /**
     * Habilita un elemento específico durante el tutorial
     */
    enableSpecificElement(selector) {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
            element.style.pointerEvents = '';
            element.style.opacity = '';
            element.style.cursor = '';
        });
    }

    /**
     * Simula la apertura de notificaciones con datos de prueba
     */
    async showTutorialNotifications() {
        // Cargar notificaciones de prueba si aún no están cargadas
        if (this.tutorialNotifications.length === 0) {
            this.tutorialNotifications = await DashboardTutorialUtils.loadTutorialNotifications();
        }

        // Verificar que se hayan cargado notificaciones
        if (this.tutorialNotifications.length === 0) {
            console.warn('[DashboardTutorial] No tutorial notifications loaded, using default data');
            // Usar notificaciones de ejemplo por defecto
            this.tutorialNotifications = [
                {
                    icon: 'calendar',
                    title: 'Nueva cita agendada',
                    message: 'Tu cita con el coordinador ha sido confirmada',
                    type: 'info'
                },
                {
                    icon: 'ticket',
                    title: 'Ticket actualizado',
                    message: 'El técnico ha respondido a tu ticket #123',
                    type: 'success'
                },
                {
                    icon: 'alert-triangle',
                    title: 'Mantenimiento programado',
                    message: 'El sistema estará en mantenimiento mañana',
                    type: 'warning'
                }
            ];
        }

        // Crear un panel temporal con las notificaciones de prueba
        this.createTutorialNotificationPanel();
    }

    /**
     * Crea un panel temporal de notificaciones para el tutorial
     */
    createTutorialNotificationPanel() {
        // Remover panel existente si lo hay
        const existingPanel = document.getElementById('tutorialNotificationPanel');
        if (existingPanel) {
            existingPanel.remove();
        }

        // Crear el panel
        const panel = document.createElement('div');
        panel.id = 'tutorialNotificationPanel';
        panel.style.cssText = `
            position: fixed;
            bottom: 48px;
            right: 20px;
            width: 350px;
            max-height: 400px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            z-index: 9999;
            overflow-y: auto;
        `;

        // Header
        const header = document.createElement('div');
        header.style.cssText = `
            padding: 16px;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 8px 8px 0 0;
        `;
        header.innerHTML = `
            <h6 style="margin: 0; font-weight: 600;">Notificaciones (Tutorial)</h6>
            <span style="background: rgba(255,255,255,0.2); padding: 2px 8px; border-radius: 12px; font-size: 0.85rem;">${this.tutorialNotifications.length}</span>
        `;

        // Body con notificaciones
        const body = document.createElement('div');
        body.style.cssText = 'padding: 8px;';

        this.tutorialNotifications.forEach(notif => {
            const notifItem = document.createElement('div');
            notifItem.style.cssText = `
                padding: 12px;
                border-bottom: 1px solid #e5e7eb;
                cursor: pointer;
                transition: background 0.2s;
            `;
            notifItem.onmouseenter = () => notifItem.style.background = '#f3f4f6';
            notifItem.onmouseleave = () => notifItem.style.background = 'transparent';

            const iconColor = notif.type === 'warning' ? '#f59e0b' : notif.type === 'success' ? '#10b981' : '#667eea';

            notifItem.innerHTML = `
                <div style="display: flex; gap: 12px; align-items: start;">
                    <div style="color: ${iconColor}; font-size: 1.2rem;">
                        <i data-lucide="${notif.icon}"></i>
                    </div>
                    <div style="flex: 1;">
                        <div style="font-weight: 600; margin-bottom: 4px; color: #111827;">${notif.title}</div>
                        <div style="font-size: 0.875rem; color: #6b7280; margin-bottom: 4px;">${notif.message}</div>
                        <div style="font-size: 0.75rem; color: #9ca3af;">Hace 5 minutos</div>
                    </div>
                </div>
            `;

            body.appendChild(notifItem);
        });

        panel.appendChild(header);
        panel.appendChild(body);
        document.body.appendChild(panel);

        // Inicializar íconos de Lucide
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    /**
     * Remueve el panel de notificaciones del tutorial
     */
    removeTutorialNotificationPanel() {
        const panel = document.getElementById('tutorialNotificationPanel');
        if (panel) {
            panel.remove();
        }
    }

    /**
     * Ícono del escritorio usado en la demostración: Help Desk si existe;
     * si no, la primera app real (para no atascar el tour a quien no la tiene).
     */
    getDemoIconSelector() {
        const preferred = '.desktop-icon[data-app="helpdesk"]';
        if (document.querySelector(preferred)) return preferred;
        const first = document.querySelector('.desktop-icon:not(.is-decorative)');
        return first ? `.desktop-icon[data-app="${first.dataset.app}"]` : preferred;
    }

    /** Abre el menú inicio (si no lo está) para los pasos que lo señalan. */
    ensureStartMenuOpen() {
        const menu = window.ItcjDesktop && window.ItcjDesktop.startMenu;
        if (menu && typeof menu.open === 'function') menu.open();
    }

    /** Cierra el menú inicio. */
    closeStartMenu() {
        const menu = window.ItcjDesktop && window.ItcjDesktop.startMenu;
        if (menu && typeof menu.close === 'function') menu.close();
    }

    /** Cierra todas las ventanas del escritorio. */
    closeDesktopWindows() {
        if (window.desktop && typeof window.desktop.closeAllWindows === 'function') {
            window.desktop.closeAllWindows();
        }
    }

    /**
     * El menú inicio se cierra con un pointerdown fuera de él; mientras dura el
     * tour, los toques dentro del popover de Shepherd no deben cerrarlo.
     */
    installMenuGuard() {
        if (this.menuGuard) return;
        this.menuGuard = (e) => {
            if (e.target && e.target.closest && e.target.closest('.shepherd-element')) {
                e.stopPropagation();
            }
        };
        window.addEventListener('pointerdown', this.menuGuard, true);
    }

    removeMenuGuard() {
        if (!this.menuGuard) return;
        window.removeEventListener('pointerdown', this.menuGuard, true);
        this.menuGuard = null;
    }

    /**
     * Pasos del tutorial del dashboard
     */
    getDashboardSteps() {
        return [
            {
                id: 'welcome',
                title: '¡Bienvenido a la plataforma Digital ITCJ!',
                text: `
                    <p>Este tutorial te guiará a través de las funcionalidades principales del dashboard.</p>
                    <p><strong>En esta plataforma tendrás acceso a varias aplicaciones:</strong></p>
                    <ul>
                        <li>📅 <strong>AgendaTec:</strong> Sistema para crear solicitudes de altas y bajas de materias agendando citas con el coordinador de carrera</li>
                        <li>🎫 <strong>Help Desk:</strong> Sistema de tickets de soporte del Centro de Cómputo</li>
                        <li>Y más aplicaciones según tus permisos...</li>
                    </ul>
                    <p><em>Nota: El acceso a cada aplicación depende de tus permisos asignados.</em></p>
                `,
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Omitir Tutorial',
                        action: function() {
                            return this.cancel();
                        },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Comenzar',
                        action: function() {
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'desktop-apps',
                title: 'Aplicaciones Disponibles',
                text: `
                    <p>Aquí puedes ver todas las aplicaciones disponibles para ti.</p>
                    <p><strong>⚠️ MUY IMPORTANTE:</strong> Para abrir cualquier aplicación debes hacer <strong style="color: #dc2626;">DOBLE CLICK</strong> sobre el ícono.</p>
                    <p>Las aplicaciones se abrirán en ventanas flotantes, similar al sistema operativo Windows.</p>
                `,
                attachTo: {
                    element: () => document.querySelector('.desktop-icon:not(.is-decorative)'),
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Siguiente',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'double-click-demo',
                title: 'Demostración: Abrir Aplicación',
                text: `
                    <p>Vamos a abrir una aplicación como ejemplo.</p>
                    <p>Recuerda: necesitas hacer <strong style="color: #dc2626;">DOBLE CLICK</strong> sobre el ícono resaltado para continuar con el tutorial.</p>
                `,
                attachTo: {
                    element: () => document.querySelector(this.getDemoIconSelector()),
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        this.enableSpecificElement(this.getDemoIconSelector());

                        // Asegurar que el elemento tenga un z-index adecuado
                        const helpdeskIcon = document.querySelector(this.getDemoIconSelector());
                        if (helpdeskIcon) {
                            helpdeskIcon.style.position = 'relative';
                            helpdeskIcon.style.zIndex = '10001';
                        }
                    },
                    hide: () => {
                        // Limpiar el z-index al salir
                        const helpdeskIcon = document.querySelector(this.getDemoIconSelector());
                        if (helpdeskIcon) {
                            helpdeskIcon.style.position = '';
                            helpdeskIcon.style.zIndex = '';
                        }
                    }
                },
                advanceOn: {
                    selector: this.getDemoIconSelector(),
                    event: 'dblclick'
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    }
                ]
            },
            {
                id: 'window-opened',
                title: 'Ventana de Aplicación',
                text: `
                    <p>¡Excelente! La aplicación se ha abierto en una ventana flotante.</p>
                    <p><strong>Características de las ventanas:</strong></p>
                    <ul>
                        <li>Puedes moverlas arrastrando desde la barra de título</li>
                        <li>Puedes redimensionarlas desde las esquinas</li>
                        <li>Puedes minimizar, maximizar o cerrar con los botones superiores</li>
                        <li>Puedes tener múltiples ventanas abiertas al mismo tiempo</li>
                    </ul>
                `,
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        // Esperar a que la ventana se abra
                        setTimeout(() => {
                            const appWindow = document.querySelector('.app-window');
                            if (appWindow) {
                                appWindow.style.pointerEvents = 'none';
                            }
                        }, 500);
                    }
                },
                buttons: [
                    {
                        text: 'Siguiente',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'close-window-demo',
                title: 'Cerrar Ventana',
                text: `
                    <p>Para cerrar una ventana, normalmente haces click en el botón <strong>✕</strong> en la esquina superior derecha.</p>
                    <p>Usa el botón <strong>"Siguiente"</strong> para cerrar la ventana y continuar con el tutorial.</p>
                `,
                attachTo: {
                    element: '.app-window .window-control.close',
                    on: 'left'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();

                        // NO habilitar el botón X, dejarlo deshabilitado
                        // Solo se podrá cerrar con el botón "Siguiente"
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Siguiente',
                        action: function() {
                            // Cerrar la ventana programáticamente
                            window.dashboardTutorial.closeDesktopWindows();
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'notifications-intro',
                title: 'Sistema de Notificaciones',
                text: `
                    <p>El ícono de campana 🔔 te muestra las notificaciones del sistema.</p>
                    <p><strong>Características:</strong></p>
                    <ul>
                        <li>Un número en rojo indica cuántas notificaciones sin leer tienes</li>
                        <li>Al hacer click, se despliega un panel con tus notificaciones</li>
                        <li>Las notificaciones pueden ser de diferentes aplicaciones</li>
                    </ul>
                `,
                attachTo: {
                    element: '#notificationBell',
                    on: 'left'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Siguiente',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'notifications-demo',
                title: 'Ver Notificaciones',
                text: `
                    <p>Vamos a ver un ejemplo de cómo se ven las notificaciones.</p>
                    <p>Para este tutorial, hemos preparado algunas notificaciones de ejemplo.</p>
                    <p>Presiona "Ver Notificaciones" para continuar.</p>
                `,
                attachTo: {
                    element: '#notificationBell',
                    on: 'left'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Ver Notificaciones',
                        action: async function() {
                            await window.dashboardTutorial.showTutorialNotifications();
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'notifications-panel',
                title: 'Panel de Notificaciones',
                text: `
                    <p>Aquí puedes ver todas tus notificaciones recientes.</p>
                    <p>Cada notificación muestra:</p>
                    <ul>
                        <li>Un ícono que indica el tipo de notificación</li>
                        <li>El título y mensaje de la notificación</li>
                        <li>Cuándo fue recibida</li>
                    </ul>
                    <p><em>Nota: Estas son notificaciones de ejemplo para el tutorial.</em></p>
                `,
                attachTo: {
                    element: '#tutorialNotificationPanel',
                    on: 'left'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Siguiente',
                        action: function() {
                            window.dashboardTutorial.removeTutorialNotificationPanel();
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'profile-menu-intro',
                title: 'Menú de Usuario',
                text: `
                    <p>El botón de inicio de la barra inferior abre el menú de inicio, que da acceso a:</p>
                    <ul>
                        <li><strong>Tus aplicaciones y el buscador:</strong> Todas las apps disponibles para ti</li>
                        <li><strong>Información de tu puesto:</strong> Detalles de tu cargo y departamento</li>
                        <li><strong>Perfil:</strong> Tu información personal y configuración</li>
                        <li><strong>Cerrar Sesión:</strong> Salir de la plataforma</li>
                    </ul>
                `,
                attachTo: {
                    element: '.start-button',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Siguiente',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'open-profile-menu',
                title: 'Abrir Menú de Usuario',
                text: `
                    <p>Haz click en el botón de inicio para ver las opciones disponibles.</p>
                `,
                attachTo: {
                    element: '.start-button',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        this.enableSpecificElement('.start-button');

                        // El menú debe estar cerrado para que el click lo abra
                        this.closeStartMenu();
                    }
                },
                advanceOn: {
                    selector: '.start-button',
                    event: 'click'
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    }
                ]
            },
            {
                id: 'profile-menu-options',
                title: 'Opciones del Menú',
                text: `
                    <p>Aquí puedes ver:</p>
                    <ul>
                        <li><strong>Tu información:</strong> Nombre, puesto y departamento</li>
                        <li><strong>Botón de Configuración:</strong> Para ajustes del sistema (Solo usuarios con permisos)</li>
                        <li><strong>Botón de Cerrar Sesión:</strong> Para salir de forma segura</li>
                    </ul>
                    <p><strong>Muy importante:</strong> Para abrir tu perfil basta con hacer <strong style="color: #dc2626;">un click</strong> en la sección donde aparece tu nombre y rol.</p>
                `,
                attachTo: {
                    element: '#startMenuUser',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        this.ensureStartMenuOpen();

                        // Resaltar el elemento del usuario (sin habilitarlo: solo se señala)
                        const userSection = document.getElementById('startMenuUser');
                        if (userSection) {
                            userSection.style.opacity = '1';
                            userSection.classList.add('tutorial-highlight');
                        }
                    },
                    hide: () => {
                        const userSection = document.getElementById('startMenuUser');
                        if (userSection) {
                            userSection.classList.remove('tutorial-highlight');
                            userSection.style.opacity = '';
                        }
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Siguiente',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'open-profile-demo',
                title: 'Abrir Perfil',
                text: `
                    <p>Ahora vamos a abrir tu perfil como ejemplo.</p>
                    <p>Haz <strong style="color: #dc2626;">click</strong> en la sección de tu nombre y rol para abrir tu perfil.</p>
                    <p><em>Recuerda: los íconos del escritorio se abren con doble click; las opciones del menú de inicio, con un click.</em></p>
                `,
                attachTo: {
                    element: '#startMenuUser',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        this.ensureStartMenuOpen();

                        // Habilitar solo la tarjeta del usuario
                        const userSection = document.getElementById('startMenuUser');
                        if (userSection) {
                            userSection.style.pointerEvents = 'auto';
                            userSection.style.opacity = '1';
                            userSection.style.cursor = 'pointer';
                        }
                    },
                    hide: () => {
                        const userSection = document.getElementById('startMenuUser');
                        if (userSection) {
                            userSection.style.pointerEvents = '';
                            userSection.style.opacity = '';
                            userSection.style.cursor = '';
                        }
                    }
                },
                advanceOn: {
                    selector: '#startMenuUser',
                    event: 'click'
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Saltar',
                        action: function() {
                            window.dashboardTutorial.closeStartMenu();
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'profile-window',
                title: 'Ventana de Perfil',
                text: `
                    <p>¡Perfecto! Tu perfil se ha abierto en una ventana.</p>
                    <p>Aquí puedes ver y editar tu información personal:</p>
                    <ul>
                        <li>Datos personales (nombre, correo, teléfono)</li>
                        <li>Información laboral (puesto, departamento)</li>
                        <li>Permisos de las aplicaciones</li>
                        <li>Historial de actividades y Notificaciones</li>
                    </ul>
                    <p><em>La primera pestaña contiene la información más importante de tu perfil.</em></p>
                `,
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        // Esperar a que la ventana se abra
                        setTimeout(() => {
                            const profileWindow = document.querySelector('.app-window[data-app-id="profile"]');
                            if (profileWindow) {
                                profileWindow.style.pointerEvents = 'none';
                            }
                        }, 500);
                    }
                },
                buttons: [
                    {
                        text: 'Siguiente',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'tutorial-complete',
                title: '¡Tutorial Completado!',
                text: `
                    <p><strong>¡Felicidades!</strong> Has completado el tutorial del dashboard ITCJ.</p>
                    <p>Ahora sabes cómo:</p>
                    <ul>
                        <li>✓ Abrir aplicaciones con doble click en el escritorio</li>
                        <li>✓ Gestionar ventanas (mover, redimensionar, cerrar)</li>
                        <li>✓ Ver tus notificaciones</li>
                        <li>✓ Acceder a tu perfil y configuración</li>
                        <li>✓ Navegar por el sistema</li>
                    </ul>
                    <p><strong>Punto importante:</strong> Recuerda que para abrir una aplicación desde el escritorio debes hacer <strong style="color: #dc2626;">DOBLE CLICK</strong>; en el menú de inicio basta un click.</p>
                    <p class="mb-0"><em>Si necesitas ver el tutorial de nuevo, haz click en el botón "Tutorial" en la barra inferior.</em></p>
                `,
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Finalizar',
                        action: function() {
                            // Cerrar cualquier ventana abierta durante el tutorial
                            window.dashboardTutorial.closeDesktopWindows();

                            // Cerrar el menú inicio si está abierto
                            window.dashboardTutorial.closeStartMenu();

                            return this.complete();
                        },
                        classes: 'btn btn-success'
                    }
                ]
            }
        ];
    }

    /**
     * Prepara el entorno para el tutorial
     * Cierra todas las ventanas abiertas y limpia el estado
     */
    prepareEnvironmentForTutorial() {
        console.log('[DashboardTutorial] Preparing environment for tutorial...');

        // Cerrar todas las ventanas de aplicaciones (iframes)
        if (window.desktop && typeof window.desktop.closeAllWindows === 'function') {
            console.log('[DashboardTutorial] Closing all open windows...');
            window.desktop.closeAllWindows();
        }

        // Cerrar el menú inicio si está abierto
        this.closeStartMenu();

        // Cerrar el panel de notificaciones si está abierto
        const notificationPanel = document.getElementById('notification-panel');
        if (notificationPanel && !notificationPanel.hidden) {
            console.log('[DashboardTutorial] Closing notification panel...');
            notificationPanel.hidden = true;
        }

        // Eliminar cualquier panel de notificaciones del tutorial anterior
        const tutorialNotifPanel = document.getElementById('tutorialNotificationPanel');
        if (tutorialNotifPanel) {
            tutorialNotifPanel.remove();
        }

        console.log('[DashboardTutorial] Environment prepared successfully');
    }

    /**
     * Muestra modal de confirmación para iniciar el tutorial
     */
    showStartConfirmationModal() {
        // Verificar si el tutorial ya está corriendo o si ya hay un modal abierto
        if (this.isRunning) {
            console.log('[DashboardTutorial] Tutorial already running, ignoring request');
            return;
        }

        // Verificar si ya hay un modal de confirmación abierto
        const existingModal = document.getElementById('dashboardTutorialStartModal');
        if (existingModal && existingModal.classList.contains('show')) {
            console.log('[DashboardTutorial] Confirmation modal already open, ignoring request');
            return;
        }

        // Deshabilitar el botón de tutorial inmediatamente
        const tutorialButton = document.getElementById('dashboardTutorialButton');
        if (tutorialButton) {
            tutorialButton.disabled = true;
            tutorialButton.style.opacity = '0.5';
            tutorialButton.style.cursor = 'not-allowed';
        }

        // Crear modal de confirmación si no existe
        let modal = document.getElementById('dashboardTutorialStartModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'dashboardTutorialStartModal';
            modal.className = 'modal fade';
            modal.setAttribute('tabindex', '-1');
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important; color: white !important; border-bottom: none;">
                            <h5 class="modal-title" style="color: white !important; font-weight: 600;">
                                <i class="bi bi-compass me-2"></i>
                                Iniciar Tutorial del Dashboard
                            </h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p class="mb-3">¿Deseas iniciar el tutorial interactivo del Dashboard?</p>
                            <div class="alert alert-info mb-0">
                                <i class="bi bi-info-circle me-2"></i>
                                <strong>Nota:</strong> El tutorial cerrará automáticamente todas las ventanas abiertas para preparar el entorno.
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                <i class="bi bi-x-circle me-1"></i>
                                Cancelar
                            </button>
                            <button type="button" class="btn btn-primary" id="dashboardTutorialStartConfirm" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important; border: none;">
                                <i class="bi bi-play-circle me-1"></i>
                                Iniciar Tutorial
                            </button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Evento cuando se cierra el modal (cancelar o cerrar con X)
        modal.addEventListener('hidden.bs.modal', () => {
            // Re-habilitar el botón de tutorial
            const tutorialButton = document.getElementById('dashboardTutorialButton');
            if (tutorialButton && !this.isRunning) {
                tutorialButton.disabled = false;
                tutorialButton.style.opacity = '';
                tutorialButton.style.cursor = '';
            }
        }, { once: true });

        // Configurar botón de confirmación
        const confirmBtn = document.getElementById('dashboardTutorialStartConfirm');
        if (confirmBtn) {
            // Remover listeners anteriores
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

            newConfirmBtn.onclick = () => {
                bsModal.hide();

                // Esperar a que el modal se cierre completamente
                setTimeout(() => {
                    // Preparar el entorno
                    this.prepareEnvironmentForTutorial();

                    // Iniciar el tutorial después de una pequeña pausa
                    setTimeout(() => {
                        this.startTutorial();
                    }, 500);
                }, 300);
            };
        }
    }

    /**
     * Inicia el tutorial
     */
    async startTutorial() {
        // Verificar si ya está corriendo
        if (this.isRunning) {
            console.log('[DashboardTutorial] Tutorial already running');
            return;
        }

        this.isNavigating = false;
        this.isRunning = true; // Marcar como activo
        this.enableTutorialMode();

        // Cargar notificaciones de prueba
        this.tutorialNotifications = await DashboardTutorialUtils.loadTutorialNotifications();

        this.initializeTour();

        const steps = this.getDashboardSteps();
        steps.forEach(step => this.tour.addStep(step));

        this.installMenuGuard();
        this.tour.start();
    }

    /**
     * Espera a que el escritorio esté listo y a que el modal de cambio de
     * contraseña (must_change.js) no esté a la vista.
     */
    waitUntilClear() {
        return new Promise((resolve) => {
            const started = Date.now();
            const check = () => {
                const ready = document.documentElement.classList.contains('desktop-ready');
                const pwModal = document.getElementById('forcePwModal');
                const pwVisible = !!(pwModal && pwModal.classList.contains('show'));
                // must_change.js decide de forma asíncrona: hasta que no expone
                // passwordModalWasShown no sabemos si el modal va a aparecer (tope 6 s).
                const gateKnown = typeof window.passwordModalWasShown === 'function' || Date.now() - started > 6000;
                if (ready && gateKnown && !pwVisible) {
                    resolve();
                } else {
                    setTimeout(check, 250);
                }
            };
            check();
        });
    }

    /**
     * Inicia automáticamente el tutorial la primera vez (sin modal de confirmación).
     */
    async autoStartTutorial() {
        if (this.hasCompletedTutorial() || !DASHBOARD_TUTORIAL_CONFIG.autoStart) return;
        await this.waitUntilClear();
        // Mientras esperábamos pudo completarse o iniciarse a mano
        if (this.hasCompletedTutorial() || this.isRunning) return;
        // Un modal de contraseña recién cerrado necesita un instante para desbloquear la interfaz
        if (typeof window.passwordModalWasShown === 'function' && window.passwordModalWasShown()) {
            await new Promise((r) => setTimeout(r, 1000));
        }
        this.prepareEnvironmentForTutorial();
        this.startTutorial();
    }
}

// ==================== PUNTO DE ENTRADA ====================
// El cargador (desktop/tutorial-loader.js) inyecta este archivo bajo demanda,
// así que no se auto-ejecuta: expone un punto de entrada con instancia perezosa.
function getDashboardTutorial() {
    if (!window.dashboardTutorial) {
        window.dashboardTutorial = new DashboardTutorial();
    }
    return window.dashboardTutorial;
}

window.DashboardTutorialEntry = {
    /** Auto-inicio de la primera visita (respeta #forcePwModal y desktop-ready). */
    autoStart() {
        return getDashboardTutorial().autoStartTutorial();
    },
    /** Botón "Tutorial": pide confirmación y arranca el tour. */
    start() {
        getDashboardTutorial().showStartConfirmationModal();
    }
};

// Exportar para uso global
window.DashboardTutorial = DashboardTutorial;
window.DashboardTutorialUtils = DashboardTutorialUtils;
