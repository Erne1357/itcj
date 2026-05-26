/**
 * priorities_tab.js — CRUD de prioridades + SLA para el tab #prioridades
 * en la página de Configuración de Mantenimiento.
 *
 * Carga lazy: window.MaintConfigPriorities.init() es invocado por
 * config_main.js la primera vez que se activa el tab #prioridades.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *   - SortableJS         (CDN, ya cargado por config.html)
 */

(function () {
    'use strict';

    // === ESTADO ===
    var _priorities = [];
    var _priModal = null;
    var _editingId = null;
    var _sortable = null;
    var _initialized = false;
    var _reorderPending = false;

    // === CONSTANTES ===
    var API_PRIORITIES = '/api/maint/v2/config/priorities';

    var BADGE_CLASS_OPTIONS = [
        { value: '',                    label: 'Por defecto (usa color)' },
        { value: 'bg-danger',           label: 'Rojo (danger)' },
        { value: 'bg-warning text-dark',label: 'Amarillo (warning)' },
        { value: 'bg-success',          label: 'Verde (success)' },
        { value: 'bg-primary',          label: 'Azul (primary)' },
        { value: 'bg-info text-dark',   label: 'Celeste (info)' },
        { value: 'bg-secondary',        label: 'Gris (secondary)' },
        { value: 'bg-dark',             label: 'Oscuro (dark)' },
    ];

    // SLA: indicador por rangos (horas)
    var SLA_RANGES = [
        { max: 4,    label: 'Crítico',  cls: 'mn-sla-indicator--critical'  },
        { max: 24,   label: 'Alto',     cls: 'mn-sla-indicator--high'      },
        { max: 72,   label: 'Medio',    cls: 'mn-sla-indicator--medium'    },
        { max: 168,  label: 'Normal',   cls: 'mn-sla-indicator--normal'    },
        { max: Infinity, label: 'Bajo', cls: 'mn-sla-indicator--low'       },
    ];

    // === API PÚBLICA (lazy init) ===
    window.MaintConfigPriorities = {
        init: function () {
            if (_initialized) return;
            _initialized = true;
            _setup();
            _loadPriorities();
        },
    };

    // === SETUP ===
    function _setup() {
        _priModal = new bootstrap.Modal(document.getElementById('modal-prioridad'));

        document.getElementById('btn-nueva-prioridad').addEventListener('click', _openCreateModal);
        document.getElementById('btn-guardar-prioridad').addEventListener('click', _handleSavePrioridad);

        // Preview en vivo: color, badge_class, label
        document.getElementById('pri-color').addEventListener('input', _updateBadgePreview);
        document.getElementById('pri-hex').addEventListener('input', _syncColorFromHex);
        document.getElementById('pri-badge-class').addEventListener('change', _updateBadgePreview);
        document.getElementById('pri-label').addEventListener('input', _updateBadgePreview);

        // Indicador SLA mientras se escribe
        document.getElementById('pri-sla-hours').addEventListener('input', _updateSlaIndicator);

        // Delegación de acciones en la tabla
        document.getElementById('tbody-prioridades').addEventListener('click', _handleTableAction);
    }

    // === CARGA DE DATOS ===
    async function _loadPriorities() {
        var tbody = document.getElementById('tbody-prioridades');
        tbody.innerHTML =
            '<tr><td colspan="7" class="text-center py-4 text-muted">' +
            '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
            'Cargando prioridades...</td></tr>';

        try {
            var data = await MaintUtils.api.fetch(API_PRIORITIES);
            _priorities = data.data || [];
            _renderTable(_priorities);
            _initSortable();
        } catch (e) {
            MaintUtils.toast(e.message || 'Error al cargar prioridades', 'error');
            tbody.innerHTML =
                '<tr><td colspan="7" class="text-center py-4 text-danger small">' +
                '<i class="fas fa-exclamation-circle me-1"></i>' +
                MaintUtils.escapeHtml(e.message || 'Error de conexión') +
                '</td></tr>';
        }
    }

    // === RENDER ===
    function _renderTable(items) {
        var tbody = document.getElementById('tbody-prioridades');

        if (!items.length) {
            tbody.innerHTML =
                '<tr><td colspan="7" class="text-center py-5 text-muted">' +
                '<i class="fas fa-flag fa-2x mb-3 d-block opacity-50"></i>' +
                'Sin prioridades. Crea la primera con el botón "Nueva prioridad".' +
                '</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(function (pri) {
            var badgeHtml = _buildBadgeHtml(pri);
            var slaHtml   = _buildSlaHtml(pri.sla_hours);
            var activeBadge = pri.is_active
                ? '<span class="badge bg-success-subtle text-success border border-success-subtle">Activa</span>'
                : '<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">Inactiva</span>';

            var defaultStar = pri.is_default
                ? '<i class="fas fa-star text-warning" title="Prioridad predeterminada"></i>'
                : '<i class="fas fa-star text-muted opacity-25" title="No predeterminada"></i>';

            var toggleDisabled = pri.is_default ? 'disabled title="No se puede desactivar la prioridad predeterminada"' : '';
            var toggleIcon = pri.is_active ? 'fa-toggle-on text-success' : 'fa-toggle-off text-secondary';
            var toggleTitle = pri.is_active ? 'Desactivar' : 'Activar';

            return '<tr data-pri-id="' + pri.id + '" data-order="' + pri.display_order + '">' +
                '<td class="mn-pri-handle text-center" style="cursor:grab; color: var(--maint-muted,#607D8B);">' +
                    '<i class="fas fa-grip-vertical"></i>' +
                '</td>' +
                '<td><code class="mn-cat-code">' + MaintUtils.escapeHtml(pri.code) + '</code></td>' +
                '<td>' + badgeHtml + '</td>' +
                '<td>' + slaHtml + '</td>' +
                '<td class="text-center">' + defaultStar + '</td>' +
                '<td class="text-center">' + activeBadge + '</td>' +
                '<td class="text-end">' +
                    '<div class="btn-group btn-group-sm" role="group">' +
                        '<button class="btn btn-outline-secondary" ' +
                                'data-action="edit" data-id="' + pri.id + '" ' +
                                'title="Editar prioridad">' +
                            '<i class="fas fa-pencil-alt"></i>' +
                        '</button>' +
                        '<button class="btn btn-outline-secondary" ' +
                                'data-action="toggle" data-id="' + pri.id + '" ' +
                                toggleDisabled + '>' +
                            '<i class="fas ' + toggleIcon + '" title="' + toggleTitle + '"></i>' +
                        '</button>' +
                    '</div>' +
                '</td>' +
            '</tr>';
        }).join('');
    }

    // === BADGE PREVIEW HTML ===
    function _buildBadgeHtml(pri) {
        var label = MaintUtils.escapeHtml(pri.label || pri.code);
        if (pri.badge_class && pri.badge_class.trim()) {
            return '<span class="badge ' + MaintUtils.escapeHtml(pri.badge_class) + '">' + label + '</span>';
        }
        if (pri.color && pri.color.trim()) {
            var textColor = _contrastColor(pri.color);
            return '<span class="badge" style="background:' + MaintUtils.escapeHtml(pri.color) + ';color:' + textColor + ';">' + label + '</span>';
        }
        return '<span class="badge bg-secondary">' + label + '</span>';
    }

    // === SLA HTML ===
    function _buildSlaHtml(hours) {
        if (!hours && hours !== 0) return '<span class="text-muted small">—</span>';
        var range = _getSlaRange(hours);
        var humanText = _humanizeSla(hours);
        return '<span class="mn-sla-indicator ' + range.cls + '" title="' + range.label + '">' +
            '<i class="fas fa-circle me-1" style="font-size:0.55rem; vertical-align:middle;"></i>' +
            MaintUtils.escapeHtml(String(hours)) + ' h' +
            '<span class="text-muted ms-1 small">(' + MaintUtils.escapeHtml(humanText) + ')</span>' +
        '</span>';
    }

    function _getSlaRange(hours) {
        for (var i = 0; i < SLA_RANGES.length; i++) {
            if (hours <= SLA_RANGES[i].max) return SLA_RANGES[i];
        }
        return SLA_RANGES[SLA_RANGES.length - 1];
    }

    function _humanizeSla(hours) {
        if (!hours) return '0 h';
        if (hours % (24 * 7) === 0) return (hours / (24 * 7)) + (hours / (24 * 7) === 1 ? ' semana' : ' semanas');
        if (hours % 24 === 0) return (hours / 24) + (hours / 24 === 1 ? ' día' : ' días');
        return hours + (hours === 1 ? ' hora' : ' horas');
    }

    // === LUMINANCIA / CONTRASTE ===
    /**
     * Devuelve '#fff' o '#000' según el color de fondo para máximo contraste.
     * @param {string} hex - Color en formato #rrggbb o #rgb
     */
    function _contrastColor(hex) {
        try {
            var c = hex.replace('#', '');
            if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
            var r = parseInt(c.substring(0,2), 16);
            var g = parseInt(c.substring(2,4), 16);
            var b = parseInt(c.substring(4,6), 16);
            // Luminancia relativa (WCAG)
            var lum = 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b);
            return lum > 0.179 ? '#000' : '#fff';
        } catch (_) {
            return '#fff';
        }
    }

    function _linearize(val) {
        var v = val / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    }

    // === SORTABLE (reorder drag-drop) ===
    function _initSortable() {
        var tbody = document.getElementById('tbody-prioridades');
        if (!tbody || !window.Sortable) return;

        if (_sortable) {
            _sortable.destroy();
            _sortable = null;
        }

        _sortable = Sortable.create(tbody, {
            handle: '.mn-pri-handle',
            animation: 150,
            ghostClass: 'mn-pri-row--ghost',
            onEnd: function () {
                _commitReorder();
            },
        });
    }

    async function _commitReorder() {
        if (_reorderPending) return;
        _reorderPending = true;

        var rows = document.querySelectorAll('#tbody-prioridades tr[data-pri-id]');
        var order = Array.from(rows).map(function (row, idx) {
            return { id: parseInt(row.getAttribute('data-pri-id'), 10), display_order: idx };
        });

        try {
            await MaintUtils.api.fetch(API_PRIORITIES + '/reorder', {
                method: 'PUT',
                body: JSON.stringify({ order: order }),
            });
            MaintUtils.toast('Orden guardado', 'success');
            // Actualizar display_order en el estado local para consistencia
            order.forEach(function (o) {
                var pri = _priorities.find(function (p) { return p.id === o.id; });
                if (pri) pri.display_order = o.display_order;
            });
        } catch (e) {
            MaintUtils.toast(e.message || 'Error al guardar el orden', 'error');
            // Re-render para restaurar el orden del servidor
            _renderTable(_priorities);
            _initSortable();
        } finally {
            _reorderPending = false;
        }
    }

    // === DELEGACIÓN DE ACCIONES EN TABLA ===
    function _handleTableAction(e) {
        var btn = e.target.closest('[data-action]');
        if (!btn || btn.disabled) return;

        var action = btn.dataset.action;
        var id = parseInt(btn.dataset.id, 10);
        var pri = _priorities.find(function (p) { return p.id === id; });
        if (!pri) return;

        if (action === 'edit') {
            _openEditModal(pri);
        } else if (action === 'toggle') {
            _handleToggle(pri, btn);
        }
    }

    // === MODAL CREAR ===
    function _openCreateModal() {
        _editingId = null;
        document.getElementById('modal-prioridad-label').textContent = 'Nueva prioridad';
        _resetForm();
        // En modo crear, code está habilitado
        document.getElementById('pri-code').disabled = false;
        document.getElementById('pri-code-group').classList.remove('d-none');
        _priModal.show();
    }

    // === MODAL EDITAR ===
    function _openEditModal(pri) {
        _editingId = pri.id;
        document.getElementById('modal-prioridad-label').textContent = 'Editar prioridad — ' + pri.code;
        _resetForm();

        document.getElementById('pri-edit-id').value = pri.id;
        document.getElementById('pri-code').value = pri.code || '';
        document.getElementById('pri-code').disabled = true;
        document.getElementById('pri-code-group').classList.remove('d-none');
        document.getElementById('pri-label').value = pri.label || '';
        document.getElementById('pri-color').value = pri.color || '#607D8B';
        document.getElementById('pri-hex').value = pri.color || '#607D8B';
        document.getElementById('pri-badge-class').value = pri.badge_class || '';
        document.getElementById('pri-sla-hours').value = pri.sla_hours !== null ? pri.sla_hours : '';
        document.getElementById('pri-is-default').checked = pri.is_default || false;
        document.getElementById('pri-display-order').value = pri.display_order !== null ? pri.display_order : 0;

        _updateBadgePreview();
        _updateSlaIndicator();
        _priModal.show();
    }

    // === RESET FORM ===
    function _resetForm() {
        var form = document.getElementById('form-prioridad');
        form.classList.remove('was-validated');
        form.reset();

        document.getElementById('pri-edit-id').value = '';
        document.getElementById('pri-code').value = '';
        document.getElementById('pri-label').value = '';
        document.getElementById('pri-color').value = '#607D8B';
        document.getElementById('pri-hex').value = '#607D8B';
        document.getElementById('pri-badge-class').value = '';
        document.getElementById('pri-sla-hours').value = '';
        document.getElementById('pri-is-default').checked = false;
        document.getElementById('pri-display-order').value = 0;

        // Limpiar errores
        ['pri-code', 'pri-label', 'pri-sla-hours'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                el.classList.remove('is-invalid');
            }
            var errEl = document.getElementById(id + '-err');
            if (errEl) errEl.textContent = '';
        });

        _updateBadgePreview();
        _updateSlaIndicator();
    }

    // === PREVIEW BADGE EN VIVO ===
    function _updateBadgePreview() {
        var label      = document.getElementById('pri-label').value.trim() || 'Etiqueta';
        var color      = document.getElementById('pri-color').value || '#607D8B';
        var badgeClass = document.getElementById('pri-badge-class').value || '';
        var preview    = document.getElementById('pri-badge-preview');
        if (!preview) return;

        var safeLabel = MaintUtils.escapeHtml(label);

        if (badgeClass.trim()) {
            preview.innerHTML = '<span class="badge ' + MaintUtils.escapeHtml(badgeClass) + '">' + safeLabel + '</span>';
        } else {
            var textColor = _contrastColor(color);
            var lowContrast = _isLowContrast(color);
            var warn = lowContrast
                ? '<small class="text-warning ms-2"><i class="fas fa-exclamation-triangle"></i> Bajo contraste</small>'
                : '';
            preview.innerHTML =
                '<span class="badge" style="background:' + MaintUtils.escapeHtml(color) + ';color:' + textColor + ';">' + safeLabel + '</span>' +
                warn;
        }

        _updateSlaIndicator();
    }

    function _isLowContrast(hex) {
        // Contraste < 3:1 se considera bajo
        try {
            var c = hex.replace('#', '');
            if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
            var r = parseInt(c.substring(0,2), 16);
            var g = parseInt(c.substring(2,4), 16);
            var b = parseInt(c.substring(4,6), 16);
            var lum = 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b);
            var textLum = lum > 0.179 ? 0 : 1; // negro o blanco
            var brighter = Math.max(lum, textLum) + 0.05;
            var darker   = Math.min(lum, textLum) + 0.05;
            return (brighter / darker) < 3;
        } catch (_) {
            return false;
        }
    }

    // === SYNC COLOR ↔ HEX INPUT ===
    function _syncColorFromHex() {
        var hexVal = document.getElementById('pri-hex').value.trim();
        if (/^#[0-9a-fA-F]{6}$/.test(hexVal)) {
            document.getElementById('pri-color').value = hexVal;
            _updateBadgePreview();
        }
    }

    // === INDICADOR SLA ===
    function _updateSlaIndicator() {
        var hours = parseInt(document.getElementById('pri-sla-hours').value, 10);
        var indicator = document.getElementById('pri-sla-indicator');
        if (!indicator) return;

        if (!hours || hours <= 0) {
            indicator.textContent = '';
            indicator.className = 'mn-sla-indicator-form';
            return;
        }

        var range = _getSlaRange(hours);
        var human = _humanizeSla(hours);
        indicator.className = 'mn-sla-indicator-form ' + range.cls;
        indicator.innerHTML =
            '<i class="fas fa-circle me-1" style="font-size:0.55rem; vertical-align:middle;"></i>' +
            MaintUtils.escapeHtml(range.label) + ' — ' + MaintUtils.escapeHtml(human);
    }

    // Nota: el listener de pri-sla-hours se registra en _setup() junto con el resto.

    // === GUARDAR PRIORIDAD ===
    async function _handleSavePrioridad() {
        var btn = document.getElementById('btn-guardar-prioridad');

        var code         = document.getElementById('pri-code').value.trim().toUpperCase();
        var label        = document.getElementById('pri-label').value.trim();
        var color        = document.getElementById('pri-color').value || null;
        var badgeClass   = document.getElementById('pri-badge-class').value || null;
        var slaHours     = parseInt(document.getElementById('pri-sla-hours').value, 10);
        var isDefault    = document.getElementById('pri-is-default').checked;
        var displayOrder = parseInt(document.getElementById('pri-display-order').value, 10) || 0;

        // Validación cliente
        var valid = true;
        var CODE_RE = /^[A-Z][A-Z0-9_]*$/;

        if (!_editingId) {
            if (!code || !CODE_RE.test(code)) {
                _setFieldError('pri-code', 'Código requerido: mayúsculas, dígitos y guion bajo (ej. ALTA).');
                valid = false;
            } else {
                _clearFieldError('pri-code');
            }
        }
        if (!label) {
            _setFieldError('pri-label', 'La etiqueta es requerida.');
            valid = false;
        } else {
            _clearFieldError('pri-label');
        }
        if (!slaHours || slaHours <= 0 || isNaN(slaHours)) {
            _setFieldError('pri-sla-hours', 'Ingresa las horas SLA (número mayor a 0).');
            valid = false;
        } else {
            _clearFieldError('pri-sla-hours');
        }
        if (!valid) return;

        MaintUtils.loading.show(btn, 'Guardando...');
        try {
            if (_editingId) {
                var body = {
                    label: label,
                    color: color || null,
                    badge_class: badgeClass || null,
                    sla_hours: slaHours,
                    is_default: isDefault,
                    display_order: displayOrder,
                };
                await MaintUtils.api.fetch(API_PRIORITIES + '/' + _editingId, {
                    method: 'PATCH',
                    body: JSON.stringify(body),
                });
                MaintUtils.toast('Prioridad actualizada correctamente', 'success');
            } else {
                var createBody = {
                    code: code,
                    label: label,
                    color: color || null,
                    badge_class: badgeClass || null,
                    sla_hours: slaHours,
                    is_default: isDefault,
                    display_order: displayOrder,
                };
                await MaintUtils.api.fetch(API_PRIORITIES, {
                    method: 'POST',
                    body: JSON.stringify(createBody),
                });
                MaintUtils.toast('Prioridad creada correctamente', 'success');
            }
            _priModal.hide();
            await _loadPriorities();
        } catch (e) {
            MaintUtils.toast(e.message || 'Error al guardar', 'error');
        } finally {
            MaintUtils.loading.hide(btn);
        }
    }

    // === TOGGLE ACTIVO ===
    async function _handleToggle(pri, btn) {
        if (pri.is_default) {
            MaintUtils.alert({
                title: 'Acción no permitida',
                message: 'No se puede desactivar la prioridad predeterminada. Primero asigna otro predeterminado.',
                type: 'warning',
            });
            return;
        }

        var newState = !pri.is_active;
        MaintUtils.confirm({
            title: (newState ? 'Activar' : 'Desactivar') + ' prioridad',
            message: '¿Deseas ' + (newState ? 'activar' : 'desactivar') + ' la prioridad "' + pri.label + '"?',
            confirmLabel: newState ? 'Activar' : 'Desactivar',
            confirmClass: newState ? 'btn-success' : 'btn-warning',
            onConfirm: async function () {
                MaintUtils.loading.show(btn, '');
                try {
                    await MaintUtils.api.fetch(API_PRIORITIES + '/' + pri.id + '/toggle', {
                        method: 'PATCH',
                        body: JSON.stringify({ is_active: newState }),
                    });
                    MaintUtils.toast(
                        'Prioridad ' + (newState ? 'activada' : 'desactivada'),
                        newState ? 'success' : 'warning'
                    );
                    await _loadPriorities();
                } catch (e) {
                    MaintUtils.toast(e.message || 'Error al cambiar estado', 'error');
                    MaintUtils.loading.hide(btn);
                }
            },
        });
    }

    // === UTILIDADES DE VALIDACIÓN ===
    function _setFieldError(fieldId, msg) {
        var el = document.getElementById(fieldId);
        if (el) el.classList.add('is-invalid');
        var errEl = document.getElementById(fieldId + '-err');
        if (errEl) errEl.textContent = msg;
    }

    function _clearFieldError(fieldId) {
        var el = document.getElementById(fieldId);
        if (el) el.classList.remove('is-invalid');
        var errEl = document.getElementById(fieldId + '-err');
        if (errEl) errEl.textContent = '';
    }

})();
