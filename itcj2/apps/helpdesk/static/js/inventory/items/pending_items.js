/**
 * Equipos Pendientes de Asignación
 * Gestión de equipos en "limbo" del Centro de Cómputo
 */

(function () {
    'use strict';

    // ==================== ESTADO DEL MÓDULO ====================
    let pendingItems = [];
    let allCategories = [];
    let allDepartments = [];
    let selectedItems = new Set();
    let currentFilters = {};

    // Handler refs para cleanup
    let _searchHandler = null;
    let _categoryHandler = null;
    let _sortHandler = null;
    let _selectAllHandler = null;

    // ==================== INIT / DESTROY ====================
    function init() {
        loadCategories();
        loadDepartments();
        loadPendingItems();

        _searchHandler = debounce(applyFilters, 500);
        _categoryHandler = applyFilters;
        _sortHandler = applyFilters;
        _selectAllHandler = function (e) {
            if (e.target.checked) selectAll();
            else deselectAll();
        };

        document.getElementById('search-input').addEventListener('input', _searchHandler);
        document.getElementById('category-filter').addEventListener('change', _categoryHandler);
        document.getElementById('sort-filter').addEventListener('change', _sortHandler);
        document.getElementById('select-all-checkbox').addEventListener('change', _selectAllHandler);

        document.getElementById('assign-form').addEventListener('submit', handleAssign);
        document.getElementById('bulk-assign-form').addEventListener('submit', handleBulkAssign);

        window.openBulkAssignModal = openBulkAssignModal;
        window.selectAll = selectAll;
        window.deselectAll = deselectAll;
        window.openAssignModal = openAssignModal;
        window.toggleItemSelection = toggleItemSelection;
    }

    function destroy() {
        const searchEl = document.getElementById('search-input');
        const categoryEl = document.getElementById('category-filter');
        const sortEl = document.getElementById('sort-filter');
        const selectAllEl = document.getElementById('select-all-checkbox');

        if (searchEl && _searchHandler) searchEl.removeEventListener('input', _searchHandler);
        if (categoryEl && _categoryHandler) categoryEl.removeEventListener('change', _categoryHandler);
        if (sortEl && _sortHandler) sortEl.removeEventListener('change', _sortHandler);
        if (selectAllEl && _selectAllHandler) selectAllEl.removeEventListener('change', _selectAllHandler);

        try { $('#assignModal').modal('dispose'); } catch (_) {}
        try { $('#bulkAssignModal').modal('dispose'); } catch (_) {}

        delete window.openBulkAssignModal;
        delete window.selectAll;
        delete window.deselectAll;
        delete window.openAssignModal;
        delete window.toggleItemSelection;

        pendingItems = [];
        selectedItems = new Set();
        allCategories = [];
        allDepartments = [];
        currentFilters = {};
        _searchHandler = null;
        _categoryHandler = null;
        _sortHandler = null;
        _selectAllHandler = null;
    }

    // ==================== CARGAR DATOS ====================
    async function loadPendingItems() {
        showLoading();

        try {
            const params = new URLSearchParams(currentFilters);
            const qs = params.toString();
            const url = qs
                ? `/api/help-desk/v2/inventory/pending?${qs}`
                : '/api/help-desk/v2/inventory/pending';

            const response = await fetch(url, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Error al cargar equipos pendientes');
            }

            const result = await response.json();
            pendingItems = result.data || [];

            renderTable();
            updateStatistics();
            hideLoading();
        } catch (error) {
            console.error('Error:', error);
            showError(`No se pudieron cargar los equipos pendientes: ${error.message || 'Error desconocido'}`);
            hideLoading();
        }
    }

    async function loadCategories() {
        try {
            const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Error al cargar categorías');
            }

            const result = await response.json();
            allCategories = result.data;

            const select = document.getElementById('category-filter');
            select.innerHTML = '<option value="">Todas las categorías</option>';
            allCategories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.id;
                option.textContent = cat.name;
                select.appendChild(option);
            });
        } catch (error) {
            console.error('Error cargando categorías:', error);
            showError(`No se pudieron cargar las categorías: ${error.message || 'Error desconocido'}`);
        }
    }

    async function loadDepartments() {
        try {
            const response = await fetch('/api/core/v2/departments?active=true', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Error al cargar departamentos');
            }

            const result = await response.json();
            allDepartments = result.data;

            ['assign-department', 'bulk-department'].forEach(selectId => {
                const select = document.getElementById(selectId);
                select.innerHTML = '<option value="">Seleccionar departamento...</option>';
                allDepartments.forEach(dept => {
                    const option = document.createElement('option');
                    option.value = dept.id;
                    option.textContent = dept.name;
                    select.appendChild(option);
                });
            });
        } catch (error) {
            console.error('Error cargando departamentos:', error);
            showError(`No se pudieron cargar los departamentos: ${error.message || 'Error desconocido'}`);
        }
    }

    // ==================== RENDERIZADO ====================
    function renderTable() {
        const tbody = document.querySelector('#pending-table tbody');

        if (pendingItems.length === 0) {
            document.getElementById('table-container').style.display = 'none';
            document.getElementById('empty-state').style.display = 'block';
            return;
        }

        document.getElementById('table-container').style.display = 'block';
        document.getElementById('empty-state').style.display = 'none';

        let sortedItems = [...pendingItems];
        const sortType = document.getElementById('sort-filter').value;

        if (sortType === 'newest') {
            sortedItems.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        } else if (sortType === 'oldest') {
            sortedItems.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        } else if (sortType === 'category') {
            sortedItems.sort((a, b) => {
                const catA = allCategories.find(c => c.id === a.category_id)?.name || '';
                const catB = allCategories.find(c => c.id === b.category_id)?.name || '';
                return catA.localeCompare(catB);
            });
        }

        tbody.innerHTML = sortedItems.map(item => {
            const category = allCategories.find(c => c.id === item.category_id);
            const isSelected = selectedItems.has(item.id);

            return `
                <tr class="pending-item ${isSelected ? 'selected' : ''}" data-item-id="${item.id}">
                    <td>
                        <input
                            type="checkbox"
                            class="form-check-input item-checkbox"
                            data-item-id="${item.id}"
                            ${isSelected ? 'checked' : ''}
                            onchange="toggleItemSelection(${item.id})"
                        >
                    </td>
                    <td>
                        <span class="font-weight-bold">${item.inventory_number}</span>
                        <br>
                        <span class="badge bg-warning text-dark limbo-badge">
                            <i class="fas fa-hourglass-half"></i> Limbo
                        </span>
                    </td>
                    <td>
                        <i class="${category?.icon || 'fas fa-box'} mr-1"></i>
                        ${category?.name || 'N/A'}
                    </td>
                    <td>
                        <div class="font-weight-bold">${item.brand || 'N/A'}</div>
                        <small class="text-muted">${item.model || ''}</small>
                    </td>
                    <td>
                        <small>${item.supplier_serial || item.itcj_serial || 'N/A'}</small>
                    </td>
                    <td>
                        <small>${formatDate(item.created_at)}</small>
                        <br>
                        <small class="text-muted">${formatTimeAgo(item.created_at)}</small>
                    </td>
                    <td>
                        <small>${item.registered_by?.full_name || 'N/A'}</small>
                    </td>
                    <td class="text-center">
                        <div class="btn-group btn-group-sm">
                            <button
                                class="btn btn-sm btn-success quick-assign-btn"
                                onclick="openAssignModal(${item.id})"
                                title="Asignar a departamento"
                            >
                                <i class="fas fa-building"></i>
                            </button>
                            <a
                                href="/help-desk/inventory/items/${item.id}"
                                class="btn btn-sm btn-outline-primary"
                                title="Ver detalle"
                            >
                                <i class="fas fa-eye"></i>
                            </a>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    function updateStatistics() {
        document.getElementById('pending-count').textContent = pendingItems.length;
        document.getElementById('stat-total').textContent = pendingItems.length;
        document.getElementById('stat-selected').textContent = selectedItems.size;

        const uniqueCategories = new Set(pendingItems.map(item => item.category_id));
        document.getElementById('stat-categories').textContent = uniqueCategories.size;
        document.getElementById('stat-assigned-today').textContent = '0';

        const assignBtn = document.getElementById('assign-selected-btn');
        assignBtn.disabled = selectedItems.size === 0;
        assignBtn.innerHTML = selectedItems.size > 0
            ? `<i class="fas fa-users"></i> Asignar ${selectedItems.size} Seleccionados`
            : '<i class="fas fa-users"></i> Asignar Seleccionados';
    }

    // ==================== FILTROS ====================
    function applyFilters() {
        const search = document.getElementById('search-input').value.trim();
        const categoryId = document.getElementById('category-filter').value;
        currentFilters = {};
        if (search) currentFilters.search = search;
        if (categoryId) currentFilters.category_id = categoryId;
        loadPendingItems();
    }

    // ==================== SELECCIÓN ====================
    function toggleItemSelection(itemId) {
        if (selectedItems.has(itemId)) selectedItems.delete(itemId);
        else selectedItems.add(itemId);
        updateStatistics();
        renderTable();
    }

    function selectAll() {
        pendingItems.forEach(item => selectedItems.add(item.id));
        document.querySelectorAll('.item-checkbox').forEach(cb => cb.checked = true);
        updateStatistics();
        renderTable();
    }

    function deselectAll() {
        selectedItems.clear();
        document.querySelectorAll('.item-checkbox').forEach(cb => cb.checked = false);
        const selectAllCb = document.getElementById('select-all-checkbox');
        if (selectAllCb) selectAllCb.checked = false;
        updateStatistics();
        renderTable();
    }

    // ==================== ASIGNACIÓN INDIVIDUAL ====================
    function openAssignModal(itemId) {
        const item = pendingItems.find(i => i.id === itemId);
        if (!item) return;

        document.getElementById('assign-item-id').value = itemId;
        document.getElementById('assign-item-number').textContent = item.inventory_number;
        document.getElementById('assign-department').value = '';
        document.getElementById('assign-notes').value = '';

        $('#assignModal').modal('show');
    }

    async function handleAssign(e) {
        e.preventDefault();

        const submitBtn = e.target.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Asignando...';

        try {
            const itemId = document.getElementById('assign-item-id').value;
            const departmentId = document.getElementById('assign-department').value;
            const notes = document.getElementById('assign-notes').value.trim();

            if (!departmentId) throw new Error('Selecciona un departamento');

            const response = await fetch('/api/help-desk/v2/inventory/pending/assign-to-department', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_ids: [parseInt(itemId)],
                    department_id: parseInt(departmentId),
                    notes: notes || null
                })
            });

            if (!response.ok) {
                let errData = {};
                try { errData = await response.json(); } catch (_) {}
                const d = errData.detail || errData;
                const msg = (typeof d === 'string') ? d : (d.error || d.message || 'Error al asignar equipo');
                throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            }

            $('#assignModal').modal('hide');
            showSuccess('Equipo asignado exitosamente');
            selectedItems.delete(parseInt(itemId));
            loadPendingItems();
        } catch (error) {
            console.error('Error:', error);
            showError(`Error al asignar equipo: ${error.message || 'Error desconocido'}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-check"></i> Asignar';
        }
    }

    // ==================== ASIGNACIÓN MASIVA ====================
    function openBulkAssignModal() {
        if (selectedItems.size === 0) { showError('Selecciona al menos un equipo'); return; }

        document.getElementById('bulk-count').textContent = selectedItems.size;
        document.getElementById('bulk-department').value = '';
        document.getElementById('bulk-notes').value = '';

        const preview = document.getElementById('bulk-items-preview');
        const selectedItemsData = pendingItems.filter(item => selectedItems.has(item.id));
        preview.innerHTML = selectedItemsData.map(item => {
            const category = allCategories.find(c => c.id === item.category_id);
            return `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div>
                        <strong>${item.inventory_number}</strong> -
                        ${item.brand || 'N/A'} ${item.model || ''}
                    </div>
                    <span class="badge bg-primary text-white">
                        ${category?.name || 'N/A'}
                    </span>
                </div>
            `;
        }).join('');

        $('#bulkAssignModal').modal('show');
    }

    async function handleBulkAssign(e) {
        e.preventDefault();

        const submitBtn = e.target.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Asignando...';

        try {
            const departmentId = document.getElementById('bulk-department').value;
            const notes = document.getElementById('bulk-notes').value.trim();

            if (!departmentId) throw new Error('Selecciona un departamento');

            const itemIds = Array.from(selectedItems);

            const response = await fetch('/api/help-desk/v2/inventory/pending/assign-to-department', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_ids: itemIds,
                    department_id: parseInt(departmentId),
                    notes: notes || null
                })
            });

            if (!response.ok) {
                let errData = {};
                try { errData = await response.json(); } catch (_) {}
                const d = errData.detail || errData;
                const msg = (typeof d === 'string') ? d : (d.error || d.message || 'Error al asignar equipos');
                throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            }

            const result = await response.json();

            $('#bulkAssignModal').modal('hide');
            showSuccess(result.message || `${result.items?.length || 0} equipo(s) asignado(s) exitosamente`);
            selectedItems.clear();
            loadPendingItems();
        } catch (error) {
            console.error('Error:', error);
            showError(`Error al asignar equipos: ${error.message || 'Error desconocido'}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-check"></i> Asignar Todo';
        }
    }

    // ==================== HELPERS ====================
    function formatDate(dateString) {
        if (!dateString) return 'N/A';
        return new Date(dateString).toLocaleDateString('es-MX', {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function formatTimeAgo(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'Hace un momento';
        if (diffMins < 60) return `Hace ${diffMins} min`;
        if (diffHours < 24) return `Hace ${diffHours}h`;
        if (diffDays === 1) return 'Ayer';
        if (diffDays < 7) return `Hace ${diffDays} días`;
        if (diffDays < 30) return `Hace ${Math.floor(diffDays / 7)} semanas`;
        return formatDate(dateString);
    }

    function showLoading() {
        document.getElementById('loading-container').style.display = 'block';
        document.getElementById('table-container').style.display = 'none';
        document.getElementById('empty-state').style.display = 'none';
    }

    function hideLoading() {
        document.getElementById('loading-container').style.display = 'none';
    }

    function showSuccess(message) { showToast(message, 'success'); }
    function showError(message) { showToast(message, 'error'); }

    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    window.HelpdeskPage.page('inventory_items_pending_items', { init, destroy });

})();
