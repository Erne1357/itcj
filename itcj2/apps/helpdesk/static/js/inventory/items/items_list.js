/**
 * Lista de Equipos del Inventario — migrada a componentes server-side + HTMX + Alpine.
 * La tabla, los filtros y la paginación los rinde el servidor (ver
 * _items_list_results.html + pages/inventory.py). La selección masiva es estado
 * de cliente en Alpine (Set en el PADRE, regla de zonas §4.2). Este módulo conserva
 * SOLO la lógica genuinamente de cliente: modales BS5 (sin jQuery) de acciones
 * rápidas / cambio de estado / transferencia masiva, y las acciones masivas.
 */

(function () {
    'use strict';

    // === MODULE STATE ===
    let allDepartments = [];

    // === LISTENER TEARDOWN REFS ===
    let _quickDelegate = null;
    let _qaBodyDelegate = null;
    let _statusSubmit = null;
    let _confirmTransfer = null;

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

    // === HTMX REFRESH ===
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
        } catch (error) {
            console.error('Error cargando departamentos:', error);
        }
    }

    // === QUICK ACTIONS (por equipo) ===
    function showQuickActions(itemId) {
        const body = document.getElementById('quick-actions-body');
        body.innerHTML = `
            <div class="list-group">
                <a href="/help-desk/inventory/items/${itemId}" class="list-group-item list-group-item-action">
                    <i class="fas fa-eye text-primary me-2"></i> Ver Detalle
                </a>
                <button type="button" class="list-group-item list-group-item-action" data-qa-action="status" data-item-id="${itemId}">
                    <i class="fas fa-toggle-on text-warning me-2"></i> Cambiar Estado
                </button>
                <button type="button" class="list-group-item list-group-item-action text-danger" data-qa-action="baja" data-item-id="${itemId}">
                    <i class="fas fa-file-alt me-2"></i> Solicitar Baja
                </button>
                <button type="button" class="list-group-item list-group-item-action text-warning" data-qa-action="limbo" data-item-id="${itemId}">
                    <i class="fas fa-inbox me-2"></i> Enviar al Limbo
                </button>
            </div>
        `;
        modalShow('quickActionsModal');
    }

    function openChangeStatus(itemId) {
        modalHide('quickActionsModal');
        document.getElementById('change-status-item-id').value = itemId;
        document.getElementById('new-status').value = '';
        document.getElementById('status-notes').value = '';
        modalShow('changeStatusModal');
    }

    async function handleChangeStatus(e) {
        e.preventDefault();
        const itemId = document.getElementById('change-status-item-id').value;
        const newStatus = document.getElementById('new-status').value;
        const notes = document.getElementById('status-notes').value;
        if (!newStatus) { showToast('Debes seleccionar un estado', 'error'); return; }

        try {
            const response = await fetch(`/api/help-desk/v2/inventory/items/${itemId}/status`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ status: newStatus, notes })
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error((err.detail && err.detail.error) || err.error || err.message || 'Error al cambiar estado');
            }
            modalHide('changeStatusModal');
            showToast('Estado actualizado correctamente', 'success');
            refreshList();
        } catch (error) {
            console.error('Error:', error);
            showToast(`Error al cambiar estado: ${error.message || 'Error desconocido'}`, 'error');
        }
    }

    async function sendSingleToLimbo(itemId) {
        modalHide('quickActionsModal');
        if (!await HelpdeskUtils.confirmDialog('Enviar al limbo', '¿Enviar este equipo al limbo? Quedará sin departamento ni usuario asignado.')) return;
        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                body: JSON.stringify({ item_ids: [parseInt(itemId, 10)] }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');
            showToast('Equipo enviado al limbo correctamente', 'success');
            refreshList();
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }
    }

    // === ACCIONES MASIVAS (Alpine pasa los ids) ===
    function bulkTransfer(ids) {
        if (!ids || !ids.length) return;
        document.getElementById('bulk-transfer-count').textContent = ids.length;
        const deptSelect = document.getElementById('bulk-transfer-dept');
        deptSelect.innerHTML = '<option value="">Seleccionar...</option>';
        allDepartments.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = d.name;
            deptSelect.appendChild(opt);
        });
        deptSelect.dataset.ids = ids.join(',');
        modalShow('bulkTransferModal');
    }

    async function executeBulkTransfer() {
        const deptSelect = document.getElementById('bulk-transfer-dept');
        const ids = (deptSelect.dataset.ids || '').split(',').filter(Boolean).map(Number);
        const deptId = parseInt(deptSelect.value, 10);
        if (!ids.length) return;
        if (!deptId) { showToast('Selecciona un departamento destino', 'error'); return; }

        const btn = document.getElementById('btn-confirm-bulk-transfer');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Transfiriendo...';
        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-transfer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                body: JSON.stringify({ item_ids: ids, target_department_id: deptId }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al transferir');

            modalHide('bulkTransferModal');
            const transferred = data.transferred_ids ? data.transferred_ids.length : 0;
            const errors = data.errors ? data.errors.length : 0;
            let msg = `${transferred} equipo(s) transferido(s) correctamente.`;
            if (errors) msg += ` ${errors} con errores.`;
            showToast(msg, transferred > 0 ? 'success' : 'error');
            refreshList();
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-exchange-alt"></i> Transferir';
        }
    }

    function bulkBaja(ids) {
        if (!ids || !ids.length) return;
        window.HelpdeskPage.navigate(`/help-desk/inventory/retirement-requests/create?item_ids=${ids.join(',')}`);
    }

    async function bulkLimbo(ids) {
        if (!ids || !ids.length) return;
        if (!await HelpdeskUtils.confirmDialog('Enviar al limbo', `¿Enviar ${ids.length} equipo(s) al limbo? Quedarán sin departamento ni usuario asignado.`)) return;
        try {
            const res = await fetch('/api/help-desk/v2/inventory/items/bulk-send-to-limbo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                body: JSON.stringify({ item_ids: ids }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Error al enviar al limbo');
            const sent = data.sent_ids ? data.sent_ids.length : 0;
            const errors = data.errors ? data.errors.length : 0;
            let msg = `${sent} equipo(s) enviado(s) al limbo.`;
            if (errors) msg += ` ${errors} con errores.`;
            showToast(msg, sent > 0 ? 'success' : 'error');
            refreshList();
        } catch (err) {
            showToast('Error: ' + err.message, 'error');
        }
    }

    function exportToExcel() {
        showToast('Función de exportación en desarrollo', 'info');
    }

    // === HTMX PAGE LIFECYCLE ===
    window.HelpdeskPage.page('inventory_items_items_list', {
        init() {
            allDepartments = [];
            loadDepartments();

            // Delegación: botón "Acciones" de cada fila (server-rendered, sobrevive swaps).
            const results = document.getElementById('hd-items-results');
            _quickDelegate = function (e) {
                const btn = e.target.closest('[data-action="quick-actions"]');
                if (!btn) return;
                e.preventDefault();
                showQuickActions(parseInt(btn.dataset.itemId, 10));
            };
            if (results) results.addEventListener('click', _quickDelegate);

            // Delegación dentro del modal de acciones rápidas.
            const qaBody = document.getElementById('quick-actions-body');
            _qaBodyDelegate = function (e) {
                const btn = e.target.closest('[data-qa-action]');
                if (!btn) return;
                const id = parseInt(btn.dataset.itemId, 10);
                const action = btn.dataset.qaAction;
                if (action === 'status') openChangeStatus(id);
                else if (action === 'baja') { modalHide('quickActionsModal'); bulkBaja([id]); }
                else if (action === 'limbo') sendSingleToLimbo(id);
            };
            if (qaBody) qaBody.addEventListener('click', _qaBodyDelegate);

            const statusForm = document.getElementById('change-status-form');
            if (statusForm) { _statusSubmit = handleChangeStatus; statusForm.addEventListener('submit', _statusSubmit); }

            const btnConfirm = document.getElementById('btn-confirm-bulk-transfer');
            if (btnConfirm) { _confirmTransfer = executeBulkTransfer; btnConfirm.addEventListener('click', _confirmTransfer); }

            // Expuestas para Alpine (@click) y onclick del template.
            window.hdItemsBulkTransfer = bulkTransfer;
            window.hdItemsBulkBaja = bulkBaja;
            window.hdItemsBulkLimbo = bulkLimbo;
            window.exportToExcel = exportToExcel;
        },

        destroy() {
            const results = document.getElementById('hd-items-results');
            if (results && _quickDelegate) results.removeEventListener('click', _quickDelegate);

            const qaBody = document.getElementById('quick-actions-body');
            if (qaBody && _qaBodyDelegate) qaBody.removeEventListener('click', _qaBodyDelegate);

            const statusForm = document.getElementById('change-status-form');
            if (statusForm && _statusSubmit) statusForm.removeEventListener('submit', _statusSubmit);

            const btnConfirm = document.getElementById('btn-confirm-bulk-transfer');
            if (btnConfirm && _confirmTransfer) btnConfirm.removeEventListener('click', _confirmTransfer);

            modalDispose('quickActionsModal');
            modalDispose('bulkTransferModal');
            modalDispose('changeStatusModal');

            delete window.hdItemsBulkTransfer;
            delete window.hdItemsBulkBaja;
            delete window.hdItemsBulkLimbo;
            delete window.exportToExcel;

            allDepartments = [];
            _quickDelegate = null;
            _qaBodyDelegate = null;
            _statusSubmit = null;
            _confirmTransfer = null;
        }
    });
})();
