/**
 * notifications_tab.js — Editor de plantillas de notificación para el tab
 * #notif en la página de Configuración de Mantenimiento.
 *
 * Carga lazy: window.MaintConfigNotifications.init() es invocado por
 * config_main.js la primera vez que se activa el tab #notif.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *
 * Contrato API:
 *   GET    /api/maint/v2/config/notifications        → lista
 *   GET    /api/maint/v2/config/notifications/{id}   → ítem
 *   PATCH  /api/maint/v2/config/notifications/{id}   → editar (parcial)
 *   PATCH  /api/maint/v2/config/notifications/{id}/toggle  → toggle is_active
 *   POST   /api/maint/v2/config/notifications/{id}/preview → preview renderizado
 */

(function () {
    'use strict';

    // === ESTADO ===
    var _initialized      = false;
    var _notifications    = [];
    var _editingItem      = null;   // objeto completo de la plantilla en edición
    var _editModal        = null;
    var _isDirty          = false;  // hay cambios sin guardar
    var _previewDebounce  = null;   // timer para auto-preview

    // === CONSTANTES ===
    var API_BASE = '/api/maint/v2/config/notifications';

    var CHANNEL_LABELS = {
        inapp: 'In-App',
        email: 'E-mail',
        both:  'Ambos',
    };

    // === API PÚBLICA (lazy init) ===
    window.MaintConfigNotifications = {
        init: function () {
            if (_initialized) return;
            _initialized = true;
            _setup();
            _loadNotifications();
        },
    };

    // === SETUP ===
    function _setup() {
        _editModal = new bootstrap.Modal(document.getElementById('modal-notif-editor'), {
            backdrop: 'static',
            keyboard: false,
        });

        // Guardar
        document.getElementById('btn-notif-guardar').addEventListener('click', _handleSave);

        // Previsualizar manual
        document.getElementById('btn-notif-preview').addEventListener('click', function () {
            _runPreview();
        });

        // Auto-preview con debounce al editar templates
        ['notif-subject-template', 'notif-title-template', 'notif-body-template'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', function () {
                    _isDirty = true;
                    _scheduleAutoPreview();
                });
            }
        });

        // Auto-preview al cambiar channel (muestra/oculta campos + lanza preview)
        document.getElementById('notif-channel').addEventListener('change', function () {
            _isDirty = true;
            _toggleChannelFields();
            _scheduleAutoPreview();
        });

        // ticket_id para preview
        document.getElementById('notif-preview-ticket-id').addEventListener('input', function () {
            _scheduleAutoPreview();
        });

        // Cerrar modal con confirmación si hay cambios
        document.getElementById('modal-notif-editor').addEventListener('hide.bs.modal', function (e) {
            if (_isDirty) {
                e.preventDefault();
                MaintUtils.confirm({
                    title:        'Cambios sin guardar',
                    message:      'Tienes cambios sin guardar en esta plantilla. ¿Deseas cerrar de todas formas?',
                    confirmLabel: 'Cerrar sin guardar',
                    confirmClass: 'btn-warning',
                    onConfirm:    function () {
                        _isDirty = false;
                        _editModal.hide();
                    },
                });
            }
        });

        // Delegación de acciones en la tabla de plantillas
        document.getElementById('tbody-notif').addEventListener('click', _handleTableAction);

        // Delegación de chips de variables — registrada una sola vez aquí
        document.getElementById('notif-variables-chips').addEventListener('click', function (e) {
            var chip = e.target.closest('.mn-notif-var-chip');
            if (!chip) return;
            var varName = chip.dataset.variable;
            _insertAtCursor(
                document.getElementById('notif-body-template'),
                '{{ ' + varName + ' }}'
            );
            _isDirty = true;
            _scheduleAutoPreview();
        });
    }

    // === CARGA DE DATOS ===
    async function _loadNotifications() {
        var tbody = document.getElementById('tbody-notif');
        tbody.innerHTML =
            '<tr><td colspan="5" class="text-center py-4 text-muted">' +
            '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
            'Cargando plantillas de notificación...</td></tr>';

        try {
            var data = await MaintUtils.api.fetch(API_BASE);
            _notifications = data.data || [];
            _renderTable(_notifications);
        } catch (e) {
            MaintUtils.toast(e.message || 'Error al cargar plantillas', 'error');
            tbody.innerHTML =
                '<tr><td colspan="5" class="text-center py-4 text-danger small">' +
                '<i class="fas fa-exclamation-circle me-1"></i>' +
                MaintUtils.escapeHtml(e.message || 'Error de conexión') +
                '</td></tr>';
        }
    }

    // === RENDER ===
    function _renderTable(items) {
        var tbody = document.getElementById('tbody-notif');

        if (!items.length) {
            tbody.innerHTML =
                '<tr><td colspan="5" class="text-center py-5 text-muted">' +
                '<i class="fas fa-bell fa-2x mb-3 d-block opacity-50"></i>' +
                'No hay plantillas de notificación configuradas.' +
                '</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(function (notif) {
            var channelBadge = _buildChannelBadge(notif.channel);

            var activeBadge = notif.is_active
                ? '<span class="badge bg-success-subtle text-success border border-success-subtle">Activa</span>'
                : '<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">Inactiva</span>';

            var toggleIcon  = notif.is_active ? 'fa-toggle-on text-success' : 'fa-toggle-off text-secondary';
            var toggleTitle = notif.is_active ? 'Desactivar' : 'Activar';

            var updatedAt = notif.updated_at
                ? '<span class="text-muted small">' + MaintUtils.escapeHtml(_formatDate(notif.updated_at)) + '</span>'
                : '<span class="text-muted small">—</span>';

            return '<tr data-notif-id="' + notif.id + '">' +
                '<td>' +
                    '<code class="mn-cat-code">' + MaintUtils.escapeHtml(notif.code) + '</code>' +
                '</td>' +
                '<td>' + MaintUtils.escapeHtml(notif.name) + '</td>' +
                '<td>' + channelBadge + '</td>' +
                '<td class="text-center">' + activeBadge + '</td>' +
                '<td>' + updatedAt + '</td>' +
                '<td class="text-end">' +
                    '<div class="btn-group btn-group-sm" role="group">' +
                        '<button class="btn btn-outline-secondary" ' +
                                'data-action="edit" data-id="' + notif.id + '" ' +
                                'title="Editar plantilla">' +
                            '<i class="fas fa-pencil-alt"></i>' +
                            '<span class="d-none d-md-inline ms-1">Editar</span>' +
                        '</button>' +
                        '<button class="btn btn-outline-secondary" ' +
                                'data-action="toggle" data-id="' + notif.id + '" ' +
                                'title="' + toggleTitle + '">' +
                            '<i class="fas ' + toggleIcon + '"></i>' +
                        '</button>' +
                    '</div>' +
                '</td>' +
            '</tr>';
        }).join('');
    }

    // === CHANNEL BADGE ===
    function _buildChannelBadge(channel) {
        var label = MaintUtils.escapeHtml(CHANNEL_LABELS[channel] || channel);
        switch (channel) {
            case 'inapp': return '<span class="badge bg-primary-subtle text-primary border border-primary-subtle"><i class="fas fa-bell me-1"></i>' + label + '</span>';
            case 'email': return '<span class="badge bg-info-subtle text-info border border-info-subtle"><i class="fas fa-envelope me-1"></i>' + label + '</span>';
            case 'both':  return '<span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle"><i class="fas fa-layer-group me-1"></i>' + label + '</span>';
            default:      return '<span class="badge bg-secondary">' + label + '</span>';
        }
    }

    // === DELEGACIÓN DE ACCIONES ===
    function _handleTableAction(e) {
        var btn = e.target.closest('[data-action]');
        if (!btn || btn.disabled) return;

        var action = btn.dataset.action;
        var id     = parseInt(btn.dataset.id, 10);
        var notif  = _notifications.find(function (n) { return n.id === id; });
        if (!notif) return;

        if (action === 'edit') {
            _openEditor(notif);
        } else if (action === 'toggle') {
            _handleToggle(notif, btn);
        }
    }

    // === ABRIR EDITOR ===
    async function _openEditor(notif) {
        _editingItem = null;
        _isDirty     = false;

        // Limpiar UI del modal
        _resetEditorUI();
        document.getElementById('notif-editor-title').textContent = 'Editar plantilla — ' + notif.code;
        document.getElementById('notif-editor-subtitle').textContent = notif.name;

        // Mostrar spinner mientras carga detalle
        var spinnerEl = document.getElementById('notif-editor-spinner');
        var bodyEl    = document.getElementById('notif-editor-body');
        spinnerEl.classList.remove('d-none');
        bodyEl.classList.add('d-none');

        _editModal.show();

        try {
            var data = await MaintUtils.api.fetch(API_BASE + '/' + notif.id);
            _editingItem = data.data;
            _populateEditor(_editingItem);
            spinnerEl.classList.add('d-none');
            bodyEl.classList.remove('d-none');
            // Auto-preview inicial
            _scheduleAutoPreview();
        } catch (e) {
            MaintUtils.toast(e.message || 'Error al cargar la plantilla', 'error');
            _editModal.hide();
        }
    }

    // === POBLAR EDITOR ===
    function _populateEditor(item) {
        document.getElementById('notif-edit-id').value         = item.id;
        document.getElementById('notif-name').value            = item.name || '';
        document.getElementById('notif-channel').value         = item.channel || 'inapp';
        document.getElementById('notif-subject-template').value = item.subject_template || '';
        document.getElementById('notif-title-template').value  = item.title_template || '';
        document.getElementById('notif-body-template').value   = item.body_template || '';

        // Chips de variables (solo lectura)
        _renderVariableChips(item.variables || []);

        // Mostrar/ocultar campos por canal
        _toggleChannelFields();

        // Resetear estado dirty (acabamos de cargar desde server)
        _isDirty = false;
    }

    // === CHIPS DE VARIABLES ===
    function _renderVariableChips(variables) {
        var container = document.getElementById('notif-variables-chips');
        if (!container) return;

        if (!variables || !variables.length) {
            container.innerHTML = '<span class="text-muted small fst-italic">Sin variables disponibles</span>';
            return;
        }

        container.innerHTML = variables.map(function (v) {
            var safe = MaintUtils.escapeHtml(v);
            return '<button type="button" class="mn-notif-var-chip" ' +
                   'data-variable="' + safe + '" ' +
                   'title="Insertar {{ ' + safe + ' }} en el cuerpo">' +
                   '{{ ' + safe + ' }}' +
                   '</button>';
        }).join('');
        // El listener de click está en _setup() via delegación sobre el contenedor,
        // se registra una sola vez, evitando acumulación de listeners.
    }

    // === TOGGLE CAMPOS POR CANAL ===
    function _toggleChannelFields() {
        var channel = document.getElementById('notif-channel').value;
        var subjectGroup = document.getElementById('notif-subject-group');
        var titleGroup   = document.getElementById('notif-title-group');

        // subject_template → solo si canal incluye email
        if (subjectGroup) {
            var showSubject = (channel === 'email' || channel === 'both');
            subjectGroup.classList.toggle('d-none', !showSubject);
        }

        // title_template → solo si canal incluye inapp
        if (titleGroup) {
            var showTitle = (channel === 'inapp' || channel === 'both');
            titleGroup.classList.toggle('d-none', !showTitle);
        }
    }

    // === GUARDAR ===
    async function _handleSave() {
        var btn = document.getElementById('btn-notif-guardar');
        if (!_editingItem) return;

        var id      = parseInt(document.getElementById('notif-edit-id').value, 10);
        var name    = document.getElementById('notif-name').value.trim();
        var channel = document.getElementById('notif-channel').value;

        if (!name) {
            MaintUtils.toast('El nombre de la plantilla es requerido.', 'warning');
            document.getElementById('notif-name').focus();
            return;
        }

        var body = {
            name:             name,
            channel:          channel,
            subject_template: document.getElementById('notif-subject-template').value,
            title_template:   document.getElementById('notif-title-template').value,
            body_template:    document.getElementById('notif-body-template').value,
        };

        // Ocultar alerta inline previa
        _hideInlineError();

        MaintUtils.loading.show(btn, 'Guardando...');
        try {
            var result = await MaintUtils.api.fetch(API_BASE + '/' + id, {
                method: 'PATCH',
                body:   JSON.stringify(body),
            });

            // Actualizar estado local
            var idx = _notifications.findIndex(function (n) { return n.id === id; });
            if (idx !== -1) _notifications[idx] = Object.assign(_notifications[idx], result.data);

            _isDirty = false;
            MaintUtils.toast('Plantilla actualizada correctamente', 'success');
            _editModal.hide();
            _renderTable(_notifications);
        } catch (e) {
            // 422: error de Jinja inválido — mostrar en alerta inline
            if (e.status === 422) {
                _showInlineError(e.message || 'La plantilla contiene sintaxis Jinja2 inválida.');
            } else {
                MaintUtils.toast(e.message || 'Error al guardar', 'error');
            }
        } finally {
            MaintUtils.loading.hide(btn);
        }
    }

    // === TOGGLE ACTIVO ===
    async function _handleToggle(notif, btn) {
        var newState = !notif.is_active;

        MaintUtils.confirm({
            title:        (newState ? 'Activar' : 'Desactivar') + ' notificación',
            message:      '¿Deseas ' + (newState ? 'activar' : 'desactivar') +
                          ' la plantilla "' + notif.name + '"?',
            confirmLabel: newState ? 'Activar' : 'Desactivar',
            confirmClass: newState ? 'btn-success' : 'btn-warning',
            onConfirm: async function () {
                MaintUtils.loading.show(btn, '');
                try {
                    var result = await MaintUtils.api.fetch(API_BASE + '/' + notif.id + '/toggle', {
                        method: 'PATCH',
                        body:   JSON.stringify({ is_active: newState }),
                    });
                    var idx = _notifications.findIndex(function (n) { return n.id === notif.id; });
                    if (idx !== -1) _notifications[idx] = Object.assign(_notifications[idx], result.data);
                    MaintUtils.toast(
                        'Notificación ' + (newState ? 'activada' : 'desactivada'),
                        newState ? 'success' : 'warning'
                    );
                    _renderTable(_notifications);
                } catch (e) {
                    MaintUtils.toast(e.message || 'Error al cambiar estado', 'error');
                    MaintUtils.loading.hide(btn);
                }
            },
        });
    }

    // === PREVIEW ===
    function _scheduleAutoPreview() {
        clearTimeout(_previewDebounce);
        _previewDebounce = setTimeout(function () {
            _runPreview();
        }, 500);
    }

    async function _runPreview() {
        if (!_editingItem) return;

        var id       = parseInt(document.getElementById('notif-edit-id').value, 10);
        var ticketId = document.getElementById('notif-preview-ticket-id').value.trim();
        var previewBody = {};
        if (ticketId && !isNaN(parseInt(ticketId, 10))) {
            previewBody.ticket_id = parseInt(ticketId, 10);
        }

        var previewPanel  = document.getElementById('notif-preview-panel');
        var previewSpin   = document.getElementById('notif-preview-spinner');
        var previewError  = document.getElementById('notif-preview-error');

        // Estado de carga
        previewPanel.classList.add('mn-notif-preview--loading');
        previewSpin.classList.remove('d-none');
        previewError.classList.add('d-none');

        // El endpoint preview usa los templates guardados en BD.
        // Solo se envía ticket_id para inyectar variables de contexto.
        var body = {};
        if (previewBody.ticket_id) {
            body.ticket_id = previewBody.ticket_id;
        }

        try {
            var result = await MaintUtils.api.fetch(API_BASE + '/' + id + '/preview', {
                method: 'POST',
                body:   JSON.stringify(body),
            });
            var preview = result.data;
            _renderPreviewResult(preview);
        } catch (e) {
            _renderPreviewError(e.message || 'Error al generar la previsualización');
        } finally {
            previewPanel.classList.remove('mn-notif-preview--loading');
            previewSpin.classList.add('d-none');
        }
    }

    function _renderPreviewResult(preview) {
        var warningsEl = document.getElementById('notif-preview-warnings');
        var subjectEl  = document.getElementById('notif-preview-subject');
        var titleEl    = document.getElementById('notif-preview-title');
        var bodyEl     = document.getElementById('notif-preview-body');

        // Warnings de variables no provistas
        var warnings = preview.warnings || [];
        if (warnings.length) {
            warningsEl.classList.remove('d-none');
            warningsEl.innerHTML =
                '<i class="fas fa-exclamation-triangle me-1"></i>' +
                '<strong>Variables sin valor:</strong> ' +
                warnings.map(function (w) {
                    return '<code class="mn-notif-warning-var">' + MaintUtils.escapeHtml(w) + '</code>';
                }).join(', ');
        } else {
            warningsEl.classList.add('d-none');
            warningsEl.innerHTML = '';
        }

        // Subject
        var subjectWrapEl = document.getElementById('notif-preview-subject-wrap');
        if (subjectEl && subjectWrapEl) {
            if (preview.subject) {
                subjectWrapEl.classList.remove('d-none');
                subjectEl.textContent = preview.subject;
            } else {
                subjectWrapEl.classList.add('d-none');
            }
        }

        // Title
        var titleWrapEl = document.getElementById('notif-preview-title-wrap');
        if (titleEl && titleWrapEl) {
            if (preview.title) {
                titleWrapEl.classList.remove('d-none');
                titleEl.textContent = preview.title;
            } else {
                titleWrapEl.classList.add('d-none');
            }
        }

        // Body
        if (bodyEl) {
            bodyEl.textContent = preview.body || '';
        }

        // Mostrar error de preview si había
        document.getElementById('notif-preview-error').classList.add('d-none');
    }

    function _renderPreviewError(msg) {
        var errorEl = document.getElementById('notif-preview-error');
        errorEl.classList.remove('d-none');
        errorEl.textContent = msg;

        // Limpiar campos de preview
        var bodyEl = document.getElementById('notif-preview-body');
        if (bodyEl) bodyEl.textContent = '';
        var warningsEl = document.getElementById('notif-preview-warnings');
        if (warningsEl) warningsEl.classList.add('d-none');
    }

    // === ALERTA INLINE DE ERROR (422 Jinja) ===
    function _showInlineError(msg) {
        var el = document.getElementById('notif-save-error');
        if (!el) return;
        el.classList.remove('d-none');
        el.textContent = msg;
    }

    function _hideInlineError() {
        var el = document.getElementById('notif-save-error');
        if (!el) return;
        el.classList.add('d-none');
        el.textContent = '';
    }

    // === RESET UI DEL EDITOR ===
    function _resetEditorUI() {
        document.getElementById('notif-edit-id').value          = '';
        document.getElementById('notif-name').value             = '';
        document.getElementById('notif-channel').value          = 'inapp';
        document.getElementById('notif-subject-template').value = '';
        document.getElementById('notif-title-template').value   = '';
        document.getElementById('notif-body-template').value    = '';
        document.getElementById('notif-preview-ticket-id').value = '';

        var chipsEl = document.getElementById('notif-variables-chips');
        if (chipsEl) chipsEl.innerHTML = '';

        var warningsEl = document.getElementById('notif-preview-warnings');
        if (warningsEl) { warningsEl.classList.add('d-none'); warningsEl.innerHTML = ''; }

        var subjectWrap = document.getElementById('notif-preview-subject-wrap');
        if (subjectWrap) subjectWrap.classList.add('d-none');
        var subjectEl = document.getElementById('notif-preview-subject');
        if (subjectEl) subjectEl.textContent = '';

        var titleWrap = document.getElementById('notif-preview-title-wrap');
        if (titleWrap) titleWrap.classList.add('d-none');
        var titleEl = document.getElementById('notif-preview-title');
        if (titleEl) titleEl.textContent = '';

        var bodyEl = document.getElementById('notif-preview-body');
        if (bodyEl) bodyEl.textContent = '';

        var spinnerEl = document.getElementById('notif-editor-spinner');
        if (spinnerEl) spinnerEl.classList.remove('d-none');
        var editorBodyEl = document.getElementById('notif-editor-body');
        if (editorBodyEl) editorBodyEl.classList.add('d-none');

        _hideInlineError();
        _toggleChannelFields();
    }

    // === INSERTAR EN CURSOR ===
    function _insertAtCursor(textarea, text) {
        if (!textarea) return;
        var start = textarea.selectionStart;
        var end   = textarea.selectionEnd;
        var val   = textarea.value;
        textarea.value = val.slice(0, start) + text + val.slice(end);
        var newPos = start + text.length;
        textarea.setSelectionRange(newPos, newPos);
        textarea.focus();
        // Disparar input para que el debounce de preview lo detecte
        textarea.dispatchEvent(new Event('input'));
    }

    // === UTILIDADES ===
    function _formatDate(isoString) {
        if (!isoString) return '';
        try {
            var d = new Date(isoString);
            return d.toLocaleDateString('es-MX', {
                day:   '2-digit',
                month: 'short',
                year:  'numeric',
            }) + ' ' + d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });
        } catch (_) {
            return isoString;
        }
    }

})();
