/**
 * ========================================
 * TUTORIAL DE CREACIÓN DE TICKETS - Shepherd.js
 * ========================================
 *
 * Tutorial interactivo que guía al usuario a través del proceso completo
 * de creación de tickets, desde el formulario hasta la encuesta de satisfacción.
 *
 * Flujo: create_ticket → my_tickets → ticket_detail
 */

// ==================== CONFIGURACIÓN GLOBAL ====================
const TUTORIAL_CONFIG = {
    storageKey: 'helpdesk_tutorial_completed',
    tutorialTicketKey: 'helpdesk_tutorial_ticket_id',
    tutorialStateKey: 'helpdesk_tutorial_state',
    tutorialModeKey: 'helpdesk_tutorial_mode_active',
    tutorialDataKey: 'helpdesk_tutorial_ticket_data',
    autoStart: true,
    theme: 'light',
    jsonDataUrl: '/static/helpdesk/data/tutorial_ticket_example.json'
};

// ==================== UTILIDADES PARA IFRAMES ====================
const TutorialUtils = {
    /**
     * Detecta si está dentro de un iframe
     */
    isInIframe() {
        try {
            return window.self !== window.top;
        } catch (e) {
            return true;
        }
    },

    /**
     * Obtiene el storage apropiado (sessionStorage funciona mejor en iframes)
     */
    getStorage() {
        return sessionStorage;
    },

    /**
     * Navega a una URL considerando si está en iframe
     */
    navigateTo(url) {
        if (this.isInIframe()) {
            // Si está en iframe, intentar navegar el iframe
            window.location.href = url;
        } else {
            // Si no está en iframe, navegación normal
            window.location.href = url;
        }
    },

    /**
     * Guarda datos en storage
     */
    setItem(key, value) {
        this.getStorage().setItem(key, value);
    },

    /**
     * Obtiene datos del storage
     */
    getItem(key) {
        return this.getStorage().getItem(key);
    },

    /**
     * Elimina datos del storage
     */
    removeItem(key) {
        this.getStorage().removeItem(key);
    },

    /**
     * Muestra un modal con mensaje (reemplaza alert())
     */
    showModal(title, message, type = 'info') {
        // Si existe HelpdeskUtils, usar su toast
        if (typeof HelpdeskUtils !== 'undefined' && HelpdeskUtils.showToast) {
            HelpdeskUtils.showToast(message, type);
            return;
        }

        // Si no, crear un modal simple de Bootstrap
        const modalId = 'tutorialMessageModal';
        let modal = document.getElementById(modalId);

        // Crear modal si no existe
        if (!modal) {
            modal = document.createElement('div');
            modal.id = modalId;
            modal.className = 'modal fade';
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header bg-${type === 'error' ? 'danger' : type === 'warning' ? 'warning' : 'info'} text-white">
                            <h5 class="modal-title" id="tutorialMessageModalTitle">${title}</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="tutorialMessageModalBody">
                            ${message}
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-primary" data-bs-dismiss="modal">Entendido</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        } else {
            // Actualizar contenido
            modal.querySelector('#tutorialMessageModalTitle').textContent = title;
            modal.querySelector('#tutorialMessageModalBody').textContent = message;
            modal.querySelector('.modal-header').className = `modal-header bg-${type === 'error' ? 'danger' : type === 'warning' ? 'warning' : 'info'} text-white`;
        }

        // Mostrar modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    },

    /**
     * Muestra confirmación (reemplaza confirm())
     */
    showConfirm(title, message, onConfirm, onCancel) {
        const modalId = 'tutorialConfirmModal';
        let modal = document.getElementById(modalId);

        // Crear modal si no existe
        if (!modal) {
            modal = document.createElement('div');
            modal.id = modalId;
            modal.className = 'modal fade';
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="tutorialConfirmModalTitle">${title}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body" id="tutorialConfirmModalBody">
                            ${message}
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal" id="tutorialConfirmCancel">Cancelar</button>
                            <button type="button" class="btn btn-primary" id="tutorialConfirmOk">Confirmar</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        } else {
            // Actualizar contenido
            modal.querySelector('#tutorialConfirmModalTitle').textContent = title;
            modal.querySelector('#tutorialConfirmModalBody').textContent = message;
        }

        const bsModal = new bootstrap.Modal(modal);

        // Event listeners
        const confirmBtn = modal.querySelector('#tutorialConfirmOk');
        const cancelBtn = modal.querySelector('#tutorialConfirmCancel');

        confirmBtn.onclick = () => {
            bsModal.hide();
            if (onConfirm) onConfirm();
        };

        cancelBtn.onclick = () => {
            bsModal.hide();
            if (onCancel) onCancel();
        };

        bsModal.show();
    }
};

// ==================== DATOS DE EJEMPLO ====================
const TUTORIAL_DATA = {
    area: 'SOPORTE',
    title: 'Tutorial: Computadora no enciende en mi oficina',
    description: 'Este es un ticket de ejemplo creado por el tutorial. La computadora de mi escritorio no enciende cuando presiono el botón de encendido. Ya revisé que esté conectada a la corriente.',
    priority: 'MEDIA',
    location: 'Edificio A - Oficina 203',
    office_folio: 'TUT-2025-001'
};

// ==================== CLASE PRINCIPAL DEL TUTORIAL ====================
class HelpdeskTutorial {
    constructor() {
        this.tour = null;
        this.currentPage = this.detectCurrentPage();
        this.tutorialTicketId = null;
    }

    /**
     * Detecta en qué página estamos
     */
    detectCurrentPage() {
        const path = window.location.pathname;
        if (path.includes('/create')) return 'create_ticket';
        if (path.includes('/my-tickets')) return 'my_tickets';
        if (path.includes('/tickets/')) return 'ticket_detail';
        return 'unknown';
    }

    /**
     * Verifica si el usuario ya completó el tutorial
     */
    hasCompletedTutorial() {
        return TutorialUtils.getItem(TUTORIAL_CONFIG.storageKey) === 'true';
    }

    /**
     * Marca el tutorial como completado
     */
    markTutorialComplete() {
        TutorialUtils.setItem(TUTORIAL_CONFIG.storageKey, 'true');
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialStateKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialTicketKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialModeKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialDataKey);
    }

    /**
     * Reinicia el tutorial (borra el estado)
     */
    resetTutorial() {
        TutorialUtils.removeItem(TUTORIAL_CONFIG.storageKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialStateKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialTicketKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialModeKey);
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialDataKey);
        TutorialUtils.navigateTo('/help-desk/user/create');
    }

    /**
     * Guarda el estado actual del tutorial
     */
    saveTutorialState(stepId, data = {}) {
        const state = {
            stepId,
            page: this.currentPage,
            timestamp: Date.now(),
            ...data
        };
        TutorialUtils.setItem(TUTORIAL_CONFIG.tutorialStateKey, JSON.stringify(state));
    }

    /**
     * Obtiene el estado del tutorial
     */
    getTutorialState() {
        const state = TutorialUtils.getItem(TUTORIAL_CONFIG.tutorialStateKey);
        return state ? JSON.parse(state) : null;
    }

    /**
     * Activa el modo tutorial
     */
    enableTutorialMode() {
        TutorialUtils.setItem(TUTORIAL_CONFIG.tutorialModeKey, 'true');
    }

    /**
     * Desactiva el modo tutorial
     */
    disableTutorialMode() {
        TutorialUtils.removeItem(TUTORIAL_CONFIG.tutorialModeKey);
    }

    /**
     * Verifica si está en modo tutorial
     */
    isTutorialModeActive() {
        return TutorialUtils.getItem(TUTORIAL_CONFIG.tutorialModeKey) === 'true';
    }

    /**
     * Carga el ticket de ejemplo desde JSON
     */
    async loadExampleTicket() {
        try {
            const response = await fetch(TUTORIAL_CONFIG.jsonDataUrl);
            if (!response.ok) {
                throw new Error('No se pudo cargar el ticket de ejemplo');
            }
            const data = await response.json();

            // Actualizar la fecha de creación a la actual
            data.ticket.created_at = new Date().toISOString();
            data.ticket.updated_at = new Date().toISOString();

            return data;
        } catch (error) {
            console.error('Error cargando ticket de ejemplo:', error);
            return null;
        }
    }

    /**
     * Inicializa Shepherd.js con la configuración
     */
    initializeTour() {
        this.tour = new Shepherd.Tour({
            useModalOverlay: true,
            defaultStepOptions: {
                classes: 'helpdesk-tutorial-step',
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

        // Variable para controlar si estamos navegando (no es una cancelación real)
        this.isNavigating = false;

        // Evento cuando se completa el tour
        this.tour.on('complete', () => {
            this.markTutorialComplete();
            this.showCompletionMessage();
            // Restaurar todos los elementos interactivos
            this.enableAllInteractiveElements();
        });

        // Evento cuando se cancela el tour
        this.tour.on('cancel', () => {
            // Si estamos navegando entre páginas, no mostrar confirmación
            if (this.isNavigating) {
                return;
            }

            // Restaurar todos los elementos interactivos
            this.enableAllInteractiveElements();

            // Si es una cancelación real (usuario presionó X), mostrar confirmación
            TutorialUtils.showConfirm(
                'Salir del Tutorial',
                '¿Estás seguro de que quieres salir del tutorial? Podrás iniciarlo de nuevo más tarde haciendo click en el botón "Ver Tutorial".',
                () => {
                    this.markTutorialComplete();
                },
                () => {
                    // Si cancela, no hacer nada
                }
            );
            // Prevenir el cierre inmediato
            return false;
        });
    }

    /**
     * Muestra mensaje de finalización
     */
    showCompletionMessage() {
        TutorialUtils.showModal(
            '¡Tutorial Completado!',
            'Ya sabes cómo crear y gestionar tickets en el sistema de Help Desk.',
            'success'
        );
    }

    /**
     * Deshabilita todos los elementos interactivos de la página
     */
    disableAllInteractiveElements() {
        // Guardar estado original si no existe
        if (!this.originalElementStates) {
            this.originalElementStates = new Map();
        }

        // Seleccionar todos los elementos interactivos
        const selectors = [
            'button:not(.shepherd-button)',
            'input[type="radio"]',
            'input[type="checkbox"]',
            'input[type="text"]',
            'input[type="email"]',
            'input[type="number"]',
            'textarea',
            'select',
            'a.btn',
            '[onclick]'
        ];

        selectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(element => {
                // Guardar estado original solo la primera vez
                if (!this.originalElementStates.has(element)) {
                    this.originalElementStates.set(element, {
                        disabled: element.disabled,
                        pointerEvents: element.style.pointerEvents,
                        opacity: element.style.opacity,
                        cursor: element.style.cursor
                    });
                }

                // Deshabilitar
                element.disabled = true;
                element.style.pointerEvents = 'none';
                element.style.opacity = '0.5';
                element.style.cursor = 'not-allowed';
            });
        });
    }

    /**
     * Re-habilita todos los elementos interactivos
     */
    enableAllInteractiveElements() {
        if (!this.originalElementStates) return;

        // Restaurar estado original de cada elemento
        this.originalElementStates.forEach((originalState, element) => {
            element.disabled = originalState.disabled;
            element.style.pointerEvents = originalState.pointerEvents;
            element.style.opacity = originalState.opacity;
            element.style.cursor = originalState.cursor;
        });
    }

    /**
     * Habilita un elemento específico durante el tutorial
     * @param {string} selector - Selector CSS del elemento
     * @param {boolean} forceEnable - Si es true, fuerza el habilitado sin importar el estado original
     */
    enableSpecificElement(selector, forceEnable = true) {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
            if (forceEnable) {
                // Forzar habilitado para el tutorial
                element.disabled = false;
                element.style.pointerEvents = '';
                element.style.opacity = '';
                element.style.cursor = '';
            } else if (this.originalElementStates && this.originalElementStates.has(element)) {
                // Restaurar al estado original
                const originalState = this.originalElementStates.get(element);
                element.disabled = originalState.disabled;
                element.style.pointerEvents = originalState.pointerEvents;
                element.style.opacity = originalState.opacity;
                element.style.cursor = originalState.cursor;
            }
        });
    }

    /**
     * Llena el formulario con datos de ejemplo
     */
    fillFormWithExampleData() {
        // Seleccionar área SOPORTE
        const soporteCard = document.querySelector('[data-area="SOPORTE"]');
        if (soporteCard) {
            soporteCard.click();
        }

        setTimeout(() => {
            // Llenar campos del paso 2
            document.getElementById('title').value = TUTORIAL_DATA.title;
            document.getElementById('description').value = TUTORIAL_DATA.description;
            document.getElementById('location').value = TUTORIAL_DATA.location;
            document.getElementById('office_folio').value = TUTORIAL_DATA.office_folio;

            // Seleccionar prioridad
            const priorityRadio = document.querySelector(`input[name="priority"][value="${TUTORIAL_DATA.priority}"]`);
            if (priorityRadio) {
                priorityRadio.checked = true;
            }
        }, 500);
    }

    /**
     * Crea el ticket de ejemplo (sin guardar en BD, solo en memoria)
     */
    async createExampleTicket() {
        try {
            // Asegurarse de que el formulario esté lleno
            this.fillFormWithExampleData();

            // Esperar un momento para que se llene
            await new Promise(resolve => setTimeout(resolve, 1000));

            // Cargar el ticket de ejemplo desde JSON
            const exampleData = await this.loadExampleTicket();

            if (!exampleData) {
                throw new Error('No se pudo cargar el ticket de ejemplo');
            }

            // Activar modo tutorial
            this.enableTutorialMode();

            // Guardar el ticket de ejemplo en sessionStorage
            TutorialUtils.setItem(TUTORIAL_CONFIG.tutorialDataKey, JSON.stringify(exampleData));

            // Guardar el ID del ticket
            this.tutorialTicketId = exampleData.ticket.id;
            TutorialUtils.setItem(TUTORIAL_CONFIG.tutorialTicketKey, this.tutorialTicketId);

            // Navegar a my_tickets
            this.saveTutorialState('navigate_to_my_tickets', { ticketId: this.tutorialTicketId });

            return this.tutorialTicketId;

        } catch (error) {
            console.error('Error cargando ticket de ejemplo:', error);
            TutorialUtils.showModal(
                'Error en el Tutorial',
                'Hubo un error al cargar el ticket de ejemplo. Por favor, recarga la página e intenta de nuevo.',
                'error'
            );
            return null;
        }
    }

    /**
     * Pasos del tutorial en CREATE_TICKET
     */
    getCreateTicketSteps() {
        return [
            {
                id: 'welcome',
                title: '¡Bienvenido al Sistema de Tickets!',
                text: `
                    <p>Este tutorial te guiará paso a paso en el proceso completo de creación y seguimiento de tickets.</p>
                    <p><strong>Aprenderás a:</strong></p>
                    <ul>
                        <li>Crear un ticket de soporte o desarrollo</li>
                        <li>Seleccionar equipos relacionados</li>
                        <li>Ver el estado de tus tickets</li>
                        <li>Calificar el servicio recibido</li>
                    </ul>
                    <p class="mb-0"><em>Puedes salir en cualquier momento presionando el botón X o la tecla ESC.</em></p>
                `,
                when: {
                    show: () => {
                        // Deshabilitar todo desde el inicio
                        window.helpdeskTutorial.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Salir',
                        action: function() {
                            return this.cancel();
                        },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Comenzar Tutorial',
                        action: function() {
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'step-indicators',
                title: 'Pasos del Proceso',
                text: 'Este proceso tiene 3 pasos. Aquí puedes ver en qué paso te encuentras. Actualmente estamos en el <strong>Paso 1: Tipo de Servicio</strong>.',
                attachTo: {
                    element: '.step-indicator',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'select-area-intro',
                title: 'Tipo de Servicio',
                text: `
                    <p>Primero debes seleccionar el tipo de servicio que necesitas:</p>
                    <ul>
                        <li><strong>SOPORTE:</strong> Para solicitudes con equipos físicos (computadoras, proyectores, impresoras, etc.)</li>
                        <li><strong>DESARROLLO:</strong> Para solicitudes con software y sistemas (SII, SIILE, SIISAE, Moodle, Correo, etc.)</li>
                    </ul>
                `,
                attachTo: {
                    element: '#step1',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'select-soporte',
                title: 'Selecciona SOPORTE',
                text: 'Para este tutorial, vamos a crear un ticket de <strong>Soporte Técnico</strong>. Haz click en esta tarjeta para seleccionarla.',
                attachTo: {
                    element: '[data-area="SOPORTE"]',
                    on: 'right'
                },
                when: {
                    show: () => {
                        // Deshabilitar todo
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        // Habilitar solo la tarjeta de SOPORTE
                        window.helpdeskTutorial.enableSpecificElement('[data-area="SOPORTE"]');
                    }
                },
                advanceOn: {
                    selector: '[data-area="SOPORTE"]',
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
                id: 'desarrollo-option',
                title: 'Opción: Desarrollo',
                text: `
                    <p>También existe la opción de <strong>DESARROLLO</strong> para solicitudes con sistemas y software.</p>
                    <p>Cuando seleccionas DESARROLLO, en lugar de equipos, deberás seleccionar una categoría específica del sistema que solicita (SII, SIILE, SIISAE, Moodle, Correo, etc.).</p>
                `,
                attachTo: {
                    element: '[data-area="DESARROLLO"]',
                    on: 'left'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'next-button',
                title: 'Botón Siguiente',
                text: 'Una vez que selecciones un tipo de servicio, este botón se habilitará. Haz click para avanzar al siguiente paso.',
                attachTo: {
                    element: '#btnNext',
                    on: 'top'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('#btnNext');
                    }
                },
                advanceOn: {
                    selector: '#btnNext',
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
                id: 'step2-intro',
                title: 'Paso 2: Detalles del Problema',
                text: 'Ahora estás en el <strong>Paso 2</strong> donde proporcionarás los detalles de tu problema. Vamos a revisar cada campo.',
                attachTo: {
                    element: '#step2',
                    on: 'top'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'equipment-section',
                title: 'Equipo Relacionado (Opcional)',
                text: `
                    <p>Para tickets de <strong>SOPORTE</strong>, puedes seleccionar un equipo relacionado.</p>
                    <p>Tienes 3 opciones:</p>
                    <ul>
                        <li><strong>Es mío:</strong> Equipos asignados a ti</li>
                        <li><strong>Es de alguien más:</strong> Equipos del departamento</li>
                        <li><strong>Es de un salón/grupo:</strong> Equipos de un aula o laboratorio</li>
                    </ul>
                    <p><em>Este campo es opcional.</em></p>
                `,
                attachTo: {
                    element: '#equipment-section',
                    on: 'right'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'title-field',
                title: 'Título del Problema',
                text: 'Escribe un título claro y descriptivo de tu problema. Debe tener al menos 5 caracteres. Ejemplo: "Computadora no enciende en Aula 101"',
                attachTo: {
                    element: '#title',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('#title');
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
                id: 'description-field',
                title: 'Descripción Detallada',
                text: `
                    <p>Describe el problema con el mayor detalle posible. Esto ayudará al técnico a entender y resolver tu problema más rápido.</p>
                    <p><strong>Incluye información como:</strong></p>
                    <ul>
                        <li>¿Qué estabas haciendo cuando ocurrió?</li>
                        <li>¿Es la primera vez que pasa?</li>
                        <li>¿Qué has intentado hacer?</li>
                    </ul>
                    <p><em>Mínimo 20 caracteres.</em></p>
                `,
                attachTo: {
                    element: '#description',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('#description');
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
                id: 'priority-field',
                title: 'Prioridad del Ticket',
                text: `
                    <p>Selecciona la prioridad según la urgencia:</p>
                    <ul>
                        <li><strong>Baja:</strong> Puede esperar, no afecta trabajo urgente</li>
                        <li><strong>Media:</strong> Importante pero no crítico (por defecto)</li>
                        <li><strong>Alta:</strong> Afecta trabajo importante</li>
                        <li><strong>Urgente:</strong> Bloquea completamente el trabajo</li>
                    </ul>
                `,
                attachTo: {
                    element: 'input[name="priority"]',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('input[name="priority"]');
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
                id: 'location-field',
                title: 'Ubicación Física (Opcional)',
                text: 'Indica dónde se encuentra el equipo o dónde ocurre el problema. Ejemplo: "Aula 201", "Laboratorio 3", "Oficina del Director"',
                attachTo: {
                    element: '#location',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('#location');
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
                id: 'photo-attachment',
                title: 'Adjuntar Foto del Problema',
                text: `
                    <p>Puedes adjuntar una foto del problema para ayudar al técnico a entenderlo mejor.</p>
                    <ul>
                        <li>Marca la casilla para activar la opción</li>
                        <li>Puedes seleccionar un archivo o pegar con <kbd>Ctrl+V</kbd></li>
                        <li>Formatos aceptados: JPG, PNG, GIF, WEBP</li>
                        <li>Tamaño máximo: 3MB</li>
                    </ul>
                `,
                attachTo: {
                    element: '#attach_photo_check',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('#attach_photo_check');
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
                id: 'fill-example',
                title: 'Llenar con Datos de Ejemplo',
                text: 'Para continuar con el tutorial, vamos a llenar automáticamente el formulario con datos de ejemplo. Presiona "Llenar Formulario" para continuar.',
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Llenar Formulario',
                        action: function() {
                            window.helpdeskTutorial.fillFormWithExampleData();
                            return this.next();
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'navigate-to-step3',
                title: 'Avanzar al Paso 3',
                text: 'Ahora que el formulario está completo, haz click en "Siguiente" para revisar los datos antes de enviar.',
                attachTo: {
                    element: '#btnNext',
                    on: 'top'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('#btnNext');
                    }
                },
                advanceOn: {
                    selector: '#btnNext',
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
                id: 'step3-review',
                title: 'Paso 3: Confirmar y Enviar',
                text: `
                    <p>Este es el último paso donde puedes <strong>revisar todos los datos</strong> antes de enviar el ticket.</p>
                    <p>Verifica que toda la información sea correcta. Si necesitas cambiar algo, usa el botón "Anterior".</p>
                `,
                attachTo: {
                    element: '#ticketPreview',
                    on: 'top'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'submit-ticket',
                title: 'Enviar el Ticket',
                text: `
                    <p>Cuando todo esté correcto, presiona este botón para <strong>enviar el ticket</strong>.</p>
                    <p>Para el tutorial, vamos a cargar un ticket de ejemplo (no se guardará en la base de datos). Presiona "Continuar Tutorial" para avanzar.</p>
                    <p><em>Nota: El ticket de ejemplo solo es visible durante el tutorial.</em></p>
                `,
                attachTo: {
                    element: '#btnSubmit',
                    on: 'top'
                },
                when: {
                    show: () => {
                        // Deshabilitar todos los elementos primero
                        window.helpdeskTutorial.disableAllInteractiveElements();

                        // Deshabilitar el botón normal para evitar envío accidental
                        const btnSubmit = document.getElementById('btnSubmit');
                        if (btnSubmit) {
                            btnSubmit.disabled = true;
                            btnSubmit.style.opacity = '0.5';
                            btnSubmit.style.cursor = 'not-allowed';
                        }
                    },
                    hide: () => {
                        // Re-habilitar el botón cuando se oculte el paso
                        const btnSubmit = document.getElementById('btnSubmit');
                        if (btnSubmit) {
                            btnSubmit.disabled = false;
                            btnSubmit.style.opacity = '';
                            btnSubmit.style.cursor = '';
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
                        text: 'Continuar Tutorial',
                        action: async function() {
                            const ticketId = await window.helpdeskTutorial.createExampleTicket();
                            if (ticketId) {
                                // Marcar que estamos navegando (no es cancelación)
                                window.helpdeskTutorial.isNavigating = true;

                                // Ocultar el tour actual sin marcarlo como completado
                                this.hide();

                                // Esperar un momento y navegar
                                setTimeout(() => {
                                    TutorialUtils.navigateTo('/help-desk/user/my-tickets');
                                }, 1500);
                            }
                        },
                        classes: 'btn btn-success'
                    }
                ]
            }
        ];
    }

    /**
     * Pasos del tutorial en MY_TICKETS
     */
    getMyTicketsSteps() {
        return [
            {
                id: 'my-tickets-welcome',
                title: 'Mis Tickets',
                text: `
                    <p>¡Excelente! El ticket ha sido creado.</p>
                    <p>Ahora estás en la sección de <strong>"Mis Tickets"</strong> donde puedes ver y gestionar todos tus tickets.</p>
                `,
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Continuar',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'summary-cards',
                title: 'Resumen de Tickets',
                text: `
                    <p>Estas tarjetas muestran un resumen rápido:</p>
                    <ul>
                        <li><strong>Total:</strong> Todos tus tickets</li>
                        <li><strong>Activos:</strong> Tickets pendientes, asignados o en progreso</li>
                        <li><strong>Resueltos:</strong> Tickets completados</li>
                        <li><strong>Por Calificar:</strong> Tickets resueltos que aún no has calificado</li>
                    </ul>
                `,
                attachTo: {
                    element: '.row.mb-4',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'filters',
                title: 'Filtros y Búsqueda',
                text: 'Puedes filtrar tus tickets por estado, área, o buscar por título o número. Esto es útil cuando tienes muchos tickets.',
                attachTo: {
                    element: '#filterStatus',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'ticket-card',
                title: 'Tu Ticket',
                text: `
                    <p>Aquí está el ticket que acabamos de crear. Cada tarjeta muestra:</p>
                    <ul>
                        <li>Número de ticket y estado</li>
                        <li>Título y descripción</li>
                        <li>Información de asignación</li>
                        <li>Botones de acción</li>
                    </ul>
                `,
                attachTo: {
                    element: '.ticket-card',
                    on: 'top'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'open-ticket-detail',
                title: 'Ver Detalle del Ticket',
                text: 'Haz click en el botón "Abrir" para ver todos los detalles del ticket y continuar con el tutorial.',
                attachTo: {
                    element: '.ticket-card .btn-primary',
                    on: 'left'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                        window.helpdeskTutorial.enableSpecificElement('.ticket-card .btn-primary');
                    }
                },
                buttons: [
                    {
                        text: 'Atrás',
                        action: function() { return this.back(); },
                        classes: 'btn btn-secondary'
                    },
                    {
                        text: 'Ver Detalle',
                        action: function() {
                            const ticketId = TutorialUtils.getItem(TUTORIAL_CONFIG.tutorialTicketKey);
                            if (ticketId) {
                                // Marcar que estamos navegando
                                window.helpdeskTutorial.isNavigating = true;

                                // Ocultar tour sin marcar como completado
                                this.hide();

                                setTimeout(() => {
                                    // Agregar parámetro tutorial=true para que el backend/frontend sepa que es modo tutorial
                                    TutorialUtils.navigateTo(`/help-desk/user/tickets/${ticketId}?from=my_tickets&tutorial=true`);
                                }, 500);
                            }
                        },
                        classes: 'btn btn-primary'
                    }
                ]
            }
        ];
    }

    /**
     * Pasos del tutorial en TICKET_DETAIL
     */
    getTicketDetailSteps() {
        return [
            {
                id: 'ticket-detail-welcome',
                title: 'Detalle del Ticket',
                text: `
                    <p>Esta es la vista detallada de tu ticket donde puedes:</p>
                    <ul>
                        <li>Ver toda la información del ticket</li>
                        <li>Seguir el estado del proceso</li>
                        <li>Agregar comentarios</li>
                        <li>Calificar el servicio cuando sea resuelto</li>
                    </ul>
                `,
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Continuar',
                        action: function() { return this.next(); },
                        classes: 'btn btn-primary'
                    }
                ]
            },
            {
                id: 'ticket-header',
                title: 'Información del Ticket',
                text: 'En la parte superior puedes ver el número de ticket, estado actual, área, prioridad y toda la información relevante.',
                attachTo: {
                    element: '#ticketNumber',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'status-timeline',
                title: 'Historial de Estados',
                text: `
                    <p>Este timeline muestra el progreso de tu ticket:</p>
                    <ul>
                        <li><strong>Creado:</strong> Ticket recién creado</li>
                        <li><strong>Asignado:</strong> Se asignó a un técnico</li>
                        <li><strong>En Progreso:</strong> El técnico está trabajando en ello</li>
                        <li><strong>Resuelto:</strong> El problema fue solucionado</li>
                        <li><strong>Cerrado:</strong> Ticket completado y calificado</li>
                    </ul>
                `,
                attachTo: {
                    element: '#statusTimeline',
                    on: 'left'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'comments-section',
                title: 'Comentarios',
                text: 'Puedes agregar comentarios para comunicarte con el técnico asignado. Esto es útil para proporcionar información adicional o hacer preguntas sobre el progreso.',
                attachTo: {
                    element: '.card-header h5',
                    on: 'bottom'
                },
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'rating-explanation',
                title: 'Encuesta de Satisfacción',
                text: `
                    <p>Cuando tu ticket sea marcado como <strong>Resuelto</strong>, aparecerá un botón para calificar el servicio.</p>
                    <p>La encuesta incluye:</p>
                    <ul>
                        <li><strong>Atención recibida:</strong> Calificación de 1 a 5 estrellas</li>
                        <li><strong>Rapidez del servicio:</strong> Calificación de 1 a 5 estrellas</li>
                        <li><strong>Eficiencia:</strong> Sí o No</li>
                        <li><strong>Comentarios:</strong> (Opcional) Sugerencias o comentarios adicionales</li>
                    </ul>
                    <p><em>Tu opinión nos ayuda a mejorar el servicio.</em></p>
                `,
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
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
                id: 'tutorial-complete',
                title: '¡Tutorial Completado!',
                text: `
                    <p><strong>¡Felicidades!</strong> Has completado el tutorial del sistema de tickets.</p>
                    <p>Ahora sabes:</p>
                    <ul>
                        <li>✓ Cómo crear un ticket de soporte o desarrollo</li>
                        <li>✓ Cómo seleccionar equipos relacionados</li>
                        <li>✓ Cómo ver y gestionar tus tickets</li>
                        <li>✓ Cómo seguir el estado de un ticket</li>
                        <li>✓ Cómo calificar el servicio recibido</li>
                    </ul>
                    <p>Si necesitas ver el tutorial de nuevo, haz click en el botón de tutorial en la página de crear ticket.</p>
                    <p class="mb-0"><em>Puedes eliminar el ticket de ejemplo cuando quieras desde "Mis Tickets".</em></p>
                `,
                when: {
                    show: () => {
                        window.helpdeskTutorial.disableAllInteractiveElements();
                    }
                },
                buttons: [
                    {
                        text: 'Finalizar Tutorial',
                        action: function() {
                            window.helpdeskTutorial.markTutorialComplete();

                            // Ocultar el tour
                            this.complete();

                            // Esperar un momento y navegar a create_ticket con mensaje
                            setTimeout(() => {
                                TutorialUtils.navigateTo('/help-desk/user/create?tutorial_completed=true');
                            }, 500);
                        },
                        classes: 'btn btn-success'
                    }
                ]
            }
        ];
    }

    /**
     * Inicia el tutorial según la página actual
     */
    startTutorial() {
        // Resetear flag de navegación
        this.isNavigating = false;

        this.initializeTour();

        let steps = [];

        switch (this.currentPage) {
            case 'create_ticket':
                steps = this.getCreateTicketSteps();
                break;
            case 'my_tickets':
                steps = this.getMyTicketsSteps();
                break;
            case 'ticket_detail':
                steps = this.getTicketDetailSteps();
                break;
            default:
                console.warn('Página no reconocida para el tutorial');
                return;
        }

        // Agregar los pasos al tour
        steps.forEach(step => this.tour.addStep(step));

        // Iniciar el tour
        this.tour.start();
    }

    /**
     * Verifica si debe iniciar automáticamente el tutorial
     */
    autoStartTutorial() {
        // Verificar si acabamos de completar el tutorial
        const urlParams = new URLSearchParams(window.location.search);
        const tutorialCompleted = urlParams.get('tutorial_completed') === 'true';

        if (this.currentPage === 'create_ticket' && tutorialCompleted) {
            // Mostrar mensaje de bienvenida después del tutorial
            setTimeout(() => {
                TutorialUtils.showModal(
                    '¡Ahora es tu turno!',
                    'Ahora que conoces el proceso, puedes empezar a crear tus propios tickets. ¡Adelante!',
                    'success'
                );

                // Limpiar el parámetro de la URL
                window.history.replaceState({}, document.title, '/help-desk/user/create');
            }, 1000);
            return;
        }

        // Solo en create_ticket y si no lo ha completado
        if (this.currentPage === 'create_ticket' && !this.hasCompletedTutorial()) {
            // Pequeño delay para que cargue la página
            setTimeout(() => {
                this.startTutorial();
            }, 1000);
        }
        // Si viene del tutorial de create_ticket
        else if (this.currentPage === 'my_tickets') {
            // Verificar si está en modo tutorial
            if (this.isTutorialModeActive()) {
                setTimeout(() => {
                    this.startTutorial();

                    // Forzar recarga de tickets después de iniciar el tutorial
                    setTimeout(() => {
                        if (typeof loadMyTickets === 'function') {
                            loadMyTickets();
                        }
                    }, 500);
                }, 1000);
            }
        }
        // Si viene del tutorial de my_tickets
        else if (this.currentPage === 'ticket_detail') {
            const urlParams = new URLSearchParams(window.location.search);
            const fromParam = urlParams.get('from');
            const tutorialParam = urlParams.get('tutorial');

            // Iniciar si:
            // 1. Está en modo tutorial (sessionStorage)
            // 2. O tiene el parámetro tutorial=true en la URL
            // Y viene de my_tickets
            const shouldStart = (this.isTutorialModeActive() || tutorialParam === 'true') && fromParam === 'my_tickets';

            if (shouldStart) {
                setTimeout(() => {
                    this.startTutorial();
                }, 1500); // Dar más tiempo para que cargue el ticket desde JSON
            }
        }
    }
}

// ==================== INICIALIZACIÓN GLOBAL ====================
let helpdeskTutorial;

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    // Crear instancia global
    window.helpdeskTutorial = new HelpdeskTutorial();
    helpdeskTutorial = window.helpdeskTutorial;

    // Auto-iniciar si corresponde
    if (TUTORIAL_CONFIG.autoStart) {
        helpdeskTutorial.autoStartTutorial();
    }
});

// ==================== FUNCIONES GLOBALES PARA OTRAS PÁGINAS ====================
/**
 * Verifica si el modo tutorial está activo
 */
window.isTutorialModeActive = function() {
    return TutorialUtils.getItem(TUTORIAL_CONFIG.tutorialModeKey) === 'true';
};

/**
 * Obtiene los datos del ticket de ejemplo del tutorial
 */
window.getTutorialTicketData = function() {
    const data = TutorialUtils.getItem(TUTORIAL_CONFIG.tutorialDataKey);
    return data ? JSON.parse(data) : null;
};

/**
 * Obtiene el ID del ticket del tutorial
 */
window.getTutorialTicketId = function() {
    return TutorialUtils.getItem(TUTORIAL_CONFIG.tutorialTicketKey);
};

// Exportar para uso global
window.HelpdeskTutorial = HelpdeskTutorial;
window.TutorialUtils = TutorialUtils;
window.TUTORIAL_CONFIG = TUTORIAL_CONFIG;
