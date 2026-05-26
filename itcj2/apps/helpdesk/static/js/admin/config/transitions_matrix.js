/**
 * transitions_matrix.js
 * Sub-sección "Matriz de Transiciones" dentro del tab #estados del panel de Configuración.
 *
 * Responsabilidades:
 *  - Carga GET /matrix y renderiza tabla cuadrada filas=from, columnas=to.
 *  - Diagonal deshabilitada. Estados inactivos con opacidad reducida.
 *  - Click en celda vacía → crea transición (optimista local + confirmación al guardar).
 *  - Click en celda activa → abre modal para editar required_perm y required_fields.
 *  - Botón en celda activa → desactivar (soft DELETE).
 *  - "Guardar matriz" → PUT /bulk con el estado completo de la matriz local.
 *  - Lazy init: se activa con el mismo evento config:tab-shown #estados.
 *  - Estado local: Map keyed por "from_id->to_id".
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let matrixStatuses  = [];          // array de status objects (del endpoint /matrix)
    let transitionsMap  = new Map();   // clave: "from_id->to_id", valor: transition object | null
    let pendingChanges  = false;       // indica si hay cambios sin guardar

    // === CONSTANTES ===
    const API_MATRIX   = '/api/help-desk/v2/config/transitions/matrix';
    const API_TRANS    = '/api/help-desk/v2/config/transitions';
    const BULK_URL     = '/api/help-desk/v2/config/transitions/bulk';

    // Campos requeribles disponibles para multiselect
    const REQUIRED_FIELDS_OPTIONS = [
        { value: 'resolution_notes',       label: 'Notas de resolución' },
        { value: 'time_invested_minutes',  label: 'Tiempo invertido (min)' },
        { value: 'observations',           label: 'Observaciones' },
    ];

    // === HELPERS ===
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function apiErrorMsg(res, fallback) {
        try {
            const d = await res.json();
            const v = d.error || d.message || d.detail;
            if (typeof v === 'string' && v) return v;
            if (Array.isArray(v)) {
                return v.map(function (e) { return (e && e.msg) ? e.msg : String(e); }).join('; ') || fallback;
            }
            return fallback;
        } catch (_) {
            return fallback + ' (HTTP ' + res.status + ')';
        }
    }

    function matrixKey(fromId, toId) {
        return fromId + '->' + toId;
    }

    function getTransition(fromId, toId) {
        return transitionsMap.get(matrixKey(fromId, toId)) || null;
    }

    function setTransition(fromId, toId, transition) {
        transitionsMap.set(matrixKey(fromId, toId), transition);
    }

    function removeTransition(fromId, toId) {
        transitionsMap.delete(matrixKey(fromId, toId));
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#estados') {
            if (!initialized) {
                initialized = true;
                initMatrixSection();
            }
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '';
        if (hash === '#estados') {
            if (!initialized) {
                initialized = true;
                initMatrixSection();
            }
        }
        bindTransitionModal();
    });

    function initMatrixSection() {
        renderShell();
        loadMatrix();
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('estados-transitions-section');
        if (!root) return;

        root.innerHTML = `
            <hr class="my-4">
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <div>
                    <h5 class="mb-0 fw-semibold">
                        <i class="fas fa-project-diagram me-2 text-success"></i>Matriz de Transiciones
                    </h5>
                    <small class="text-muted">
                        Define qué transiciones entre estados son legales. Haz click en una celda para activar o editar.
                    </small>
                </div>
                <button class="btn btn-sm btn-success" id="btn-save-matrix" disabled>
                    <i class="fas fa-save me-1"></i><span class="d-none d-sm-inline">Guardar matriz</span>
                </button>
            </div>

            <div class="alert alert-light border small py-2 mb-3">
                <span class="me-3"><span class="matrix-legend matrix-cell--active-legend"></span> Transición activa (click para editar)</span>
                <span class="me-3"><span class="matrix-legend matrix-cell--inactive-legend"></span> Sin transición (click para activar)</span>
                <span class="me-3"><span class="matrix-legend matrix-cell--disabled-legend"></span> Inactivo / diagonal</span>
            </div>

            <div id="matrix-table-wrapper" class="matrix-table-scroll">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando matriz...
                </div>
            </div>
        `;

        const btnSave = root.querySelector('#btn-save-matrix');
        if (btnSave) {
            btnSave.addEventListener('click', handleSaveMatrix);
        }
    }

    // === CARGA DE DATOS ===
    async function loadMatrix() {
        const wrapper = document.getElementById('matrix-table-wrapper');
        if (wrapper) {
            wrapper.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando matriz...
                </div>`;
        }

        try {
            const res = await fetch(API_MATRIX);
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cargar la matriz');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) wrapper.innerHTML = '<div class="text-danger small p-2">Error al cargar la matriz de transiciones.</div>';
                return;
            }
            const data = await res.json();
            matrixStatuses = data.statuses || [];
            transitionsMap = new Map();

            (data.transitions || []).forEach(function (t) {
                setTransition(t.from_status_id, t.to_status_id, t);
            });

            pendingChanges = false;
            renderMatrix();
        } catch (err) {
            console.error('Error loading matrix:', err);
            HelpdeskUtils.showToast('Error de conexión al cargar la matriz', 'error');
        }
    }

    // === RENDER MATRIZ ===
    function renderMatrix() {
        const wrapper = document.getElementById('matrix-table-wrapper');
        if (!wrapper) return;

        if (!matrixStatuses.length) {
            wrapper.innerHTML = '<div class="text-muted small p-2">Sin estados configurados.</div>';
            return;
        }

        // Encabezados de columna (destino)
        const colHeaders = matrixStatuses.map(function (s) {
            const inactiveCls = s.is_active ? '' : ' opacity-50';
            return `
                <th class="col-header${inactiveCls}" title="${escapeHtml(s.label)} (${escapeHtml(s.code)})">
                    <span class="matrix-col-label">${escapeHtml(s.label)}</span>
                </th>`;
        }).join('');

        // Filas (origen)
        const rows = matrixStatuses.map(function (fromStatus) {
            const fromInactive = !fromStatus.is_active;
            const rowOpacity = fromInactive ? ' class="opacity-50"' : '';

            const cells = matrixStatuses.map(function (toStatus) {
                return renderCell(fromStatus, toStatus);
            }).join('');

            return `
                <tr${rowOpacity}>
                    <th class="row-header" title="${escapeHtml(fromStatus.label)} (${escapeHtml(fromStatus.code)})">
                        <span class="badge ${escapeHtml(fromStatus.badge_class || 'bg-secondary')}" style="font-size:0.7rem;">
                            <i class="fas ${escapeHtml(fromStatus.icon || 'fa-circle')} me-1"></i>${escapeHtml(fromStatus.label)}
                        </span>
                    </th>
                    ${cells}
                </tr>`;
        }).join('');

        wrapper.innerHTML = `
            <table class="transitions-matrix" id="transitions-matrix-table">
                <thead>
                    <tr>
                        <th class="matrix-corner-header">
                            <span class="matrix-from-label">Desde \\ Hacia</span>
                        </th>
                        ${colHeaders}
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>`;

        wrapper.querySelectorAll('.matrix-cell').forEach(function (cell) {
            cell.addEventListener('click', handleCellClick);
        });

        updateSaveButton();
    }

    function renderCell(fromStatus, toStatus) {
        const isDiagonal = (fromStatus.id === toStatus.id);
        const fromInactive = !fromStatus.is_active;
        const toInactive   = !toStatus.is_active;

        if (isDiagonal) {
            return `<td class="matrix-cell matrix-cell--diagonal" data-from="${fromStatus.id}" data-to="${toStatus.id}">
                        <span class="matrix-cell-diagonal">—</span>
                    </td>`;
        }

        if (fromInactive || toInactive) {
            return `<td class="matrix-cell matrix-cell--disabled"
                        data-from="${fromStatus.id}" data-to="${toStatus.id}"
                        title="Estado inactivo — no se puede crear esta transición">
                        <span class="matrix-cell-disabled">×</span>
                    </td>`;
        }

        const t = getTransition(fromStatus.id, toStatus.id);

        if (!t) {
            return `<td class="matrix-cell matrix-cell--inactive"
                        data-from="${fromStatus.id}" data-to="${toStatus.id}"
                        title="Sin transición — click para activar">
                    </td>`;
        }

        const hasReqs = !!(t.required_perm || (t.required_fields && t.required_fields.length));
        const reqIcon = hasReqs ? '<i class="fas fa-lock matrix-cell-lock" title="Tiene requisitos configurados"></i>' : '';

        if (t.is_active) {
            return `<td class="matrix-cell matrix-cell--active"
                        data-from="${fromStatus.id}" data-to="${toStatus.id}"
                        data-tid="${t.id}"
                        title="Transición activa — click para editar">
                        <i class="fas fa-check matrix-cell-check"></i>${reqIcon}
                    </td>`;
        } else {
            return `<td class="matrix-cell matrix-cell--soft-deleted"
                        data-from="${fromStatus.id}" data-to="${toStatus.id}"
                        data-tid="${t.id}"
                        title="Transición desactivada — click para reactivar">
                        <span class="matrix-cell-dot"></span>
                    </td>`;
        }
    }

    // === CLICK EN CELDA ===
    function handleCellClick(e) {
        const cell = e.currentTarget;
        const fromId = parseInt(cell.dataset.from, 10);
        const toId   = parseInt(cell.dataset.to, 10);

        if (cell.classList.contains('matrix-cell--diagonal')) return;
        if (cell.classList.contains('matrix-cell--disabled')) return;

        const t = getTransition(fromId, toId);

        if (!t) {
            // Sin transición: crear localmente y marcar como pendiente
            activateTransitionLocal(fromId, toId);
        } else if (t.is_active) {
            // Transición activa: abrir modal edición
            openTransitionModal(fromId, toId, t);
        } else {
            // Transición soft-deleted: reactivar local
            t.is_active = true;
            pendingChanges = true;
            rerenderCell(fromId, toId);
            updateSaveButton();
            HelpdeskUtils.showToast('Transición reactivada. Recuerda guardar la matriz.', 'info');
        }
    }

    function activateTransitionLocal(fromId, toId) {
        // Crear objeto de transición local pendiente (sin ID hasta que se guarde)
        setTransition(fromId, toId, {
            id: null,
            from_status_id: fromId,
            to_status_id: toId,
            is_active: true,
            required_perm: null,
            required_fields: null,
        });
        pendingChanges = true;
        rerenderCell(fromId, toId);
        updateSaveButton();
        HelpdeskUtils.showToast('Transición marcada. Recuerda guardar la matriz.', 'info');
    }

    // === RERENDER CELDA INDIVIDUAL ===
    function rerenderCell(fromId, toId) {
        const table = document.getElementById('transitions-matrix-table');
        if (!table) return;

        const cell = table.querySelector('.matrix-cell[data-from="' + fromId + '"][data-to="' + toId + '"]');
        if (!cell) return;

        const fromStatus = matrixStatuses.find(function (s) { return s.id === fromId; });
        const toStatus   = matrixStatuses.find(function (s) { return s.id === toId; });
        if (!fromStatus || !toStatus) return;

        const newCellHtml = renderCell(fromStatus, toStatus);
        const tmp = document.createElement('tbody');
        tmp.innerHTML = '<tr>' + newCellHtml + '</tr>';
        const newCell = tmp.querySelector('td');
        if (newCell) {
            newCell.addEventListener('click', handleCellClick);
            cell.parentNode.replaceChild(newCell, cell);
        }
    }

    // === MODAL TRANSICIÓN ===
    function openTransitionModal(fromId, toId, transition) {
        const modal = document.getElementById('modal-transition-edit');
        if (!modal) return;

        const fromStatus = matrixStatuses.find(function (s) { return s.id === fromId; });
        const toStatus   = matrixStatuses.find(function (s) { return s.id === toId; });

        modal.querySelector('#trans-edit-from-id').value = fromId;
        modal.querySelector('#trans-edit-to-id').value   = toId;
        modal.querySelector('#trans-edit-tid').value      = transition.id || '';

        // Labels de visualización
        const fromLabel = modal.querySelector('#trans-edit-from-label');
        const toLabel   = modal.querySelector('#trans-edit-to-label');
        if (fromLabel && fromStatus) fromLabel.textContent = fromStatus.label + ' (' + fromStatus.code + ')';
        if (toLabel   && toStatus)   toLabel.textContent   = toStatus.label   + ' (' + toStatus.code   + ')';

        // required_perm
        const permInput = modal.querySelector('#trans-edit-perm');
        if (permInput) permInput.value = transition.required_perm || '';

        // required_fields checkboxes
        const currentFields = Array.isArray(transition.required_fields) ? transition.required_fields : [];
        REQUIRED_FIELDS_OPTIONS.forEach(function (opt) {
            const chk = modal.querySelector('#trans-field-' + opt.value);
            if (chk) chk.checked = currentFields.indexOf(opt.value) !== -1;
        });

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    // === BIND MODAL TRANSICIÓN ===
    function bindTransitionModal() {
        const modal = document.getElementById('modal-transition-edit');
        if (!modal) return;
        if (modal.dataset.transListenerBound) return;
        modal.dataset.transListenerBound = '1';

        // Botón "Guardar cambios de transición"
        const btnSave = modal.querySelector('#btn-trans-edit-save');
        if (btnSave) {
            btnSave.addEventListener('click', function () {
                handleSaveTransitionModal(modal);
            });
        }

        // Botón "Desactivar transición" (soft delete local)
        const btnDeactivate = modal.querySelector('#btn-trans-deactivate');
        if (btnDeactivate) {
            btnDeactivate.addEventListener('click', function () {
                handleDeactivateTransition(modal);
            });
        }
    }

    function handleSaveTransitionModal(modal) {
        const fromId = parseInt(modal.querySelector('#trans-edit-from-id').value, 10);
        const toId   = parseInt(modal.querySelector('#trans-edit-to-id').value, 10);

        const permInput = modal.querySelector('#trans-edit-perm');
        const required_perm = permInput ? (permInput.value.trim() || null) : null;

        const selectedFields = [];
        REQUIRED_FIELDS_OPTIONS.forEach(function (opt) {
            const chk = modal.querySelector('#trans-field-' + opt.value);
            if (chk && chk.checked) selectedFields.push(opt.value);
        });
        const required_fields = selectedFields.length ? selectedFields : null;

        const t = getTransition(fromId, toId);
        if (t) {
            t.required_perm   = required_perm;
            t.required_fields = required_fields;
            t.is_active       = true;
        } else {
            setTransition(fromId, toId, {
                id: null,
                from_status_id: fromId,
                to_status_id: toId,
                is_active: true,
                required_perm: required_perm,
                required_fields: required_fields,
            });
        }

        pendingChanges = true;
        bootstrap.Modal.getInstance(modal).hide();
        rerenderCell(fromId, toId);
        updateSaveButton();
        HelpdeskUtils.showToast('Transición actualizada localmente. Recuerda guardar la matriz.', 'info');
    }

    function handleDeactivateTransition(modal) {
        const fromId = parseInt(modal.querySelector('#trans-edit-from-id').value, 10);
        const toId   = parseInt(modal.querySelector('#trans-edit-to-id').value, 10);

        HelpdeskUtils.confirmDialog(
            'Desactivar transición',
            'La transición de <strong>' + escapeHtml(getStatusLabel(fromId)) + '</strong> a ' +
            '<strong>' + escapeHtml(getStatusLabel(toId)) + '</strong> será desactivada. ' +
            '¿Continuar?',
            'Desactivar',
            'Cancelar'
        ).then(function (confirmed) {
            if (!confirmed) return;

            const t = getTransition(fromId, toId);
            if (t) {
                t.is_active = false;
            }
            pendingChanges = true;
            bootstrap.Modal.getInstance(modal).hide();
            rerenderCell(fromId, toId);
            updateSaveButton();
            HelpdeskUtils.showToast('Transición desactivada localmente. Recuerda guardar la matriz.', 'info');
        });
    }

    function getStatusLabel(id) {
        const s = matrixStatuses.find(function (st) { return st.id === id; });
        return s ? s.label : String(id);
    }

    // === GUARDAR MATRIZ (BULK) ===
    async function handleSaveMatrix() {
        const btn = document.getElementById('btn-save-matrix');
        if (btn) btn.disabled = true;

        // Recopilar TODOS los pares activos de la matriz local
        const transitions = [];
        transitionsMap.forEach(function (t) {
            if (!t) return;
            // Enviar activos e inactivos para que el bulk haga el upsert correcto
            transitions.push({
                from_status_id: t.from_status_id,
                to_status_id:   t.to_status_id,
                required_perm:  t.required_perm  || null,
                required_fields: t.required_fields || null,
                is_active:      t.is_active !== false,
            });
        });

        try {
            const res = await fetch(BULK_URL, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ transitions: transitions }),
            });

            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al guardar la matriz');
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }

            const data = await res.json();
            HelpdeskUtils.showToast(data.message || 'Matriz guardada exitosamente', 'success');
            pendingChanges = false;
            // Recargar para obtener IDs reales del backend
            await loadMatrix();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión al guardar la matriz', 'error');
        } finally {
            if (btn) {
                btn.disabled = !pendingChanges;
            }
        }
    }

    function updateSaveButton() {
        const btn = document.getElementById('btn-save-matrix');
        if (btn) {
            btn.disabled = !pendingChanges;
            if (pendingChanges) {
                btn.classList.add('btn-warning');
                btn.classList.remove('btn-success');
                btn.innerHTML = '<i class="fas fa-exclamation-circle me-1"></i><span class="d-none d-sm-inline">Guardar cambios pendientes</span>';
            } else {
                btn.classList.remove('btn-warning');
                btn.classList.add('btn-success');
                btn.innerHTML = '<i class="fas fa-save me-1"></i><span class="d-none d-sm-inline">Guardar matriz</span>';
            }
        }
    }

})();
