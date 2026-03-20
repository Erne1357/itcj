'use strict';
(function () {

    const API_BASE = '/api/help-desk/v2/inventory';

    const STATUS_LABELS = {
        DRAFT:     { label: 'Borrador',  cls: 'bg-secondary text-white' },
        PENDING:   { label: 'Pendiente', cls: 'bg-warning text-dark' },
        APPROVED:  { label: 'Aprobada',  cls: 'bg-success text-white' },
        REJECTED:  { label: 'Rechazada', cls: 'bg-danger text-white' },
        CANCELLED: { label: 'Cancelada', cls: 'bg-secondary text-white' },
    };

    let requestData = null;
    let pendingAddItemId = null;

    const el = {
        folioDisplay:    document.getElementById('folio-display'),
        statusBadge:     document.getElementById('status-badge'),
        headerMeta:      document.getElementById('header-meta'),
        actionButtons:   document.getElementById('action-buttons'),
        detailReqBy:     document.getElementById('detail-requested-by'),
        detailCreatedAt: document.getElementById('detail-created-at'),
        detailReason:    document.getElementById('detail-reason'),
        reviewedByRow:   document.getElementById('reviewed-by-row'),
        reviewedAtRow:   document.getElementById('reviewed-at-row'),
        reviewNotesRow:  document.getElementById('review-notes-row'),
        detailReviewedBy:document.getElementById('detail-reviewed-by'),
        detailReviewedAt:document.getElementById('detail-reviewed-at'),
        detailRevNotes:  document.getElementById('detail-review-notes'),
        itemsTbody:      document.getElementById('items-tbody'),
        itemsCountBadge: document.getElementById('items-count-badge'),
        btnAddItem:      document.getElementById('btn-add-item'),
        addItemSearch:   document.getElementById('add-item-search'),
        addItemResults:  document.getElementById('add-item-results'),
        addItemNotes:    document.getElementById('add-item-notes'),
        addItemSelected: document.getElementById('add-item-selected'),
        addItemSelLabel: document.getElementById('add-item-selected-label'),
        btnConfirmAdd:   document.getElementById('btn-confirm-add-item'),
        colActions:      document.getElementById('col-actions'),
        reviewPanel:     document.getElementById('review-panel'),
        reviewNotes:     document.getElementById('review-notes-input'),
        btnApprove:      document.getElementById('btn-approve'),
        btnReject:       document.getElementById('btn-reject'),
        statusTimeline:  document.getElementById('status-timeline'),
        docName:         document.getElementById('doc-name'),
        btnAttachDoc:    document.getElementById('btn-attach-doc'),
        docFileInput:    document.getElementById('doc-file-input'),
        btnUploadDoc:    document.getElementById('btn-upload-doc'),
        confirmModal:    document.getElementById('confirm-modal'),
        confirmTitle:    document.getElementById('confirm-modal-title'),
        confirmBody:     document.getElementById('confirm-modal-body'),
        confirmOk:       document.getElementById('confirm-modal-ok'),
    };

    function fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleString('es-MX', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    // ── Load request ──────────────────────────────────────────────────────────
    async function loadRequest() {
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}?include_items=true`);
            if (!res.ok) throw new Error('No se pudo cargar la solicitud');
            const json = await res.json();
            requestData = json.data;
            renderRequest(requestData);
        } catch (err) {
            el.headerMeta.textContent = 'Error: ' + err.message;
        }
    }

    function renderRequest(r) {
        // Header
        el.folioDisplay.textContent = r.folio;
        const s = STATUS_LABELS[r.status] || { label: r.status, cls: '' };
        el.statusBadge.textContent  = s.label;
        el.statusBadge.className    = `status-badge-lg ${s.cls}`;
        el.headerMeta.textContent   = `Creada el ${fmtDate(r.created_at)}`;

        // Detail
        el.detailReqBy.textContent     = r.requested_by ? r.requested_by.full_name : '—';
        el.detailCreatedAt.textContent = fmtDate(r.created_at);
        el.detailReason.textContent    = r.reason;

        if (r.reviewed_by) {
            el.reviewedByRow.style.display  = '';
            el.reviewedAtRow.style.display  = '';
            el.detailReviewedBy.textContent = r.reviewed_by.full_name;
            el.detailReviewedAt.textContent = fmtDate(r.reviewed_at);
        }
        if (r.review_notes) {
            el.reviewNotesRow.style.display = '';
            el.detailRevNotes.textContent   = r.review_notes;
        }

        // Items
        renderItems(r.items || []);

        // Document
        if (r.document_original_name) {
            el.docName.textContent = r.document_original_name;
        }

        // Actions by status
        renderActions(r.status);

        // Timeline
        renderTimeline(r);
    }

    function renderItems(items) {
        el.itemsCountBadge.textContent = items.length;
        if (!items.length) {
            el.itemsTbody.innerHTML = `<tr><td colspan="6" class="text-center py-3 text-muted">
                Sin equipos en esta solicitud.
            </td></tr>`;
            return;
        }
        const isDraft = requestData && requestData.status === 'DRAFT';
        if (isDraft && el.colActions) el.colActions.style.display = '';

        el.itemsTbody.innerHTML = items.map(ri => {
            const item = ri.item || {};
            const dept = item.department ? item.department.name : '—';
            const removeBtn = isDraft
                ? `<button class="btn btn-sm btn-outline-danger py-0 px-1 remove-item-btn" data-item-id="${ri.id}">
                    <i class="fas fa-trash-alt"></i>
                   </button>`
                : '';
            return `<tr>
                <td class="pl-3">
                    <span class="font-weight-bold">${item.inventory_number || '—'}</span>
                    <br><small class="text-muted">${item.brand || ''} ${item.model || ''}</small>
                </td>
                <td class="d-none d-md-table-cell"><small>${item.supplier_serial || '—'}</small></td>
                <td class="d-none d-md-table-cell"><small>${item.itcj_serial || '—'}</small></td>
                <td class="d-none d-sm-table-cell"><small>${dept}</small></td>
                <td><small class="text-muted">${ri.item_notes || '—'}</small></td>
                <td>${removeBtn}</td>
            </tr>`;
        }).join('');

        el.itemsTbody.querySelectorAll('.remove-item-btn').forEach(btn => {
            btn.addEventListener('click', () => removeItem(parseInt(btn.dataset.itemId)));
        });
    }

    function renderActions(status) {
        // Action buttons for the requester
        const actions = [];

        if (status === 'DRAFT') {
            actions.push(`<button class="btn btn-sm btn-primary" id="btn-submit">
                <i class="fas fa-paper-plane"></i> Enviar a Revisión
            </button>`);
            actions.push(`<button class="btn btn-sm btn-outline-danger" id="btn-cancel">
                <i class="fas fa-ban"></i> Cancelar
            </button>`);
            if (el.btnAddItem) el.btnAddItem.style.display = '';
            if (el.btnAttachDoc) el.btnAttachDoc.style.display = '';
        } else if (status === 'PENDING') {
            actions.push(`<button class="btn btn-sm btn-outline-danger" id="btn-cancel">
                <i class="fas fa-ban"></i> Cancelar
            </button>`);
            if (el.reviewPanel && CAN_APPROVE) el.reviewPanel.style.removeProperty('display');
        }

        if (el.actionButtons) el.actionButtons.innerHTML = actions.join(' ');

        const btnSubmitEl = document.getElementById('btn-submit');
        if (btnSubmitEl) {
            btnSubmitEl.addEventListener('click', () => confirmAction(
                'Enviar a revisión',
                '¿Enviar esta solicitud al administrador para su revisión?',
                () => doAction('submit')
            ));
        }
        const btnCancelEl = document.getElementById('btn-cancel');
        if (btnCancelEl) {
            btnCancelEl.addEventListener('click', () => confirmAction(
                'Cancelar solicitud',
                '¿Cancelar esta solicitud? Esta acción no se puede deshacer.',
                () => doAction('cancel')
            ));
        }
    }

    function renderTimeline(r) {
        const steps = [
            { status: 'DRAFT',    label: 'Borrador creado',       icon: 'fa-file-alt', color: '#6c757d' },
            { status: 'PENDING',  label: 'Enviada a revisión',     icon: 'fa-paper-plane', color: '#ffc107' },
            { status: 'APPROVED', label: 'Aprobada',               icon: 'fa-check-circle', color: '#28a745' },
            { status: 'REJECTED', label: 'Rechazada',              icon: 'fa-times-circle', color: '#dc3545' },
            { status: 'CANCELLED',label: 'Cancelada',              icon: 'fa-ban', color: '#6c757d' },
        ];
        const order = ['DRAFT', 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'];
        const idx   = order.indexOf(r.status);

        const relevant = r.status === 'CANCELLED'
            ? steps.filter(s => s.status === 'DRAFT' || s.status === 'CANCELLED')
            : r.status === 'REJECTED'
            ? steps.filter(s => ['DRAFT','PENDING','REJECTED'].includes(s.status))
            : steps.filter(s => ['DRAFT','PENDING','APPROVED'].includes(s.status));

        el.statusTimeline.innerHTML = relevant.map(s => {
            const isCurrentOrPast = order.indexOf(s.status) <= idx;
            const opacity = isCurrentOrPast ? '1' : '0.35';
            return `<div class="timeline-item" style="opacity:${opacity};">
                <div class="timeline-icon" style="background:${s.color}20; color:${s.color};">
                    <i class="fas ${s.icon} fa-sm"></i>
                </div>
                <div>
                    <div class="font-weight-bold">${s.label}</div>
                    ${s.status === r.status && r.updated_at
                        ? `<small class="text-muted">${fmtDate(r.updated_at)}</small>` : ''}
                </div>
            </div>`;
        }).join('');
    }

    // ── Add item (DRAFT) ──────────────────────────────────────────────────────
    let searchTimer = null;
    if (el.addItemSearch) {
        el.addItemSearch.addEventListener('input', () => {
            clearTimeout(searchTimer);
            const q = el.addItemSearch.value.trim();
            if (!q) { el.addItemResults.style.display = 'none'; return; }
            searchTimer = setTimeout(() => searchForAdd(q), 300);
        });
    }

    document.addEventListener('click', e => {
        if (el.addItemSearch && !el.addItemSearch.contains(e.target) &&
            el.addItemResults && !el.addItemResults.contains(e.target)) {
            if (el.addItemResults) el.addItemResults.style.display = 'none';
        }
    });

    async function searchForAdd(q) {
        if (!el.addItemResults) return;
        try {
            const res = await fetch(`${API_BASE}/items?search=${encodeURIComponent(q)}&per_page=8`);
            if (!res.ok) return;
            const data = await res.json();
            const items = data.data || [];
            el.addItemResults.innerHTML = items.map(item => {
                const serial = item.itcj_serial || item.supplier_serial || '—';
                return `<div class="search-result-item" data-id="${item.id}"
                             data-number="${item.inventory_number}" style="cursor:pointer; padding:.4rem .75rem; border-bottom:1px solid #f0f0f0;">
                    <span class="font-weight-bold">${item.inventory_number}</span>
                    <span class="text-muted small ml-1">${item.brand || ''} ${item.model || ''}</span>
                    <span class="float-right text-muted small">${serial}</span>
                </div>`;
            }).join('') || '<div class="p-2 text-muted small">Sin resultados</div>';
            el.addItemResults.style.display = 'block';

            el.addItemResults.querySelectorAll('[data-id]').forEach(row => {
                row.addEventListener('click', () => {
                    pendingAddItemId = parseInt(row.dataset.id);
                    if (el.addItemSelected) el.addItemSelected.classList.remove('d-none');
                    if (el.addItemSelLabel) el.addItemSelLabel.textContent = row.dataset.number;
                    el.addItemSearch.value = row.dataset.number;
                    el.addItemResults.style.display = 'none';
                });
            });
        } catch (_) { /* ignore */ }
    }

    if (el.btnConfirmAdd) {
        el.btnConfirmAdd.addEventListener('click', async () => {
            if (!pendingAddItemId) return;
            try {
                const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: [{ item_id: pendingAddItemId, item_notes: el.addItemNotes ? el.addItemNotes.value || null : null }] }),
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
                pendingAddItemId = null;
                if (el.addItemSearch) el.addItemSearch.value = '';
                if (el.addItemNotes)  el.addItemNotes.value  = '';
                if (el.addItemSelected) el.addItemSelected.classList.add('d-none');
                // Close collapse
                const panel = document.getElementById('add-item-panel');
                if (panel && window.$ && $(panel).collapse) $(panel).collapse('hide');
                loadRequest();
            } catch (err) { showToast(err.message, 'error'); }
        });
    }

    async function removeItem(retirementItemId) {
        if (!await HelpdeskUtils.confirmDialog('Quitar equipo', '¿Quitar este equipo de la solicitud?')) return;
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/items/${retirementItemId}`, {
                method: 'DELETE',
            });
            if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
            loadRequest();
        } catch (err) { showToast(err.message, 'error'); }
    }

    // ── Actions ───────────────────────────────────────────────────────────────
    async function doAction(action, extra = {}) {
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(extra),
            });
            if (!res.ok) { const e = await res.json(); throw new Error(e.detail || `Error en ${action}`); }
            closeConfirmModal();
            loadRequest();
        } catch (err) { showToast(err.message, 'error'); }
    }

    // Approve / Reject
    if (el.btnApprove) {
        el.btnApprove.addEventListener('click', () => confirmAction(
            'Aprobar solicitud',
            '¿Aprobar esta solicitud? Los equipos incluidos serán dados de baja del inventario.',
            () => doAction('approve', { notes: el.reviewNotes ? el.reviewNotes.value || null : null })
        ));
    }
    if (el.btnReject) {
        el.btnReject.addEventListener('click', () => confirmAction(
            'Rechazar solicitud',
            '¿Rechazar esta solicitud?',
            () => doAction('reject', { notes: el.reviewNotes ? el.reviewNotes.value || null : null })
        ));
    }

    // Upload document
    if (el.btnUploadDoc) {
        el.btnUploadDoc.addEventListener('click', async () => {
            const file = el.docFileInput ? el.docFileInput.files[0] : null;
            if (!file) { showToast('Selecciona un archivo primero', 'warning'); return; }
            const fd = new FormData();
            fd.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/attach`, {
                    method: 'POST', body: fd,
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
                loadRequest();
            } catch (err) { showToast(err.message, 'error'); }
        });
    }

    // ── Confirm modal ─────────────────────────────────────────────────────────
    function confirmAction(title, body, onConfirm) {
        el.confirmTitle.textContent = title;
        el.confirmBody.textContent  = body;
        el.confirmOk.onclick = onConfirm;
        if (window.$ && $(el.confirmModal).modal) {
            $(el.confirmModal).modal('show');
        }
    }

    function closeConfirmModal() {
        if (window.$ && $(el.confirmModal).modal) {
            $(el.confirmModal).modal('hide');
        }
    }

    // ── Init ──────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', loadRequest);

})();
