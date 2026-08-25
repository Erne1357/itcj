/**
 * panel/users.js — usuarios con acceso a Calidad (módulo RECORTADO, D8).
 *
 * Expone SOLO `window.AdhocPanelUsers` (IIFE; el legacy dejaba
 * `class UsuariosManager` en el scope global).
 *
 * QUÉ DESAPARECE del legacy (`js/control_panel/users.js`, 300+ líneas)
 * -------------------------------------------------------------------
 *  · El alta de personas y el cambio de contraseña: el formulario construía a
 *    mano <input type="password"> y pegaba a un endpoint ANÓNIMO que creaba el
 *    usuario con `role_id=4` (en esta BD, `admin`). Ahora eso vive en
 *    /itcj/config y aquí solo hay un enlace.
 *  · El borrado, que apuntaba a `/api/usuarios/delete/` — una ruta inexistente:
 *    tras el confirm() nativo, un 404 silencioso.
 *  · Los dos `confirm()`/`alert()` (borrado y validación de contraseñas).
 *  · El `<select>` de áreas construido concatenando `${a.name}` sin escapar
 *    dentro de un template literal, alimentado por un array JS que Jinja
 *    serializaba a mano. Aquí las áreas se piden a la API y cada opción se
 *    construye con createElement + textContent.
 *
 * QUÉ HACE
 * --------
 *  · Lista los usuarios con acceso a Calidad (GET /users).
 *  · Asigna el rol de la app  (PUT /users/{id}/app-role).
 *  · Asigna las áreas         (PUT /users/{id}/areas).
 *
 * CONFIGURACIÓN
 * -------------
 *   Sección: data-adhoc-users, data-adhoc-api, data-adhoc-areas-api,
 *            data-adhoc-can-assign-role, data-adhoc-can-assign-areas.
 *   Bloque JSON `adhoc-page-data`: {roles: [{value,label}], canAssignRole,
 *            canAssignAreas, canReadAreas}.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var DASH = '—';   // guion largo para las celdas vacías

    // ==================== HELPERS ====================

    function bool(value) {
        return value === '1' || value === 'true' || value === true;
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    function modalFor(el) {
        if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
        return window.bootstrap.Modal.getOrCreateInstance(el);
    }

    /** <td> con texto plano (textContent: nada de innerHTML con datos). */
    function textCell(key, value, css) {
        var td = document.createElement('td');
        td.setAttribute('data-adhoc-cell', key);
        if (css) td.className = css;
        td.textContent = (value === null || value === undefined || value === '')
            ? DASH : String(value);
        return td;
    }

    function mutedSpan(text) {
        var span = document.createElement('span');
        span.className = 'adhoc-users-muted';
        span.textContent = text;
        return span;
    }

    // ==================== INSTANCIA ====================

    function PanelUsers(root) {
        var d = root.dataset;
        var data = (U && typeof U.pageData === 'function') ? U.pageData() : {};

        this.root = root;
        this.api = d.adhocApi || '/api/adhoc/v2/users';
        this.areasApi = d.adhocAreasApi || '/api/adhoc/v2/areas';
        this.canAssignRole = bool(d.adhocCanAssignRole) && data.canAssignRole !== false;
        this.canAssignAreas = bool(d.adhocCanAssignAreas) && data.canAssignAreas !== false;
        this.canReadAreas = data.canReadAreas !== false;

        this.roles = Array.isArray(data.roles) ? data.roles : [];
        this.roleLabels = {};
        for (var i = 0; i < this.roles.length; i++) {
            this.roleLabels[this.roles[i].value] = this.roles[i].label;
        }

        this.table = root.querySelector('table[data-adhoc-table]');
        this.body = this.table ? this.table.querySelector('[data-adhoc-table-body]') : null;
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;

        this.roleModal = document.querySelector('[data-adhoc-users-modal="role"]');
        this.areasModal = document.querySelector('[data-adhoc-users-modal="areas"]');

        this.users = [];
        this.areas = null;          // null = aún no cargadas
        this.targetId = null;
    }

    PanelUsers.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] panel/users: falta la tabla de usuarios');
            return;
        }
        this.bind();
        this.load();
    };

    // ---------- carga y pintado ----------

    PanelUsers.prototype.load = function () {
        var self = this;
        return U.fetchJson(this.api)
            .then(function (payload) {
                self.users = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                self.users = [];
                self.render();
                toast('No se pudieron cargar los usuarios: ' + err.message, 'error');
            });
    };

    PanelUsers.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.users.length; i++) {
            frag.appendChild(this.buildRow(this.users[i]));
        }

        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) {
            this.body.insertBefore(frag, this.emptyRow);
        } else {
            this.body.appendChild(frag);
        }

        if (window.AdhocTableFilter && this.table) {
            window.AdhocTableFilter.apply(this.table);
        }
    };

    PanelUsers.prototype.buildRow = function (user) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(user.id));

        // --- nombre ---
        var tdName = document.createElement('td');
        tdName.setAttribute('data-adhoc-cell', 'name');
        var name = document.createElement('div');
        name.className = 'adhoc-users-name';
        name.textContent = user.full_name || [user.last_name, user.first_name]
            .filter(Boolean).join(' ') || DASH;
        tdName.appendChild(name);
        tr.appendChild(tdName);

        // --- usuario / número de control ---
        tr.appendChild(textCell('username', user.username || user.control_number));

        // --- correo ---
        tr.appendChild(textCell('email', user.email));

        // --- roles en la app ---
        var tdRoles = document.createElement('td');
        tdRoles.setAttribute('data-adhoc-cell', 'roles');
        var roles = Array.isArray(user.roles) ? user.roles : [];
        if (!roles.length) {
            tdRoles.appendChild(mutedSpan('Sin rol'));
        } else {
            var rolesBox = document.createElement('div');
            rolesBox.className = 'adhoc-users-chips';
            for (var r = 0; r < roles.length; r++) {
                // Rol: texto violeta, no pastilla (el legacy pinta las celdas
                // de la tabla en texto plano).
                var badge = document.createElement('span');
                badge.className = 'adhoc-badge adhoc-status adhoc-badge-primary';
                badge.textContent = this.roleLabels[roles[r]] || roles[r];
                rolesBox.appendChild(badge);
            }
            tdRoles.appendChild(rolesBox);
        }
        tr.appendChild(tdRoles);

        // --- áreas ---
        var tdAreas = document.createElement('td');
        tdAreas.setAttribute('data-adhoc-cell', 'areas');
        var areas = Array.isArray(user.areas) ? user.areas : [];
        if (!areas.length) {
            tdAreas.appendChild(mutedSpan('Sin áreas'));
        } else {
            var areasBox = document.createElement('div');
            areasBox.className = 'adhoc-users-chips';
            for (var a = 0; a < areas.length; a++) {
                var chip = document.createElement('span');
                chip.className = 'adhoc-chip';
                var chipLabel = document.createElement('span');
                chipLabel.className = 'adhoc-chip-label';
                chipLabel.textContent = areas[a].name || '';
                chip.appendChild(chipLabel);
                areasBox.appendChild(chip);
            }
            tdAreas.appendChild(areasBox);
        }
        tr.appendChild(tdAreas);

        // --- estatus del usuario en el core ---
        var tdActive = document.createElement('td');
        tdActive.setAttribute('data-adhoc-cell', 'is_active');
        tdActive.className = 'adhoc-col-center';
        // Estatus como en el legacy: texto en verde/rojo, no una pastilla.
        var status = document.createElement('span');
        status.className = 'adhoc-badge adhoc-status ' +
            (user.is_active ? 'adhoc-badge-success' : 'adhoc-badge-danger');
        status.textContent = user.is_active ? 'Activo' : 'Inactivo';
        tdActive.appendChild(status);
        tr.appendChild(tdActive);

        // --- acciones ---
        if (this.canAssignRole || this.canAssignAreas) {
            var tdActions = document.createElement('td');
            tdActions.className = 'adhoc-col-end';
            tdActions.appendChild(this.buildActions());
            tr.appendChild(tdActions);
        }

        return tr;
    };

    PanelUsers.prototype.buildActions = function () {
        var box = document.createElement('div');
        box.className = 'adhoc-actions';
        var html = '';
        if (this.canAssignRole) {
            html += '<button type="button" class="btn btn-sm btn-outline-secondary adhoc-btn-icon" ' +
                    'data-adhoc-action="role" title="Cambiar rol" aria-label="Cambiar rol">' +
                    '<i class="fa-solid fa-user-tag"></i></button>';
        }
        if (this.canAssignAreas) {
            html += '<button type="button" class="btn btn-sm btn-outline-secondary adhoc-btn-icon" ' +
                    'data-adhoc-action="areas" title="Asignar áreas" aria-label="Asignar áreas">' +
                    '<i class="fa-solid fa-layer-group"></i></button>';
        }
        box.innerHTML = html;   // markup estático, sin datos del servidor
        return box;
    };

    // ---------- utilidades ----------

    PanelUsers.prototype.find = function (id) {
        for (var i = 0; i < this.users.length; i++) {
            if (String(this.users[i].id) === String(id)) return this.users[i];
        }
        return null;
    };

    PanelUsers.prototype.showTarget = function (modal, user) {
        var box = modal ? modal.querySelector('[data-adhoc-users-target]') : null;
        if (!box) return;
        box.textContent = 'Usuario: ';
        var strong = document.createElement('strong');
        strong.textContent = user.full_name || String(user.id);
        box.appendChild(strong);
    };

    // ---------- rol de la app ----------

    PanelUsers.prototype.openRole = function (id) {
        var user = this.find(id);
        if (!user || !this.roleModal) return;

        this.targetId = user.id;
        this.showTarget(this.roleModal, user);

        var select = this.roleModal.querySelector('[data-adhoc-users-role-select]');
        if (select) {
            select.textContent = '';
            var placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Seleccionar...';
            select.appendChild(placeholder);

            for (var i = 0; i < this.roles.length; i++) {
                var opt = document.createElement('option');
                opt.value = this.roles[i].value;
                opt.textContent = this.roles[i].label;   // textContent, nunca innerHTML
                select.appendChild(opt);
            }

            // Preselección: el primer rol del usuario que exista en el vocabulario.
            var current = '';
            var owned = Array.isArray(user.roles) ? user.roles : [];
            for (var r = 0; r < owned.length; r++) {
                if (this.roleLabels[owned[r]] !== undefined) { current = owned[r]; break; }
            }
            select.value = current;
        }

        var modal = modalFor(this.roleModal);
        if (modal) modal.show();
    };

    PanelUsers.prototype.saveRole = function () {
        var self = this;
        var id = this.targetId;
        if (id === null || id === undefined) return;

        var select = this.roleModal.querySelector('[data-adhoc-users-role-select]');
        var btn = this.roleModal.querySelector('[data-adhoc-users-save-role]');
        var role = select ? select.value : '';

        if (!role) {
            toast('Selecciona un rol.', 'warning');
            if (select) select.focus();
            return;
        }

        busy(btn, true);
        U.fetchJson(this.api + '/' + encodeURIComponent(id) + '/app-role', {
            method: 'PUT',
            body: JSON.stringify({ role: role })
        }).then(function (payload) {
            toast((payload && payload.message) || 'Rol actualizado.', 'success');
            var modal = modalFor(self.roleModal);
            if (modal) modal.hide();
            return self.load();
        }).catch(function (err) {
            toast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    // ---------- áreas ----------

    PanelUsers.prototype.openAreas = function (id) {
        var self = this;
        var user = this.find(id);
        if (!user || !this.areasModal) return;

        this.targetId = user.id;
        this.showTarget(this.areasModal, user);

        var modal = modalFor(this.areasModal);
        if (modal) modal.show();

        this.ensureAreas().then(function () {
            self.renderAreaOptions(user);
        });
    };

    /** Carga el catálogo de áreas una sola vez y lo cachea. */
    PanelUsers.prototype.ensureAreas = function () {
        var self = this;
        if (this.areas !== null) return Promise.resolve(this.areas);
        if (!this.canReadAreas) {
            this.areas = [];
            return Promise.resolve(this.areas);
        }
        return U.fetchJson(this.areasApi)
            .then(function (payload) {
                self.areas = (payload && payload.data) || [];
                return self.areas;
            })
            .catch(function (err) {
                self.areas = [];
                toast('No se pudo cargar el catálogo de áreas: ' + err.message, 'error');
                return self.areas;
            });
    };

    PanelUsers.prototype.renderAreaOptions = function (user) {
        var box = this.areasModal.querySelector('[data-adhoc-users-areas-list]');
        if (!box) return;

        box.textContent = '';

        var areas = this.areas || [];
        if (!areas.length) {
            var empty = document.createElement('p');
            empty.className = 'adhoc-users-areas-empty';
            empty.textContent = this.canReadAreas
                ? 'No hay áreas registradas.'
                : 'No tienes permiso para consultar el catálogo de áreas.';
            box.appendChild(empty);
            return;
        }

        var owned = {};
        var userAreas = Array.isArray(user.areas) ? user.areas : [];
        for (var u = 0; u < userAreas.length; u++) owned[String(userAreas[u].id)] = true;

        for (var i = 0; i < areas.length; i++) {
            var area = areas[i];
            var id = 'adhoc-users-area-' + area.id;

            var option = document.createElement('label');
            option.className = 'adhoc-users-area-option form-check';
            option.setAttribute('for', id);

            var input = document.createElement('input');
            input.type = 'checkbox';
            input.className = 'form-check-input';
            input.id = id;
            input.value = String(area.id);
            input.checked = owned[String(area.id)] === true;
            input.setAttribute('data-adhoc-users-area', '');

            var label = document.createElement('span');
            label.className = 'adhoc-users-area-name';
            label.textContent = area.name || '';        // textContent, nunca innerHTML
            if (area.is_active === false) label.textContent += ' (inactiva)';

            option.appendChild(input);
            option.appendChild(label);
            box.appendChild(option);
        }
    };

    PanelUsers.prototype.saveAreas = function () {
        var self = this;
        var id = this.targetId;
        if (id === null || id === undefined) return;

        var btn = this.areasModal.querySelector('[data-adhoc-users-save-areas]');
        var inputs = this.areasModal.querySelectorAll('[data-adhoc-users-area]');
        var ids = [];

        for (var i = 0; i < inputs.length; i++) {
            if (inputs[i].checked) {
                var value = parseInt(inputs[i].value, 10);
                if (!isNaN(value)) ids.push(value);
            }
        }

        busy(btn, true);
        U.fetchJson(this.api + '/' + encodeURIComponent(id) + '/areas', {
            method: 'PUT',
            body: JSON.stringify({ area_ids: ids })
        }).then(function (payload) {
            toast((payload && payload.message) || 'Áreas actualizadas.', 'success');
            var modal = modalFor(self.areasModal);
            if (modal) modal.hide();
            return self.load();
        }).catch(function (err) {
            toast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    PanelUsers.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            var btn = evt.target.closest('[data-adhoc-action]');
            if (!btn) return;
            var tr = btn.closest('tr[data-id]');
            if (!tr) return;
            evt.preventDefault();

            var action = btn.getAttribute('data-adhoc-action');
            var id = tr.getAttribute('data-id');
            if (action === 'role') self.openRole(id);
            else if (action === 'areas') self.openAreas(id);
        });

        if (this.roleModal) {
            this.roleModal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-adhoc-users-save-role]')) {
                    evt.preventDefault();
                    self.saveRole();
                }
            });
        }

        if (this.areasModal) {
            this.areasModal.addEventListener('click', function (evt) {
                if (evt.target.closest('[data-adhoc-users-save-areas]')) {
                    evt.preventDefault();
                    self.saveAreas();
                }
            });
        }
    };

    // ==================== API PÚBLICA ====================

    function init(root) {
        var node = root || document.querySelector('[data-adhoc-users]');
        if (!node) return null;
        if (node.dataset.adhocUsersBound === '1') return null;   // idempotente
        node.dataset.adhocUsersBound = '1';

        var instance = new PanelUsers(node);
        instance.init();
        return instance;
    }

    function initAll(scope) {
        var node = scope || document;
        var out = [];
        var made;

        if (node.matches && node.matches('[data-adhoc-users]')) {
            made = init(node);
            if (made) out.push(made);
        }

        var roots = node.querySelectorAll('[data-adhoc-users]');
        for (var i = 0; i < roots.length; i++) {
            made = init(roots[i]);
            if (made) out.push(made);
        }
        return out;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }

    window.AdhocPanelUsers = { init: init, initAll: initAll };
})();
