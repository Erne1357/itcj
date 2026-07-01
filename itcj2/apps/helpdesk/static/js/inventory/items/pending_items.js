/**
 * Equipos Pendientes de Asignación — migrada a componentes server-side + HTMX + Alpine.
 * La tabla, los filtros y la paginación los rinde el servidor (ver
 * _pending_items_results.html + pages/inventory.py). La selección masiva es estado
 * de cliente en Alpine (Set en el PADRE, regla de zonas §4.2). Este módulo conserva
 * SOLO la lógica de cliente: modales BS5 (sin jQuery) de asignación individual/masiva.
 */

(function () {
    'use strict';

    // === MODULE STATE ===
    let allDepartments = [];

    // === LISTENER TEARDOWN REFS ===
    let _assignDelegate = null;
    let _assignSubmit = null;
    let _bulkSubmit = null;

    // === BS5 MODAL HELPERS ===
    function modalShow(id) { bootstrap.Modal.getOrCreateInstance(document.getElementById(id)).show(); }
    function modalHide(id) {
        const el = document.getElementById(id);
        if (el) { try { bootstrap.Modal.getInstance(el)?.hide(); } catch (_) { /* ignore */ } }
    }
    function modalDispose(id) {
        const el = document.getElementById(id);
        if (el) { try { bootstrap.Modal.getInstance(el)?.dispose(); } catch (_) { /* ignore */ } }
    }

    // Recarga el fragmento server-side y limpia la selección Alpine (evento que el
    // x-data del padre escucha con @items-reset.window).
    function refreshList() {
        window.dispatchEvent(new CustomEvent('items-reset'));
        const form = document.getElementById('hd-filter-form');
        if (form && window.htmx) window.htmx.trigger(form, 'refresh');
    }

    // === DATA ===
    async function loadDepartments() {
        try {
            const response = await fetch('/api/core/v2/departments?active=true', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!response.ok) return;
            const result = await response.json();
            allDepartments = result.data || [];
            ['assign-department', 'bulk-department'].forEach(selectId => {
                const select = document.getElementById(selectId);
                if (!select) return;
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
        }
    }

    // === ASIGNACIÓN INDIVIDUAL ===
    function openAssignModal(itemId, itemNumber) {
        document.getElementById('assign-item-id').value = itemId;
        document.getElementById('assign-item-number').textContent = itemNumber || itemId;
        document.getElementById('assign-department').value = '';
        document.getElementById('assign-notes').value = '';
        modalShow('assignModal');
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
                    item_ids: [parseInt(itemId, 10)],
                    department_id: parseInt(departmentId, 10),
                    notes: notes || null
                })
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                const d = err.detail || err;
                const msg = (typeof d === 'string') ? d : (d.error || d.message || 'Error al asignar equipo');
                throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            }
            modalHide('assignModal');
            showToast('Equipo asignado exitosamente', 'success');
            refreshList();
        } catch (error) {
            console.error('Error:', error);
            showToast(`Error al asignar equipo: ${error.message || 'Error desconocido'}`, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-check"></i> Asignar';
        }
    }

    // === ASIGNACIÓN MASIVA (Alpine pasa los ids) ===
    function openBulkAssignModal(ids) {
        if (!ids || !ids.length) { showToast('Selecciona al menos un equipo', 'error'); return; }
        document.getElementById('bulk-count').textContent = ids.length;
        document.getElementById('bulk-department').value = '';
        document.getElementById('bulk-notes').value = '';
        const form = document.getElementById('bulk-assign-form');
        form.dataset.ids = ids.join(',');
        modalShow('bulkAssignModal');
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

            const itemIds = (e.target.dataset.ids || '').split(',').filter(Boolean).map(Number);

            const response = await fetch('/api/help-desk/v2/inventory/pending/assign-to-department', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_ids: itemIds,
                    department_id: parseInt(departmentId, 10),
                    notes: notes || null
                })
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                const d = err.detail || err;
                const msg = (typeof d === 'string') ? d : (d.error || d.message || 'Error al asignar equipos');
                throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            }
            const result = await response.json();
            modalHide('bulkAssignModal');
            showToast(result.message || `${result.items?.length || 0} equipo(s) asignado(s) exitosamente`, 'success');
            refreshList();
        } catch (error) {
            console.error('Error:', error);
            showToast(`Error al asignar equipos: ${error.message || 'Error desconocido'}`, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-check"></i> Asignar Todo';
        }
    }

    // === HTMX PAGE LIFECYCLE ===
    window.HelpdeskPage.page('inventory_items_pending_items', {
        init() {
            allDepartments = [];
            loadDepartments();

            // Delegación: botón "Asignar" de cada fila (server-rendered, sobrevive swaps).
            const results = document.getElementById('hd-pending-results');
            _assignDelegate = function (e) {
                const btn = e.target.closest('[data-action="assign-item"]');
                if (!btn) return;
                e.preventDefault();
                openAssignModal(parseInt(btn.dataset.itemId, 10), btn.dataset.itemNumber);
            };
            if (results) results.addEventListener('click', _assignDelegate);

            const assignForm = document.getElementById('assign-form');
            if (assignForm) { _assignSubmit = handleAssign; assignForm.addEventListener('submit', _assignSubmit); }

            const bulkForm = document.getElementById('bulk-assign-form');
            if (bulkForm) { _bulkSubmit = handleBulkAssign; bulkForm.addEventListener('submit', _bulkSubmit); }

            // Expuesta para Alpine (@click).
            window.hdPendingBulkAssign = openBulkAssignModal;
        },

        destroy() {
            const results = document.getElementById('hd-pending-results');
            if (results && _assignDelegate) results.removeEventListener('click', _assignDelegate);

            const assignForm = document.getElementById('assign-form');
            if (assignForm && _assignSubmit) assignForm.removeEventListener('submit', _assignSubmit);

            const bulkForm = document.getElementById('bulk-assign-form');
            if (bulkForm && _bulkSubmit) bulkForm.removeEventListener('submit', _bulkSubmit);

            modalDispose('assignModal');
            modalDispose('bulkAssignModal');

            delete window.hdPendingBulkAssign;

            allDepartments = [];
            _assignDelegate = null;
            _assignSubmit = null;
            _bulkSubmit = null;
        }
    });
})();
