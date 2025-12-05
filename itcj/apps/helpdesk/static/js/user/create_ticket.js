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
        ownerType: null, // 'mine' | 'department' | 'group'
        available: [],
        filtered: [],
        selected: null,
        categories: [],
        groups: [],
        filteredGroups: [],
        selectedGroup: null,
        groupEquipment: [],
        selectedGroupEquipment: []
    },
    modal: null,
    groupModal: null,
    groupEquipmentModal: null
};

// ==================== GESTIÓN DE REQUESTER ====================
const RequesterSelection = {
    modal: null,
    selectedRequester: null,
    availableRequesters: [],
    filteredRequesters: [],
    searchTimeout: null,

    init() {
        const modalElement = document.getElementById('requesterModal');
        if (!modalElement) return; // No hay modal (usuario no puede crear para otros)

        this.modal = new bootstrap.Modal(modalElement);

        // Botón para abrir modal
        document.getElementById('open-requester-modal')?.addEventListener('click', () => {
            this.openModal();
        });

        // Botón para confirmar selección
        document.getElementById('confirm-requester-btn')?.addEventListener('click', () => {
            this.confirmSelection();
        });

        // Botón para limpiar selección
        document.getElementById('clear-requester-btn')?.addEventListener('click', () => {
            this.clearSelection();
        });

        // Búsqueda con debounce
        document.getElementById('requester-search')?.addEventListener('input', (e) => {
            clearTimeout(this.searchTimeout);
            this.searchTimeout = setTimeout(() => {
                this.searchRequesters(e.target.value);
            }, 300);
        });
    },

    async openModal() {
        this.modal.show();
        await this.loadRequesters();
    },

    async loadRequesters(search = '') {
        const listContainer = document.getElementById('requester-list');
        const loadingDiv = document.getElementById('requester-loading');
        const emptyDiv = document.getElementById('requester-empty');

        loadingDiv.style.display = 'block';
        emptyDiv.style.display = 'none';
        listContainer.innerHTML = '';

        try {
            const url = `/api/core/v1/users/by-app/helpdesk?search=${encodeURIComponent(search)}`;
            const response = await fetch(url);

            if (!response.ok) throw new Error('Error al cargar usuarios');

            const result = await response.json();
            this.availableRequesters = result.data?.users || [];
            this.filteredRequesters = [...this.availableRequesters];

            loadingDiv.style.display = 'none';

            if (this.availableRequesters.length === 0) {
                emptyDiv.style.display = 'block';
            } else {
                this.renderRequesterList();
            }
        } catch (error) {
            console.error('❌ Error cargando usuarios:', error);
            loadingDiv.style.display = 'none';
            emptyDiv.style.display = 'block';
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar usuarios: ${errorMessage}`, 'error');
        }
    },

    async searchRequesters(searchTerm) {
        await this.loadRequesters(searchTerm);
    },

    renderRequesterList() {
        const listContainer = document.getElementById('requester-list');
        listContainer.innerHTML = '';

        if (this.filteredRequesters.length === 0) {
            listContainer.innerHTML = `
                <div class="text-center py-4">
                    <i class="fas fa-search fa-2x text-muted mb-2"></i>
                    <p class="text-muted">No se encontraron usuarios con ese criterio</p>
                </div>
            `;
            return;
        }

        this.filteredRequesters.forEach(user => {
            const card = this.createRequesterCard(user);
            listContainer.appendChild(card);
        });
    },

    createRequesterCard(user) {
        const card = document.createElement('div');
        card.className = 'equipment-card'; // Reutilizar estilos
        if (this.selectedRequester?.id === user.id) {
            card.classList.add('selected');
        }

        card.innerHTML = `
            <div class="d-flex align-items-start">
                <div class="equipment-icon me-3">
                    <i class="fas fa-user-circle"></i>
                </div>
                <div class="flex-grow-1">
                    <div class="fw-bold text-primary">${user.full_name}</div>
                    <div class="text-dark">${user.email || 'Sin email'}</div>
                    <small class="text-muted">
                        <i class="fas fa-id-card me-1"></i>${user.username}
                    </small>
                </div>
            </div>
        `;

        card.addEventListener('click', () => {
            this.selectRequesterInModal(user);
        });

        return card;
    },

    selectRequesterInModal(user) {
        this.selectedRequester = user;

        // Actualizar UI del modal
        document.querySelectorAll('#requester-list .equipment-card').forEach(card => {
            card.classList.remove('selected');
        });
        event.currentTarget.classList.add('selected');

        // Habilitar botón de confirmar
        document.getElementById('confirm-requester-btn').disabled = false;
    },

    confirmSelection() {
        if (!this.selectedRequester) return;

        // Cerrar modal
        this.modal.hide();

        // Mostrar preview
        this.showRequesterPreview(this.selectedRequester);

        // Guardar ID en input oculto
        document.getElementById('requester_id').value = this.selectedRequester.id;

        // Limpiar selecciones de equipos/grupos ya que el contexto cambió
        Equipment.clearSelection();
        Equipment.clearGroupSelection();

        // Re-actualizar textos de botones si hay una selección de tipo de propietario
        if (AppState.equipment.ownerType) {
            Equipment.handleOwnerSelection(AppState.equipment.ownerType);
        }

        HelpdeskUtils.showToast(`Ticket será creado para: ${this.selectedRequester.full_name}`, 'success');
    },

    showRequesterPreview(user) {
        const preview = document.getElementById('selected-requester-preview');
        const name = document.getElementById('preview-requester-name');
        const info = document.getElementById('preview-requester-info');

        name.textContent = user.full_name;
        info.textContent = `${user.email || ''} • ${user.username}`;

        preview.style.display = 'block';

        // Actualizar texto del botón
        document.getElementById('requester-button-text').textContent = 'Cambiar usuario';
    },

    clearSelection() {
        this.selectedRequester = null;
        document.getElementById('selected-requester-preview').style.display = 'none';
        document.getElementById('requester_id').value = '';
        document.getElementById('requester-button-text').textContent = 'Seleccionar usuario (opcional)';

        // Limpiar selecciones de equipos/grupos ya que ahora se basará en el usuario actual
        Equipment.clearSelection();
        Equipment.clearGroupSelection();

        // Re-actualizar textos de botones si hay una selección de tipo de propietario
        if (AppState.equipment.ownerType) {
            Equipment.handleOwnerSelection(AppState.equipment.ownerType);
        }
    }
};

// ==================== INICIALIZACIÓN ====================
document.addEventListener('DOMContentLoaded', () => {

    // Inicializar componentes
    AreaSelection.init();
    FormValidation.init();
    Navigation.init();
    Equipment.init();
    RequesterSelection.init(); // Nuevo componente

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
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar categorías: ${errorMessage}`, 'error');
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

// ==================== GESTIÓN DE EQUIPOS Y GRUPOS ====================
const Equipment = {
    init() {
        // Event listeners para selección de propietario
        document.querySelectorAll('input[name="equipment-owner"]').forEach(radio => {
            radio.addEventListener('change', (e) => this.handleOwnerSelection(e.target.value));
        });

        // Botones para abrir modales
        document.getElementById('open-equipment-modal')?.addEventListener('click', () => {
            this.openEquipmentModal();
        });

        document.getElementById('open-group-modal')?.addEventListener('click', () => {
            this.openGroupModal();
        });

        // Botones para confirmar selección
        document.getElementById('confirm-equipment-btn')?.addEventListener('click', () => {
            this.confirmEquipmentSelection();
        });

        document.getElementById('confirm-group-btn')?.addEventListener('click', () => {
            this.confirmGroupSelection();
        });

        document.getElementById('confirm-group-equipment-btn')?.addEventListener('click', () => {
            this.confirmGroupEquipmentSelection();
        });

        // Botones para limpiar selección
        document.getElementById('clear-equipment-btn')?.addEventListener('click', () => {
            this.clearSelection();
        });

        document.getElementById('clear-group-btn')?.addEventListener('click', () => {
            this.clearGroupSelection();
        });

        // Búsqueda en modales
        document.getElementById('equipment-search')?.addEventListener('input', (e) => {
            this.filterEquipment(e.target.value);
        });

        document.getElementById('group-search')?.addEventListener('input', (e) => {
            this.filterGroups(e.target.value);
        });

        // Filtro por categoría en modal
        document.getElementById('equipment-category-filter')?.addEventListener('change', (e) => {
            this.filterByCategory(e.target.value);
        });

        // Selección múltiple en modal de equipos de grupo
        document.getElementById('select-all-group-equipment')?.addEventListener('click', () => {
            this.selectAllGroupEquipment();
        });

        document.getElementById('clear-all-group-equipment')?.addEventListener('click', () => {
            this.clearAllGroupEquipment();
        });

        // Inicializar modales de Bootstrap
        const equipmentModalElement = document.getElementById('equipmentModal');
        const groupModalElement = document.getElementById('groupModal');
        const groupEquipmentModalElement = document.getElementById('groupEquipmentModal');

        if (equipmentModalElement) {
            AppState.modal = new bootstrap.Modal(equipmentModalElement);
        }
        if (groupModalElement) {
            AppState.groupModal = new bootstrap.Modal(groupModalElement);
        }
        if (groupEquipmentModalElement) {
            AppState.groupEquipmentModal = new bootstrap.Modal(groupEquipmentModalElement);
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
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar categorías de inventario: ${errorMessage}`, 'error');
        }
    },

    handleOwnerSelection(ownerType) {
        AppState.equipment.ownerType = ownerType;

        // Ocultar todos los contenedores
        document.getElementById('equipment-selector-container').style.display = 'none';
        document.getElementById('group-selector-container').style.display = 'none';

        // Limpiar selecciones previas
        this.clearSelection();
        this.clearGroupSelection();

        // Mostrar contenedor apropiado
        if (ownerType === 'group') {
            document.getElementById('group-selector-container').style.display = 'block';
        } else {
            document.getElementById('equipment-selector-container').style.display = 'block';

            // Actualizar texto del botón según si hay requester seleccionado
            const buttonText = document.getElementById('equipment-button-text');
            const selectedRequester = RequesterSelection.selectedRequester;

            if (ownerType === 'mine') {
                if (selectedRequester) {
                    buttonText.textContent = `Seleccionar de Equipos de ${selectedRequester.full_name.split(' ')[0]}`;
                } else {
                    buttonText.textContent = 'Seleccionar de Mis Equipos';
                }
            } else {
                if (selectedRequester) {
                    buttonText.textContent = `Seleccionar de Equipos del Departamento de ${selectedRequester.full_name.split(' ')[0]}`;
                } else {
                    buttonText.textContent = 'Seleccionar de Equipos del Departamento';
                }
            }
        }
    },

    // ==================== MODAL DE GRUPOS ====================
    async openGroupModal() {
        AppState.groupModal.show();
        await this.loadGroupsForModal();
    },

    async loadGroupsForModal() {
        const listContainer = document.getElementById('group-list');
        const loadingDiv = document.getElementById('group-loading');
        const emptyDiv = document.getElementById('group-empty');

        loadingDiv.style.display = 'block';
        emptyDiv.style.display = 'none';
        listContainer.innerHTML = '';

        try {
            // Determinar si hay un requester seleccionado (Centro de Cómputo creando por otro usuario)
            const selectedRequesterId = RequesterSelection.selectedRequester?.id;
            let deptId;

            if (selectedRequesterId) {
                // Obtener departamento del requester seleccionado
                const deptResponse = await fetch(`/api/core/v1/users/${selectedRequesterId}/department`);
                if (!deptResponse.ok) {
                    throw new Error('No se pudo obtener el departamento del usuario seleccionado');
                }
                const deptData = await deptResponse.json();
                if (!deptData.success || !deptData.data) {
                    throw new Error('No se pudo obtener el departamento del usuario seleccionado');
                }
                deptId = deptData.data.id;
            } else {
                // Obtener departamento del usuario actual
                const userResponse = await fetch('/api/core/v1/users/me/department');
                const userData = await userResponse.json();
                if (!userData.success || !userData.data) {
                    throw new Error('No se pudo obtener el departamento');
                }
                deptId = userData.data.id;
            }

            // Obtener grupos del departamento
            const response = await fetch(`/api/help-desk/v1/inventory/groups/department/${deptId}`);
            if (!response.ok) throw new Error('Error al cargar grupos');
            const result = await response.json();
            AppState.equipment.groups = result.data || [];
            AppState.equipment.filteredGroups = [...AppState.equipment.groups];

            loadingDiv.style.display = 'none';

            if (AppState.equipment.groups.length === 0) {
                emptyDiv.style.display = 'block';
            } else {
                this.renderGroupList();
            }

        } catch (error) {
            console.error('❌ Error cargando grupos:', error);
            loadingDiv.style.display = 'none';
            emptyDiv.style.display = 'block';
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar grupos: ${errorMessage}`, 'error');
        }
    },

    renderGroupList() {
        const listContainer = document.getElementById('group-list');
        listContainer.innerHTML = '';

        if (AppState.equipment.filteredGroups.length === 0) {
            listContainer.innerHTML = `
                <div class="text-center py-4">
                    <i class="fas fa-search fa-2x text-muted mb-2"></i>
                    <p class="text-muted">No se encontraron grupos con ese criterio</p>
                </div>
            `;
            return;
        }

        AppState.equipment.filteredGroups.forEach(group => {
            const card = this.createGroupCard(group);
            listContainer.appendChild(card);
        });
    },

    createGroupCard(group) {
        const card = document.createElement('div');
        card.className = 'group-card equipment-card';
        if (AppState.equipment.selectedGroup?.id === group.id) {
            card.classList.add('selected');
        }

        const groupTypeIcons = {
            'CLASSROOM': 'fa-chalkboard-teacher',
            'LABORATORY': 'fa-flask',
            'OFFICE': 'fa-briefcase',
            'MEETING_ROOM': 'fa-users',
            'WORKSHOP': 'fa-tools',
            'OTHER': 'fa-door-open'
        };

        const icon = groupTypeIcons[group.group_type] || 'fa-door-open';

        card.innerHTML = `
            <div class="d-flex align-items-start">
                <div class="equipment-icon me-3">
                    <i class="fas ${icon}"></i>
                </div>
                <div class="flex-grow-1">
                    <div class="fw-bold text-info">${group.name}</div>
                    <div class="text-dark">${group.description || 'Sin descripción'}</div>
                    <small class="text-muted">
                        <i class="fas fa-laptop me-1"></i>${group.total_assigned} equipos
                    </small>
                    <div class="mt-2">
                        ${group.building ? `<span class="badge bg-light text-dark"><i class="fas fa-building me-1"></i>${group.building}</span>` : ''}
                        ${group.floor ? `<span class="badge bg-light text-dark"><i class="fas fa-layer-group me-1"></i>Piso ${group.floor}</span>` : ''}
                    </div>
                </div>
            </div>
        `;

        card.addEventListener('click', () => {
            this.selectGroupInModal(group);
        });

        return card;
    },

    selectGroupInModal(group) {
        AppState.equipment.selectedGroup = group;

        // Actualizar UI del modal
        document.querySelectorAll('.group-card').forEach(card => {
            card.classList.remove('selected');
        });
        event.currentTarget.classList.add('selected');

        // Habilitar botón de confirmar
        document.getElementById('confirm-group-btn').disabled = false;
    },

    confirmGroupSelection() {
        if (!AppState.equipment.selectedGroup) return;

        // Cerrar modal de grupos
        AppState.groupModal.hide();

        // Mostrar preview del grupo
        this.showGroupPreview(AppState.equipment.selectedGroup);

        // Abrir modal de equipos del grupo
        setTimeout(() => {
            this.openGroupEquipmentModal();
        }, 300);
    },

    showGroupPreview(group) {
        const preview = document.getElementById('selected-group-preview');
        const name = document.getElementById('preview-group-name');
        const info = document.getElementById('preview-group-info');
        const location = document.getElementById('preview-group-location');

        name.textContent = group.name;
        info.textContent = `${group.total_assigned} equipos disponibles`;
        location.textContent = [group.building, group.floor ? `Piso ${group.floor}` : ''].filter(Boolean).join(' - ') || 'Sin ubicación';

        preview.style.display = 'block';

        // Guardar ID en input oculto
        document.getElementById('selected_group_id').value = group.id;
    },

    clearGroupSelection() {
        AppState.equipment.selectedGroup = null;
        AppState.equipment.selectedGroupEquipment = [];
        document.getElementById('selected-group-preview').style.display = 'none';
        document.getElementById('selected-group-equipment-preview').style.display = 'none';
        document.getElementById('selected_group_id').value = '';
        document.getElementById('inventory_item_ids').value = '';
        document.getElementById('group-button-text').textContent = 'Seleccionar Salón/Grupo';
    },

    // ==================== MODAL DE EQUIPOS DE GRUPO ====================
    async openGroupEquipmentModal() {
        if (!AppState.equipment.selectedGroup) return;

        AppState.groupEquipmentModal.show();

        // Actualizar título
        document.getElementById('group-equipment-modal-title').textContent =
            `Equipos de: ${AppState.equipment.selectedGroup.name}`;

        await this.loadGroupEquipmentForModal();
    },

    async loadGroupEquipmentForModal() {
        const listContainer = document.getElementById('group-equipment-list-modal');
        const loadingDiv = document.getElementById('group-equipment-loading');
        const emptyDiv = document.getElementById('group-equipment-empty');

        loadingDiv.style.display = 'block';
        emptyDiv.style.display = 'none';
        listContainer.innerHTML = '';

        try {
            const groupId = AppState.equipment.selectedGroup.id;
            const response = await fetch(`/api/help-desk/v1/inventory/groups/${groupId}/items`);

            if (!response.ok) throw new Error('Error al cargar equipos');

            const result = await response.json();
            AppState.equipment.groupEquipment = result.data || [];

            loadingDiv.style.display = 'none';

            if (AppState.equipment.groupEquipment.length === 0) {
                emptyDiv.style.display = 'block';
            } else {
                this.renderGroupEquipmentList();
            }

        } catch (error) {
            console.error('❌ Error cargando equipos del grupo:', error);
            loadingDiv.style.display = 'none';
            emptyDiv.style.display = 'block';
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar equipos del grupo: ${errorMessage}`, 'error');
        }
    },

    renderGroupEquipmentList() {
        const listContainer = document.getElementById('group-equipment-list-modal');
        listContainer.innerHTML = '';

        AppState.equipment.groupEquipment.forEach(item => {
            const card = this.createGroupEquipmentCard(item);
            listContainer.appendChild(card);
        });

        this.updateGroupEquipmentSelectionCount();
    },

    createGroupEquipmentCard(item) {
        const card = document.createElement('div');
        card.className = 'equipment-card group-equipment-item';
        card.dataset.itemId = item.id;

        const isSelected = AppState.equipment.selectedGroupEquipment.includes(item.id);
        if (isSelected) {
            card.classList.add('selected');
        }

        const icon = this.getEquipmentIcon(item.category?.icon || 'fa-laptop');

        card.innerHTML = `
            <div class="d-flex align-items-start">
                <div class="form-check me-3 mt-1">
                    <input class="form-check-input" type="checkbox" ${isSelected ? 'checked' : ''}>
                </div>
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
                        ${item.location_detail ? `<span class="badge bg-light text-dark"><i class="fas fa-map-marker-alt me-1"></i>${item.location_detail}</span>` : ''}
                        ${this.getStatusBadge(item.status)}
                    </div>
                </div>
            </div>
        `;

        card.addEventListener('click', () => {
            this.toggleGroupEquipmentSelection(item.id);
        });

        return card;
    },

    toggleGroupEquipmentSelection(itemId) {
        const index = AppState.equipment.selectedGroupEquipment.indexOf(itemId);

        if (index > -1) {
            // Deseleccionar
            AppState.equipment.selectedGroupEquipment.splice(index, 1);
        } else {
            // Seleccionar
            AppState.equipment.selectedGroupEquipment.push(itemId);
        }

        // Actualizar UI
        const card = document.querySelector(`.group-equipment-item[data-item-id="${itemId}"]`);
        const checkbox = card.querySelector('input[type="checkbox"]');

        if (index > -1) {
            card.classList.remove('selected');
            checkbox.checked = false;
        } else {
            card.classList.add('selected');
            checkbox.checked = true;
        }

        this.updateGroupEquipmentSelectionCount();
    },

    selectAllGroupEquipment() {
        AppState.equipment.selectedGroupEquipment = AppState.equipment.groupEquipment.map(item => item.id);

        document.querySelectorAll('.group-equipment-item').forEach(card => {
            card.classList.add('selected');
            card.querySelector('input[type="checkbox"]').checked = true;
        });

        this.updateGroupEquipmentSelectionCount();
    },

    clearAllGroupEquipment() {
        AppState.equipment.selectedGroupEquipment = [];

        document.querySelectorAll('.group-equipment-item').forEach(card => {
            card.classList.remove('selected');
            card.querySelector('input[type="checkbox"]').checked = false;
        });

        this.updateGroupEquipmentSelectionCount();
    },

    updateGroupEquipmentSelectionCount() {
        const count = AppState.equipment.selectedGroupEquipment.length;
        document.getElementById('group-equipment-selected-count').textContent = count;
        document.getElementById('confirm-group-equipment-btn').disabled = count === 0;
    },

    confirmGroupEquipmentSelection() {
        if (AppState.equipment.selectedGroupEquipment.length === 0) return;

        // Cerrar modal
        AppState.groupEquipmentModal.hide();

        // Mostrar preview de equipos seleccionados
        this.showGroupEquipmentPreview();

        // Guardar IDs en input oculto (como JSON string)
        document.getElementById('inventory_item_ids').value = JSON.stringify(AppState.equipment.selectedGroupEquipment);

        HelpdeskUtils.showToast(`${AppState.equipment.selectedGroupEquipment.length} equipos seleccionados`, 'success');
    },

    showGroupEquipmentPreview() {
        const preview = document.getElementById('selected-group-equipment-preview');
        const listDiv = document.getElementById('group-equipment-list');
        const countSpan = document.getElementById('group-equipment-count');

        countSpan.textContent = AppState.equipment.selectedGroupEquipment.length;

        // Crear badges de equipos seleccionados
        listDiv.innerHTML = '';
        AppState.equipment.selectedGroupEquipment.forEach(itemId => {
            const item = AppState.equipment.groupEquipment.find(eq => eq.id === itemId);
            if (item) {
                const badge = document.createElement('span');
                badge.className = 'badge bg-success me-2 mb-2';
                badge.innerHTML = `
                    <i class="fas fa-laptop me-1"></i>
                    ${item.inventory_number}
                `;
                listDiv.appendChild(badge);
            }
        });

        preview.style.display = 'block';
    },

    filterGroups(searchTerm) {
        const term = searchTerm.toLowerCase().trim();

        if (!term) {
            AppState.equipment.filteredGroups = [...AppState.equipment.groups];
        } else {
            AppState.equipment.filteredGroups = AppState.equipment.groups.filter(group => {
                return (
                    group.name.toLowerCase().includes(term) ||
                    (group.code && group.code.toLowerCase().includes(term)) ||
                    (group.description && group.description.toLowerCase().includes(term))
                );
            });
        }

        this.renderGroupList();
    },

    // ==================== MODAL DE EQUIPOS INDIVIDUAL (ya existente) ====================
    async openEquipmentModal() {
        if (!AppState.equipment.ownerType || AppState.equipment.ownerType === 'group') {
            HelpdeskUtils.showToast('Por favor selecciona primero el tipo de propietario', 'warning');
            return;
        }

        AppState.modal.show();
        await this.loadEquipmentForModal();
    },

    async loadEquipmentForModal() {
        const listContainer = document.getElementById('equipment-list');
        const loadingDiv = document.getElementById('equipment-loading');
        const emptyDiv = document.getElementById('equipment-empty');

        loadingDiv.style.display = 'block';
        emptyDiv.style.display = 'none';
        listContainer.innerHTML = '';

        try {
            let endpoint;

            // Determinar si hay un requester seleccionado (Centro de Cómputo creando por otro usuario)
            const selectedRequesterId = RequesterSelection.selectedRequester?.id;

            if (AppState.equipment.ownerType === 'mine') {
                // "Es mio" - equipos del usuario
                if (selectedRequesterId) {
                    // Si hay requester seleccionado, obtener equipos de ese usuario
                    endpoint = `/api/help-desk/v1/inventory/items/user/${selectedRequesterId}/equipment`;
                } else {
                    // Si no, obtener equipos del usuario actual
                    endpoint = '/api/help-desk/v1/inventory/items/my-equipment';
                }
            } else {
                // "Es de alguien más" - equipos del departamento
                let deptId;

                if (selectedRequesterId) {
                    // Obtener departamento del requester seleccionado
                    const deptResponse = await fetch(`/api/core/v1/users/${selectedRequesterId}/department`);
                    if (!deptResponse.ok) {
                        throw new Error('No se pudo obtener el departamento del usuario seleccionado');
                    }
                    const deptData = await deptResponse.json();
                    deptId = deptData.data.id;
                } else {
                    // Obtener departamento del usuario actual
                    const userResponse = await fetch('/api/core/v1/users/me/department');
                    const userData = await userResponse.json();
                    deptId = userData.data.id;
                }

                endpoint = `/api/help-desk/v1/inventory/items?department_id=${deptId}`;
            }

            const response = await fetch(endpoint);
            if (!response.ok) throw new Error('Error al cargar equipos');

            const result = await response.json();
            AppState.equipment.available = result.data || [];
            AppState.equipment.filtered = [...AppState.equipment.available];

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
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(`Error al cargar equipos: ${errorMessage}`, 'error');
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

        const icon = this.getEquipmentIcon(item.category?.icon || 'fa-laptop');

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

        card.addEventListener('click', () => {
            this.selectEquipmentInModal(item);
        });

        return card;
    },

    getEquipmentIcon(iconClass) {
        if (iconClass) return iconClass;
        return 'fas fa-laptop';
    },

    getStatusBadge(status) {
        const statusMap = {
            'ACTIVE': { class: 'success', text: 'Activo' },
            'MAINTENANCE': { class: 'warning', text: 'Mantenimiento' },
            'DAMAGED': { class: 'danger', text: 'Dañado' },
            'RETIRED': { class: 'secondary', text: 'Retirado' },
            'LOST': { class: 'dark', text: 'Extraviado' },
            'PENDING_ASSIGNMENT': { class: 'info', text: 'Pendiente' }
        };
        const config = statusMap[status] || { class: 'secondary', text: status };
        return `<span class="badge bg-${config.class}">${config.text}</span>`;
    },

    selectEquipmentInModal(item) {
        AppState.equipment.selected = item;

        document.querySelectorAll('.equipment-card').forEach(card => {
            card.classList.remove('selected');
        });
        event.currentTarget.classList.add('selected');

        document.getElementById('confirm-equipment-btn').disabled = false;
    },

    confirmEquipmentSelection() {
        if (!AppState.equipment.selected) return;

        AppState.modal.hide();
        this.showEquipmentPreview(AppState.equipment.selected);

        // Guardar ID como array de un solo elemento
        document.getElementById('inventory_item_ids').value = JSON.stringify([AppState.equipment.selected.id]);

        HelpdeskUtils.showToast('Equipo seleccionado correctamente', 'success');
    },

    showEquipmentPreview(item) {
        const preview = document.getElementById('selected-equipment-preview');
        const icon = document.getElementById('preview-equipment-icon');
        const number = document.getElementById('preview-equipment-number');
        const info = document.getElementById('preview-equipment-info');
        const owner = document.getElementById('preview-equipment-owner');
        const location = document.getElementById('preview-equipment-location');

        icon.innerHTML = `<i class="${this.getEquipmentIcon(item.category?.icon)} fa-2x text-success"></i>`;
        number.textContent = item.inventory_number;
        info.textContent = `${item.brand || 'N/A'} ${item.model || ''}`.trim();

        if (item.assigned_to_user) {
            owner.innerHTML = `<i class="fas fa-user me-1"></i>${item.assigned_to_user.full_name}`;
        } else {
            owner.innerHTML = `<i class="fas fa-building me-1"></i>Global del Departamento`;
        }

        location.textContent = item.location_detail || item.department?.name || 'Sin ubicación';

        preview.style.display = 'block';
        document.getElementById('equipment-button-text').textContent = 'Cambiar Equipo';
    },

    clearSelection() {
        AppState.equipment.selected = null;
        AppState.equipment.selectedGroupEquipment = [];
        document.getElementById('selected-equipment-preview').style.display = 'none';
        document.getElementById('selected-group-equipment-preview').style.display = 'none';
        document.getElementById('inventory_item_ids').value = '';

        const buttonText = document.getElementById('equipment-button-text');
        if (buttonText) {
            buttonText.textContent = AppState.equipment.ownerType === 'mine'
                ? 'Seleccionar de Mis Equipos'
                : 'Seleccionar de Equipos del Departamento';
        }
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

        // Incluir requester_id si se seleccionó
        const requesterIdInput = document.getElementById('requester_id');
        if (requesterIdInput && requesterIdInput.value) {
            data.requester_id = parseInt(requesterIdInput.value);
        }

        // Para DESARROLLO: incluir category_id
        if (data.area === 'DESARROLLO') {
            data.category_id = parseInt(document.getElementById('category_id').value);
        }

        // Para SOPORTE: incluir inventory_item_ids si se seleccionaron
        if (data.area === 'SOPORTE') {
            const inventoryItemIds = document.getElementById('inventory_item_ids').value;
            if (inventoryItemIds) {
                try {
                    data.inventory_item_ids = JSON.parse(inventoryItemIds);
                } catch {
                    data.inventory_item_ids = [];
                }
            }

            // Para SOPORTE aún necesitamos una categoría (puede ser genérica)
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
                const response = await fetch('/api/help-desk/v1/tickets/', {
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
            const errorMessage = error.message || 'Error desconocido';
            HelpdeskUtils.showToast(
                `Error al crear el ticket: ${errorMessage}`,
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

            <div class="row g-3">`;

        // Mostrar requester si es diferente del usuario actual
        if (RequesterSelection.selectedRequester) {
            summary += `
                <div class="col-12">
                    <div class="alert alert-info">
                        <strong><i class="fas fa-user-circle me-2"></i>Solicitante:</strong><br>
                        ${RequesterSelection.selectedRequester.full_name} (${RequesterSelection.selectedRequester.username})
                        <br>
                        <small>Este ticket aparecerá en la sección "Mis Tickets" del usuario seleccionado</small>
                    </div>
                </div>
            `;
        }

        summary += `
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
    photo: PhotoUpload,
    requester: RequesterSelection
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

