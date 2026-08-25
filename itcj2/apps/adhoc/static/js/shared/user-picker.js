/**
 * shared/user-picker.js — selector múltiple de usuarios de Calidad.
 *
 * Expone SOLO `window.AdhocUserPicker` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * En el legacy los usuarios se inyectaban desde Jinja como HTML CRUDO dentro de
 * un template literal (`INCIDENTS_CONFIG.htmlUsers`, `TAREAS_CONFIG.htmlUsers`,
 * `PROGRAMS_CONFIG.htmlUsers`, `USUARIOS_CONFIG.areasAppJson`), sin `|tojson` ni
 * escape de backticks: un apellido con un apóstrofo o con `${` rompía la página
 * o inyectaba script. Y la pantalla de asignación (`tasks_users.html`) pintaba
 * la tabla entera desde Jinja con un N+1 por usuario.
 *
 * Aquí los usuarios llegan como JSON en el bloque `page_data_script()` y el DOM
 * se construye en JS con textContent (cero innerHTML con datos del servidor).
 *
 * DÓNDE SE USA
 * ------------
 *   - asignación de responsables de tarea  → PUT /api/adhoc/v2/tasks/{id}/assignees
 *   - validadores de un paso de flujo      → PUT /api/adhoc/v2/approval-flows/steps/{id}/validators
 *   - avisos de vencimiento                → PUT …/overdue-notifications
 * Los tres reciben `{"user_ids": [1, 2, 3]}`.
 *
 * EL ORDEN IMPORTA
 * ----------------
 * Con `ordered: true` la selección se numera y `getSelection()` devuelve los ids
 * EN EL ORDEN EN QUE SE MARCARON: en los pasos de aprobación ese es el orden
 * secuencial de validación (lo dice la propia pantalla del legacy). Sin
 * `ordered` el orden sigue siendo estable, pero no se muestra.
 *
 * MARCADO DECLARATIVO (macro `user_picker()` de partials/_macros.html)
 * -------------------------------------------------------------------
 *   <div data-adhoc-user-picker
 *        data-adhoc-users-key="users"          ← clave dentro de page_data
 *        data-adhoc-selected-key="assigned_ids"
 *        data-adhoc-name="user_ids"
 *        data-adhoc-ordered="1"></div>
 *
 * USO DESDE JS
 * ------------
 *   var picker = AdhocUserPicker.mount(el, { users: [...], selected: [3], ordered: true });
 *   picker.getSelection();            // [3, 7]
 *   picker.setSelection([1, 2]);
 *   el.addEventListener('adhoc:user-picker-change', function (e) { e.detail.selected });
 *
 * Para un <select> de UN solo usuario (el caso del modal de tareas del legacy):
 *   AdhocUserPicker.fillSelect(selectEl, users, { selected: 4 });
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    // ==================== HELPERS ====================

    function displayName(user) {
        if (!user) return '';
        if (user.full_name) return String(user.full_name);
        var parts = [];
        if (user.first_name) parts.push(user.first_name);
        if (user.last_name) parts.push(user.last_name);
        if (user.middle_name) parts.push(user.middle_name);
        if (parts.length) return parts.join(' ');
        if (user.name) return String(user.name);
        if (user.username) return String(user.username);
        return '#' + user.id;
    }

    /** Segunda línea: puesto / departamento / correo, lo que haya. */
    function metaLine(user) {
        var bits = [];
        if (user.position) bits.push(user.position);
        if (user.position_title) bits.push(user.position_title);
        if (user.department) bits.push(user.department);
        if (user.area) bits.push(user.area);
        if (user.email) bits.push(user.email);
        if (!bits.length && user.username) bits.push(user.username);
        return bits.join(' · ');
    }

    function normalize(value) {
        var text = (value === null || value === undefined) ? '' : String(value);
        if (text.normalize) text = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        return text.toLowerCase();
    }

    function searchBlob(user) {
        return normalize([
            displayName(user), user.email, user.username, user.control_number,
            user.position, user.position_title, user.department, user.area
        ].filter(Boolean).join(' '));
    }

    function toIdList(value) {
        if (!value) return [];
        var list = Array.isArray(value) ? value : [value];
        var out = [];
        for (var i = 0; i < list.length; i++) {
            if (list[i] === null || list[i] === undefined || list[i] === '') continue;
            out.push(String(list[i]));
        }
        return out;
    }

    // ==================== INSTANCIA ====================

    function Picker(root, opts) {
        var o = opts || {};
        var d = root.dataset || {};

        this.root = root;
        this.users = o.users || [];
        this.ordered = o.ordered !== undefined ? !!o.ordered : (d.adhocOrdered === '1');
        this.name = o.name || d.adhocName || 'user_ids';
        this.searchPlaceholder = o.searchPlaceholder || d.adhocSearchPlaceholder ||
            'Buscar por nombre, correo o puesto...';
        this.emptyMessage = o.emptyMessage || 'No hay usuarios disponibles.';
        this.selected = toIdList(o.selected);
        this.term = '';
        this.nodes = {};
    }

    Picker.prototype.render = function () {
        var box = document.createElement('div');
        box.className = 'adhoc-user-picker-box';

        // — cabecera: buscador + contador —
        var head = document.createElement('div');
        head.className = 'adhoc-user-picker-head';

        var search = document.createElement('input');
        search.type = 'search';
        search.className = 'form-control form-control-sm adhoc-user-picker-search';
        search.placeholder = this.searchPlaceholder;
        search.setAttribute('aria-label', this.searchPlaceholder);
        head.appendChild(search);

        var count = document.createElement('span');
        count.className = 'adhoc-user-picker-count';
        head.appendChild(count);

        var clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'btn btn-sm btn-outline-secondary';
        clear.innerHTML = '<i class="fa-solid fa-eraser"></i>';   // markup estático
        clear.title = 'Limpiar selección';
        clear.setAttribute('aria-label', 'Limpiar selección');
        clear.setAttribute('data-adhoc-picker-clear', '');
        head.appendChild(clear);

        box.appendChild(head);

        // — lista —
        var list = document.createElement('div');
        list.className = 'adhoc-user-picker-list';
        list.setAttribute('role', 'group');
        box.appendChild(list);

        // — chips de lo seleccionado —
        var chips = document.createElement('div');
        chips.className = 'adhoc-user-picker-selected';
        box.appendChild(chips);

        // — valor para envíos por formulario clásico (opcional) —
        var hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = this.name;
        box.appendChild(hidden);

        this.root.appendChild(box);
        this.nodes = { box: box, search: search, count: count, list: list, chips: chips, hidden: hidden };

        this.renderList();
        this.renderSelection();
        this.bind();
    };

    Picker.prototype.renderList = function () {
        var list = this.nodes.list;
        list.textContent = '';

        var visible = 0;
        for (var i = 0; i < this.users.length; i++) {
            var user = this.users[i];
            if (this.term && searchBlob(user).indexOf(this.term) === -1) continue;
            list.appendChild(this.buildOption(user));
            visible++;
        }

        if (!visible) {
            var empty = document.createElement('p');
            empty.className = 'adhoc-picker-empty';
            empty.textContent = this.users.length ? 'Sin coincidencias.' : this.emptyMessage;
            list.appendChild(empty);
        }
        this.renderCount();
    };

    Picker.prototype.buildOption = function (user) {
        var id = String(user.id);
        var label = document.createElement('label');
        label.className = 'adhoc-user-option';

        var check = document.createElement('input');
        check.type = 'checkbox';
        check.className = 'form-check-input';
        check.value = id;
        check.checked = this.selected.indexOf(id) !== -1;
        check.setAttribute('data-adhoc-picker-check', '');
        label.appendChild(check);

        var body = document.createElement('div');
        body.className = 'adhoc-user-option-body';

        var name = document.createElement('span');
        name.className = 'adhoc-user-option-name';
        name.textContent = displayName(user);      // textContent, nunca innerHTML
        body.appendChild(name);

        var meta = metaLine(user);
        if (meta) {
            var metaEl = document.createElement('span');
            metaEl.className = 'adhoc-user-option-meta';
            metaEl.textContent = meta;
            body.appendChild(metaEl);
        }
        label.appendChild(body);

        if (this.ordered) {
            var order = this.selected.indexOf(id);
            var badge = document.createElement('span');
            badge.className = 'adhoc-order-badge';
            badge.setAttribute('data-adhoc-picker-order', id);
            badge.textContent = order === -1 ? '' : String(order + 1);
            badge.hidden = order === -1;
            label.appendChild(badge);
        }

        return label;
    };

    Picker.prototype.renderSelection = function () {
        var chips = this.nodes.chips;
        chips.textContent = '';

        for (var i = 0; i < this.selected.length; i++) {
            var user = this.find(this.selected[i]);
            var chip = document.createElement('span');
            chip.className = 'adhoc-chip';

            if (this.ordered) {
                var order = document.createElement('span');
                order.className = 'adhoc-order-badge';
                order.textContent = String(i + 1);
                chip.appendChild(order);
            }

            var text = document.createElement('span');
            text.className = 'adhoc-chip-label';
            text.textContent = user ? displayName(user) : ('#' + this.selected[i]);
            chip.appendChild(text);

            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'adhoc-chip-remove';
            remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';   // markup estático
            remove.title = 'Quitar';
            remove.setAttribute('aria-label', 'Quitar');
            remove.setAttribute('data-adhoc-picker-remove', this.selected[i]);
            chip.appendChild(remove);

            chips.appendChild(chip);
        }

        chips.hidden = this.selected.length === 0;
        this.nodes.hidden.value = this.selected.join(',');
        this.renderCount();
        this.syncBadges();
    };

    Picker.prototype.renderCount = function () {
        this.nodes.count.textContent = this.selected.length
            ? (this.selected.length + ' seleccionado(s)')
            : 'Ninguno seleccionado';
    };

    Picker.prototype.syncBadges = function () {
        if (!this.ordered) return;
        var badges = this.nodes.list.querySelectorAll('[data-adhoc-picker-order]');
        for (var i = 0; i < badges.length; i++) {
            var id = badges[i].getAttribute('data-adhoc-picker-order');
            var pos = this.selected.indexOf(id);
            badges[i].textContent = pos === -1 ? '' : String(pos + 1);
            badges[i].hidden = pos === -1;
        }
    };

    Picker.prototype.find = function (id) {
        for (var i = 0; i < this.users.length; i++) {
            if (String(this.users[i].id) === String(id)) return this.users[i];
        }
        return null;
    };

    Picker.prototype.toggle = function (id, on) {
        var key = String(id);
        var at = this.selected.indexOf(key);
        if (on && at === -1) this.selected.push(key);
        else if (!on && at !== -1) this.selected.splice(at, 1);
        this.renderSelection();
        this.emit();
    };

    Picker.prototype.emit = function () {
        try {
            this.root.dispatchEvent(new CustomEvent('adhoc:user-picker-change', {
                bubbles: true,
                detail: { selected: this.getSelection() }
            }));
        } catch (e) { /* sin CustomEvent constructor: no es crítico */ }
    };

    Picker.prototype.bind = function () {
        var self = this;

        this.nodes.search.addEventListener('input', function () {
            self.term = normalize(this.value);
            self.renderList();
            self.syncBadges();
        });

        this.nodes.list.addEventListener('change', function (evt) {
            var check = evt.target.closest('[data-adhoc-picker-check]');
            if (!check) return;
            self.toggle(check.value, check.checked);
        });

        this.nodes.chips.addEventListener('click', function (evt) {
            var btn = evt.target.closest('[data-adhoc-picker-remove]');
            if (!btn) return;
            evt.preventDefault();
            var id = btn.getAttribute('data-adhoc-picker-remove');
            self.toggle(id, false);
            var check = self.nodes.list.querySelector(
                '[data-adhoc-picker-check][value="' + String(id).replace(/["\\]/g, '\\$&') + '"]'
            );
            if (check) check.checked = false;
        });

        this.nodes.box.addEventListener('click', function (evt) {
            if (!evt.target.closest('[data-adhoc-picker-clear]')) return;
            evt.preventDefault();
            self.clear();
        });
    };

    // ---------- API de instancia ----------

    /** ids seleccionados, como enteros y EN ORDEN DE SELECCIÓN. */
    Picker.prototype.getSelection = function () {
        var out = [];
        for (var i = 0; i < this.selected.length; i++) {
            var n = parseInt(this.selected[i], 10);
            out.push(isNaN(n) ? this.selected[i] : n);
        }
        return out;
    };

    Picker.prototype.setSelection = function (ids) {
        this.selected = toIdList(ids);
        this.renderList();
        this.renderSelection();
    };

    Picker.prototype.setUsers = function (users) {
        this.users = users || [];
        this.renderList();
        this.renderSelection();
    };

    Picker.prototype.clear = function () {
        this.selected = [];
        this.renderList();
        this.renderSelection();
        this.emit();
    };

    Picker.prototype.destroy = function () {
        this.root.textContent = '';
        delete this.root.dataset.adhocPickerBound;
    };

    // ==================== API PÚBLICA ====================

    /**
     * Monta un selector en `el`.
     * @param {HTMLElement|string} el  elemento o id
     * @param {{users:Array, selected:Array, ordered:boolean, name:string,
     *          searchPlaceholder:string, emptyMessage:string}} [opts]
     * @returns {Picker|null}
     */
    function mount(el, opts) {
        var root = (typeof el === 'string') ? document.getElementById(el) : el;
        if (!root) return null;
        if (root.dataset.adhocPickerBound === '1') return root._adhocPicker || null;
        root.dataset.adhocPickerBound = '1';

        var picker = new Picker(root, opts);
        picker.render();
        root._adhocPicker = picker;
        return picker;
    }

    /** Devuelve la instancia ya montada sobre `el`, si la hay. */
    function get(el) {
        var root = (typeof el === 'string') ? document.getElementById(el) : el;
        return (root && root._adhocPicker) || null;
    }

    /**
     * Rellena un <select> de usuarios desde JSON. Reemplaza al `htmlUsers` del
     * legacy: cada <option> se crea con createElement + textContent, así que un
     * apellido con comillas o con markup no puede inyectar nada.
     * @param {HTMLSelectElement|string} select
     * @param {Array} users
     * @param {{selected:*, placeholder:?string, labelFn:Function}} [opts]
     */
    function fillSelect(select, users, opts) {
        var el = (typeof select === 'string') ? document.getElementById(select) : select;
        if (!el) return;
        var o = opts || {};
        var chosen = toIdList(o.selected);
        var label = typeof o.labelFn === 'function' ? o.labelFn : displayName;

        el.textContent = '';
        if (o.placeholder !== null) {
            var ph = document.createElement('option');
            ph.value = '';
            ph.textContent = o.placeholder || 'Seleccionar usuario...';
            el.appendChild(ph);
        }
        for (var i = 0; i < (users || []).length; i++) {
            var user = users[i];
            var option = document.createElement('option');
            option.value = String(user.id);
            option.textContent = label(user);
            if (chosen.indexOf(String(user.id)) !== -1) option.selected = true;
            el.appendChild(option);
        }
    }

    /** Monta los `[data-adhoc-user-picker]` que haya en `scope`, leyendo page_data. */
    function initAll(scope) {
        var node = scope || document;
        var data = (U && typeof U.pageData === 'function') ? U.pageData() : {};
        var roots = [];
        var i;

        if (node.matches && node.matches('[data-adhoc-user-picker]')) roots.push(node);
        var found = node.querySelectorAll('[data-adhoc-user-picker]');
        for (i = 0; i < found.length; i++) roots.push(found[i]);

        var out = [];
        for (i = 0; i < roots.length; i++) {
            var root = roots[i];
            var usersKey = root.dataset.adhocUsersKey || 'users';
            var selectedKey = root.dataset.adhocSelectedKey;
            var made = mount(root, {
                users: data[usersKey] || [],
                selected: selectedKey ? data[selectedKey] : []
            });
            if (made) out.push(made);
        }
        return out;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }

    window.AdhocUserPicker = {
        mount: mount,
        get: get,
        initAll: initAll,
        fillSelect: fillSelect,
        displayName: displayName
    };
})();
