/**
 * catalogs_tab.js — CRUD de catálogos simples para el tab #tipos
 * en la página de Configuración de Mantenimiento.
 *
 * Maneja DOS catálogos independientes con la misma forma:
 *   - Tipo de mantenimiento  (/api/maint/v2/config/maint-types)
 *   - Origen del servicio    (/api/maint/v2/config/service-origins)
 *
 * Carga lazy: window.MaintConfigCatalogs.init() es invocado por
 * config_main.js la primera vez que se activa el tab #tipos.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *   - SortableJS         (CDN, ya cargado por config.html)
 */

'use strict';

// === ESTADO ===
var _initialized = false;

// Estado por catálogo (keyed por catalogKey)
var _state = {};

// Modal compartido entre catálogos
var _modal = null;
var _activeCatalogKey = null;

// === CONFIGURACIÓN DE CATÁLOGOS ===
var CATALOGS = {
    'maint-types': {
        key:         'maint-types',
        apiBase:     '/api/maint/v2/config/maint-types',
        entityLabel: 'tipo de mantenimiento',
        entityLabelPlural: 'tipos de mantenimiento',
        icon:        'fa-wrench',
        tbodyId:     'tbody-maint-types',
        btnNewId:    'btn-nuevo-maint-type',
        dataAttr:    'data-maint-type-id',
    },
    'service-origins': {
        key:         'service-origins',
        apiBase:     '/api/maint/v2/config/service-origins',
        entityLabel: 'origen del servicio',
        entityLabelPlural: 'orígenes del servicio',
        icon:        'fa-project-diagram',
        tbodyId:     'tbody-service-origins',
        btnNewId:    'btn-nuevo-service-origin',
        dataAttr:    'data-service-origin-id',
    },
};

// Regex de validación del código (igual que el servidor)
var CODE_RE = /^[A-Z][A-Z0-9_]*$/;

// === API PÚBLICA ===
window.MaintConfigCatalogs = {
    init: function () {
        if (_initialized) return;
        _initialized = true;
        _setupModal();
        Object.keys(CATALOGS).forEach(function (key) {
            _state[key] = {
                items:          [],
                sortable:       null,
                reorderPending: false,
                editingId:      null,
            };
            _setupCatalog(CATALOGS[key]);
            _loadCatalog(key);
        });
    },
};

// === SETUP MODAL COMPARTIDO ===
function _setupModal() {
    _modal = new bootstrap.Modal(document.getElementById('modal-catalog'));

    document.getElementById('btn-guardar-catalog').addEventListener('click', _handleSave);

    // Convertir code a mayúsculas en tiempo real
    document.getElementById('catalog-code').addEventListener('input', function () {
        var pos = this.selectionStart;
        this.value = this.value.toUpperCase();
        this.setSelectionRange(pos, pos);
    });
}

// === SETUP POR CATÁLOGO ===
function _setupCatalog(cfg) {
    var btnNew = document.getElementById(cfg.btnNewId);
    if (btnNew) {
        btnNew.addEventListener('click', function () {
            _openCreateModal(cfg.key);
        });
    }

    var tbody = document.getElementById(cfg.tbodyId);
    if (tbody) {
        tbody.addEventListener('click', function (e) {
            _handleTableAction(e, cfg.key);
        });
    }
}

// === CARGA DE DATOS ===
async function _loadCatalog(key) {
    var cfg = CATALOGS[key];
    var tbody = document.getElementById(cfg.tbodyId);
    if (!tbody) return;

    tbody.innerHTML =
        '<tr><td colspan="4" class="text-center py-4 text-muted">' +
        '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
        'Cargando ' + cfg.entityLabelPlural + '...</td></tr>';

    try {
        var data = await MaintUtils.api.fetch(cfg.apiBase);
        _state[key].items = data.data || [];
        _renderTable(key);
        _initSortable(key);
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al cargar ' + cfg.entityLabelPlural, 'error');
        tbody.innerHTML =
            '<tr><td colspan="4" class="text-center py-4 text-danger small">' +
            '<i class="fas fa-exclamation-circle me-1"></i>' +
            MaintUtils.escapeHtml(e.message || 'Error de conexión') +
            '</td></tr>';
    }
}

// === RENDER ===
function _renderTable(key) {
    var cfg   = CATALOGS[key];
    var items = _state[key].items;
    var tbody = document.getElementById(cfg.tbodyId);
    if (!tbody) return;

    if (!items.length) {
        tbody.innerHTML =
            '<tr><td colspan="4" class="text-center py-5 text-muted">' +
            '<i class="fas ' + cfg.icon + ' fa-2x mb-3 d-block opacity-50"></i>' +
            'Sin ' + cfg.entityLabelPlural + '. Crea el primero con el botón "Nuevo".' +
            '</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(function (item) {
        var activeBadge = item.is_active
            ? '<span class="badge bg-success-subtle text-success border border-success-subtle">Activo</span>'
            : '<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">Inactivo</span>';

        var toggleIcon  = item.is_active ? 'fa-toggle-on text-success' : 'fa-toggle-off text-secondary';
        var toggleTitle = item.is_active ? 'Desactivar' : 'Activar';

        return '<tr data-catalog-id="' + item.id + '" data-order="' + item.display_order + '">' +
            '<td class="mn-cat-handle text-center" style="cursor:grab; color: var(--maint-muted,#607D8B);">' +
                '<i class="fas fa-grip-vertical"></i>' +
            '</td>' +
            '<td><code class="mn-cat-code">' + MaintUtils.escapeHtml(item.code) + '</code></td>' +
            '<td>' + MaintUtils.escapeHtml(item.label) + '</td>' +
            '<td class="text-center">' + activeBadge + '</td>' +
            '<td class="text-end">' +
                '<div class="btn-group btn-group-sm" role="group">' +
                    '<button class="btn btn-outline-secondary" ' +
                            'data-action="edit" data-id="' + item.id + '" ' +
                            'title="Editar">' +
                        '<i class="fas fa-pencil-alt"></i>' +
                    '</button>' +
                    '<button class="btn btn-outline-secondary" ' +
                            'data-action="toggle" data-id="' + item.id + '" ' +
                            'title="' + toggleTitle + '">' +
                        '<i class="fas ' + toggleIcon + '"></i>' +
                    '</button>' +
                '</div>' +
            '</td>' +
        '</tr>';
    }).join('');
}

// === SORTABLE ===
function _initSortable(key) {
    var cfg   = CATALOGS[key];
    var tbody = document.getElementById(cfg.tbodyId);
    if (!tbody || !window.Sortable) return;

    var st = _state[key];
    if (st.sortable) {
        st.sortable.destroy();
        st.sortable = null;
    }

    st.sortable = Sortable.create(tbody, {
        handle:     '.mn-cat-handle',
        animation:  150,
        ghostClass: 'mn-cat-row--ghost',
        onEnd: function () {
            _commitReorder(key);
        },
    });
}

async function _commitReorder(key) {
    var st = _state[key];
    if (st.reorderPending) return;
    st.reorderPending = true;

    var cfg  = CATALOGS[key];
    var rows = document.querySelectorAll('#' + cfg.tbodyId + ' tr[data-catalog-id]');
    var order = Array.from(rows).map(function (row, idx) {
        return { id: parseInt(row.getAttribute('data-catalog-id'), 10), display_order: idx };
    });

    try {
        await MaintUtils.api.fetch(cfg.apiBase + '/reorder', {
            method: 'PUT',
            body:   JSON.stringify({ order: order }),
        });
        MaintUtils.toast('Orden guardado', 'success');
        order.forEach(function (o) {
            var item = st.items.find(function (i) { return i.id === o.id; });
            if (item) item.display_order = o.display_order;
        });
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al guardar el orden', 'error');
        _renderTable(key);
        _initSortable(key);
    } finally {
        st.reorderPending = false;
    }
}

// === DELEGACIÓN DE ACCIONES EN TABLA ===
function _handleTableAction(e, key) {
    var btn = e.target.closest('[data-action]');
    if (!btn || btn.disabled) return;

    var action = btn.dataset.action;
    var id     = parseInt(btn.dataset.id, 10);
    var item   = _state[key].items.find(function (i) { return i.id === id; });
    if (!item) return;

    if (action === 'edit') {
        _openEditModal(key, item);
    } else if (action === 'toggle') {
        _handleToggle(key, item, btn);
    }
}

// === MODAL CREAR ===
function _openCreateModal(key) {
    var cfg = CATALOGS[key];
    _activeCatalogKey = key;
    _state[key].editingId = null;

    document.getElementById('modal-catalog-label').textContent =
        'Nuevo ' + cfg.entityLabel;
    document.getElementById('catalog-entity-name').textContent = cfg.entityLabel;

    _resetModalForm();

    var codeGroup = document.getElementById('catalog-code-group');
    var codeInput = document.getElementById('catalog-code');
    codeGroup.classList.remove('d-none');
    codeInput.disabled = false;

    _modal.show();
}

// === MODAL EDITAR ===
function _openEditModal(key, item) {
    var cfg = CATALOGS[key];
    _activeCatalogKey = key;
    _state[key].editingId = item.id;

    document.getElementById('modal-catalog-label').textContent =
        'Editar ' + cfg.entityLabel + ' — ' + item.code;
    document.getElementById('catalog-entity-name').textContent = cfg.entityLabel;

    _resetModalForm();

    document.getElementById('catalog-edit-id').value    = item.id;
    document.getElementById('catalog-code').value       = item.code || '';
    document.getElementById('catalog-code').disabled    = true;
    document.getElementById('catalog-label').value      = item.label || '';
    document.getElementById('catalog-display-order').value =
        item.display_order !== null ? item.display_order : 0;

    document.getElementById('catalog-code-group').classList.remove('d-none');

    _modal.show();
}

// === RESET FORM ===
function _resetModalForm() {
    var form = document.getElementById('form-catalog');
    form.classList.remove('was-validated');
    form.reset();

    document.getElementById('catalog-edit-id').value        = '';
    document.getElementById('catalog-code').value           = '';
    document.getElementById('catalog-label').value          = '';
    document.getElementById('catalog-display-order').value  = 0;

    ['catalog-code', 'catalog-label'].forEach(function (id) {
        var el   = document.getElementById(id);
        var errEl = document.getElementById(id + '-err');
        if (el)    el.classList.remove('is-invalid');
        if (errEl) errEl.textContent = '';
    });
}

// === GUARDAR ===
async function _handleSave() {
    var key = _activeCatalogKey;
    if (!key) return;

    var cfg  = CATALOGS[key];
    var st   = _state[key];
    var btn  = document.getElementById('btn-guardar-catalog');

    var code         = document.getElementById('catalog-code').value.trim();
    var label        = document.getElementById('catalog-label').value.trim();
    var displayOrder = parseInt(document.getElementById('catalog-display-order').value, 10) || 0;

    // Validación cliente
    var valid = true;

    if (!st.editingId) {
        if (!code || !CODE_RE.test(code)) {
            _setFieldError(
                'catalog-code',
                'Código requerido: mayúsculas, dígitos y guion bajo, empieza con letra (ej. PREV).'
            );
            valid = false;
        } else {
            _clearFieldError('catalog-code');
        }
    }

    if (!label) {
        _setFieldError('catalog-label', 'La etiqueta es requerida.');
        valid = false;
    } else {
        _clearFieldError('catalog-label');
    }

    if (!valid) return;

    MaintUtils.loading.show(btn, 'Guardando...');
    try {
        if (st.editingId) {
            await MaintUtils.api.fetch(cfg.apiBase + '/' + st.editingId, {
                method: 'PATCH',
                body:   JSON.stringify({ label: label, display_order: displayOrder }),
            });
            MaintUtils.toast(
                _capitalize(cfg.entityLabel) + ' actualizado correctamente',
                'success'
            );
        } else {
            await MaintUtils.api.fetch(cfg.apiBase, {
                method: 'POST',
                body:   JSON.stringify({ code: code, label: label, display_order: displayOrder }),
            });
            MaintUtils.toast(
                _capitalize(cfg.entityLabel) + ' creado correctamente',
                'success'
            );
        }
        _modal.hide();
        await _loadCatalog(key);
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al guardar', 'error');
    } finally {
        MaintUtils.loading.hide(btn);
    }
}

// === TOGGLE ACTIVO ===
async function _handleToggle(key, item, btn) {
    var cfg      = CATALOGS[key];
    var newState = !item.is_active;

    MaintUtils.confirm({
        title:        (newState ? 'Activar' : 'Desactivar') + ' ' + cfg.entityLabel,
        message:      '¿Deseas ' + (newState ? 'activar' : 'desactivar') +
                      ' "' + item.label + '"?',
        confirmLabel: newState ? 'Activar' : 'Desactivar',
        confirmClass: newState ? 'btn-success' : 'btn-warning',
        onConfirm: async function () {
            MaintUtils.loading.show(btn, '');
            try {
                await MaintUtils.api.fetch(cfg.apiBase + '/' + item.id + '/toggle', {
                    method: 'PATCH',
                    body:   JSON.stringify({ is_active: newState }),
                });
                MaintUtils.toast(
                    _capitalize(cfg.entityLabel) + (newState ? ' activado' : ' desactivado'),
                    newState ? 'success' : 'warning'
                );
                await _loadCatalog(key);
            } catch (e) {
                // El servidor puede devolver 400 si es el último activo
                MaintUtils.toast(e.message || 'Error al cambiar estado', 'error');
                MaintUtils.loading.hide(btn);
            }
        },
    });
}

// === UTILIDADES DE VALIDACIÓN ===
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

// === UTILIDADES GENÉRICAS ===
function _capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}
