/**
 * ticket-create.js — Formulario de nueva solicitud de Mantenimiento
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var _selectedCategory = null;  // objeto completo {id, code, name, icon, field_template}
    var _selectedPriority = 'MEDIA';  // se ajusta en _bindPriority() según la prioridad default de BD
    var _attachedFiles = [];       // archivos seleccionados para adjuntar al crear
    var _userDepartments = [];     // deptos activos del usuario
    var _canCreateBehalf = (typeof CAN_CREATE_BEHALF !== 'undefined') && CAN_CREATE_BEHALF;

    // Estado del modal "Solicitar para"
    var _behalfUsers = [];         // lista completa cargada del API
    var _behalfSelected = null;    // {id, name, email} o null = yo mismo
    var _behalfModal = null;       // instancia Bootstrap Modal
    var _behalfDebounceTimer = null;

    document.addEventListener('DOMContentLoaded', function () {
        _checkUnratedTickets();
        _loadCategories();
        _loadDepartments();
        _bindPriority();
        _bindDropzone();
        _bindSubmit();
        if (_canCreateBehalf) {
            _initBehalfModal();
        }
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

    // ── Modal "Solicitar para" ────────────────────────────────────────────────

    /** Inicializa el modal de Bootstrap y enlaza eventos del trigger y del buscador. */
    function _initBehalfModal() {
        var modalEl = document.getElementById('behalfModal');
        var trigger = document.getElementById('behalfTrigger');
        var searchInput = document.getElementById('behalfSearchInput');
        if (!modalEl || !trigger) return;

        _behalfModal = new bootstrap.Modal(modalEl);

        // El selector siempre está disponible para quien puede crear en nombre
        // de otro (no depende de un departamento: mantenimiento atiende a todos).
        var behalfWrap = document.getElementById('behalfWrap');
        if (behalfWrap) behalfWrap.style.display = '';
        _updateBehalfTrigger(null);  // por defecto "Yo mismo"

        // Abrir modal al clicar el trigger
        trigger.addEventListener('click', function () {
            if (trigger.getAttribute('aria-disabled') === 'true') return;
            _renderBehalfList('');
            _behalfModal.show();
            trigger.setAttribute('aria-expanded', 'true');
        });

        // También abrir con Enter/Space (accesibilidad)
        trigger.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                trigger.click();
            }
        });

        // Resetear buscador al abrir
        modalEl.addEventListener('show.bs.modal', function () {
            if (searchInput) searchInput.value = '';
        });

        // Focus en buscador tras apertura
        modalEl.addEventListener('shown.bs.modal', function () {
            if (searchInput) searchInput.focus();
        });

        modalEl.addEventListener('hidden.bs.modal', function () {
            trigger.setAttribute('aria-expanded', 'false');
        });

        // Búsqueda server-side (todo el instituto) con debounce
        if (searchInput) {
            searchInput.addEventListener('input', function () {
                clearTimeout(_behalfDebounceTimer);
                var q = searchInput.value;
                _behalfDebounceTimer = setTimeout(function () {
                    _searchBehalfUsers(q);
                }, 300);
            });
        }
    }

    /**
     * Busca usuarios en TODO el instituto vía API (mantenimiento atiende a
     * cualquier departamento). Requiere >=2 caracteres.
     * @param {string} query
     */
    function _searchBehalfUsers(query) {
        var q = (query || '').trim();
        if (q.length < 2) {
            _behalfUsers = [];
            _renderBehalfList(query);  // mostrará la pista de "escribe para buscar"
            return;
        }
        var list = document.getElementById('behalfUserList');
        if (list) {
            list.innerHTML =
                '<li class="mn-behalf-loading">' +
                    '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>' +
                    'Buscando...' +
                '</li>';
        }
        fetch(API_BASE + '/users?search=' + encodeURIComponent(q), { credentials: 'include' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (resp) {
                _behalfUsers = (resp && resp.data) ? resp.data : [];
                _renderBehalfList(query);
            })
            .catch(function () {
                _behalfUsers = [];
                _renderBehalfList(query);
            });
    }

    /**
     * Carga usuarios del dpto desde la API y los guarda en _behalfUsers.
     * Muestra el wrap si hay usuarios; oculta si no hay.
     * @param {number} departmentId
     */
    function _loadBehalfUsers(departmentId) {
        if (!_canCreateBehalf) return;
        var behalfWrap = document.getElementById('behalfWrap');
        if (!behalfWrap) return;

        // Mostrar spinner en la lista mientras carga (por si el modal ya estuviera abierto)
        _behalfUsers = [];
        _renderBehalfList('');   // mostrará estado "cargando"

        fetch(API_BASE + '/users?department_id=' + departmentId, { credentials: 'include' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (resp) {
                if (!resp || !resp.data || resp.data.length === 0) {
                    _clearBehalfSelect();
                    return;
                }
                _behalfUsers = resp.data;  // [{id, name, email?}, ...]
                behalfWrap.style.display = '';
                _renderBehalfList('');
            })
            .catch(function () {
                _clearBehalfSelect();
            });
    }

    /** Resetea la selección y oculta el wrap. */
    function _clearBehalfSelect() {
        _behalfUsers = [];
        _behalfSelected = null;
        _updateBehalfTrigger(null);
        var behalfWrap = document.getElementById('behalfWrap');
        if (behalfWrap) behalfWrap.style.display = 'none';
        var hiddenInput = document.getElementById('behalfUserId');
        if (hiddenInput) hiddenInput.value = '';
    }

    /**
     * Renderiza la lista filtrada en el modal.
     * @param {string} query  Texto del buscador.
     */
    function _renderBehalfList(query) {
        var list = document.getElementById('behalfUserList');
        if (!list) return;

        var q = (query || '').trim();

        // Siempre incluir "Yo mismo" al inicio
        var items = [];
        var selfSelected = !_behalfSelected;
        var selfClasses = 'mn-behalf-item' + (selfSelected ? ' selected' : '');
        items.push(
            '<li class="' + selfClasses + '" data-user-id="" role="option" aria-selected="' + selfSelected + '">' +
                '<span class="mn-avatar mn-avatar-lg" style="background:var(--maint-accent);">YO</span>' +
                '<div class="d-flex flex-column overflow-hidden">' +
                    '<span class="mn-behalf-item-name">— Yo mismo —</span>' +
                '</div>' +
                (selfSelected ? '<i class="bi bi-check2 text-success ms-auto flex-shrink-0"></i>' : '') +
            '</li>'
        );

        if (q.length < 2) {
            // Pista: hay que escribir para buscar en todo el instituto
            items.push(
                '<li class="mn-behalf-empty">' +
                    '<i class="bi bi-search d-block fs-4 mb-1"></i>' +
                    'Escribe al menos 2 letras para buscar un usuario de cualquier departamento.' +
                '</li>'
            );
        } else if (_behalfUsers.length === 0) {
            items.push(
                '<li class="mn-behalf-empty">' +
                    '<i class="bi bi-person-x d-block fs-4 mb-1"></i>' +
                    'No se encontraron usuarios para <strong>"' + _esc(query) + '"</strong>' +
                '</li>'
            );
        } else {
            _behalfUsers.forEach(function (u) {
                var isSelected = _behalfSelected && _behalfSelected.id === u.id;
                var cls = 'mn-behalf-item' + (isSelected ? ' selected' : '');
                var initials = _getInitials(u.name);
                var color = _avatarColor(u.name);
                var metaParts = [];
                if (u.department) metaParts.push(_esc(u.department));
                if (u.email) metaParts.push(_esc(u.email));
                var metaHtml = metaParts.length
                    ? '<span class="mn-behalf-item-email">' + metaParts.join(' · ') + '</span>'
                    : '';
                items.push(
                    '<li class="' + cls + '" data-user-id="' + u.id + '" data-user-name="' + _esc(u.name) + '"' +
                        (u.email ? ' data-user-email="' + _esc(u.email) + '"' : '') +
                        ' role="option" aria-selected="' + isSelected + '">' +
                        '<span class="mn-avatar mn-avatar-lg" style="background:' + color + ';">' + initials + '</span>' +
                        '<div class="d-flex flex-column overflow-hidden">' +
                            '<span class="mn-behalf-item-name">' + _esc(u.name) + '</span>' +
                            metaHtml +
                        '</div>' +
                        (isSelected ? '<i class="bi bi-check2 text-success ms-auto flex-shrink-0"></i>' : '') +
                    '</li>'
                );
            });
        }

        list.innerHTML = items.join('');

        // Vincular clicks en los items
        list.querySelectorAll('.mn-behalf-item[data-user-id]').forEach(function (li) {
            li.addEventListener('click', function () {
                var uid = li.dataset.userId;
                if (!uid) {
                    // "Yo mismo"
                    _selectBehalfUser(null);
                } else {
                    _selectBehalfUser({
                        id: parseInt(uid, 10),
                        name: li.dataset.userName || '',
                        email: li.dataset.userEmail || '',
                    });
                }
            });
        });
    }

    /**
     * Selecciona un usuario (o null = yo mismo), actualiza trigger, cierra modal.
     * @param {{id:number, name:string, email?:string}|null} user
     */
    function _selectBehalfUser(user) {
        _behalfSelected = user || null;
        _updateBehalfTrigger(user);

        var hiddenInput = document.getElementById('behalfUserId');
        if (hiddenInput) hiddenInput.value = user ? user.id : '';

        if (_behalfModal) {
            _behalfModal.hide();
        }
    }

    /**
     * Actualiza el campo trigger con el avatar e info del usuario seleccionado.
     * @param {{id:number, name:string, email?:string}|null} user
     */
    function _updateBehalfTrigger(user) {
        var avatarEl = document.getElementById('behalfTriggerAvatar');
        var nameEl   = document.getElementById('behalfTriggerName');
        var emailEl  = document.getElementById('behalfTriggerEmail');
        if (!avatarEl || !nameEl) return;

        if (!user) {
            avatarEl.textContent = 'YO';
            avatarEl.style.background = 'var(--maint-accent)';
            nameEl.textContent = '— Yo mismo —';
            if (emailEl) { emailEl.textContent = ''; emailEl.style.display = 'none'; }
        } else {
            avatarEl.textContent = _getInitials(user.name);
            avatarEl.style.background = _avatarColor(user.name);
            nameEl.textContent = user.name;
            if (emailEl) {
                if (user.email) {
                    emailEl.textContent = user.email;
                    emailEl.style.display = '';
                } else {
                    emailEl.textContent = '';
                    emailEl.style.display = 'none';
                }
            }
        }
    }

    /**
     * Obtiene las iniciales de un nombre (máx 2 letras).
     * @param {string} name
     * @returns {string}
     */
    function _getInitials(name) {
        if (!name) return '?';
        var parts = name.trim().split(/\s+/).filter(Boolean);
        if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    /**
     * Genera un color HSL estable a partir del nombre (hash simple).
     * @param {string} name
     * @returns {string} color CSS hsl(...)
     */
    function _avatarColor(name) {
        var s = String(name || '');
        var hash = 0;
        for (var i = 0; i < s.length; i++) {
            hash = s.charCodeAt(i) + ((hash << 5) - hash);
            hash = hash & hash; // forzar 32 bits
        }
        var hue = Math.abs(hash) % 360;
        // Evitar tonos muy cercanos al gris del tema (200-220°) para no confundir con "Yo mismo"
        if (hue >= 195 && hue <= 225) hue = (hue + 40) % 360;
        return 'hsl(' + hue + ', 48%, 42%)';
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
        var cards = document.querySelectorAll('.mn-priority-card');
        // Preseleccionar la prioridad default (data-default) o la que ya venga marcada,
        // o la primera tarjeta como último recurso.
        var defaultCard = document.querySelector('.mn-priority-card[data-default="true"]') ||
            document.querySelector('.mn-priority-card.selected') ||
            (cards.length ? cards[0] : null);
        if (defaultCard) {
            cards.forEach(function (c) { c.classList.remove('selected'); });
            defaultCard.classList.add('selected');
            _selectedPriority = defaultCard.dataset.priority;
            document.getElementById('priorityId').value = _selectedPriority;
        }

        document.getElementById('priorityCards').addEventListener('click', function (e) {
            var card = e.target.closest('.mn-priority-card');
            if (!card) return;
            cards.forEach(function (c) { c.classList.remove('selected'); });
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

        // Solicitante: otro usuario si se eligió en el modal behalf
        var behalfHidden = document.getElementById('behalfUserId');
        var behalfVal = (behalfHidden && _canCreateBehalf) ? behalfHidden.value.trim() : '';
        var requesterId = behalfVal ? parseInt(behalfVal, 10) : null;

        var payload = {
            category_id: _selectedCategory.id,
            priority: _selectedPriority,
            title: title,
            description: description,
            location: document.getElementById('locationInput').value.trim() || null,
            custom_fields: Object.keys(customFields).length > 0 ? customFields : null,
            department_id: deptVal ? parseInt(deptVal, 10) : null,
        };

        // Solo enviar requester_id si se eligió a otro usuario
        if (requesterId) {
            payload.requester_id = requesterId;
        }

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
