/**
 * notifications_tab.js
 * Tab "Plantillas de Notificación" del panel de Configuración.
 *
 * Responsabilidades:
 *  - Lista de plantillas en cards (10 del seed, sin crear/borrar).
 *  - Toggle is_active por plantilla.
 *  - Modal editor (modal-xl) con form izquierda + preview derecha.
 *    · Auto-preview con debounce 500ms al editar body_template.
 *    · Inserción de variables en cursor del textarea.
 *    · Validación de sintaxis Jinja (error 400 del backend).
 *    · Detección de cambios sin guardar al cerrar modal.
 *  - Modal vista previa rápida (modal-lg) sin abrir editor.
 *  - Lazy init: carga datos solo la primera vez que el tab #notif es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let templates = [];
    let showInactive = false;

    // Estado del modal editor
    let editingTemplate = null;
    let editHasChanges = false;
    let previewDebounceTimer = null;

    // === CONSTANTES ===
    const API_BASE = '/api/help-desk/v2/config/notifications';

    const CHANNEL_OPTIONS = [
        { value: 'inapp', label: 'In-app (notificación interna)' },
        { value: 'email', label: 'Email' },
        { value: 'both',  label: 'Ambos (in-app + email)' },
    ];

    const CHANNEL_CHIP_CLASS = {
        inapp: 'notification-channel-chip--inapp',
        email: 'notification-channel-chip--email',
        both:  'notification-channel-chip--both',
    };

    const CHANNEL_LABEL = {
        inapp: 'In-app',
        email: 'Email',
        both:  'Ambos',
    };

    // === HELPERS ===
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
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

    async function apiErrorDetail(res, fallback) {
        try {
            const d = await res.json();
            return d;
        } catch (_) {
            return { error: fallback };
        }
    }

    function formatRelativeDate(isoStr) {
        if (!isoStr) return null;
        try {
            const d = new Date(isoStr);
            if (isNaN(d.getTime())) return escapeHtml(isoStr);
            const now   = new Date();
            const diff  = Math.floor((now - d) / 1000);
            if (diff < 60)         return 'hace un momento';
            if (diff < 3600)       return 'hace ' + Math.floor(diff / 60) + ' min';
            if (diff < 86400)      return 'hace ' + Math.floor(diff / 3600) + ' h';
            if (diff < 86400 * 7)  return 'hace ' + Math.floor(diff / 86400) + ' d';
            const pad = function (n) { return String(n).padStart(2, '0'); };
            return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear();
        } catch (_) {
            return escapeHtml(isoStr);
        }
    }

    function findById(id) {
        return templates.find(function (t) { return t.id === id; }) || null;
    }

    function channelChipHtml(channel) {
        const cls   = CHANNEL_CHIP_CLASS[channel] || 'notification-channel-chip--inapp';
        const label = CHANNEL_LABEL[channel]       || escapeHtml(channel);
        return '<span class="notification-channel-chip ' + cls + '">' + label + '</span>';
    }

    function buildVariableChips(variables, dataAttr) {
        if (!variables || !variables.length) return '<span class="text-muted small fst-italic">Sin variables declaradas</span>';
        return variables.map(function (v) {
            return '<span class="notification-variable-chip" ' + (dataAttr ? 'data-var="' + escapeHtml(v) + '"' : '') + '>{{ ' + escapeHtml(v) + ' }}</span>';
        }).join('');
    }

    function insertAtCursor(textarea, text) {
        const start = textarea.selectionStart;
        const end   = textarea.selectionEnd;
        const val   = textarea.value;
        textarea.value = val.substring(0, start) + text + val.substring(end);
        // Mover cursor al final del texto insertado
        const newPos = start + text.length;
        textarea.selectionStart = newPos;
        textarea.selectionEnd   = newPos;
        textarea.focus();
        // Disparar evento input para que el debounce se active
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function debounce(fn, delay) {
        let timer;
        return function () {
            const args = arguments;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(null, args); }, delay);
        };
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#notif') {
            if (!initialized) {
                initialized = true;
                initNotifTab();
            }
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '';
        if (hash === '#notif') {
            if (!initialized) {
                initialized = true;
                initNotifTab();
            }
        }
        bindEditModal();
        bindPreviewModal();
    });

    function initNotifTab() {
        renderShell();
        loadTemplates();
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('notif-root');
        if (!root) return;

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-bell me-2 text-primary"></i>Plantillas de Notificación
                </h5>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" id="toggle-inactive-notif"
                               role="switch" ${showInactive ? 'checked' : ''}>
                        <label class="form-check-label small text-muted" for="toggle-inactive-notif">
                            Mostrar inactivas
                        </label>
                    </div>
                </div>
            </div>
            <div class="alert alert-info py-2 small mb-3">
                <i class="fas fa-info-circle me-1"></i>
                Las 10 plantillas vienen predefinidas. Puedes editar el asunto, cuerpo, canal y descripción.
                El código y nombre son de solo lectura.
            </div>
            <div id="notif-list-wrapper">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando plantillas...
                </div>
            </div>
        `;

        root.addEventListener('change', function (e) {
            if (e.target.id === 'toggle-inactive-notif') {
                showInactive = e.target.checked;
                renderList();
            }
        });
    }

    // === CARGA DE DATOS ===
    async function loadTemplates() {
        const wrapper = document.getElementById('notif-list-wrapper');
        if (wrapper) {
            wrapper.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando plantillas...
                </div>`;
        }

        try {
            const res = await fetch(API_BASE + '?include_inactive=true');
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cargar plantillas');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) wrapper.innerHTML = '<div class="text-danger small p-2"><i class="fas fa-exclamation-circle me-1"></i>Error al cargar plantillas.</div>';
                return;
            }
            const data = await res.json();
            templates = data.templates || [];
            renderList();
        } catch (err) {
            console.error('notifications_tab: loadTemplates error', err);
            HelpdeskUtils.showToast('Error de conexión al cargar plantillas', 'error');
        }
    }

    // === RENDER LISTA ===
    function renderList() {
        const wrapper = document.getElementById('notif-list-wrapper');
        if (!wrapper) return;

        const visible = templates.filter(function (t) {
            return showInactive ? true : t.is_active;
        });

        if (!visible.length) {
            wrapper.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-bell fa-3x mb-3 opacity-50"></i>
                    <p>${showInactive ? 'Sin plantillas configuradas.' : 'Sin plantillas activas.'}</p>
                </div>`;
            return;
        }

        wrapper.innerHTML = visible.map(renderTemplateCard).join('');
        bindCardActions(wrapper);
    }

    function renderTemplateCard(t) {
        const inactiveCls = t.is_active ? '' : 'notification-card--inactive';

        // Snippet del body (primeras 200 chars)
        const body    = t.body_template || '';
        const snippet = body.length > 200 ? escapeHtml(body.substring(0, 200)) + '...' : escapeHtml(body);

        // Fecha relativa
        const dateRel  = formatRelativeDate(t.updated_at);
        const footerHtml = dateRel
            ? '<div class="notification-card-footer text-muted small px-3 pb-2">Actualizado: ' + dateRel + '</div>'
            : '';

        return `
            <div class="notification-card ${inactiveCls}" data-id="${t.id}">
                <div class="notification-card-header">
                    <span class="notification-code">${escapeHtml(t.code)}</span>
                    <span class="flex-grow-1 fw-semibold small">${escapeHtml(t.name)}</span>
                    ${channelChipHtml(t.channel)}
                    ${!t.is_active ? '<span class="badge bg-warning text-dark small">Inactiva</span>' : ''}
                    <div class="form-check form-switch mb-0 ms-auto me-1" title="${t.is_active ? 'Desactivar' : 'Activar'}">
                        <input class="form-check-input notif-toggle" type="checkbox"
                               data-id="${t.id}" ${t.is_active ? 'checked' : ''}>
                    </div>
                    <button class="btn btn-sm btn-outline-secondary notif-btn-preview" data-id="${t.id}" title="Vista previa rápida">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary notif-btn-edit" data-id="${t.id}" title="Editar plantilla">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                </div>
                <div class="notification-card-body">
                    ${t.description ? '<p class="mb-2 small text-secondary">' + escapeHtml(t.description) + '</p>' : ''}
                    ${snippet ? '<div class="notification-preview-snippet">' + snippet + '</div>' : ''}
                    <div class="notification-variables mt-2">
                        ${buildVariableChips(t.variables, false)}
                    </div>
                </div>
                ${footerHtml}
            </div>`;
    }

    function bindCardActions(container) {
        container.querySelectorAll('.notif-toggle').forEach(function (chk) {
            chk.addEventListener('change', function () {
                handleToggle(parseInt(chk.dataset.id, 10), chk.checked, chk);
            });
        });

        container.querySelectorAll('.notif-btn-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const t = findById(parseInt(btn.dataset.id, 10));
                if (t) openEditModal(t);
            });
        });

        container.querySelectorAll('.notif-btn-preview').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const t = findById(parseInt(btn.dataset.id, 10));
                if (t) openPreviewModal(t);
            });
        });
    }

    // === TOGGLE ===
    async function handleToggle(id, isActive, checkbox) {
        const original = !isActive;
        checkbox.disabled = true;

        try {
            const res = await fetch(API_BASE + '/' + id + '/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: isActive }),
            });
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cambiar estado');
                HelpdeskUtils.showToast(msg, 'error');
                checkbox.checked = original;
                return;
            }
            const data = await res.json();
            const t = findById(id);
            if (t) t.is_active = isActive;
            HelpdeskUtils.showToast(data.message || (isActive ? 'Plantilla activada' : 'Plantilla desactivada'), 'success');
            renderList();
        } catch (err) {
            HelpdeskUtils.showToast('Error de conexión', 'error');
            checkbox.checked = original;
        } finally {
            checkbox.disabled = false;
        }
    }

    // === MODAL EDITAR ===

    function openEditModal(t) {
        const modal = document.getElementById('modal-notification-edit');
        if (!modal) return;

        editingTemplate = t;
        editHasChanges  = false;
        clearPreviewDebounce();

        // Rellenar campos
        modal.querySelector('#notif-edit-code-display').textContent = t.code;
        modal.querySelector('#notif-edit-name').value        = t.name || '';
        modal.querySelector('#notif-edit-description').value = t.description || '';
        modal.querySelector('#notif-edit-body').value        = t.body_template || '';

        // Channel select
        const channelSelect = modal.querySelector('#notif-edit-channel');
        if (channelSelect) channelSelect.value = t.channel || 'inapp';

        // Subject: visible solo si channel != inapp
        const subjectInput = modal.querySelector('#notif-edit-subject');
        if (subjectInput) subjectInput.value = t.subject_template || '';
        updateSubjectVisibility(modal, t.channel || 'inapp');

        // Variables disponibles
        const varContainer = modal.querySelector('#notif-edit-variables');
        if (varContainer) {
            varContainer.innerHTML = buildVariableChips(t.variables, true);
        }

        // Limpiar errores de sintaxis
        clearSyntaxError(modal);

        // Limpiar preview
        const previewArea = modal.querySelector('#notif-edit-preview-area');
        if (previewArea) {
            previewArea.innerHTML = '<div class="text-muted small fst-italic text-center py-4">Haz clic en "Renderizar" o edita el cuerpo para ver la vista previa.</div>';
        }

        // Contador inicial
        updateBodyCounter(modal);

        // Precargar ticket ID vacío
        const ticketInput = modal.querySelector('#notif-edit-ticket-id');
        if (ticketInput) ticketInput.value = '';

        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    function updateSubjectVisibility(modal, channel) {
        const subjectWrap = modal.querySelector('#notif-edit-subject-wrap');
        if (!subjectWrap) return;
        if (channel === 'inapp') {
            subjectWrap.style.display = 'none';
        } else {
            subjectWrap.style.display = '';
        }
    }

    function updateBodyCounter(modal) {
        const textarea = modal.querySelector('#notif-edit-body');
        const counter  = modal.querySelector('#notif-body-counter');
        if (!textarea || !counter) return;
        const lines = textarea.value.split('\n').length;
        const chars  = textarea.value.length;
        counter.textContent = lines + ' líneas · ' + chars + ' caracteres';
    }

    function clearSyntaxError(modal) {
        const textarea  = modal.querySelector('#notif-edit-body');
        const errDiv    = modal.querySelector('#notif-syntax-error');
        if (textarea) textarea.classList.remove('is-invalid');
        if (errDiv)   errDiv.classList.add('d-none');
    }

    function showSyntaxError(modal, message, lineno) {
        const textarea = modal.querySelector('#notif-edit-body');
        const errDiv   = modal.querySelector('#notif-syntax-error');
        if (textarea) textarea.classList.add('is-invalid');
        if (errDiv) {
            let msg = message || 'Error de sintaxis en la plantilla.';
            if (lineno) msg += ' (línea ' + lineno + ')';
            errDiv.querySelector('#notif-syntax-error-text').textContent = msg;
            errDiv.classList.remove('d-none');
        }
    }

    // Auto-preview con debounce de 500ms
    function scheduleAutoPreview(modal) {
        clearPreviewDebounce();
        previewDebounceTimer = setTimeout(function () {
            if (editingTemplate) {
                renderPreviewInModal(modal, editingTemplate.id, false);
            }
        }, 500);
    }

    function clearPreviewDebounce() {
        if (previewDebounceTimer) {
            clearTimeout(previewDebounceTimer);
            previewDebounceTimer = null;
        }
    }

    function bindEditModal() {
        const modal = document.getElementById('modal-notification-edit');
        if (!modal) return;
        if (modal.dataset.notifEditBound) return;
        modal.dataset.notifEditBound = '1';

        // Cambio de channel: mostrar/ocultar subject
        modal.addEventListener('change', function (e) {
            if (e.target.id === 'notif-edit-channel') {
                updateSubjectVisibility(modal, e.target.value);
                markDirty();
            }
        });

        // Edición de campos → marcar como modificado
        modal.addEventListener('input', function (e) {
            const id = e.target.id;
            if (id === 'notif-edit-description' || id === 'notif-edit-subject') {
                markDirty();
            }
            if (id === 'notif-edit-body') {
                markDirty();
                updateBodyCounter(modal);
                clearSyntaxError(modal);
                scheduleAutoPreview(modal);
            }
        });

        // Clic en chips de variables → insertar en textarea
        modal.addEventListener('click', function (e) {
            const chip = e.target.closest('.notification-variable-chip[data-var]');
            if (chip) {
                const textarea = modal.querySelector('#notif-edit-body');
                if (textarea) {
                    insertAtCursor(textarea, '{{ ' + chip.dataset.var + ' }}');
                }
            }

            // Botón renderizar manual
            if (e.target.closest('#btn-notif-render-preview')) {
                if (editingTemplate) {
                    renderPreviewInModal(modal, editingTemplate.id, true);
                }
            }
        });

        // Guardar cambios
        const btnSave = modal.querySelector('#btn-notif-edit-save');
        if (btnSave) {
            btnSave.addEventListener('click', function () {
                handleSaveEdit(modal);
            });
        }

        // Detectar cierre del modal con cambios sin guardar
        modal.addEventListener('hide.bs.modal', function (e) {
            if (editHasChanges) {
                // Bootstrap no soporta cancelar hide.bs.modal directamente;
                // usamos confirmModal de HelpdeskUtils si está disponible,
                // pero no podemos cancelar el evento nativo de Bootstrap de forma limpia.
                // Por eso usamos una estrategia: re-abrimos si el usuario cancela.
                // Nota: esto es una limitación conocida del modal de Bootstrap 5.
                // La solución práctica es usar un atributo para registrar la intención.
                if (modal.dataset.forceClose === '1') {
                    modal.dataset.forceClose = '0';
                    return;
                }
                // Prevenir el cierre (solo funciona con show/hide programático,
                // no con data-bs-dismiss click en Bootstrap 5)
                // Mostramos confirm y si el usuario confirma cerramos forzado
                if (typeof HelpdeskUtils !== 'undefined' && HelpdeskUtils.confirmModal) {
                    HelpdeskUtils.confirmModal(
                        'Cambios sin guardar',
                        'Tienes cambios sin guardar en la plantilla. ¿Seguro que quieres cerrar sin guardar?',
                        function () {
                            editHasChanges = false;
                            modal.dataset.forceClose = '1';
                            bootstrap.Modal.getInstance(modal).hide();
                        }
                    );
                }
            }
        });

        modal.addEventListener('hidden.bs.modal', function () {
            editingTemplate = null;
            editHasChanges  = false;
            clearPreviewDebounce();
        });
    }

    function markDirty() {
        editHasChanges = true;
    }

    async function handleSaveEdit(modal) {
        if (!editingTemplate) return;

        const description      = (modal.querySelector('#notif-edit-description').value || '').trim();
        const channel          = modal.querySelector('#notif-edit-channel').value;
        const subject_template = (modal.querySelector('#notif-edit-subject').value || '').trim() || null;
        const body_template    = modal.querySelector('#notif-edit-body').value;

        clearSyntaxError(modal);

        const btnSave = modal.querySelector('#btn-notif-edit-save');
        if (btnSave) btnSave.disabled = true;

        try {
            const payload = {
                description:      description || null,
                channel:          channel,
                subject_template: subject_template,
                body_template:    body_template,
            };

            const res = await fetch(API_BASE + '/' + editingTemplate.id, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                if (res.status === 400) {
                    const errData = await apiErrorDetail(res, 'Error de validación');
                    if (errData.error === 'invalid_template_syntax') {
                        showSyntaxError(modal, errData.message || 'Sintaxis Jinja inválida', errData.lineno || null);
                        return;
                    }
                    const msg = errData.message || errData.error || errData.detail || 'Error al guardar plantilla';
                    HelpdeskUtils.showToast(String(msg), 'error');
                    return;
                }
                const msg = await apiErrorMsg(res, 'Error al guardar plantilla');
                HelpdeskUtils.showToast(msg, 'error');
                return;
            }

            const data = await res.json();
            HelpdeskUtils.showToast(data.message || 'Plantilla actualizada', 'success');

            // Actualizar estado local
            const idx = templates.findIndex(function (t) { return t.id === editingTemplate.id; });
            if (idx !== -1 && data.template) {
                templates[idx] = data.template;
            } else if (idx !== -1) {
                templates[idx] = Object.assign({}, templates[idx], payload);
            }

            editHasChanges = false;
            modal.dataset.forceClose = '1';
            bootstrap.Modal.getInstance(modal).hide();
            renderList();
        } catch (err) {
            console.error('notifications_tab: handleSaveEdit error', err);
            HelpdeskUtils.showToast('Error de conexión', 'error');
        } finally {
            if (btnSave) btnSave.disabled = false;
        }
    }

    // === RENDER PREVIEW ===
    /**
     * Llama POST /{id}/preview con el body actual del textarea del modal (o del template).
     * Si showSpinner=true, muestra spinner mientras carga.
     * renderInElement: elemento donde volcar el resultado (o null para usar #notif-edit-preview-area).
     */
    async function renderPreviewInModal(modal, templateId, showSpinner) {
        const previewArea = modal.querySelector('#notif-edit-preview-area');
        if (!previewArea) return;

        const ticketInput  = modal.querySelector('#notif-edit-ticket-id');
        const ticketId     = ticketInput && ticketInput.value.trim() ? parseInt(ticketInput.value.trim(), 10) : null;

        // Body actual del textarea (puede diferir del guardado)
        const bodyTextarea = modal.querySelector('#notif-edit-body');
        const bodyVal      = bodyTextarea ? bodyTextarea.value : null;

        if (showSpinner) {
            previewArea.innerHTML = '<div class="text-center py-4 text-muted small"><div class="spinner-border spinner-border-sm" role="status"></div> Renderizando...</div>';
        }

        try {
            const payload = {};
            if (ticketId) payload.ticket_id = ticketId;
            // Pasamos el body actual aunque no esté guardado, si el backend lo soporta via sample_data
            // La API preview usa el template guardado; si el body ha cambiado mostramos nota.

            const res = await fetch(API_BASE + '/' + templateId + '/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al renderizar vista previa');
                previewArea.innerHTML = '<div class="alert alert-danger small py-2"><i class="fas fa-exclamation-circle me-1"></i>' + escapeHtml(msg) + '</div>';
                return;
            }

            const data = await res.json();
            renderPreviewResult(previewArea, data, bodyVal !== null && bodyVal !== (editingTemplate && editingTemplate.body_template));
        } catch (err) {
            console.error('notifications_tab: renderPreviewInModal error', err);
            previewArea.innerHTML = '<div class="alert alert-danger small py-2"><i class="fas fa-exclamation-circle me-1"></i>Error de conexión al renderizar.</div>';
        }
    }

    function renderPreviewResult(container, data, showUnsavedNote) {
        const subject  = data.subject  || null;
        const body     = data.body     || '';
        const warnings = data.warnings || [];

        let html = '';

        if (showUnsavedNote) {
            html += '<div class="alert alert-warning py-2 small mb-2"><i class="fas fa-exclamation-triangle me-1"></i>Vista previa basada en la versión guardada. Guarda los cambios para ver el resultado actualizado.</div>';
        }

        if (warnings.length) {
            html += '<div class="alert alert-warning py-2 small mb-2"><i class="fas fa-exclamation-triangle me-1"></i><strong>Advertencias:</strong><ul class="mb-0 mt-1">' +
                warnings.map(function (w) { return '<li>' + escapeHtml(w) + '</li>'; }).join('') +
                '</ul></div>';
        }

        if (subject) {
            html += '<div class="notification-preview-subject"><i class="fas fa-envelope me-1 text-warning"></i>Asunto: ' + escapeHtml(subject) + '</div>';
        }

        html += '<pre class="notification-preview-body">' + escapeHtml(body) + '</pre>';

        container.innerHTML = html;
    }

    // === MODAL VISTA PREVIA RÁPIDA ===

    function openPreviewModal(t) {
        const modal = document.getElementById('modal-notification-preview');
        if (!modal) return;

        // Header: code + name
        const headerEl = modal.querySelector('#notif-preview-header');
        if (headerEl) {
            headerEl.innerHTML =
                '<span class="notification-code me-2">' + escapeHtml(t.code) + '</span>' +
                '<span class="fw-semibold">' + escapeHtml(t.name) + '</span> ' +
                channelChipHtml(t.channel);
        }

        // Limpiar y mostrar spinner en área de preview
        const previewArea = modal.querySelector('#notif-preview-body-area');
        if (previewArea) {
            previewArea.innerHTML = '<div class="text-center py-4 text-muted small"><div class="spinner-border spinner-border-sm" role="status"></div> Renderizando...</div>';
        }

        // Botón "Editar"
        const btnEdit = modal.querySelector('#btn-notif-preview-open-edit');
        if (btnEdit) {
            // Clonar para limpiar listeners anteriores
            const newBtn = btnEdit.cloneNode(true);
            btnEdit.parentNode.replaceChild(newBtn, btnEdit);
            newBtn.addEventListener('click', function () {
                bootstrap.Modal.getInstance(modal).hide();
                // Esperar que el modal se cierre antes de abrir el editor
                modal.addEventListener('hidden.bs.modal', function onHidden() {
                    modal.removeEventListener('hidden.bs.modal', onHidden);
                    const fresh = findById(t.id);
                    if (fresh) openEditModal(fresh);
                });
            });
        }

        bootstrap.Modal.getOrCreateInstance(modal).show();

        // Llamar preview con dummy data (sin ticket_id)
        loadPreviewForPreviewModal(t.id, previewArea);
    }

    async function loadPreviewForPreviewModal(templateId, container) {
        try {
            const res = await fetch(API_BASE + '/' + templateId + '/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });

            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al renderizar');
                container.innerHTML = '<div class="alert alert-danger small py-2"><i class="fas fa-exclamation-circle me-1"></i>' + escapeHtml(msg) + '</div>';
                return;
            }

            const data = await res.json();
            renderPreviewResult(container, data, false);
        } catch (err) {
            console.error('notifications_tab: loadPreviewForPreviewModal error', err);
            container.innerHTML = '<div class="alert alert-danger small py-2"><i class="fas fa-exclamation-circle me-1"></i>Error de conexión.</div>';
        }
    }

    function bindPreviewModal() {
        const modal = document.getElementById('modal-notification-preview');
        if (!modal) return;
        if (modal.dataset.notifPreviewBound) return;
        modal.dataset.notifPreviewBound = '1';

        // Nada extra necesario aquí: el listener del botón Editar se regenera en openPreviewModal.
    }

})();
