/**
 * ticket-create.js — Formulario de nueva solicitud de Mantenimiento
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var _selectedCategory = null;  // objeto completo {id, code, name, icon, field_template}
    var _selectedPriority = 'MEDIA';
    var _attachedFiles = [];       // archivos seleccionados para adjuntar al crear
    var _userDepartments = [];     // deptos activos del usuario

    document.addEventListener('DOMContentLoaded', function () {
        _checkUnratedTickets();
        _loadCategories();
        _loadDepartments();
        _bindPriority();
        _bindDropzone();
        _bindSubmit();
    });

    // ── Departamentos del solicitante ─────────────────────────────────────────
    function _loadDepartments() {
        fetch(API_BASE + '/tickets/my-departments', { credentials: 'include' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (resp) {
                if (!resp) return;
                _userDepartments = resp.data || [];
                var wrap = document.getElementById('departmentWrap');
                var sel = document.getElementById('departmentSelect');
                if (!wrap || !sel) return;
                if (_userDepartments.length <= 1) {
                    wrap.style.display = 'none';
                    return;
                }
                wrap.style.display = '';
                sel.innerHTML = '<option value="">Selecciona un departamento...</option>' +
                    _userDepartments.map(function (d) {
                        return '<option value="' + d.id + '">' + _esc(d.name) + '</option>';
                    }).join('');
            })
            .catch(function () { /* silent */ });
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

    // ── Aviso de solicitudes sin calificar ────────────────────────────────────

    function _checkUnratedTickets() {
        fetch(API_BASE + '/dashboard', { credentials: 'include' })
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) {
                if (!data) return;
                var unrated = data.unrated_resolved;
                if (typeof unrated !== 'number' || unrated < 3) return;

                var form = document.getElementById('createTicketForm');
                if (!form) return;

                var alert = document.createElement('div');
                alert.id = 'unratedAlert';
                alert.className = 'alert alert-warning mb-4';
                alert.innerHTML =
                    '<div class="d-flex align-items-start gap-2">' +
                        '<i class="bi bi-exclamation-triangle-fill mt-1 flex-shrink-0"></i>' +
                        '<div>' +
                            '<strong>Tienes ' + unrated + ' solicitudes resueltas sin calificar.</strong> ' +
                            'Por favor califícalas antes de crear nuevas.' +
                            '<div class="mt-2">' +
                                '<a href="/maint/tickets?status=RESOLVED_SUCCESS,RESOLVED_FAILED" class="btn btn-sm btn-warning me-2">' +
                                    '<i class="bi bi-star me-1"></i>Ver mis solicitudes' +
                                '</a>' +
                            '</div>' +
                            '<div class="form-check mt-3">' +
                                '<input class="form-check-input" type="checkbox" id="unratedBypass">' +
                                '<label class="form-check-label small" for="unratedBypass">Continuar de todos modos</label>' +
                            '</div>' +
                        '</div>' +
                    '</div>';
                form.insertBefore(alert, form.firstChild);

                // Deshabilitar submit hasta que el checkbox esté marcado
                var submitBtn = document.getElementById('submitBtn');
                if (submitBtn) submitBtn.disabled = true;

                document.getElementById('unratedBypass').addEventListener('change', function () {
                    if (submitBtn) submitBtn.disabled = !this.checked;
                });
            })
            .catch(function () {
                // Fail silently — no bloquear el formulario
            });
    }

    // ── Dropzone de adjuntos ──────────────────────────────────────────────────

    function _bindDropzone() {
        var zone = document.getElementById('attachDropzone');
        var input = document.getElementById('attachFileInput');
        var preview = document.getElementById('attachPreview');
        if (!zone || !input) return;

        zone.addEventListener('click', function () { input.click(); });

        zone.addEventListener('dragover', function (e) {
            e.preventDefault();
            zone.classList.add('dragover');
        });
        zone.addEventListener('dragleave', function () { zone.classList.remove('dragover'); });
        zone.addEventListener('drop', function (e) {
            e.preventDefault();
            zone.classList.remove('dragover');
            _addFiles(Array.from(e.dataTransfer.files || []));
        });

        input.addEventListener('change', function () {
            _addFiles(Array.from(input.files || []));
            input.value = '';  // reset so same file can be re-selected
        });

        function _addFiles(files) {
            files.forEach(function (f) {
                if (f.size > 3 * 1024 * 1024) {
                    MaintUtils.toast('El archivo "' + f.name + '" supera el límite de 3 MB', 'warning');
                    return;
                }
                _attachedFiles.push(f);
            });
            _renderAttachPreview();
        }

        function _renderAttachPreview() {
            if (!preview) return;
            if (!_attachedFiles.length) {
                preview.innerHTML = '';
                return;
            }
            var items = _attachedFiles.map(function (f, idx) {
                return '<div class="d-flex align-items-center gap-2 p-1 border rounded bg-light small">' +
                    '<i class="bi bi-file-earmark text-secondary flex-shrink-0"></i>' +
                    '<span class="text-truncate flex-grow-1">' + _esc(f.name) + '</span>' +
                    '<button type="button" class="btn btn-sm btn-link text-danger p-0" data-idx="' + idx + '" title="Quitar">' +
                        '<i class="bi bi-x-lg"></i>' +
                    '</button>' +
                '</div>';
            });
            preview.innerHTML = '<div class="d-flex flex-column gap-1 mt-2">' + items.join('') + '</div>';
            preview.querySelectorAll('[data-idx]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var idx = parseInt(btn.dataset.idx, 10);
                    _attachedFiles.splice(idx, 1);
                    _renderAttachPreview();
                });
            });
        }
    }

    // ── Cargar categorías ─────────────────────────────────────────────────────

    function _loadCategories() {
        MaintUtils.api.fetch(API_BASE + '/categories')
            .then(function (data) {
                _renderCategories(data.categories || []);
            })
            .catch(function () {
                document.getElementById('categorySkeleton').innerHTML =
                    '<div class="col-12"><div class="alert alert-warning mb-0">No se pudieron cargar las categorías.</div></div>';
            });
    }

    var CAT_ICON_MAP = {
        TRANSPORT: 'bi-truck', GENERAL: 'bi-tools', ELECTRICAL: 'bi-lightning-charge',
        CARPENTRY: 'bi-hammer', AC: 'bi-thermometer-snow', GARDENING: 'bi-tree',
    };

    function _renderCategories(categories) {
        var skeleton = document.getElementById('categorySkeleton');
        var container = document.getElementById('categoryCards');

        skeleton.style.display = 'none';
        container.style.display = '';

        categories.forEach(function (cat) {
            var icon = cat.icon || CAT_ICON_MAP[cat.code] || 'bi-tools';
            var col = document.createElement('div');
            col.className = 'col-6 col-sm-4 col-md-3 col-lg-2';
            col.innerHTML =
                '<div class="mn-category-card" data-id="' + cat.id + '">' +
                    '<div class="cat-icon"><i class="bi ' + _esc(icon) + '"></i></div>' +
                    '<div class="cat-name">' + _esc(cat.name) + '</div>' +
                '</div>';
            col.querySelector('.mn-category-card').addEventListener('click', function () {
                _selectCategory(cat);
            });
            container.appendChild(col);
        });
    }

    function _selectCategory(cat) {
        _selectedCategory = cat;

        document.querySelectorAll('.mn-category-card').forEach(function (c) {
            c.classList.remove('selected');
        });
        document.querySelector('[data-id="' + cat.id + '"]').classList.add('selected');
        document.getElementById('categoryId').value = cat.id;
        document.getElementById('categoryError').style.display = 'none';

        _renderCustomFields(cat.field_template || []);
    }

    // ── Campos dinámicos ──────────────────────────────────────────────────────

    function _renderCustomFields(fields) {
        var section = document.getElementById('customFieldsSection');
        var body = document.getElementById('customFieldsBody');
        body.innerHTML = '';

        if (!fields || fields.length === 0) {
            section.style.display = 'none';
            return;
        }

        fields.forEach(function (f) {
            var col = document.createElement('div');
            col.className = 'col-md-6';
            var required = f.required ? ' <span class="text-danger">*</span>' : '';
            var input = '';

            if (f.type === 'select' && Array.isArray(f.options)) {
                input = '<select class="form-select" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>' +
                    '<option value="">Selecciona...</option>' +
                    f.options.map(function (o) { return '<option value="' + _esc(o) + '">' + _esc(o) + '</option>'; }).join('') +
                    '</select>';
            } else if (f.type === 'number') {
                input = '<input type="number" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '" min="0"' +
                    (f.required ? ' required' : '') + '>';
            } else if (f.type === 'date') {
                input = '<input type="date" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>';
            } else if (f.type === 'time') {
                input = '<input type="time" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>';
            } else {
                input = '<input type="text" class="form-control" id="cf_' + _esc(f.key) + '" data-cf-key="' + _esc(f.key) + '"' +
                    (f.required ? ' required' : '') + '>';
            }

            col.innerHTML =
                '<label class="form-label fw-medium" for="cf_' + _esc(f.key) + '">' + _esc(f.label) + required + '</label>' +
                input;
            body.appendChild(col);
        });

        section.style.display = '';
    }

    // ── Prioridad ─────────────────────────────────────────────────────────────

    function _bindPriority() {
        document.getElementById('priorityCards').addEventListener('click', function (e) {
            var card = e.target.closest('.mn-priority-card');
            if (!card) return;
            document.querySelectorAll('.mn-priority-card').forEach(function (c) { c.classList.remove('selected'); });
            card.classList.add('selected');
            _selectedPriority = card.dataset.priority;
            document.getElementById('priorityId').value = _selectedPriority;
        });
    }

    // ── Submit ────────────────────────────────────────────────────────────────

    function _bindSubmit() {
        document.getElementById('createTicketForm').addEventListener('submit', function (e) {
            e.preventDefault();
            _submitForm();
        });
    }

    function _submitForm() {
        var btn = document.getElementById('submitBtn');
        var valid = true;

        // Validar categoría
        if (!_selectedCategory) {
            document.getElementById('categoryError').style.display = 'block';
            valid = false;
        }

        var title = document.getElementById('titleInput').value.trim();
        var description = document.getElementById('descriptionInput').value.trim();

        _setInvalid('titleInput', title.length < 5);
        _setInvalid('descriptionInput', description.length < 10);
        if (title.length < 5 || description.length < 10) valid = false;

        // Validar custom fields requeridos
        if (_selectedCategory && _selectedCategory.field_template) {
            _selectedCategory.field_template.forEach(function (f) {
                if (f.required) {
                    var el = document.getElementById('cf_' + f.key);
                    if (el && !el.value.trim()) {
                        el.classList.add('is-invalid');
                        valid = false;
                    }
                }
            });
        }

        if (!valid) return;

        // Recopilar custom fields
        var customFields = {};
        document.querySelectorAll('[data-cf-key]').forEach(function (el) {
            var key = el.dataset.cfKey;
            if (el.value.trim()) customFields[key] = el.value.trim();
        });

        var deptSel = document.getElementById('departmentSelect');
        var deptVal = deptSel ? deptSel.value : '';
        if (deptSel && _userDepartments.length > 1 && !deptVal) {
            MaintUtils.toast('Selecciona el departamento solicitante.', 'warning');
            deptSel.classList.add('is-invalid');
            return;
        }
        var payload = {
            category_id: _selectedCategory.id,
            priority: _selectedPriority,
            title: title,
            description: description,
            location: document.getElementById('locationInput').value.trim() || null,
            custom_fields: Object.keys(customFields).length > 0 ? customFields : null,
            department_id: deptVal ? parseInt(deptVal, 10) : null,
        };

        MaintUtils.loading.show(btn, 'Enviando...');

        MaintUtils.api.fetch(API_BASE + '/tickets', {
            method: 'POST',
            body: JSON.stringify(payload),
        })
            .then(function (data) {
                MaintUtils.toast('Solicitud creada: ' + data.ticket_number, 'success');
                var ticketId = data.ticket_id || data.id;
                if (_attachedFiles.length && ticketId) {
                    _uploadAttachments(ticketId, _attachedFiles).then(function () {
                        window.location.href = '/maint/tickets/' + ticketId;
                    });
                } else {
                    setTimeout(function () {
                        window.location.href = '/maint/tickets/' + ticketId;
                    }, 800);
                }
            })
            .catch(function (err) {
                MaintUtils.loading.hide(btn);
                MaintUtils.alert({ title: 'No se pudo crear la solicitud', message: err.message, type: 'error' });
            });
    }

    // ── Subida de adjuntos post-creación ──────────────────────────────────────

    function _uploadAttachments(ticketId, files) {
        var url = API_BASE + '/tickets/' + ticketId + '/attachments';
        var promises = files.map(function (file) {
            var fd = new FormData();
            fd.append('file', file);
            fd.append('attachment_type', 'ticket');
            return fetch(url, { method: 'POST', credentials: 'include', body: fd })
                .then(function (res) {
                    if (!res.ok) {
                        MaintUtils.toast('No se pudo subir: ' + file.name, 'warning');
                    }
                })
                .catch(function () {
                    MaintUtils.toast('Error al subir: ' + file.name, 'warning');
                });
        });
        return Promise.all(promises);
    }

    function _setInvalid(id, isInvalid) {
        var el = document.getElementById(id);
        if (!el) return;
        if (isInvalid) {
            el.classList.add('is-invalid');
            el.addEventListener('input', function () { el.classList.remove('is-invalid'); }, { once: true });
        } else {
            el.classList.remove('is-invalid');
        }
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

})();
