// itcj/apps/helpdesk/static/js/user/create_ticket.js

/**
 * ========================================
 * CREATE TICKET - Sistema de Help Desk
 * ========================================
 * 
 * Maneja la creación de tickets con un flujo de 3 pasos:
 * 1. Selección de área (DESARROLLO/SOPORTE)
 * 2. Detalles del problema
 * 3. Confirmación
 * 
 * Para SOPORTE: Permite seleccionar equipos del inventario
 * Para DESARROLLO: Solo pide categoría del problema
 */

// ==================== ESTADO GLOBAL ====================
const AppState = {
    currentStep: 1,
    totalSteps: 3,
    selectedArea: null,
    categories: [],
    equipment: {
        ownerType: null, // 'mine' | 'department'
        available: [],
        filtered: [],
        selected: null,
        categories: []
    },
    modal: null
};

// ==================== INICIALIZACIÓN ====================
document.addEventListener('DOMContentLoaded', () => {

    // Inicializar componentes
    AreaSelection.init();
    FormValidation.init();
    Navigation.init();
    Equipment.init();

    // Cargar datos necesarios
    Equipment.loadCategories();

    PhotoUpload.init();
});

// ==================== SELECCIÓN DE ÁREA ====================
const AreaSelection = {
    init() {
        document.querySelectorAll('.area-card').forEach(card => {
            card.addEventListener('click', () => {
                const area = card.dataset.area;
                this.selectArea(area);
            });
        });
    },

    async selectArea(area) {
        // Visual feedback
        document.querySelectorAll('.area-card .card').forEach(card => {
            card.classList.remove('selected');
        });

        const selectedCard = document.querySelector(`[data-area="${area}"] .card`);
        selectedCard.classList.add('selected');

        // Guardar selección
        AppState.selectedArea = area;
        document.getElementById('area').value = area;

        // Cargar categorías
        await this.loadCategories(area);

        // Configurar UI según área
        this.configureUIForArea(area);

        // Habilitar botón siguiente
        document.getElementById('btnNext').disabled = false;
    },

    async loadCategories(area) {
        try {
            const response = await HelpdeskUtils.api.getCategories(area);
            AppState.categories = response.categories || [];

            const categorySelect = document.getElementById('category_id');
            categorySelect.innerHTML = '<option value="">Selecciona una categoría...</option>';

            AppState.categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.id;
                option.textContent = cat.name;
                categorySelect.appendChild(option);
            });

        } catch (error) {
            console.error('❌ Error loading categories:', error);
            HelpdeskUtils.showToast('Error al cargar categorías', 'error');
        }
    },

    configureUIForArea(area) {
        const categorySection = document.getElementById('category-section');
        const equipmentSection = document.getElementById('equipment-section');

        if (area === 'SOPORTE') {
            // Para SOPORTE: ocultar categorías, mostrar equipos
            categorySection.style.display = 'none';
            equipmentSection.style.display = 'block';
            document.getElementById('category_id').required = false;
        } else {
            // Para DESARROLLO: mostrar categorías, ocultar equipos
            categorySection.style.display = 'block';
            equipmentSection.style.display = 'none';
            document.getElementById('category_id').required = true;
            // Limpiar selección de equipo si había
            Equipment.clearSelection();
        }
    }
};

// ==================== GESTIÓN DE EQUIPOS ====================
const Equipment = {
    init() {
        // Event listeners para selección de propietario
        document.querySelectorAll('input[name="equipment-owner"]').forEach(radio => {
            radio.addEventListener('change', (e) => this.handleOwnerSelection(e.target.value));
        });

        // Botón para abrir modal
        document.getElementById('open-equipment-modal')?.addEventListener('click', () => {
            this.openModal();
        });

        // Botón para confirmar selección en modal
        document.getElementById('confirm-equipment-btn')?.addEventListener('click', () => {
            this.confirmSelection();
        });

        // Botón para limpiar selección
        document.getElementById('clear-equipment-btn')?.addEventListener('click', () => {
            this.clearSelection();
        });

        // Búsqueda en modal
        document.getElementById('equipment-search')?.addEventListener('input', (e) => {
            this.filterEquipment(e.target.value);
        });

        // Filtro por categoría en modal
        document.getElementById('equipment-category-filter')?.addEventListener('change', (e) => {
            this.filterByCategory(e.target.value);
        });

        // Inicializar modal de Bootstrap
        const modalElement = document.getElementById('equipmentModal');
        if (modalElement) {
            AppState.modal = new bootstrap.Modal(modalElement);
        }
    },

    async loadCategories() {
        try {
            const response = await fetch('/api/help-desk/v1/inventory/categories?active=true');
            if (!response.ok) return;

            const result = await response.json();
            AppState.equipment.categories = result.data || [];

            // Llenar select de filtro
            const select = document.getElementById('equipment-category-filter');
            if (select) {
                select.innerHTML = '<option value="">Todas las categorías</option>';
                AppState.equipment.categories.forEach(cat => {
                    const option = document.createElement('option');
                    option.value = cat.id;
                    option.textContent = cat.name;
                    select.appendChild(option);
                });
            }

        } catch (error) {
            console.error('❌ Error cargando categorías de inventario:', error);
        }
    },

    handleOwnerSelection(ownerType) {
        AppState.equipment.ownerType = ownerType;

        // Mostrar selector de equipos
        document.getElementById('equipment-selector-container').style.display = 'block';

        // Actualizar texto del botón
        const buttonText = document.getElementById('equipment-button-text');
        if (ownerType === 'mine') {
            buttonText.textContent = 'Seleccionar de Mis Equipos';
        } else {
            buttonText.textContent = 'Seleccionar de Equipos del Departamento';
        }

        // Limpiar selección previa si cambia el tipo
        this.clearSelection();
    },

    async openModal() {
        if (!AppState.equipment.ownerType) {
            HelpdeskUtils.showToast('Por favor selecciona primero el tipo de propietario', 'warning');
            return;
        }

        // Mostrar modal
        AppState.modal.show();

        // Cargar equipos
        await this.loadEquipmentForModal();
    },

    async loadEquipmentForModal() {
        const listContainer = document.getElementById('equipment-list');
        const loadingDiv = document.getElementById('equipment-loading');
        const emptyDiv = document.getElementById('equipment-empty');

        // Mostrar loading
        loadingDiv.style.display = 'block';
        emptyDiv.style.display = 'none';
        listContainer.innerHTML = '';

        try {
            let endpoint;
            if (AppState.equipment.ownerType === 'mine') {
                endpoint = '/api/help-desk/v1/inventory/items/my-equipment';
            } else {
                // Obtener departamento del usuario
                const userResponse = await fetch('/api/core/v1/users/me/department');
                const userData = await userResponse.json();
                const deptId = userData.data.id;
                endpoint = `/api/help-desk/v1/inventory/items?department_id=${deptId}`;
            }

            const response = await fetch(endpoint);
            if (!response.ok) throw new Error('Error al cargar equipos');

            const result = await response.json();
            AppState.equipment.available = result.data || [];
            AppState.equipment.filtered = [...AppState.equipment.available];

            // Ocultar loading
            loadingDiv.style.display = 'none';

            if (AppState.equipment.available.length === 0) {
                emptyDiv.style.display = 'block';
            } else {
                this.renderEquipmentList();
            }

        } catch (error) {
            console.error('❌ Error cargando equipos:', error);
            loadingDiv.style.display = 'none';
            emptyDiv.style.display = 'block';
            HelpdeskUtils.showToast('Error al cargar equipos', 'error');
        }
    },

    renderEquipmentList() {
        const listContainer = document.getElementById('equipment-list');
        listContainer.innerHTML = '';

        if (AppState.equipment.filtered.length === 0) {
            listContainer.innerHTML = `
                <div class="text-center py-4">
                    <i class="fas fa-search fa-2x text-muted mb-2"></i>
                    <p class="text-muted">No se encontraron equipos con ese criterio</p>
                </div>
            `;
            return;
        }

        AppState.equipment.filtered.forEach(item => {
            const card = this.createEquipmentCard(item);
            listContainer.appendChild(card);
        });
    },

    createEquipmentCard(item) {
        const card = document.createElement('div');
        card.className = 'equipment-card';
        if (AppState.equipment.selected?.id === item.id) {
            card.classList.add('selected');
        }

        // Icono según categoría
        const icon = this.getEquipmentIcon(item.category?.icon || 'fa-laptop');

        // Información del propietario
        const ownerInfo = item.assigned_to_user
            ? `<span class="badge bg-info"><i class="fas fa-user me-1"></i>${item.assigned_to_user.full_name}</span>`
            : `<span class="badge bg-secondary"><i class="fas fa-building me-1"></i>Global del Departamento</span>`;

        card.innerHTML = `
            <div class="d-flex align-items-start">
                <div class="equipment-icon me-3">
                    <i class="${icon}"></i>
                </div>
                <div class="flex-grow-1">
                    <div class="fw-bold text-primary">${item.inventory_number}</div>
                    <div class="text-dark">${item.brand || 'N/A'} ${item.model || ''}</div>
                    <small class="text-muted">
                        <i class="fas fa-tag me-1"></i>${item.category?.name || 'Sin categoría'}
                    </small>
                    <div class="mt-2">
                        ${ownerInfo}
                        ${item.location_detail ? `<span class="badge bg-light text-dark"><i class="fas fa-map-marker-alt me-1"></i>${item.location_detail}</span>` : ''}
                    </div>
                </div>
                <div class="ms-2">
                    ${this.getStatusBadge(item.status)}
                </div>
            </div>
        `;

        // Click para seleccionar
        card.addEventListener('click', () => {
            this.selectEquipmentInModal(item);
        });

        return card;
    },

    getEquipmentIcon(iconClass) {
        // Si ya viene el icono completo de la categoría
        if (iconClass) return iconClass;
        // Por defecto
        return 'fas fa-laptop';
    },

    getStatusBadge(status) {
        const statusMap = {
            'ACTIVE': { class: 'success', text: 'Activo' },
            'MAINTENANCE': { class: 'warning', text: 'Mantenimiento' },
            'DAMAGED': { class: 'danger', text: 'Dañado' },
            'RETIRED': { class: 'secondary', text: 'Retirado' },
            'LOST': { class: 'dark', text: 'Extraviado' }
        };
        const config = statusMap[status] || { class: 'secondary', text: status };
        return `<span class="badge bg-${config.class}">${config.text}</span>`;
    },

    selectEquipmentInModal(item) {
        // Actualizar selección
        AppState.equipment.selected = item;

        // Actualizar UI del modal
        document.querySelectorAll('.equipment-card').forEach(card => {
            card.classList.remove('selected');
        });
        event.currentTarget.classList.add('selected');

        // Habilitar botón de confirmar
        document.getElementById('confirm-equipment-btn').disabled = false;
    },

    confirmSelection() {
        if (!AppState.equipment.selected) return;

        // Cerrar modal
        AppState.modal.hide();

        // Actualizar preview
        this.showPreview(AppState.equipment.selected);

        // Guardar ID en input oculto
        document.getElementById('inventory_item_id').value = AppState.equipment.selected.id;

        HelpdeskUtils.showToast('Equipo seleccionado correctamente', 'success');
    },

    showPreview(item) {
        const preview = document.getElementById('selected-equipment-preview');
        const icon = document.getElementById('preview-equipment-icon');
        const number = document.getElementById('preview-equipment-number');
        const info = document.getElementById('preview-equipment-info');
        const owner = document.getElementById('preview-equipment-owner');
        const location = document.getElementById('preview-equipment-location');

        // Actualizar contenido
        icon.innerHTML = `<i class="${this.getEquipmentIcon(item.category?.icon)} fa-2x text-success"></i>`;
        number.textContent = item.inventory_number;
        info.textContent = `${item.brand || 'N/A'} ${item.model || ''}`.trim();

        if (item.assigned_to_user) {
            owner.innerHTML = `<i class="fas fa-user me-1"></i>${item.assigned_to_user.full_name}`;
        } else {
            owner.innerHTML = `<i class="fas fa-building me-1"></i>Global del Departamento`;
        }

        location.textContent = item.location_detail || item.department?.name || 'Sin ubicación';

        // Mostrar preview
        preview.style.display = 'block';

        // Actualizar texto del botón
        document.getElementById('equipment-button-text').textContent = 'Cambiar Equipo';
    },

    clearSelection() {
        AppState.equipment.selected = null;
        document.getElementById('inventory_item_id').value = '';
        document.getElementById('selected-equipment-preview').style.display = 'none';
        document.getElementById('equipment-button-text').textContent =
            AppState.equipment.ownerType === 'mine' ? 'Seleccionar de Mis Equipos' : 'Seleccionar de Equipos del Departamento';
    },

    filterEquipment(searchTerm) {
        const term = searchTerm.toLowerCase().trim();

        if (!term) {
            AppState.equipment.filtered = [...AppState.equipment.available];
        } else {
            AppState.equipment.filtered = AppState.equipment.available.filter(item => {
                return (
                    item.inventory_number.toLowerCase().includes(term) ||
                    (item.brand && item.brand.toLowerCase().includes(term)) ||
                    (item.model && item.model.toLowerCase().includes(term)) ||
                    (item.serial_number && item.serial_number.toLowerCase().includes(term))
                );
            });
        }

        this.renderEquipmentList();
    },

    filterByCategory(categoryId) {
        if (!categoryId) {
            AppState.equipment.filtered = [...AppState.equipment.available];
        } else {
            AppState.equipment.filtered = AppState.equipment.available.filter(item =>
                item.category_id === parseInt(categoryId)
            );
        }

        this.renderEquipmentList();
    }
};

// ==================== VALIDACIÓN DE FORMULARIO ====================
const FormValidation = {
    init() {
        const form = document.getElementById('ticketForm');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            if (AppState.currentStep !== AppState.totalSteps) return;

            if (!form.checkValidity()) {
                e.stopPropagation();
                form.classList.add('was-validated');
                return;
            }

            await this.submitTicket();
        });

        // Contador de descripción
        this.setupDescriptionCounter();
    },

    setupDescriptionCounter() {
        const textarea = document.getElementById('description');
        const counter = document.getElementById('descCharCount');

        textarea.addEventListener('input', () => {
            const length = textarea.value.length;
            counter.textContent = `${length} / 20 caracteres mínimo`;

            if (length >= 20) {
                counter.classList.remove('text-danger');
                counter.classList.add('text-success');
            } else {
                counter.classList.remove('text-success');
                counter.classList.add('text-danger');
            }
        });
    },

    validateCurrentStep() {
        switch (AppState.currentStep) {
            case 1:
                if (!AppState.selectedArea) {
                    HelpdeskUtils.showToast('Por favor selecciona el tipo de servicio', 'warning');
                    return false;
                }
                return true;

            case 2:
                // Para DESARROLLO, validar categoría
                if (AppState.selectedArea === 'DESARROLLO') {
                    const categoryId = document.getElementById('category_id').value;
                    if (!categoryId) {
                        HelpdeskUtils.showToast('Por favor selecciona una categoría', 'warning');
                        document.getElementById('category_id').focus();
                        return false;
                    }
                }

                // Validar título
                const title = document.getElementById('title').value.trim();
                if (title.length < 5) {
                    HelpdeskUtils.showToast('El título debe tener al menos 5 caracteres', 'warning');
                    document.getElementById('title').focus();
                    return false;
                }

                // Validar descripción
                const description = document.getElementById('description').value.trim();
                if (description.length < 20) {
                    HelpdeskUtils.showToast('La descripción debe tener al menos 20 caracteres', 'warning');
                    document.getElementById('description').focus();
                    return false;
                }

                return true;

            default:
                return true;
        }
    },

    getFormData() {
        const data = {
            area: document.getElementById('area').value,
            title: document.getElementById('title').value.trim(),
            description: document.getElementById('description').value.trim(),
            priority: document.querySelector('input[name="priority"]:checked').value,
            location: document.getElementById('location').value.trim() || null,
            office_folio: document.getElementById('office_folio').value.trim() || null
        };

        // Para DESARROLLO: incluir category_id
        if (data.area === 'DESARROLLO') {
            data.category_id = parseInt(document.getElementById('category_id').value);
        }

        // Para SOPORTE: incluir inventory_item_id si se seleccionó
        if (data.area === 'SOPORTE') {
            const inventoryItemId = document.getElementById('inventory_item_id').value;
            if (inventoryItemId) {
                data.inventory_item_id = parseInt(inventoryItemId);
            }
            // Para SOPORTE aún necesitamos una categoría (puede ser genérica o derivada del equipo)
            // Por ahora ponemos una categoría por defecto o la primera disponible
            if (AppState.categories.length > 0) {
                data.category_id = AppState.categories[0].id;
            }
        }

        return data;
    },

    async submitTicket() {
        const submitBtn = document.getElementById('btnSubmit');
        const originalText = submitBtn.innerHTML;

        // Disable button and show loading
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Enviando...';

        const preview = document.getElementById('ticketPreview');
        preview.style.animation = 'ticket-send 1.5s ease-out forwards';

        try {
            const formData = this.getFormData();
            const photoFile = PhotoUpload.getFile();

            // Si hay foto, usar FormData en lugar de JSON
            if (photoFile) {
                const formDataMultipart = new FormData();

                // Agregar campos del ticket
                Object.keys(formData).forEach(key => {
                    if (formData[key] !== null && formData[key] !== undefined) {
                        formDataMultipart.append(key, formData[key]);
                    }
                });

                // Agregar foto
                formDataMultipart.append('photo', photoFile);

                // Enviar con fetch directamente
                const response = await fetch('/api/help-desk/v1/tickets', {
                    method: 'POST',
                    body: formDataMultipart
                    // No incluir Content-Type, el browser lo pone automáticamente
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.message || 'Error al crear ticket');
                }

                const result = await response.json();

                HelpdeskUtils.showToast(
                    '¡Ticket creado exitosamente! Serás notificado cuando sea asignado.',
                    'success'
                );

                setTimeout(() => {
                    window.location.href = '/help-desk/user/my-tickets';
                }, 2000);

            } else {
                // Sin foto, enviar JSON normal
                const response = await HelpdeskUtils.api.createTicket(formData);

                HelpdeskUtils.showToast(
                    '¡Ticket creado exitosamente! Serás notificado cuando sea asignado.',
                    'success'
                );

                setTimeout(() => {
                    window.location.href = '/help-desk/user/my-tickets';
                }, 2000);
            }
        } catch (error) {
            console.error('❌ Error creating ticket:', error);
            HelpdeskUtils.showToast(
                error.message || 'Error al crear el ticket. Intenta nuevamente.',
                'error'
            );

            // Re-enable button
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
            preview.style.animation = '';
        }
    }
};

// ==================== NAVEGACIÓN ENTRE PASOS ====================
const Navigation = {
    init() {
        document.getElementById('btnNext').addEventListener('click', () => this.nextStep());
        document.getElementById('btnPrevious').addEventListener('click', () => this.previousStep());
    },

    nextStep() {
        if (!FormValidation.validateCurrentStep()) return;

        if (AppState.currentStep < AppState.totalSteps) {
            AppState.currentStep++;
            this.showStep(AppState.currentStep);

            if (AppState.currentStep === AppState.totalSteps) {
                this.showSummary();
            }
        }
    },

    previousStep() {
        if (AppState.currentStep > 1) {
            AppState.currentStep--;
            this.showStep(AppState.currentStep);
        }
    },

    showStep(step) {
        // Hide all steps
        document.querySelectorAll('.step-content').forEach(content => {
            content.classList.add('d-none');
        });

        // Show current step
        document.getElementById(`step${step}`).classList.remove('d-none');

        // Update indicators
        for (let i = 1; i <= AppState.totalSteps; i++) {
            const indicator = document.getElementById(`step-indicator-${i}`);
            if (i <= step) {
                indicator.classList.add('active');
            } else {
                indicator.classList.remove('active');
            }
        }

        // Update buttons
        const btnPrevious = document.getElementById('btnPrevious');
        const btnNext = document.getElementById('btnNext');
        const btnSubmit = document.getElementById('btnSubmit');

        btnPrevious.style.display = step > 1 ? 'block' : 'none';
        btnNext.style.display = step < AppState.totalSteps ? 'block' : 'none';
        btnSubmit.style.display = step === AppState.totalSteps ? 'block' : 'none';

        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    showSummary() {
        const formData = FormValidation.getFormData();
        let category = null;

        if (AppState.selectedArea === 'DESARROLLO') {
            category = AppState.categories.find(c => c.id === formData.category_id);
        }

        let summary = `
            <h5 class="mb-3">
                <i class="fas fa-clipboard-check me-2 text-primary"></i>
                Resumen de tu Ticket
            </h5>
            
            <div class="row g-3">
                <div class="col-md-6">
                    <strong><i class="fas fa-layer-group me-2 text-muted"></i>Área:</strong><br>
                    ${HelpdeskUtils.getAreaBadge(formData.area)}
                </div>
        `;

        if (category) {
            summary += `
                <div class="col-md-6">
                    <strong><i class="fas fa-tag me-2 text-muted"></i>Categoría:</strong><br>
                    <span class="badge bg-secondary">${category.name}</span>
                </div>
            `;
        }

        if (AppState.equipment.selected) {
            summary += `
                <div class="col-12">
                    <strong><i class="fas fa-laptop me-2 text-muted"></i>Equipo:</strong><br>
                    <span class="badge bg-info">${AppState.equipment.selected.inventory_number}</span>
                    <span class="text-muted">- ${AppState.equipment.selected.brand} ${AppState.equipment.selected.model}</span>
                </div>
            `;
        }
        const photoFile = PhotoUpload.getFile();
        if (photoFile) {
            summary += `
            <div class="col-12">
                <strong><i class="fas fa-camera me-2 text-muted"></i>Foto adjunta:</strong><br>
                <span class="badge bg-success">
                    <i class="fas fa-check-circle me-1"></i>
                    ${photoFile.name} (${PhotoUpload.formatFileSize(photoFile.size)})
                </span>
            </div>
        `;
        }
        summary += `
                <div class="col-12">
                    <strong><i class="fas fa-heading me-2 text-muted"></i>Título:</strong><br>
                    ${formData.title}
                </div>
                <div class="col-12">
                    <strong><i class="fas fa-align-left me-2 text-muted"></i>Descripción:</strong><br>
                    <p class="mb-0">${formData.description}</p>
                </div>
                <div class="col-md-6">
                    <strong><i class="fas fa-exclamation-circle me-2 text-muted"></i>Prioridad:</strong><br>
                    ${HelpdeskUtils.getPriorityBadge(formData.priority)}
                </div>
        `;

        if (formData.location) {
            summary += `
                <div class="col-md-6">
                    <strong><i class="fas fa-map-marker-alt me-2 text-muted"></i>Ubicación:</strong><br>
                    ${formData.location}
                </div>
            `;
        }

        if (formData.office_folio) {
            summary += `
                <div class="col-md-6">
                    <strong><i class="fas fa-file-alt me-2 text-muted"></i>Folio de Oficio:</strong><br>
                    ${formData.office_folio}
                </div>
            `;
        }

        summary += `</div>`;

        document.getElementById('ticketSummary').innerHTML = summary;
    }
};

const PhotoUpload = {
    selectedFile: null,

    init() {
        const checkbox = document.getElementById('attach_photo_check');
        const section = document.getElementById('photo_upload_section');
        const fileInput = document.getElementById('photo_file');
        const removeBtn = document.getElementById('remove_photo');

        // Toggle sección al marcar checkbox
        checkbox?.addEventListener('change', (e) => {
            section.style.display = e.target.checked ? 'block' : 'none';
            if (!e.target.checked) {
                this.clearFile();
            }
        });

        // Manejar selección de archivo
        fileInput?.addEventListener('change', (e) => {
            this.handleFileSelect(e.target.files[0]);
        });

        // Remover archivo
        removeBtn?.addEventListener('click', () => {
            this.clearFile();
        });
        document.addEventListener('paste', (e) => {
            // Solo si el checkbox está marcado y estamos en step 2
            if (!checkbox?.checked || AppState.currentStep !== 2) return;

            const items = e.clipboardData?.items;
            if (!items) return;

            for (let i = 0; i < items.length; i++) {
                if (items[i].type.indexOf('image') !== -1) {
                    e.preventDefault(); // Prevenir pegar en inputs
                    const blob = items[i].getAsFile();
                    this.handleFileSelect(blob);
                    HelpdeskUtils.showToast('Imagen pegada desde portapapeles', 'success');
                    break;
                }
            }
        });
    },

    handleFileSelect(file) {
        if (!file) return;

        // Validar tipo
        const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
        if (!allowedTypes.includes(file.type)) {
            HelpdeskUtils.showToast('Solo se permiten imágenes (JPG, PNG, GIF, WEBP)', 'error');
            this.clearFile();
            return;
        }

        // Validar tamaño (3MB)
        const maxSize = 3 * 1024 * 1024;
        if (file.size > maxSize) {
            HelpdeskUtils.showToast('La imagen no debe exceder 3MB', 'error');
            this.clearFile();
            return;
        }

        // Guardar archivo y mostrar preview
        this.selectedFile = file;
        this.showPreview(file);
    },

    showPreview(file) {
        const preview = document.getElementById('photo_preview');
        const filename = document.getElementById('photo_filename');
        const filesize = document.getElementById('photo_filesize');

        filename.textContent = file.name;
        filesize.textContent = this.formatFileSize(file.size);
        preview.style.display = 'block';
    },

    clearFile() {
        this.selectedFile = null;
        document.getElementById('photo_file').value = '';
        document.getElementById('photo_preview').style.display = 'none';
    },

    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    },

    getFile() {
        return this.selectedFile;
    }
};

// ==================== EXPORT PARA DEBUG ====================
window.CreateTicketDebug = {
    state: AppState,
    equipment: Equipment,
    validation: FormValidation,
    photo: PhotoUpload
};

const style = document.createElement('style');
style.textContent = `
@keyframes ticket-send {
    0% {
        transform: translateY(0) scale(1) rotate(0deg);
        opacity: 1;
    }
    50% {
        transform: translateY(-30px) scale(1.1) rotate(5deg);
        opacity: 0.8;
    }
    100% {
        transform: translateY(-100px) scale(0.8) rotate(10deg);
        opacity: 0;
    }
}
`;
document.head.appendChild(style);

