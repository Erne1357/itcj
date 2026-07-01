/**
 * Detalle de Grupo de Equipos (isla de cliente).
 * Migrado a BS5 (modales con bootstrap.Modal, sin jQuery) y a clases d-none en
 * lugar de style.display inline. Sigue siendo render de cliente (isla §4.3): la
 * tabla de equipos y las capacidades se pintan con fetch → innerHTML.
 */

(function () {
    'use strict';

    // === MODULE STATE ===
    let GROUP_ID = null;
    let currentGroup = null;
    let groupEquipment = [];
    let availableEquipment = [];
    let allCategories = [];

    // === LISTENER TEARDOWN REFS ===
    let _searchHandler = null;
    let _categoryFilterHandler = null;
    let _statusFilterHandler = null;
    let _selectAllHandler = null;
    let _selectAllAvailableHandler = null;
    let _deleteRedirectHandle = null;

    // === HELPERS ===
    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function show(id) { document.getElementById(id)?.classList.remove('d-none'); }
    function hide(id) { document.getElementById(id)?.classList.add('d-none'); }

    function getAddEquipmentModal() {
        return bootstrap.Modal.getOrCreateInstance(document.getElementById('addEquipmentModal'));
    }

    function goToGroups(delayMs) {
        const go = () => {
            if (window.HelpdeskPage && typeof window.HelpdeskPage.navigate === 'function') {
                window.HelpdeskPage.navigate('/help-desk/inventory/groups');
            } else {
                window.location.href = '/help-desk/inventory/groups';
            }
        };
        if (delayMs) {
            _deleteRedirectHandle = setTimeout(go, delayMs);
        } else {
            go();
        }
    }

    // ==================== CARGAR DATOS ====================
    async function loadGroupDetail() {
        showLoading();

        try {
            const response = await fetch(`/api/help-desk/v2/inventory/groups/${GROUP_ID}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                if (response.status === 404) {
                    showError('Grupo no encontrado');
                    goToGroups(2000);
                    return;
                }
                throw new Error('Error al cargar grupo');
            }

            const result = await response.json();
            currentGroup = result.data;

            renderGroupHeader();
            renderStatistics();
            renderCapacities();
            loadGroupEquipment();

        } catch (error) {
            console.error('Error:', error);
            showError(`No se pudo cargar el grupo: ${error.message || 'Error desconocido'}`);
        }
    }

    async function loadCategories() {
        try {
            const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) throw new Error('Error al cargar categorías');

            const result = await response.json();
            allCategories = result.data;

            // Llenar filtros
            const filters = ['equipment-category-filter', 'available-category-filter'];
            filters.forEach(filterId => {
                const select = document.getElementById(filterId);
                if (!select) return;
                select.innerHTML = '<option value="">Todas las categorías</option>';
                allCategories.forEach(cat => {
                    const option = document.createElement('option');
                    option.value = cat.id;
                    option.textContent = cat.name;
                    select.appendChild(option);
                });
            });

        } catch (error) {
            console.error('Error cargando categorías:', error);
        }
    }

    async function loadGroupEquipment() {
        show('equipment-loading');
        hide('equipment-table-container');
        hide('equipment-empty');

        try {
            const response = await fetch(`/api/help-desk/v2/inventory/selection/by-group/${GROUP_ID}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) throw new Error('Error al cargar equipos');

            const result = await response.json();
            groupEquipment = result.items_by_category.flatMap(cat => cat.items);

            renderGroupEquipment(groupEquipment);

        } catch (error) {
            console.error('Error:', error);
            showError(`No se pudieron cargar los equipos del grupo: ${error.message || 'Error desconocido'}`);
        } finally {
            hide('equipment-loading');
        }
    }

    async function loadAvailableEquipment() {
        if (!currentGroup) return;

        show('available-equipment-loading');
        hide('available-equipment-container');
        hide('available-equipment-empty');

        try {
            const params = new URLSearchParams({
                department_id: currentGroup.department_id,
                include_group_equipment: 'false'
            });

            const search = document.getElementById('available-search').value.trim();
            if (search) params.append('search', search);

            const categoryId = document.getElementById('available-category-filter').value;
            if (categoryId) params.append('category_id', categoryId);

            const response = await fetch(`/api/help-desk/v2/inventory/items?${params}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) throw new Error('Error al cargar equipos disponibles');

            const result = await response.json();
            availableEquipment = result.data.filter(item => !item.group_id);

            renderAvailableEquipment(availableEquipment);

        } catch (error) {
            console.error('Error:', error);
            showError(`No se pudieron cargar los equipos disponibles: ${error.message || 'Error desconocido'}`);
        } finally {
            hide('available-equipment-loading');
        }
    }

    // ==================== RENDERIZADO ====================
    function renderGroupHeader() {
        const typeInfo = getGroupTypeInfo(currentGroup.group_type);

        document.getElementById('group-icon').className = typeInfo.icon + ' me-2';
        document.getElementById('group-name').textContent = currentGroup.name;
        document.getElementById('group-description').textContent = currentGroup.description || '';
        document.getElementById('group-type-badge').textContent = typeInfo.label;
        document.getElementById('group-type-badge').className = `badge bg-${typeInfo.color} text-white me-2`;
        document.getElementById('group-department').textContent = currentGroup.department?.name || 'N/A';

        // Ubicación
        if (currentGroup.building || currentGroup.floor) {
            let locationText = '';
            if (currentGroup.building) locationText += `Edificio ${currentGroup.building}`;
            if (currentGroup.floor) locationText += ` - Piso ${currentGroup.floor}`;
            if (currentGroup.location_notes) locationText += ` (${currentGroup.location_notes})`;

            document.getElementById('location-text').textContent = locationText;
            show('location-info');
        }

        hideLoading();
    }

    function renderStatistics() {
        const capacities = currentGroup.capacities || [];
        const totalCapacity = capacities.reduce((sum, cap) => sum + (cap.max_capacity || 0), 0);
        const totalCurrent = capacities.reduce((sum, cap) => sum + (cap.current_count || 0), 0);
        const occupancy = totalCapacity > 0 ? Math.round((totalCurrent / totalCapacity) * 100) : 0;

        document.getElementById('stat-total').textContent = totalCurrent;
        document.getElementById('stat-capacity').textContent = totalCapacity;
        document.getElementById('stat-occupancy').textContent = occupancy + '%';
        document.getElementById('stat-categories').textContent = capacities.length;
    }

    function renderCapacities() {
        const container = document.getElementById('capacities-list');
        const capacities = currentGroup.capacities || [];

        if (capacities.length === 0) {
            container.innerHTML = '<p class="text-muted">No hay capacidades definidas para este grupo</p>';
            return;
        }

        container.innerHTML = capacities.map(cap => {
            const category = allCategories.find(c => c.id === cap.category_id);
            const percentage = cap.max_capacity > 0 ? Math.round((cap.current_count / cap.max_capacity) * 100) : 0;
            const progressClass = percentage <= 50 ? 'success' : percentage <= 80 ? 'warning' : 'danger';

            return `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <div>
                        <i class="${category?.icon || 'fas fa-box'} me-2"></i>
                        <strong>${category?.name || 'N/A'}</strong>
                    </div>
                    <div>
                        <span class="badge bg-${progressClass} text-white">
                            ${cap.current_count} / ${cap.max_capacity}
                        </span>
                    </div>
                </div>
                <div class="progress capacity-progress">
                    <div
                        class="progress-bar bg-${progressClass}"
                        style="width: ${percentage}%"
                        role="progressbar"
                    >
                        ${percentage}%
                    </div>
                </div>
            </div>
        `;
        }).join('');
    }

    function renderGroupEquipment(equipment) {
        const tbody = document.querySelector('#equipment-table tbody');

        if (equipment.length === 0) {
            hide('equipment-table-container');
            show('equipment-empty');
            if (tbody) tbody.innerHTML = '';
            return;
        }

        hide('equipment-empty');
        show('equipment-table-container');

        tbody.innerHTML = equipment.map(item => {
            const statusBadge = getStatusBadge(item.status);
            const category = allCategories.find(c => c.id === item.category_id);

            return `
            <tr class="equipment-item">
                ${document.getElementById('select-all-equipment') ? `
                    <td>
                        <input
                            type="checkbox"
                            class="equipment-checkbox equipment-item-checkbox"
                            data-item-id="${item.id}"
                            onchange="updateRemoveButton()"
                        >
                    </td>
                ` : ''}
                <td>
                    <a href="/help-desk/inventory/items/${item.id}" class="fw-bold">
                        ${item.inventory_number}
                    </a>
                </td>
                <td>
                    <i class="${category?.icon || 'fas fa-box'} me-1"></i>
                    <small>${category?.name || 'N/A'}</small>
                </td>
                <td>
                    <div class="fw-bold">${item.brand || 'N/A'}</div>
                    <small class="text-muted">${item.model || ''}</small>
                </td>
                <td>
                    <span class="badge bg-${statusBadge.color} text-white">
                        ${statusBadge.text}
                    </span>
                </td>
                <td>
                    <small>${item.location_detail || 'N/A'}</small>
                </td>
                <td class="text-center">
                    <div class="btn-group btn-group-sm">
                        <a href="/help-desk/inventory/items/${item.id}"
                           class="btn btn-sm btn-outline-primary"
                           title="Ver detalle">
                            <i class="fas fa-eye"></i>
                        </a>
                        ${document.getElementById('select-all-equipment') ? `
                            <button
                                class="btn btn-sm btn-outline-danger"
                                onclick="removeEquipmentFromGroup(${item.id})"
                                title="Remover del grupo">
                                <i class="fas fa-times"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
        }).join('');
    }

    function renderAvailableEquipment(equipment) {
        const tbody = document.getElementById('available-equipment-tbody');

        if (equipment.length === 0) {
            hide('available-equipment-container');
            show('available-equipment-empty');
            if (tbody) tbody.innerHTML = '';
            return;
        }

        hide('available-equipment-empty');
        show('available-equipment-container');

        tbody.innerHTML = equipment.map(item => {
            const statusBadge = getStatusBadge(item.status);
            const category = allCategories.find(c => c.id === item.category_id);

            return `
            <tr>
                <td>
                    <input
                        type="checkbox"
                        class="equipment-checkbox available-equipment-checkbox"
                        data-item-id="${item.id}"
                        onchange="updateSelectedCount()"
                    >
                </td>
                <td>${item.inventory_number}</td>
                <td>
                    <i class="${category?.icon || 'fas fa-box'} me-1"></i>
                    ${category?.name || 'N/A'}
                </td>
                <td>
                    ${item.brand || 'N/A'} ${item.model || ''}
                </td>
                <td>
                    <span class="badge bg-${statusBadge.color} text-white">
                        ${statusBadge.text}
                    </span>
                </td>
            </tr>
        `;
        }).join('');
    }

    // ==================== FILTROS ====================
    function filterGroupEquipment() {
        const search = document.getElementById('equipment-search').value.toLowerCase();
        const categoryId = document.getElementById('equipment-category-filter').value;
        const status = document.getElementById('equipment-status-filter').value;

        let filtered = [...groupEquipment];

        if (search) {
            filtered = filtered.filter(item =>
                item.inventory_number.toLowerCase().includes(search) ||
                (item.brand && item.brand.toLowerCase().includes(search)) ||
                (item.model && item.model.toLowerCase().includes(search))
            );
        }

        if (categoryId) {
            filtered = filtered.filter(item => item.category_id == categoryId);
        }

        if (status) {
            filtered = filtered.filter(item => item.status === status);
        }

        renderGroupEquipment(filtered);
    }

    // ==================== ACCIONES ====================
    function openAddEquipmentModal() {
        loadAvailableEquipment();
        getAddEquipmentModal().show();
    }

    async function addSelectedEquipment() {
        const checkboxes = document.querySelectorAll('.available-equipment-checkbox:checked');

        if (checkboxes.length === 0) {
            showError('Selecciona al menos un equipo');
            return;
        }

        const itemIds = Array.from(checkboxes).map(cb => parseInt(cb.dataset.itemId));

        try {
            const response = await fetch(`/api/help-desk/v2/inventory/groups/${GROUP_ID}/bulk-assign`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ item_ids: itemIds })
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error((error.detail && error.detail.error) || error.error || 'Error al agregar equipos');
            }

            getAddEquipmentModal().hide();
            showSuccess(`${itemIds.length} equipo(s) agregado(s) al grupo`);

            loadGroupDetail();

        } catch (error) {
            console.error('Error:', error);
            showError(`Error al agregar equipos: ${error.message || 'Error desconocido'}`);
        }
    }

    async function removeEquipmentFromGroup(itemId) {
        if (!await HelpdeskUtils.confirmDialog('Remover equipo', '¿Remover este equipo del grupo?')) return;

        try {
            const response = await fetch(`/api/help-desk/v2/inventory/groups/unassign-item/${itemId}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail?.error || error.error || 'Error al remover equipo');
            }

            showSuccess('Equipo removido del grupo');
            loadGroupDetail();

        } catch (error) {
            console.error('Error:', error);
            showError(`Error al remover equipo: ${error.message || 'Error desconocido'}`);
        }
    }

    async function removeSelectedEquipment() {
        const checkboxes = document.querySelectorAll('.equipment-item-checkbox:checked');

        if (checkboxes.length === 0) {
            showError('Selecciona al menos un equipo');
            return;
        }

        if (!await HelpdeskUtils.confirmDialog('Remover equipos', `¿Remover ${checkboxes.length} equipo(s) del grupo?`)) return;

        const itemIds = Array.from(checkboxes).map(cb => parseInt(cb.dataset.itemId));

        try {
            // Remover uno por uno
            for (const itemId of itemIds) {
                await fetch(`/api/help-desk/v2/inventory/groups/unassign-item/${itemId}`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
                });
            }

            showSuccess(`${itemIds.length} equipo(s) removido(s) del grupo`);
            loadGroupDetail();

        } catch (error) {
            console.error('Error:', error);
            showError(`Error al remover equipos: ${error.message || 'Error desconocido'}`);
        }
    }

    function updateRemoveButton() {
        const checked = document.querySelectorAll('.equipment-item-checkbox:checked').length;
        const btn = document.getElementById('remove-selected-btn');
        if (btn) {
            btn.classList.toggle('d-none', checked === 0);
            btn.textContent = `Remover ${checked} Seleccionado(s)`;
        }
    }

    function updateSelectedCount() {
        const count = document.querySelectorAll('.available-equipment-checkbox:checked').length;
        document.getElementById('selected-count').textContent = count;
    }

    function editGroup() {
        const url = `/help-desk/inventory/groups?edit=${GROUP_ID}`;
        if (window.HelpdeskPage && typeof window.HelpdeskPage.navigate === 'function') {
            window.HelpdeskPage.navigate(url);
        } else {
            window.location.href = url;
        }
    }

    async function confirmDeleteGroup() {
        if (!await HelpdeskUtils.confirmDialog('Eliminar grupo', '¿Eliminar este grupo? Los equipos NO serán eliminados, solo se removerán del grupo.')) return;

        try {
            const response = await fetch(`/api/help-desk/v2/inventory/groups/${GROUP_ID}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error((error.detail && error.detail.error) || error.error || 'Error al eliminar grupo');
            }

            showSuccess('Grupo eliminado');
            goToGroups(1500);

        } catch (error) {
            console.error('Error:', error);
            showError(`Error al eliminar grupo: ${error.message || 'Error desconocido'}`);
        }
    }

    // ==================== HELPERS ====================
    function getGroupTypeInfo(type) {
        const types = {
            'CLASSROOM': { icon: 'fas fa-chalkboard-teacher', label: 'Salón', color: 'primary' },
            'LABORATORY': { icon: 'fas fa-flask', label: 'Laboratorio', color: 'success' },
            'OFFICE': { icon: 'fas fa-briefcase', label: 'Oficina', color: 'info' },
            'MEETING_ROOM': { icon: 'fas fa-users', label: 'Sala de Reuniones', color: 'warning' },
            'WORKSHOP': { icon: 'fas fa-tools', label: 'Taller', color: 'danger' },
            'OTHER': { icon: 'fas fa-folder', label: 'Otro', color: 'secondary' }
        };
        return types[type] || types['OTHER'];
    }

    function getStatusBadge(status) {
        const badges = {
            'ACTIVE': { color: 'success', text: 'Activo' },
            'MAINTENANCE': { color: 'warning', text: 'Mantenimiento' },
            'DAMAGED': { color: 'danger', text: 'Dañado' },
            'RETIRED': { color: 'secondary', text: 'Retirado' },
            'LOST': { color: 'dark', text: 'Extraviado' },
            'PENDING_ASSIGNMENT': { color: 'warning', text: 'Pendiente' }
        };
        return badges[status] || { color: 'secondary', text: status };
    }

    function showLoading() {
        show('loading-container');
        hide('main-content');
    }

    function hideLoading() {
        hide('loading-container');
        show('main-content');
    }

    function showSuccess(message) { showToast(message, 'success'); }
    function showError(message) { showToast(message, 'error'); }

    // ==================== HTMX PAGE LIFECYCLE ====================
    window.HelpdeskPage.page('inventory_groups_group_detail', {
        init() {
            const root = document.querySelector('[data-hd-page]');

            // Read GROUP_ID from data-* attribute
            GROUP_ID = parseInt(root.dataset.groupId, 10);

            // Reset state
            currentGroup = null;
            groupEquipment = [];
            availableEquipment = [];
            allCategories = [];
            _deleteRedirectHandle = null;

            // Load data
            loadCategories();
            loadGroupDetail();

            // Event listeners — stored for teardown
            const searchEl = document.getElementById('equipment-search');
            const categoryFilterEl = document.getElementById('equipment-category-filter');
            const statusFilterEl = document.getElementById('equipment-status-filter');
            const selectAllEl = document.getElementById('select-all-equipment');
            const selectAllAvailableEl = document.getElementById('select-all-available');

            _searchHandler = debounce(filterGroupEquipment, 300);
            _categoryFilterHandler = filterGroupEquipment;
            _statusFilterHandler = filterGroupEquipment;

            searchEl.addEventListener('input', _searchHandler);
            categoryFilterEl.addEventListener('change', _categoryFilterHandler);
            statusFilterEl.addEventListener('change', _statusFilterHandler);

            if (selectAllEl) {
                _selectAllHandler = function (e) {
                    document.querySelectorAll('.equipment-item-checkbox').forEach(cb => {
                        cb.checked = e.target.checked;
                    });
                    updateRemoveButton();
                };
                selectAllEl.addEventListener('change', _selectAllHandler);
            }

            if (selectAllAvailableEl) {
                _selectAllAvailableHandler = function (e) {
                    document.querySelectorAll('.available-equipment-checkbox').forEach(cb => {
                        cb.checked = e.target.checked;
                    });
                    updateSelectedCount();
                };
                selectAllAvailableEl.addEventListener('change', _selectAllAvailableHandler);
            }

            // Expose window functions used by inline onclick
            window.editGroup = editGroup;
            window.confirmDeleteGroup = confirmDeleteGroup;
            window.openAddEquipmentModal = openAddEquipmentModal;
            window.removeSelectedEquipment = removeSelectedEquipment;
            window.addSelectedEquipment = addSelectedEquipment;
            window.loadAvailableEquipment = loadAvailableEquipment;
            window.removeEquipmentFromGroup = removeEquipmentFromGroup;
            window.updateRemoveButton = updateRemoveButton;
            window.updateSelectedCount = updateSelectedCount;
        },

        destroy() {
            // Cancel pending redirects
            if (_deleteRedirectHandle !== null) {
                clearTimeout(_deleteRedirectHandle);
                _deleteRedirectHandle = null;
            }

            const searchEl = document.getElementById('equipment-search');
            const categoryFilterEl = document.getElementById('equipment-category-filter');
            const statusFilterEl = document.getElementById('equipment-status-filter');
            const selectAllEl = document.getElementById('select-all-equipment');
            const selectAllAvailableEl = document.getElementById('select-all-available');

            if (searchEl && _searchHandler) searchEl.removeEventListener('input', _searchHandler);
            if (categoryFilterEl && _categoryFilterHandler) categoryFilterEl.removeEventListener('change', _categoryFilterHandler);
            if (statusFilterEl && _statusFilterHandler) statusFilterEl.removeEventListener('change', _statusFilterHandler);
            if (selectAllEl && _selectAllHandler) selectAllEl.removeEventListener('change', _selectAllHandler);
            if (selectAllAvailableEl && _selectAllAvailableHandler) selectAllAvailableEl.removeEventListener('change', _selectAllAvailableHandler);

            const modalEl = document.getElementById('addEquipmentModal');
            if (modalEl) {
                try { bootstrap.Modal.getInstance(modalEl)?.dispose(); } catch (_) { /* ignore */ }
            }

            // Clean up window functions
            delete window.editGroup;
            delete window.confirmDeleteGroup;
            delete window.openAddEquipmentModal;
            delete window.removeSelectedEquipment;
            delete window.addSelectedEquipment;
            delete window.loadAvailableEquipment;
            delete window.removeEquipmentFromGroup;
            delete window.updateRemoveButton;
            delete window.updateSelectedCount;

            // Reset state
            GROUP_ID = null;
            currentGroup = null;
            groupEquipment = [];
            availableEquipment = [];
            allCategories = [];

            _searchHandler = null;
            _categoryFilterHandler = null;
            _statusFilterHandler = null;
            _selectAllHandler = null;
            _selectAllAvailableHandler = null;
        }
    });
})();
