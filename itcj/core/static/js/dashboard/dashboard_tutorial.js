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
                        <div class="modal-header">
                            <h5 class="modal-title">Salir del Tutorial</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            ¿Estás seguro de que quieres salir del tutorial? Podrás iniciarlo de nuevo más tarde haciendo click en el botón "Tutorial" en la barra inferior.
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                            <button type="button" class="btn btn-primary" id="dashboardTutorialCancelConfirm">Salir del Tutorial</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Configurar botón de confirmación
        const confirmBtn = document.getElementById('dashboardTutorialCancelConfirm');
        if (confirmBtn) {
            confirmBtn.onclick = () => {
                bsModal.hide();
                this.markTutorialComplete();
                DashboardTutorialUtils.showMessage(
                    'Tutorial Omitido',
                    'Puedes reiniciar el tutorial en cualquier momento desde el botón "Tutorial" en la barra inferior.',
                    'info'
                );
            };
        }
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

        // Evento cuando se completa el tour
        this.tour.on('complete', () => {
            this.markTutorialComplete();
            this.enableAllInteractiveElements();
            DashboardTutorialUtils.showMessage(
                '¡Tutorial Completado!',
                'Ya conoces las funcionalidades principales del dashboard ITCJ. ¡Comienza a explorar!',
                'success'
            );
        });

        // Evento cuando se cancela el tour
        this.tour.on('cancel', () => {
            if (this.isNavigating) {
                return;
            }

            // Restaurar todos los elementos interactivos
            this.enableAllInteractiveElements();

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
            '.pinned-app',
            '.system-icon',
            'button:not(.shepherd-button):not(#dashboardTutorialButton)',
            'a',
            'input',
            'select',
            'textarea'
        ];

        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(element => {
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
     * Pasos del tutorial del dashboard
     */
    getDashboardSteps() {
        return [
            {
                id: 'welcome',
                title: 'Bienvenido a la plataforma ITCJ',
                text: `
                    <p>Este tutorial te guiará a través de las funcionalidades principales del dashboard.</p>
                    <p><strong>En esta plataforma tendrás acceso a varias aplicaciones:</strong></p>
                    <ul>
                        <li>📅 <strong>AgendaTec:</strong> Sistema para crear solicitudes de altas y bajas de materias agendando citas con el coordinador de carrera</li>
                        <li>🎫 <strong>Help Desk:</strong> Sistema de tickets de soporte técnico</li>
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
                    element: '.desktop-icon[data-app="agendatec"]',
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
                    <p>Vamos a abrir Help Desk como ejemplo.</p>
                    <p>Recuerda: necesitas hacer <strong style="color: #dc2626;">DOBLE CLICK</strong> sobre el ícono de Help Desk.</p>
                    <p>Haz doble click ahora sobre el ícono de Help Desk para continuar.</p>
                `,
                attachTo: {
                    element: '[data-app="helpdesk"]',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        this.enableSpecificElement('[data-app="helpdesk"]');

                        // Asegurar que el elemento tenga un z-index adecuado
                        const helpdeskIcon = document.querySelector('[data-app="helpdesk"]');
                        if (helpdeskIcon) {
                            helpdeskIcon.style.position = 'relative';
                            helpdeskIcon.style.zIndex = '10001';
                        }
                    },
                    hide: () => {
                        // Limpiar el z-index al salir
                        const helpdeskIcon = document.querySelector('[data-app="helpdesk"]');
                        if (helpdeskIcon) {
                            helpdeskIcon.style.position = '';
                            helpdeskIcon.style.zIndex = '';
                        }
                    }
                },
                advanceOn: {
                    selector: '[data-app="helpdesk"]',
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
                            const window = document.querySelector('.window-container');
                            if (window) {
                                window.style.pointerEvents = 'none';
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
                    element: '.window-control.close',
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
                            const closeBtn = document.querySelector('.window-control.close');
                            if (closeBtn) {
                                closeBtn.click();
                            }
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
                        <li>Un badge rojo indica cuántas notificaciones sin leer tienes</li>
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
                    <p>El botón de menú (☰) en la parte inferior izquierda da acceso a:</p>
                    <ul>
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
                    <p>Haz click en el botón de menú (☰) para ver las opciones disponibles.</p>
                `,
                attachTo: {
                    element: '.start-button',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        this.enableSpecificElement('.start-button');

                        // Guardar el estado original del menú
                        this.profileMenuTutorialMode = true;
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
                        <li><strong>Botón de Configuración:</strong> Para ajustes del sistema</li>
                        <li><strong>Botón de Cerrar Sesión:</strong> Para salir de forma segura</li>
                    </ul>
                    <p><strong>Muy importante:</strong> Para abrir tu perfil necesitas hacer <strong style="color: #dc2626;">DOBLE CLICK</strong> en la sección donde aparece tu nombre y rol.</p>
                `,
                attachTo: {
                    element: '#profileMenuUser',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();

                        // Deshabilitar el cierre automático del overlay del menú
                        const overlay = document.getElementById('profileMenuOverlay');
                        if (overlay) {
                            overlay.style.pointerEvents = 'none';
                        }

                        // Esperar a que el menú se abra
                        setTimeout(() => {
                            const menu = document.getElementById('profileMenu');
                            if (menu) {
                                menu.style.pointerEvents = 'none';
                            }

                            // Resaltar el elemento del usuario
                            const userSection = document.getElementById('profileMenuUser');
                            if (userSection) {
                                userSection.style.pointerEvents = '';
                                userSection.classList.add('tutorial-highlight');
                            }
                        }, 300);
                    },
                    hide: () => {
                        const userSection = document.getElementById('profileMenuUser');
                        if (userSection) {
                            userSection.classList.remove('tutorial-highlight');
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
                    <p>Haz <strong style="color: #dc2626;">DOBLE CLICK</strong> en la sección de tu nombre y rol para abrir tu perfil.</p>
                    <p><em>Recuerda: siempre es doble click para abrir ventanas.</em></p>
                `,
                attachTo: {
                    element: '#profileMenuUser',
                    on: 'right'
                },
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();

                        // Deshabilitar el cierre automático del overlay del menú
                        const overlay = document.getElementById('profileMenuOverlay');
                        if (overlay) {
                            overlay.style.pointerEvents = 'none';
                        }

                        // Deshabilitar el menú pero habilitar solo el userSection
                        const menu = document.getElementById('profileMenu');
                        if (menu) {
                            menu.style.pointerEvents = 'none';
                        }

                        // Habilitar el elemento del usuario con z-index alto
                        const userSection = document.getElementById('profileMenuUser');
                        if (userSection) {
                            userSection.style.pointerEvents = 'auto';
                            userSection.style.position = 'relative';
                            userSection.style.zIndex = '10001';
                            userSection.style.opacity = '1';
                            userSection.style.cursor = 'pointer';
                        }
                    },
                    hide: () => {
                        const userSection = document.getElementById('profileMenuUser');
                        if (userSection) {
                            userSection.style.position = '';
                            userSection.style.zIndex = '';
                        }

                        // Restaurar el overlay
                        const overlay = document.getElementById('profileMenuOverlay');
                        if (overlay) {
                            overlay.style.pointerEvents = '';
                        }

                        // Desactivar modo tutorial del menú
                        this.profileMenuTutorialMode = false;
                    }
                },
                advanceOn: {
                    selector: '#profileMenuUser',
                    event: 'dblclick'
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
                            // Cerrar el menú de perfil si está abierto
                            const menu = document.getElementById('profileMenu');
                            if (menu && menu.classList.contains('show')) {
                                menu.classList.remove('show');
                            }

                            // Restaurar el overlay
                            const overlay = document.getElementById('profileMenuOverlay');
                            if (overlay) {
                                overlay.style.pointerEvents = '';
                                overlay.classList.remove('show');
                            }

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
                        <li>Cambiar tu contraseña</li>
                        <li>Configurar preferencias</li>
                    </ul>
                    <p><em>La primera pestaña contiene la información más importante de tu perfil.</em></p>
                `,
                when: {
                    show: () => {
                        this.disableAllInteractiveElements();
                        // Esperar a que la ventana se abra
                        setTimeout(() => {
                            const profileWindow = document.querySelector('.window-container[data-app="profile"]');
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
                        <li>✓ Abrir aplicaciones con doble click</li>
                        <li>✓ Gestionar ventanas (mover, redimensionar, cerrar)</li>
                        <li>✓ Ver tus notificaciones</li>
                        <li>✓ Acceder a tu perfil y configuración</li>
                        <li>✓ Navegar por el sistema</li>
                    </ul>
                    <p><strong>Punto importante:</strong> Recuerda que para abrir cualquier aplicación o tu perfil siempre debes hacer <strong style="color: #dc2626;">DOBLE CLICK</strong>.</p>
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
                            const windows = document.querySelectorAll('.window-container');
                            windows.forEach(w => {
                                const closeBtn = w.querySelector('.close-button');
                                if (closeBtn) closeBtn.click();
                            });

                            // Cerrar menú de perfil si está abierto
                            const menu = document.getElementById('profileMenu');
                            if (menu && menu.classList.contains('show')) {
                                menu.classList.remove('show');
                            }

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

        // Cerrar el menú de perfil si está abierto
        const profileMenu = document.getElementById('profileMenu');
        const profileOverlay = document.getElementById('profileMenuOverlay');
        if (profileMenu && profileMenu.classList.contains('show')) {
            console.log('[DashboardTutorial] Closing profile menu...');
            profileMenu.classList.remove('show');
        }
        if (profileOverlay && profileOverlay.classList.contains('show')) {
            profileOverlay.classList.remove('show');
        }

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
                        <div class="modal-header bg-gradient" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
                            <h5 class="modal-title">
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
                            <button type="button" class="btn btn-primary" id="dashboardTutorialStartConfirm" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none;">
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
        this.isNavigating = false;
        this.enableTutorialMode();

        // Cargar notificaciones de prueba
        this.tutorialNotifications = await DashboardTutorialUtils.loadTutorialNotifications();

        this.initializeTour();

        const steps = this.getDashboardSteps();
        steps.forEach(step => this.tour.addStep(step));

        this.tour.start();
    }

    /**
     * Verifica si debe iniciar automáticamente el tutorial
     */
    autoStartTutorial() {
        if (!this.hasCompletedTutorial() && DASHBOARD_TUTORIAL_CONFIG.autoStart) {
            // Verificar si el modal de cambio de contraseña está presente
            const passwordModal = document.getElementById('forcePwModal');

            if (passwordModal) {
                // Esperar a que el modal de contraseña se cierre antes de iniciar
                console.log('[DashboardTutorial] Waiting for password modal to close...');

                window.addEventListener('passwordModalClosed', () => {
                    console.log('[DashboardTutorial] Password modal closed, starting tutorial');
                    setTimeout(() => {
                        this.startTutorial();
                    }, 1000);
                }, { once: true });

                // Si el modal nunca se mostró, iniciar el tutorial normalmente
                setTimeout(() => {
                    if (typeof window.passwordModalWasShown === 'function' && !window.passwordModalWasShown()) {
                        console.log('[DashboardTutorial] No password modal shown, starting tutorial');
                        this.startTutorial();
                    }
                }, 2000);
            } else {
                // Si no hay modal de contraseña, iniciar normalmente
                setTimeout(() => {
                    this.startTutorial();
                }, 1000);
            }
        }
    }
}

// ==================== INICIALIZACIÓN GLOBAL ====================
let dashboardTutorial;

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    // Crear instancia global
    window.dashboardTutorial = new DashboardTutorial();
    dashboardTutorial = window.dashboardTutorial;

    // Auto-iniciar si corresponde
    dashboardTutorial.autoStartTutorial();

    // Agregar evento al botón de tutorial si existe
    const tutorialButton = document.getElementById('dashboardTutorialButton');
    if (tutorialButton) {
        tutorialButton.addEventListener('click', () => {
            // Mostrar modal de confirmación en lugar de iniciar directamente
            dashboardTutorial.showStartConfirmationModal();
        });
    }
});

// Exportar para uso global
window.DashboardTutorial = DashboardTutorial;
window.DashboardTutorialUtils = DashboardTutorialUtils;
