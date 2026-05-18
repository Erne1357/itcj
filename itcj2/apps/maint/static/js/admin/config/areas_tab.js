/**
 * areas_tab.js — CRUD de catálogo de áreas técnicas + asignación técnico↔área
 * para el tab #areas en la página de Configuración de Mantenimiento.
 *
 * Carga lazy: window.MaintConfigAreas.init() es invocado por
 * config_main.js la primera vez que se activa el tab #areas.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *   - SortableJS         (CDN, ya cargado por config.html)
 *
 * Portado de areas.js (MaintAdminAreas):
 *   - loadTechnicians / renderTable (técnicos)
 *   - openAssignModal / saveArea / removeArea
 * Cambios respecto al original:
 *   - El catálogo de áreas se carga desde /api/maint/v2/config/areas (dinámico),
 *     no desde la lista hardcoded de AREAS en areas.js.
 *   - El select de asignación se alimenta de las áreas activas del catálogo.
 *   - La leyenda se reemplaza por la tabla CRUD de catálogo con drag-reorder.
 *   - Se usa el ID de IDs de HTML del panel de config (sin colisión con areas.html).
 */

'use strict';

// === ESTADO ===
var _initialized = false;

// Catálogo de áreas
var _areas = [];
var _areaModal = null;
var _editingAreaId = null;
var _areaSortable = null;
var _areaReorderPending = false;

// Técnicos
var _technicians = [];
var _assignModal = null;

// === CONSTANTES ===
var API_AREAS      = '/api/maint/v2/config/areas';
var API_TECHNICIANS = '/api/maint/v2/technicians';
var CODE_RE        = /^[A-Z][A-Z0-9_]*$/;

// === API PÚBLICA (lazy init) ===
window.MaintConfigAreas = {
    init: function () {
        if (_initialized) return;
        _initialized = true;
        _setupAreaCatalog();
        _setupAssignSection();
        _loadAreas();
        _loadTechnicians();
    },
    // Expuesto para onclick inline en filas de técnicos
    openAssignModal: _openAssignModal,
    removeArea: _removeTechnicianArea,
};

// ─────────────────────────────────────────────────────────────────────────────
// SETUP
// ─────────────────────────────────────────────────────────────────────────────

function _setupAreaCatalog() {
    _areaModal = new bootstrap.Modal(document.getElementById('modal-area'));

    // Botón nueva área
    document.getElementById('btn-nueva-area').addEventListener('click', _openCreateAreaModal);

    // Guardar área
    document.getElementById('btn-guardar-area').addEventListener('click', _handleSaveArea);

    // Preview icono en vivo
    document.getElementById('area-icon').addEventListener('input', _updateAreaPreview);

    // Sync color ↔ hex
    document.getElementById('area-color').addEventListener('input', _syncHexFromColor);
    document.getElementById('area-hex').addEventListener('input', _syncColorFromHex);

    // Preview label en vivo
    document.getElementById('area-label').addEventListener('input', _updateAreaPreview);

    // Código: forzar mayúsculas
    document.getElementById('area-code').addEventListener('input', function () {
        var pos = this.selectionStart;
        this.value = this.value.toUpperCase();
        this.setSelectionRange(pos, pos);
    });

    // Delegación de acciones en tabla de catálogo
    document.getElementById('tbody-areas').addEventListener('click', _handleAreaTableAction);
}

function _setupAssignSection() {
    _assignModal = new bootstrap.Modal(document.getElementById('modal-assign-area'));

    document.getElementById('btn-save-assign-area').addEventListener('click', _saveAssignArea);

    document.getElementById('btn-recargar-tecnicos').addEventListener('click', function () {
        _loadTechnicians();
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// CATÁLOGO DE ÁREAS — CARGA Y RENDER
// ─────────────────────────────────────────────────────────────────────────────

async function _loadAreas() {
    var tbody = document.getElementById('tbody-areas');
    tbody.innerHTML =
        '<tr><td colspan="6" class="text-center py-4 text-muted">' +
        '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
        'Cargando áreas...</td></tr>';

    try {
        var data = await MaintUtils.api.fetch(API_AREAS);
        _areas = data.data || [];
        _renderAreaTable(_areas);
        _initAreaSortable();
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al cargar áreas', 'error');
        tbody.innerHTML =
            '<tr><td colspan="6" class="text-center py-4 text-danger small">' +
            '<i class="fas fa-exclamation-circle me-1"></i>' +
            MaintUtils.escapeHtml(e.message || 'Error de conexión') +
            '</td></tr>';
    }
}

function _renderAreaTable(items) {
    var tbody = document.getElementById('tbody-areas');

    if (!items.length) {
        tbody.innerHTML =
            '<tr><td colspan="6" class="text-center py-5 text-muted">' +
            '<i class="fas fa-users-cog fa-2x mb-3 d-block opacity-50"></i>' +
            'Sin áreas. Crea la primera con el botón "Nueva área".' +
            '</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(function (area) {
        var activeBadge = area.is_active
            ? '<span class="badge bg-success-subtle text-success border border-success-subtle">Activa</span>'
            : '<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">Inactiva</span>';

        var toggleIcon  = area.is_active ? 'fa-toggle-on text-success' : 'fa-toggle-off text-secondary';
        var toggleTitle = area.is_active ? 'Desactivar' : 'Activar';

        var iconClass = area.icon ? MaintUtils.escapeHtml(area.icon) : 'bi-question-circle';
        var color     = area.color ? MaintUtils.escapeHtml(area.color) : '#607D8B';

        var iconPreview =
            '<span class="mn-area-icon-dot me-2" style="background:' + color + '20;border:1.5px solid ' + color + ';color:' + color + ';">' +
                '<i class="bi ' + iconClass + '"></i>' +
            '</span>';

        var descHtml = area.description
            ? '<span class="text-muted small">' + MaintUtils.escapeHtml(area.description) + '</span>'
            : '<span class="text-muted small fst-italic">—</span>';

        return '<tr data-area-id="' + area.id + '" data-order="' + area.display_order + '">' +
            '<td class="mn-cat-handle text-center" style="cursor:grab; color: var(--maint-muted,#607D8B);">' +
                '<i class="fas fa-grip-vertical"></i>' +
            '</td>' +
            '<td><code class="mn-cat-code">' + MaintUtils.escapeHtml(area.code) + '</code></td>' +
            '<td>' +
                '<div class="d-flex align-items-center">' +
                    iconPreview +
                    '<span class="fw-medium">' + MaintUtils.escapeHtml(area.label) + '</span>' +
                '</div>' +
            '</td>' +
            '<td class="d-none d-md-table-cell">' + descHtml + '</td>' +
            '<td class="text-center">' + activeBadge + '</td>' +
            '<td class="text-end">' +
                '<div class="btn-group btn-group-sm" role="group">' +
                    '<button class="btn btn-outline-secondary" ' +
                            'data-action="edit" data-id="' + area.id + '" ' +
                            'title="Editar área">' +
                        '<i class="fas fa-pencil-alt"></i>' +
                    '</button>' +
                    '<button class="btn btn-outline-secondary" ' +
                            'data-action="toggle" data-id="' + area.id + '" ' +
                            'title="' + toggleTitle + '">' +
                        '<i class="fas ' + toggleIcon + '"></i>' +
                    '</button>' +
                '</div>' +
            '</td>' +
        '</tr>';
    }).join('');
}

// ─────────────────────────────────────────────────────────────────────────────
// SORTABLE — catálogo de áreas
// ─────────────────────────────────────────────────────────────────────────────

function _initAreaSortable() {
    var tbody = document.getElementById('tbody-areas');
    if (!tbody || !window.Sortable) return;

    if (_areaSortable) {
        _areaSortable.destroy();
        _areaSortable = null;
    }

    _areaSortable = Sortable.create(tbody, {
        handle:     '.mn-cat-handle',
        animation:  150,
        ghostClass: 'mn-cat-row--ghost',
        onEnd: function () {
            _commitAreaReorder();
        },
    });
}

async function _commitAreaReorder() {
    if (_areaReorderPending) return;
    _areaReorderPending = true;

    var rows  = document.querySelectorAll('#tbody-areas tr[data-area-id]');
    var order = Array.from(rows).map(function (row, idx) {
        return { id: parseInt(row.getAttribute('data-area-id'), 10), display_order: idx };
    });

    try {
        await MaintUtils.api.fetch(API_AREAS + '/reorder', {
            method: 'PUT',
            body: JSON.stringify({ order: order }),
        });
        MaintUtils.toast('Orden guardado', 'success');
        order.forEach(function (o) {
            var area = _areas.find(function (a) { return a.id === o.id; });
            if (area) area.display_order = o.display_order;
        });
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al guardar el orden', 'error');
        _renderAreaTable(_areas);
        _initAreaSortable();
    } finally {
        _areaReorderPending = false;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// DELEGACIÓN DE ACCIONES EN TABLA DE CATÁLOGO
// ─────────────────────────────────────────────────────────────────────────────

function _handleAreaTableAction(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn || btn.disabled) return;

    var action = btn.dataset.action;
    var id     = parseInt(btn.dataset.id, 10);
    var area   = _areas.find(function (a) { return a.id === id; });
    if (!area) return;

    if (action === 'edit') {
        _openEditAreaModal(area);
    } else if (action === 'toggle') {
        _handleAreaToggle(area, btn);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MODAL ÁREA — CREAR / EDITAR
// ─────────────────────────────────────────────────────────────────────────────

function _openCreateAreaModal() {
    _editingAreaId = null;
    document.getElementById('modal-area-label').textContent = 'Nueva área técnica';
    _resetAreaForm();
    document.getElementById('area-code').disabled = false;
    document.getElementById('area-code-group').classList.remove('d-none');
    _areaModal.show();
}

function _openEditAreaModal(area) {
    _editingAreaId = area.id;
    document.getElementById('modal-area-label').textContent = 'Editar área — ' + area.code;
    _resetAreaForm();

    document.getElementById('area-edit-id').value         = area.id;
    document.getElementById('area-code').value            = area.code || '';
    document.getElementById('area-code').disabled         = true;
    document.getElementById('area-code-group').classList.remove('d-none');
    document.getElementById('area-label').value           = area.label || '';
    document.getElementById('area-icon').value            = area.icon || '';
    document.getElementById('area-color').value           = area.color || '#1565C0';
    document.getElementById('area-hex').value             = area.color || '#1565C0';
    document.getElementById('area-description').value     = area.description || '';
    document.getElementById('area-display-order').value   = area.display_order !== null ? area.display_order : 0;

    _updateAreaPreview();
    _areaModal.show();
}

function _resetAreaForm() {
    var form = document.getElementById('form-area');
    form.classList.remove('was-validated');
    form.reset();

    document.getElementById('area-edit-id').value        = '';
    document.getElementById('area-code').value           = '';
    document.getElementById('area-label').value          = '';
    document.getElementById('area-icon').value           = '';
    document.getElementById('area-color').value          = '#1565C0';
    document.getElementById('area-hex').value            = '#1565C0';
    document.getElementById('area-description').value    = '';
    document.getElementById('area-display-order').value  = 0;

    ['area-code', 'area-label'].forEach(function (id) {
        var el    = document.getElementById(id);
        var errEl = document.getElementById(id + '-err');
        if (el)    el.classList.remove('is-invalid');
        if (errEl) errEl.textContent = '';
    });

    _updateAreaPreview();
}

// ─────────────────────────────────────────────────────────────────────────────
// PREVIEW EN VIVO — MODAL ÁREA
// ─────────────────────────────────────────────────────────────────────────────

function _updateAreaPreview() {
    var iconVal  = document.getElementById('area-icon').value.trim() || 'bi-question-circle';
    var labelVal = document.getElementById('area-label').value.trim() || 'Etiqueta';
    var colorVal = document.getElementById('area-color').value || '#1565C0';

    // Preview icono en el input-group
    var previewI = document.getElementById('area-icon-preview-i');
    if (previewI) {
        previewI.className = 'bi ' + MaintUtils.escapeHtml(iconVal);
    }

    // Preview chip completo
    var previewIcon  = document.getElementById('area-preview-icon');
    var previewLabel = document.getElementById('area-preview-label');
    var chipEl       = document.querySelector('#area-chip-preview .mn-area-chip');

    if (previewIcon)  previewIcon.className = 'bi ' + MaintUtils.escapeHtml(iconVal);
    if (previewLabel) previewLabel.textContent = labelVal;
    if (chipEl) {
        chipEl.style.background = colorVal + '20';
        chipEl.style.border     = '1.5px solid ' + colorVal;
        chipEl.style.color      = colorVal;
    }
}

function _syncHexFromColor() {
    var val = document.getElementById('area-color').value;
    document.getElementById('area-hex').value = val;
    _updateAreaPreview();
}

function _syncColorFromHex() {
    var hexVal = document.getElementById('area-hex').value.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(hexVal)) {
        document.getElementById('area-color').value = hexVal;
        _updateAreaPreview();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// GUARDAR ÁREA
// ─────────────────────────────────────────────────────────────────────────────

async function _handleSaveArea() {
    var btn = document.getElementById('btn-guardar-area');

    var code         = document.getElementById('area-code').value.trim().toUpperCase();
    var label        = document.getElementById('area-label').value.trim();
    var icon         = document.getElementById('area-icon').value.trim() || null;
    var color        = document.getElementById('area-color').value || null;
    var description  = document.getElementById('area-description').value.trim() || null;
    var displayOrder = parseInt(document.getElementById('area-display-order').value, 10) || 0;

    // Validación cliente
    var valid = true;

    if (!_editingAreaId) {
        if (!code || !CODE_RE.test(code)) {
            _setFieldError('area-code', 'Código requerido: mayúsculas, dígitos y _ (ej. ELEC).');
            valid = false;
        } else {
            _clearFieldError('area-code');
        }
    }

    if (!label) {
        _setFieldError('area-label', 'La etiqueta es requerida.');
        valid = false;
    } else {
        _clearFieldError('area-label');
    }

    if (!valid) return;

    MaintUtils.loading.show(btn, 'Guardando...');
    try {
        if (_editingAreaId) {
            var patchBody = { label: label, display_order: displayOrder };
            if (icon        !== null) patchBody.icon        = icon;
            if (color       !== null) patchBody.color       = color;
            if (description !== null) patchBody.description = description;
            else patchBody.description = null;

            await MaintUtils.api.fetch(API_AREAS + '/' + _editingAreaId, {
                method: 'PATCH',
                body: JSON.stringify(patchBody),
            });
            MaintUtils.toast('Área actualizada correctamente', 'success');
        } else {
            var createBody = { code: code, label: label, display_order: displayOrder };
            if (icon)        createBody.icon        = icon;
            if (color)       createBody.color       = color;
            if (description) createBody.description = description;

            await MaintUtils.api.fetch(API_AREAS, {
                method: 'POST',
                body: JSON.stringify(createBody),
            });
            MaintUtils.toast('Área creada correctamente', 'success');
        }
        _areaModal.hide();
        await _loadAreas();
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al guardar', 'error');
    } finally {
        MaintUtils.loading.hide(btn);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// TOGGLE ACTIVO — CATÁLOGO
// ─────────────────────────────────────────────────────────────────────────────

async function _handleAreaToggle(area, btn) {
    var newState = !area.is_active;

    MaintUtils.confirm({
        title:        (newState ? 'Activar' : 'Desactivar') + ' área',
        message:      '¿Deseas ' + (newState ? 'activar' : 'desactivar') + ' el área "' + area.label + '"?',
        confirmLabel: newState ? 'Activar' : 'Desactivar',
        confirmClass: newState ? 'btn-success' : 'btn-warning',
        onConfirm: async function () {
            MaintUtils.loading.show(btn, '');
            try {
                var res = await MaintUtils.api.fetch(API_AREAS + '/' + area.id + '/toggle', {
                    method: 'PATCH',
                    body: JSON.stringify({ is_active: newState }),
                });
                // El servidor puede devolver un warning (ej. técnicos aún asignados)
                if (res && res.data && res.data.warning) {
                    MaintUtils.alert({
                        title:   'Área desactivada con aviso',
                        message: res.data.warning,
                        type:    'warning',
                    });
                } else {
                    MaintUtils.toast(
                        'Área ' + (newState ? 'activada' : 'desactivada'),
                        newState ? 'success' : 'warning'
                    );
                }
                await _loadAreas();
            } catch (e) {
                MaintUtils.toast(e.message || 'Error al cambiar estado', 'error');
                MaintUtils.loading.hide(btn);
            }
        },
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// TÉCNICOS — CARGA Y RENDER
// (Portado de areas.js: loadTechnicians + renderTable)
// ─────────────────────────────────────────────────────────────────────────────

async function _loadTechnicians() {
    var container = document.getElementById('areas-technicians-container');
    container.innerHTML =
        '<div class="text-center py-5 text-muted">' +
        '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
        'Cargando técnicos...</div>';

    try {
        var data = await MaintUtils.api.fetch(API_TECHNICIANS);
        _technicians = data.technicians || [];
        _renderTechniciansTable();
    } catch (e) {
        container.innerHTML =
            '<div class="alert alert-danger m-3">' +
            '<i class="fas fa-exclamation-triangle me-2"></i>' +
            MaintUtils.escapeHtml(e.message || 'Error al cargar los técnicos.') +
            '</div>';
    }
}

function _renderTechniciansTable() {
    var container = document.getElementById('areas-technicians-container');

    if (!_technicians.length) {
        container.innerHTML =
            '<div class="text-center py-5 text-muted">' +
            '<i class="fas fa-users fa-2x mb-3 d-block opacity-50"></i>' +
            'No hay técnicos registrados en la aplicación de mantenimiento.' +
            '</div>';
        return;
    }

    var rows = _technicians.map(function (tech) {
        var areaBadges = (tech.areas && tech.areas.length)
            ? tech.areas.map(function (a) {
                var info = _areas.find(function (ca) { return ca.code === a.area_code; });
                var areaLabel = info ? info.label : a.area_code;
                var areaColor = (info && info.color) ? info.color : '#607D8B';
                var areaIcon  = (info && info.icon)  ? info.icon  : 'bi-question-circle';
                var primaryStar = a.is_primary
                    ? '<i class="fas fa-star ms-1" title="Área principal" style="font-size:0.6rem;color:#F59E0B;vertical-align:middle;"></i>'
                    : '';

                return '<span class="mn-tech-area-chip me-1 mb-1" ' +
                    'style="background:' + areaColor + '18;color:' + areaColor + ';border:1.5px solid ' + areaColor + '40;" ' +
                    'title="' + MaintUtils.escapeHtml(areaLabel) + (a.is_primary ? ' (principal)' : '') + '">' +
                    '<i class="bi ' + MaintUtils.escapeHtml(areaIcon) + ' me-1"></i>' +
                    MaintUtils.escapeHtml(areaLabel) +
                    primaryStar +
                    '<button type="button" class="mn-tech-area-remove" ' +
                    'onclick="window.MaintConfigAreas.removeArea(' + tech.id + ', \'' + MaintUtils.escapeHtml(a.area_code) + '\')" ' +
                    'title="Quitar área" aria-label="Quitar ' + MaintUtils.escapeHtml(areaLabel) + '">' +
                    '&times;' +
                    '</button>' +
                    '</span>';
            }).join('')
            : '<span class="text-muted small fst-italic">Sin áreas asignadas</span>';

        var initials = (tech.name || 'U')
            .split(' ')
            .slice(0, 2)
            .map(function (w) { return w[0] || ''; })
            .join('')
            .toUpperCase();

        return '<tr>' +
            '<td>' +
                '<div class="d-flex align-items-center gap-2">' +
                    '<div class="mn-tech-avatar">' + MaintUtils.escapeHtml(initials) + '</div>' +
                    '<span class="fw-semibold" style="color:var(--maint-primary-darker);">' +
                        MaintUtils.escapeHtml(tech.name) +
                    '</span>' +
                '</div>' +
            '</td>' +
            '<td>' +
                '<div class="d-flex flex-wrap align-items-center">' +
                    areaBadges +
                '</div>' +
            '</td>' +
            '<td style="width:120px;">' +
                '<button class="btn btn-sm btn-outline-primary" ' +
                    'onclick="window.MaintConfigAreas.openAssignModal(' + tech.id + ')" ' +
                    'title="Asignar área">' +
                    '<i class="fas fa-plus me-1"></i>Área' +
                '</button>' +
            '</td>' +
        '</tr>';
    }).join('');

    container.innerHTML =
        '<div class="table-responsive">' +
        '<table class="table table-hover align-middle mb-0" style="font-size:0.88rem;">' +
        '<thead class="table-light">' +
        '<tr>' +
        '<th style="min-width:180px;">Técnico</th>' +
        '<th>Áreas de especialidad</th>' +
        '<th style="width:120px;"></th>' +
        '</tr>' +
        '</thead>' +
        '<tbody>' + rows + '</tbody>' +
        '</table>' +
        '</div>';
}

// ─────────────────────────────────────────────────────────────────────────────
// MODAL ASIGNAR ÁREA A TÉCNICO
// (Portado de areas.js: openAssignModal — ahora usa /config/areas en vez de lista hardcoded)
// ─────────────────────────────────────────────────────────────────────────────

function _openAssignModal(userId) {
    var tech = _technicians.find(function (t) { return t.id === userId; });
    if (!tech) return;

    document.getElementById('assign-user-id').value   = userId;
    document.getElementById('assign-user-name').textContent = tech.name;

    // Áreas activas del catálogo que el técnico aún no tiene
    var assignedCodes = (tech.areas || []).map(function (a) { return a.area_code; });
    var available = _areas.filter(function (a) {
        return a.is_active && assignedCodes.indexOf(a.code) === -1;
    });

    var select = document.getElementById('assign-area-code');
    var saveBtn = document.getElementById('btn-save-assign-area');

    if (!available.length) {
        select.innerHTML = '<option value="">— Ya tiene todas las áreas activas —</option>';
        saveBtn.disabled = true;
    } else {
        saveBtn.disabled = false;
        select.innerHTML = available.map(function (a) {
            return '<option value="' + MaintUtils.escapeHtml(a.code) + '">' +
                MaintUtils.escapeHtml(a.label) +
                '</option>';
        }).join('');
    }

    _assignModal.show();
}

// ─────────────────────────────────────────────────────────────────────────────
// GUARDAR ASIGNACIÓN
// (Portado de areas.js: saveArea)
// ─────────────────────────────────────────────────────────────────────────────

async function _saveAssignArea() {
    var userId   = document.getElementById('assign-user-id').value;
    var areaCode = document.getElementById('assign-area-code').value;
    var btn      = document.getElementById('btn-save-assign-area');

    if (!areaCode) {
        MaintUtils.toast('Selecciona un área', 'warning');
        return;
    }

    MaintUtils.loading.show(btn, 'Asignando...');
    try {
        await MaintUtils.api.fetch(API_TECHNICIANS + '/' + userId + '/areas', {
            method: 'POST',
            body: JSON.stringify({ area_code: areaCode }),
        });
        var areaInfo = _areas.find(function (a) { return a.code === areaCode; });
        MaintUtils.toast(
            'Área ' + ((areaInfo && areaInfo.label) ? areaInfo.label : areaCode) + ' asignada',
            'success'
        );
        _assignModal.hide();
        await _loadTechnicians();
    } catch (e) {
        MaintUtils.toast((e && e.message) || 'Error al asignar área', 'error');
    } finally {
        MaintUtils.loading.hide(btn);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// QUITAR ÁREA DE TÉCNICO
// (Portado de areas.js: removeArea)
// ─────────────────────────────────────────────────────────────────────────────

function _removeTechnicianArea(userId, areaCode) {
    var areaInfo  = _areas.find(function (a) { return a.code === areaCode; });
    var areaLabel = areaInfo ? areaInfo.label : areaCode;

    MaintUtils.confirm({
        title:        'Quitar área',
        message:      '¿Quitar el área "' + areaLabel + '" de este técnico?',
        confirmLabel: 'Quitar',
        confirmClass: 'btn-warning',
        onConfirm: async function () {
            try {
                await MaintUtils.api.fetch(API_TECHNICIANS + '/' + userId + '/areas/' + areaCode, {
                    method: 'DELETE',
                });
                MaintUtils.toast('Área ' + areaLabel + ' removida', 'success');
                await _loadTechnicians();
            } catch (e) {
                MaintUtils.toast((e && e.message) || 'Error al quitar el área', 'error');
            }
        },
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// UTILIDADES DE VALIDACIÓN
// ─────────────────────────────────────────────────────────────────────────────

function _setFieldError(fieldId, msg) {
    var el    = document.getElementById(fieldId);
    var errEl = document.getElementById(fieldId + '-err');
    if (el)    el.classList.add('is-invalid');
    if (errEl) errEl.textContent = msg;
}

function _clearFieldError(fieldId) {
    var el    = document.getElementById(fieldId);
    var errEl = document.getElementById(fieldId + '-err');
    if (el)    el.classList.remove('is-invalid');
    if (errEl) errEl.textContent = '';
}

// ─────────────────────────────────────────────────────────────────────────────
// REEXPOSICIÓN PARA ONCLICK INLINE (necesario para callbacks en filas renderizadas)
// ─────────────────────────────────────────────────────────────────────────────

// Reasignar después de definir las funciones
window.MaintConfigAreas.openAssignModal = _openAssignModal;
window.MaintConfigAreas.removeArea      = _removeTechnicianArea;
