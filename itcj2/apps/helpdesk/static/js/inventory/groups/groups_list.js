/**
 * Lista de Grupos de Equipos — migrada a componentes server-side + HTMX.
 * El grid, los filtros y la paginación los rinde el servidor (ver
 * _groups_list_results.html + pages/inventory.py). Este módulo conserva SOLO la
 * lógica genuinamente de cliente: el modal Crear/Editar grupo (BS5, sin jQuery)
 * y el ancho de las barras de ocupación (data-driven).
 */

(function () {
    'use strict';

    // === MODULE STATE ===
    // Categorías: se usan para pintar el form de capacidades del modal (dinámico
    // por grupo). El resto de los datos (grupos/departamentos) los rinde el server.
    let allCategories = [];

    // === LISTENER TEARDOWN REFS ===
    let _formSubmitHandler = null;
    let _editDelegate = null;
    let _clearHandler = null;
    let _barsHandler = null;

    // === HELPERS ===
    function escapeHtml(text) {
        if (!text) return '';
        return String(text).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
    }

    function getGroupModal() {
        return bootstrap.Modal.getOrCreateInstance(document.getElementById('groupModal'));
    }

    // ==================== CARGAR DATOS ====================
    async function loadCategories() {
        try {
            const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error((err.detail && err.detail.error) || err.error || err.message || 'Error al cargar categorías');
            }
            const result = await response.json();
            allCategories = result.data || [];
        } catch (error) {
            console.error('Error cargando categorías:', error);
            showError(`No se pudieron cargar las categorías: ${error.message || 'Error desconocido'}`);
        }
    }

    // ==================== MODAL CREATE/EDIT ====================
    function openCreateGroupModal() {
        resetGroupForm();
        document.getElementById('modal-title').textContent = 'Crear Grupo';
        document.getElementById('group-id').value = '';
        renderCapacitiesForm();
        getGroupModal().show();
    }

    async function openEditGroupModal(groupId) {
        try {
            const response = await fetch(`/api/help-desk/v2/inventory/groups/${groupId}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error((err.detail && err.detail.error) || err.error || err.message || 'Error al cargar grupo');
            }

            const result = await response.json();
            const group = result.data;

            document.getElementById('modal-title').textContent = 'Editar Grupo';
            document.getElementById('group-id').value = group.id;
            document.getElementById('group-name').value = group.name || '';
            document.getElementById('group-type').value = group.group_type || '';
            document.getElementById('group-department').value = group.department_id || '';
            document.getElementById('group-description').value = group.description || '';
            document.getElementById('group-building').value = group.building || '';
            document.getElementById('group-floor').value = group.floor || '';
            document.getElementById('group-location-notes').value = group.location_notes || '';

            renderCapacitiesForm(group.capacities || []);

            getGroupModal().show();
        } catch (error) {
            console.error('Error:', error);
            showError(`No se pudo cargar el grupo: ${error.message || 'Error desconocido'}`);
        }
    }

    function resetGroupForm() {
        document.getElementById('group-form').reset();
        document.getElementById('group-id').value = '';
    }

    function renderCapacitiesForm(existingCapacities = []) {
        const container = document.getElementById('capacities-container');

        if (allCategories.length === 0) {
            container.innerHTML = '<p class="text-muted">Cargando categorías...</p>';
            return;
        }

        container.innerHTML = allCategories.map(category => {
            const existing = existingCapacities.find(c => c.category_id === category.id);
            const maxCapacity = existing?.max_capacity || '';
            const icon = escapeHtml(category.icon || 'fas fa-box');

            return `
            <div class="row g-2 align-items-center mb-2">
                <div class="col-md-6">
                    <label class="mb-0">
                        <i class="${icon} me-1"></i>
                        ${escapeHtml(category.name || '')}
                    </label>
                </div>
                <div class="col-md-4">
                    <input
                        type="number"
                        class="form-control form-control-sm"
                        name="capacity_${category.id}"
                        placeholder="Capacidad máxima"
                        min="0"
                        value="${escapeHtml(String(maxCapacity))}"
                    >
                </div>
                <div class="col-md-2">
                    ${existing ? `<small class="text-muted">Actual: ${existing.current_count}</small>` : ''}
                </div>
            </div>
        `;
        }).join('');
    }

    // ==================== SUBMIT ====================
    async function handleSubmit(e) {
        e.preventDefault();

        const submitBtn = e.target.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Guardando...';

        try {
            const formData = collectGroupFormData();

            if (!validateGroupData(formData)) {
                throw new Error('Complete todos los campos requeridos');
            }

            const groupId = document.getElementById('group-id').value;
            const isEdit = !!groupId;

            const authHeaders = {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                'Content-Type': 'application/json',
            };

            if (isEdit) {
                // Edit: primero campos básicos (incluido department_id), después capacidades.
                const { capacities, ...basic } = formData;

                const resBasic = await fetch(`/api/help-desk/v2/inventory/groups/${groupId}`, {
                    method: 'PUT',
                    headers: authHeaders,
                    body: JSON.stringify(basic),
                });
                if (!resBasic.ok) {
                    const err = await resBasic.json().catch(() => ({}));
                    throw new Error((err.detail && err.detail.error) || err.error || err.message || 'Error al actualizar grupo');
                }

                const resCap = await fetch(`/api/help-desk/v2/inventory/groups/${groupId}/capacities`, {
                    method: 'PUT',
                    headers: authHeaders,
                    body: JSON.stringify({ capacities: capacities || [] }),
                });
                if (!resCap.ok) {
                    const err = await resCap.json().catch(() => ({}));
                    throw new Error((err.detail && err.detail.error) || err.error || err.message || 'Error al actualizar capacidades');
                }
            } else {
                const response = await fetch('/api/help-desk/v2/inventory/groups', {
                    method: 'POST',
                    headers: authHeaders,
                    body: JSON.stringify(formData),
                });
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    throw new Error((err.detail && err.detail.error) || err.error || err.message || 'Error al crear grupo');
                }
            }

            getGroupModal().hide();
            showSuccess(isEdit ? 'Grupo actualizado' : 'Grupo creado exitosamente');
            refreshList(); // recarga el fragmento server-side vía HTMX

        } catch (error) {
            console.error('Error:', error);
            showError(`Error al guardar grupo: ${error.message || 'Error desconocido'}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-save"></i> Guardar Grupo';
        }
    }

    function collectGroupFormData() {
        const form = document.getElementById('group-form');

        const data = {
            name: form.querySelector('#group-name').value.trim(),
            group_type: form.querySelector('#group-type').value,
            department_id: parseInt(form.querySelector('#group-department').value),
            description: form.querySelector('#group-description').value.trim() || null,
            building: form.querySelector('#group-building').value.trim() || null,
            floor: form.querySelector('#group-floor').value.trim() || null,
            location_notes: form.querySelector('#group-location-notes').value.trim() || null
        };

        // Capacidades: backend espera lista [{category_id, max_capacity}]
        const capacities = [];
        allCategories.forEach(cat => {
            const input = form.querySelector(`[name="capacity_${cat.id}"]`);
            if (input && input.value) {
                const value = parseInt(input.value);
                if (value > 0) {
                    capacities.push({ category_id: cat.id, max_capacity: value });
                }
            }
        });
        data.capacities = capacities;

        return data;
    }

    function validateGroupData(data) {
        if (!data.name) {
            showError('El nombre es requerido');
            return false;
        }
        if (!data.group_type) {
            showError('El tipo es requerido');
            return false;
        }
        if (!data.department_id || Number.isNaN(data.department_id)) {
            showError('El departamento es requerido');
            return false;
        }
        return true;
    }

    // ==================== FILTROS (HTMX) ====================
    function refreshList() {
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    function bindClearButton() {
        const btn = document.getElementById('btnClearFilters');
        const form = document.getElementById('hd-filter-form');
        if (!btn || !form) return;
        _clearHandler = function () {
            form.querySelectorAll('select').forEach((s) => { s.value = ''; });
            const search = document.getElementById('searchInput');
            if (search) search.value = '';
            refreshList();
        };
        btn.addEventListener('click', _clearHandler);
    }

    // Aplica el ancho (data-driven) a las barras de ocupación del grid. Se re-aplica
    // tras cada swap HTMX (filtro/paginación) porque el fragmento se re-renderiza.
    function applyOccupancyBars() {
        document.querySelectorAll('#hd-groups-results [data-hd-width]').forEach((bar) => {
            const w = parseInt(bar.getAttribute('data-hd-width'), 10) || 0;
            bar.style.width = Math.max(0, Math.min(100, w)) + '%';
        });
    }

    // ==================== HELPERS UI ====================
    function showSuccess(message) { showToast(message, 'success'); }
    function showError(message) { showToast(message, 'error'); }

    // ==================== HTMX PAGE LIFECYCLE ====================
    window.HelpdeskPage.page('inventory_groups_groups_list', {
        init() {
            allCategories = [];
            loadCategories();
            applyOccupancyBars();

            const formEl = document.getElementById('group-form');
            if (formEl) {
                _formSubmitHandler = handleSubmit;
                formEl.addEventListener('submit', _formSubmitHandler);
            }

            // Botones Editar (server-rendered en cada tarjeta) → delegación en el
            // contenedor de resultados (sobrevive a los swaps HTMX del fragmento).
            const results = document.getElementById('hd-groups-results');
            _editDelegate = function (e) {
                const btn = e.target.closest('[data-action="edit-group"]');
                if (!btn) return;
                e.preventDefault();
                openEditGroupModal(parseInt(btn.dataset.groupId, 10));
            };
            if (results) results.addEventListener('click', _editDelegate);

            // Re-aplicar anchos de barras tras cada settle HTMX (filtro/paginación).
            _barsHandler = function () { applyOccupancyBars(); };
            document.body.addEventListener('htmx:afterSettle', _barsHandler);

            bindClearButton();

            // Expuestas para los onclick del template (crear grupo).
            window.openCreateGroupModal = openCreateGroupModal;
            window.openEditGroupModal = openEditGroupModal;

            // Si se llegó con ?edit=ID (desde el botón "Editar" del detalle), abrir el modal.
            try {
                const editId = new URLSearchParams(window.location.search).get('edit');
                if (editId) openEditGroupModal(parseInt(editId, 10));
            } catch (_) { /* noop */ }
        },

        destroy() {
            const formEl = document.getElementById('group-form');
            if (formEl && _formSubmitHandler) formEl.removeEventListener('submit', _formSubmitHandler);

            const results = document.getElementById('hd-groups-results');
            if (results && _editDelegate) results.removeEventListener('click', _editDelegate);

            if (_barsHandler) document.body.removeEventListener('htmx:afterSettle', _barsHandler);

            const btn = document.getElementById('btnClearFilters');
            if (btn && _clearHandler) btn.removeEventListener('click', _clearHandler);

            const modalEl = document.getElementById('groupModal');
            if (modalEl) {
                try { bootstrap.Modal.getInstance(modalEl)?.dispose(); } catch (_) { /* ignore */ }
            }

            delete window.openCreateGroupModal;
            delete window.openEditGroupModal;

            allCategories = [];
            _formSubmitHandler = null;
            _editDelegate = null;
            _clearHandler = null;
            _barsHandler = null;
        }
    });
})();
