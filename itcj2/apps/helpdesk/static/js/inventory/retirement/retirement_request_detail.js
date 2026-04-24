'use strict';
(function () {

    const API_BASE = '/api/help-desk/v2/inventory';

    // Estados que forman parte del flujo de firmas (ordenados)
    const AWAITING_STATUSES = [
        'AWAITING_RECURSOS_MATERIALES',
        'AWAITING_SUBDIRECTOR',
        'AWAITING_DIRECTOR',
    ];

    const STATUS_LABELS = {
        DRAFT:                          { label: 'Borrador',                            cls: 'bg-secondary text-white' },
        PENDING:                        { label: 'Pendiente de Envío',                  cls: 'bg-warning text-dark' },
        AWAITING_RECURSOS_MATERIALES:   { label: 'Esperando Firma (Rec. Mat.)',         cls: 'bg-warning text-dark' },
        AWAITING_SUBDIRECTOR:           { label: 'Esperando Firma (Subdirector)',        cls: 'bg-warning text-dark' },
        AWAITING_DIRECTOR:              { label: 'Esperando Firma (Director)',           cls: 'bg-warning text-dark' },
        APPROVED:                       { label: 'Aprobada',                            cls: 'bg-success text-white' },
        REJECTED:                       { label: 'Rechazada',                           cls: 'bg-danger text-white' },
        CANCELLED:                      { label: 'Cancelada',                           cls: 'bg-secondary text-white' },
    };

    // Permiso por step de firma
    const SIGN_PERM_BY_STEP = {
        1: 'helpdesk.retirement.sign.recursos_materiales',
        2: 'helpdesk.retirement.sign.subdirector',
        3: 'helpdesk.retirement.sign.director',
    };

    let requestData = null;
    let pendingAddItemId = null;

    const el = {
        folioDisplay:       document.getElementById('folio-display'),
        statusBadge:        document.getElementById('status-badge'),
        headerMeta:         document.getElementById('header-meta'),
        actionButtons:      document.getElementById('action-buttons'),
        detailReqBy:        document.getElementById('detail-requested-by'),
        detailCreatedAt:    document.getElementById('detail-created-at'),
        detailReason:       document.getElementById('detail-reason'),
        reviewedByRow:      document.getElementById('reviewed-by-row'),
        reviewedAtRow:      document.getElementById('reviewed-at-row'),
        reviewNotesRow:     document.getElementById('review-notes-row'),
        detailReviewedBy:   document.getElementById('detail-reviewed-by'),
        detailReviewedAt:   document.getElementById('detail-reviewed-at'),
        detailRevNotes:     document.getElementById('detail-review-notes'),
        itemsTbody:         document.getElementById('items-tbody'),
        itemsCountBadge:    document.getElementById('items-count-badge'),
        btnAddItem:         document.getElementById('btn-add-item'),
        addItemSearch:      document.getElementById('add-item-search'),
        addItemResults:     document.getElementById('add-item-results'),
        addItemNotes:       document.getElementById('add-item-notes'),
        addItemSelected:    document.getElementById('add-item-selected'),
        addItemSelLabel:    document.getElementById('add-item-selected-label'),
        btnConfirmAdd:      document.getElementById('btn-confirm-add-item'),
        colActions:         document.getElementById('col-actions'),
        reviewPanel:        document.getElementById('review-panel'),
        reviewNotes:        document.getElementById('review-notes-input'),
        btnApprove:         document.getElementById('btn-approve'),
        btnReject:          document.getElementById('btn-reject'),
        statusTimeline:     document.getElementById('status-timeline'),
        docName:            document.getElementById('doc-name'),
        btnAttachDoc:       document.getElementById('btn-attach-doc'),
        docFileInput:       document.getElementById('doc-file-input'),
        btnUploadDoc:       document.getElementById('btn-upload-doc'),
        confirmModal:       document.getElementById('confirm-modal'),
        confirmTitle:       document.getElementById('confirm-modal-title'),
        confirmBody:        document.getElementById('confirm-modal-body'),
        confirmOk:          document.getElementById('confirm-modal-ok'),
        // Firma multi-paso
        signingPanel:       document.getElementById('signing-panel'),
        signingRoleTitle:   document.getElementById('signing-role-title'),
        signingNotes:       document.getElementById('signing-notes'),
        btnApproveSign:     document.getElementById('btn-approve-sign'),
        btnRejectSign:      document.getElementById('btn-reject-sign'),
        signaturesTimeline: document.getElementById('signatures-timeline'),
        signaturesBody:     document.getElementById('signatures-timeline-body'),
    };

    function fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleString('es-MX', {
            day: '2-digit', month: 'short', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ── Carga de solicitud ────────────────────────────────────────────────────
    async function loadRequest() {
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}?include_items=true`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) throw new Error('No se pudo cargar la solicitud');
            const json = await res.json();
            requestData = json.data;
            renderRequest(requestData);
            await loadSignatures();
        } catch (err) {
            el.headerMeta.textContent = 'Error: ' + err.message;
        }
    }

    function renderRequest(r) {
        // Header
        el.folioDisplay.textContent = r.folio;
        const s = STATUS_LABELS[r.status] || { label: r.status, cls: '' };
        el.statusBadge.textContent = s.label;
        el.statusBadge.className   = `status-badge-lg ${s.cls}`;
        el.headerMeta.textContent  = `Creada el ${fmtDate(r.created_at)}`;

        // Detalle
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

        // Documento adjunto
        if (r.document_original_name) {
            el.docName.textContent = r.document_original_name;
        }

        // Acciones según status
        renderActions(r.status);

        // Timeline de estado
        renderStatusTimeline(r);
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
            const dept = item.department ? escapeHtml(item.department.name) : '—';
            const removeBtn = isDraft
                ? `<button class="btn btn-sm btn-outline-danger py-0 px-1 remove-item-btn" data-item-id="${ri.id}">
                    <i class="fas fa-trash-alt"></i>
                   </button>`
                : '';
            return `<tr>
                <td class="pl-3">
                    <span class="font-weight-bold">${escapeHtml(item.inventory_number || '—')}</span>
                    <br><small class="text-muted">${escapeHtml(item.brand || '')} ${escapeHtml(item.model || '')}</small>
                </td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml(item.supplier_serial || '—')}</small></td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml(item.itcj_serial || '—')}</small></td>
                <td class="d-none d-sm-table-cell"><small>${dept}</small></td>
                <td><small class="text-muted">${escapeHtml(ri.item_notes || '—')}</small></td>
                <td>${removeBtn}</td>
            </tr>`;
        }).join('');

        el.itemsTbody.querySelectorAll('.remove-item-btn').forEach(btn => {
            btn.addEventListener('click', () => removeItem(parseInt(btn.dataset.itemId)));
        });
    }

    function renderActions(status) {
        const actions = [];

        if (status === 'DRAFT') {
            actions.push(`<button class="btn btn-sm btn-primary" id="btn-submit">
                <i class="fas fa-paper-plane"></i> Enviar a Revisión
            </button>`);
            actions.push(`<button class="btn btn-sm btn-outline-danger" id="btn-cancel">
                <i class="fas fa-ban"></i> Cancelar
            </button>`);
            if (el.btnAddItem)   el.btnAddItem.style.display   = '';
            if (el.btnAttachDoc) el.btnAttachDoc.style.display = '';

        } else if (status === 'PENDING') {
            // Enviar al flujo de firmas multi-paso
            actions.push(`<button class="btn btn-sm btn-primary" id="btn-submit-for-approval">
                <i class="fas fa-paper-plane"></i> Enviar a Firma
            </button>`);
            actions.push(`<button class="btn btn-sm btn-outline-danger" id="btn-cancel">
                <i class="fas fa-ban"></i> Cancelar
            </button>`);
            if (el.reviewPanel && CAN_APPROVE) el.reviewPanel.style.removeProperty('display');

        } else if (status === 'REJECTED') {
            // El solicitante puede corregir y re-enviar (vuelve a DRAFT)
            actions.push(`<button class="btn btn-sm btn-warning" id="btn-resubmit">
                <i class="fas fa-redo"></i> Corregir y Re-enviar
            </button>`);
        }

        // Generar oficio disponible desde el inicio del flujo de firmas o si está aprobada
        if (AWAITING_STATUSES.includes(status) || status === 'APPROVED') {
            actions.push(`<a class="btn btn-sm btn-outline-secondary" id="btn-generate-doc"
                href="${API_BASE}/retirement-requests/${REQUEST_ID}/generate-document?format=pdf"
                target="_blank">
                <i class="fas fa-file-pdf"></i> Generar Oficio
            </a>`);
        }

        if (el.actionButtons) el.actionButtons.innerHTML = actions.join(' ');

        // Vincular eventos
        const btnSubmit = document.getElementById('btn-submit');
        if (btnSubmit) {
            btnSubmit.addEventListener('click', () => confirmAction(
                'Enviar a revisión',
                '¿Enviar esta solicitud al administrador para su revisión?',
                () => doAction('submit')
            ));
        }

        const btnSubmitForApproval = document.getElementById('btn-submit-for-approval');
        if (btnSubmitForApproval) {
            btnSubmitForApproval.addEventListener('click', () => confirmAction(
                'Enviar a firma',
                '¿Iniciar el flujo de firmas? La solicitud será enviada a Recursos Materiales para su autorización.',
                () => doAction('submit-for-approval')
            ));
        }

        const btnCancel = document.getElementById('btn-cancel');
        if (btnCancel) {
            btnCancel.addEventListener('click', () => confirmAction(
                'Cancelar solicitud',
                '¿Cancelar esta solicitud? Esta acción no se puede deshacer.',
                () => doAction('cancel')
            ));
        }

        const btnResubmit = document.getElementById('btn-resubmit');
        if (btnResubmit) {
            btnResubmit.addEventListener('click', () => confirmAction(
                'Corregir y re-enviar',
                '¿Regresar esta solicitud a borrador para hacer correcciones?',
                () => doAction('resubmit')
            ));
        }
    }

    function renderStatusTimeline(r) {
        const order = ['DRAFT', 'PENDING', 'AWAITING_RECURSOS_MATERIALES', 'AWAITING_SUBDIRECTOR', 'AWAITING_DIRECTOR', 'APPROVED', 'REJECTED', 'CANCELLED'];
        const steps = [
            { status: 'DRAFT',                        label: 'Borrador creado',                       icon: 'fa-file-alt',      color: '#6c757d' },
            { status: 'PENDING',                      label: 'Enviada a revisión',                    icon: 'fa-paper-plane',   color: '#ffc107' },
            { status: 'AWAITING_RECURSOS_MATERIALES', label: 'En firma — Rec. Materiales',            icon: 'fa-pen-nib',       color: '#fd7e14' },
            { status: 'AWAITING_SUBDIRECTOR',         label: 'En firma — Subdirector',                icon: 'fa-pen-nib',       color: '#fd7e14' },
            { status: 'AWAITING_DIRECTOR',            label: 'En firma — Director',                   icon: 'fa-pen-nib',       color: '#fd7e14' },
            { status: 'APPROVED',                     label: 'Aprobada',                              icon: 'fa-check-circle',  color: '#28a745' },
            { status: 'REJECTED',                     label: 'Rechazada',                             icon: 'fa-times-circle',  color: '#dc3545' },
            { status: 'CANCELLED',                    label: 'Cancelada',                             icon: 'fa-ban',           color: '#6c757d' },
        ];

        const idx = order.indexOf(r.status);

        let relevant;
        if (r.status === 'CANCELLED') {
            relevant = steps.filter(s => s.status === 'DRAFT' || s.status === 'CANCELLED');
        } else if (r.status === 'REJECTED') {
            // Mostrar hasta el paso donde fue rechazado
            const rejIdx = order.indexOf('REJECTED');
            relevant = steps.filter(s => order.indexOf(s.status) <= rejIdx && s.status !== 'CANCELLED');
        } else {
            relevant = steps.filter(s => !['REJECTED', 'CANCELLED'].includes(s.status));
        }

        el.statusTimeline.innerHTML = relevant.map(s => {
            const isCurrentOrPast = order.indexOf(s.status) <= idx;
            const opacity = isCurrentOrPast ? '1' : '0.35';
            return `<div class="timeline-item" style="opacity:${opacity};">
                <div class="timeline-icon" style="background:${s.color}20; color:${s.color};">
                    <i class="fas ${s.icon} fa-sm"></i>
                </div>
                <div>
                    <div class="font-weight-bold">${escapeHtml(s.label)}</div>
                    ${s.status === r.status && r.updated_at
                        ? `<small class="text-muted">${fmtDate(r.updated_at)}</small>` : ''}
                </div>
            </div>`;
        }).join('');
    }

    // ── Firmas multi-paso ─────────────────────────────────────────────────────

    async function loadSignatures() {
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/signatures`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) return;
            const json = await res.json();
            if (!json.success) return;

            renderSignaturesTimeline(json.data);
            checkIfCurrentUserCanSign(json.data);
        } catch (_) { /* no bloquea si falla */ }
    }

    function renderSignaturesTimeline(signatures) {
        if (!el.signaturesTimeline || !el.signaturesBody) return;

        // Mostrar el card solo si al menos un paso ha comenzado (no todo en WAITING)
        const hasStarted = signatures.some(s => s.status !== 'WAITING');
        if (!hasStarted) {
            el.signaturesTimeline.style.display = 'none';
            return;
        }

        el.signaturesTimeline.style.display = '';

        const iconMap = {
            APPROVED: { icon: 'fa-check-circle', color: '#28a745', label: 'Autorizado' },
            REJECTED: { icon: 'fa-times-circle',  color: '#dc3545', label: 'Rechazado' },
            PENDING:  { icon: 'fa-hourglass-half', color: '#ffc107', label: 'Pendiente' },
            WAITING:  { icon: 'fa-circle',         color: '#adb5bd', label: 'En espera' },
        };

        el.signaturesBody.innerHTML = signatures.map(sig => {
            const ic = iconMap[sig.status] || iconMap.WAITING;
            let detailText = ic.label;

            if (sig.status === 'APPROVED' || sig.status === 'REJECTED') {
                const who  = sig.signed_by ? escapeHtml(sig.signed_by.full_name) : '—';
                const when = fmtDate(sig.signed_at);
                detailText = `${escapeHtml(who)} — ${escapeHtml(when)}`;
            } else if (sig.status === 'PENDING') {
                detailText = 'Esperando firma';
            }

            const notesHtml = sig.notes
                ? `<br><small class="text-muted fst-italic">${escapeHtml(sig.notes)}</small>`
                : '';

            return `<div class="timeline-item" style="opacity:1;">
                <div class="timeline-icon" style="background:${ic.color}20; color:${ic.color}; flex-shrink:0;">
                    <i class="fas ${ic.icon} fa-sm"></i>
                </div>
                <div>
                    <div class="fw-bold" style="font-size:.8rem;">
                        Paso ${sig.step} — ${escapeHtml(sig.position_title)}
                    </div>
                    <small class="text-muted">${detailText}</small>
                    ${notesHtml}
                </div>
            </div>`;
        }).join('');
    }

    function checkIfCurrentUserCanSign(signatures) {
        if (!el.signingPanel || !el.signingRoleTitle) return;

        // Buscar el primer paso en PENDING
        const pendingStep = signatures.find(s => s.status === 'PENDING');
        if (!pendingStep) {
            el.signingPanel.style.display = 'none';
            return;
        }

        // Verificar si el usuario tiene el permiso correspondiente a este step
        const requiredPerm = SIGN_PERM_BY_STEP[pendingStep.step];
        const userPerms = (typeof CURRENT_USER_PERMS !== 'undefined') ? CURRENT_USER_PERMS : [];
        const canSign = requiredPerm && userPerms.includes(requiredPerm);

        if (canSign) {
            el.signingRoleTitle.textContent = pendingStep.position_title;
            el.signingPanel.style.display   = '';
        } else {
            el.signingPanel.style.display   = 'none';
        }
    }

    async function signRequest(action) {
        const notes = el.signingNotes ? el.signingNotes.value.trim() : '';
        const btn = action === 'APPROVED' ? el.btnApproveSign : el.btnRejectSign;
        if (btn) btn.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/sign`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
                body: JSON.stringify({ action, notes: notes || null }),
            });
            const json = await res.json();
            if (json.success) {
                showToast(json.message || 'Solicitud actualizada', 'success');
                await loadRequest();
            } else {
                const msg = json.error || json.detail || 'Error al procesar la firma';
                showToast(msg, 'error');
            }
        } catch (_) {
            showToast('Error de conexión', 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // Vincular botones de firma
    if (el.btnApproveSign) {
        el.btnApproveSign.addEventListener('click', () => {
            confirmAction(
                'Autorizar solicitud',
                '¿Confirmas la autorización de esta solicitud de baja?',
                () => { closeConfirmModal(); signRequest('APPROVED'); }
            );
        });
    }

    if (el.btnRejectSign) {
        el.btnRejectSign.addEventListener('click', () => {
            const notes = el.signingNotes ? el.signingNotes.value.trim() : '';
            if (!notes) {
                showToast('Debes indicar el motivo del rechazo en el campo de observaciones', 'warning');
                if (el.signingNotes) el.signingNotes.focus();
                return;
            }
            confirmAction(
                'Rechazar solicitud',
                '¿Confirmas el rechazo de esta solicitud de baja?',
                () => { closeConfirmModal(); signRequest('REJECTED'); }
            );
        });
    }

    // ── Agregar equipo (DRAFT) ────────────────────────────────────────────────
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
            const res = await fetch(`${API_BASE}/items?search=${encodeURIComponent(q)}&per_page=8`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) return;
            const data = await res.json();
            const items = data.data || [];
            el.addItemResults.innerHTML = items.map(item => {
                const serial = item.itcj_serial || item.supplier_serial || '—';
                return `<div class="search-result-item" data-id="${item.id}"
                             data-number="${escapeHtml(item.inventory_number)}" style="cursor:pointer; padding:.4rem .75rem; border-bottom:1px solid #f0f0f0;">
                    <span class="font-weight-bold">${escapeHtml(item.inventory_number)}</span>
                    <span class="text-muted small ml-1">${escapeHtml(item.brand || '')} ${escapeHtml(item.model || '')}</span>
                    <span class="float-right text-muted small">${escapeHtml(serial)}</span>
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
        } catch (_) { /* ignorar */ }
    }

    if (el.btnConfirmAdd) {
        el.btnConfirmAdd.addEventListener('click', async () => {
            if (!pendingAddItemId) return;
            try {
                const _notes = el.addItemNotes ? el.addItemNotes.value || null : null;
                const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/items`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    },
                    body: JSON.stringify({
                        item_ids: [pendingAddItemId],
                        notes_map: _notes ? { [pendingAddItemId]: _notes } : {}
                    }),
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
                pendingAddItemId = null;
                if (el.addItemSearch)   el.addItemSearch.value  = '';
                if (el.addItemNotes)    el.addItemNotes.value   = '';
                if (el.addItemSelected) el.addItemSelected.classList.add('d-none');
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
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
            });
            if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
            loadRequest();
        } catch (err) { showToast(err.message, 'error'); }
    }

    // ── Acciones generales ────────────────────────────────────────────────────
    async function doAction(action, extra = {}) {
        try {
            const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/${action}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                },
                body: JSON.stringify(extra),
            });
            if (!res.ok) { const e = await res.json(); throw new Error(e.detail || e.error || `Error en ${action}`); }
            closeConfirmModal();
            loadRequest();
        } catch (err) { showToast(err.message, 'error'); }
    }

    // Aprobar / Rechazar (panel admin — flujo original PENDING)
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

    // Subir documento
    if (el.btnUploadDoc) {
        el.btnUploadDoc.addEventListener('click', async () => {
            const file = el.docFileInput ? el.docFileInput.files[0] : null;
            if (!file) { showToast('Selecciona un archivo primero', 'warning'); return; }
            const fd = new FormData();
            fd.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/retirement-requests/${REQUEST_ID}/attach`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
                    body: fd,
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
                loadRequest();
            } catch (err) { showToast(err.message, 'error'); }
        });
    }

    // ── Modal de confirmación ─────────────────────────────────────────────────
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

    // ── Inicialización ────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', loadRequest);

})();
