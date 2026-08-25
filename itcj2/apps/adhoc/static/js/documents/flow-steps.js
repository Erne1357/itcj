/**
 * documents/flow-steps.js — diseño de un flujo de aprobación
 * (/adhoc/documentos/flujos/{flow_id}/pasos).
 *
 * Expone SOLO `window.AdhocFlowSteps` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `documents_steps.js` del legacy (clase global `ConfigFlujoManager`):
 *   - guardaba con `this.form.submit()` contra `save_flow_steps`, que BORRABA
 *     todos los pasos y los recreaba con ids nuevos (bug #3): las tareas ya
 *     creadas y el `current_step_id` de los documentos quedaban colgando;
 *   - abría el modal de confirmación con `style.display='flex'`;
 *   - añadía filas con `tr.innerHTML = \`…\`` y estilos inline;
 *   - mandaba a otra PÁGINA para asignar validadores
 *     (`window.location.href = data-url`), y recargaba con un
 *     `pageshow`/`location.reload()` para esquivar la caché del "atrás".
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   GET /approval-flows/{flow_id}/steps
 *       → {success, data: [{id, flow_id, name, days_limit, step_order, assignee_count}]}
 *   PUT /approval-flows/{flow_id}/steps
 *       body {"steps": [{name, days_limit, step_order}]}   ← UPSERT por step_order
 *       409 si hay documentos en revisión con este flujo, o si un paso a
 *       eliminar está referenciado por tareas o documentos.
 *   GET /approval-flows/steps/{step_id}
 *       → {success, data: {step, assigned: [...], notify: [...]}}
 *   PUT /approval-flows/steps/{step_id}/validators             body {"user_ids": []}
 *   PUT /approval-flows/steps/{step_id}/overdue-notifications  body {"user_ids": []}
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var Picker = window.AdhocUserPicker;

    var TABLE_ID = 'adhoc-steps-table';
    var API = '/approval-flows';
    var COLUMNS = 5;
    var MAX_DAYS = 365;

    var MODES = {
        validators: {
            title: 'Validadores del paso',
            icon: 'bi-person-check',
            path: '/validators',
            hint: 'Quién tiene que aprobar el documento en este paso.',
            key: 'assigned',
            ok: 'Validadores asignados al paso.'
        },
        notify: {
            title: 'Avisos de atraso del paso',
            icon: 'bi-alarm',
            path: '/overdue-notifications',
            hint: 'Quién recibe el aviso si el paso se pasa de sus días límite. ' +
                  'Marcar a alguien que todavía no era validador también lo asigna al paso.',
            key: 'notify',
            ok: 'Avisos de atraso configurados.'
        }
    };

    // ==================== HELPERS ====================

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    function iconButton(action, icon, label, variant, disabled) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm ' + (variant || 'btn-outline-secondary') + ' adhoc-btn-icon';
        btn.setAttribute('data-adhoc-step-action', action);
        btn.title = label;
        btn.setAttribute('aria-label', label);
        if (disabled) btn.disabled = true;
        btn.innerHTML = '<i class="bi ' + icon + '"></i>';   // markup estático
        return btn;
    }

    function cellWith(row, node, className) {
        var td = document.createElement('td');
        if (className) td.className = className;
        td.appendChild(node);
        row.appendChild(td);
        return td;
    }

    // ==================== INSTANCIA ====================

    function FlowSteps(root) {
        this.root = root;
        this.data = (U && typeof U.pageData === 'function') ? U.pageData() : {};

        this.flowId = this.data.flow_id;
        this.canUpdate = !!this.data.can_update;
        this.canAssign = !!this.data.can_assign;

        this.table = root.querySelector('#' + TABLE_ID);
        this.body = root.querySelector('#' + TABLE_ID + '-body');
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;
        this.qtySelect = root.querySelector('[data-adhoc-steps-qty]');

        this.modal = document.querySelector('[data-adhoc-step-modal]');
        this.modalTitle = this.modal ? this.modal.querySelector('[data-adhoc-step-modal-title]') : null;
        this.modalHint = this.modal ? this.modal.querySelector('[data-adhoc-step-modal-hint]') : null;
        this.pickerEl = document.getElementById('adhoc-step-users-picker');

        this.steps = [];
        this.details = {};          // cache stepId → {assigned, notify}
        this.mode = 'validators';
        this.currentStepId = null;
    }

    FlowSteps.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] flow-steps: falta el cuerpo de la tabla');
            return this;
        }
        this.bind();
        this.load();
        return this;
    };

    // ---------- carga y pintado ----------

    FlowSteps.prototype.load = function () {
        var self = this;
        return U.fetchJson(API + '/' + encodeURIComponent(this.flowId) + '/steps')
            .then(function (payload) {
                self.steps = (payload && payload.data) || [];
                self.details = {};
                self.render();
            })
            .catch(function (err) {
                self.steps = [];
                self.render();
                U.showToast('No se pudieron cargar los pasos: ' + err.message, 'error');
            });
    };

    FlowSteps.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.steps.length; i++) {
            var step = this.steps[i];
            frag.appendChild(this.buildRow(step, i + 1));
            frag.appendChild(this.buildDetailRow(step.id));
        }

        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) this.body.insertBefore(frag, this.emptyRow);
        else this.body.appendChild(frag);
    };

    FlowSteps.prototype.buildRow = function (step, order) {
        var saved = step.id !== null && step.id !== undefined && step.id !== '';

        var tr = document.createElement('tr');
        tr.setAttribute('data-adhoc-step-row', '');
        if (saved) tr.setAttribute('data-step-id', String(step.id));

        // — orden —
        var orderLabel = document.createElement('span');
        orderLabel.className = 'adhoc-step-order';
        orderLabel.textContent = String(order);
        cellWith(tr, orderLabel, 'adhoc-col-center');

        // — nombre —
        var name = document.createElement('input');
        name.type = 'text';
        name.className = 'form-control form-control-sm';
        name.maxLength = 100;
        name.value = step.name || '';        // .value, nunca innerHTML
        name.placeholder = 'Nombre del paso';
        name.setAttribute('aria-label', 'Nombre del paso ' + order);
        name.setAttribute('data-adhoc-step-name', '');
        if (!this.canUpdate) name.disabled = true;
        cellWith(tr, name);

        // — días límite —
        var days = document.createElement('input');
        days.type = 'number';
        days.className = 'form-control form-control-sm adhoc-step-days';
        days.min = '1';
        days.max = String(MAX_DAYS);
        days.value = String(step.days_limit || 3);
        days.setAttribute('aria-label', 'Días límite del paso ' + order);
        days.setAttribute('data-adhoc-step-days', '');
        if (!this.canUpdate) days.disabled = true;
        cellWith(tr, days);

        // — validadores —
        var badge = document.createElement('span');
        if (saved) {
            var count = parseInt(step.assignee_count, 10) || 0;
            badge.className = 'badge adhoc-badge adhoc-badge-' + (count ? 'info' : 'danger');
            badge.textContent = count ? (count + ' validador(es)') : 'Sin validadores';
        } else {
            badge.className = 'badge adhoc-badge adhoc-badge-muted';
            badge.textContent = 'Sin guardar';
        }
        cellWith(tr, badge, 'adhoc-col-center');

        // — acciones —
        var actions = document.createElement('div');
        actions.className = 'adhoc-actions';

        if (saved) {
            actions.appendChild(iconButton('toggle', 'bi-chevron-down',
                                           'Ver validadores asignados'));
        }
        if (this.canAssign) {
            actions.appendChild(iconButton(
                'validators', 'bi-person-check', saved
                    ? 'Asignar validadores'
                    : 'Guarda el diseño para poder asignar validadores',
                'btn-outline-primary', !saved));
            actions.appendChild(iconButton(
                'notify', 'bi-alarm', saved
                    ? 'Configurar avisos de atraso'
                    : 'Guarda el diseño para poder configurar los avisos',
                'btn-outline-warning', !saved));
        }
        if (this.canUpdate) {
            actions.appendChild(iconButton('remove', 'bi-trash',
                                           'Quitar este paso del diseño', 'btn-outline-danger'));
        }
        cellWith(tr, actions, 'adhoc-col-end');

        return tr;
    };

    FlowSteps.prototype.buildDetailRow = function (stepId) {
        var tr = document.createElement('tr');
        tr.className = 'adhoc-step-detail';
        tr.setAttribute('data-detail-for', String(stepId));
        tr.hidden = true;

        var td = document.createElement('td');
        td.colSpan = COLUMNS;
        td.setAttribute('data-adhoc-step-detail-body', '');
        tr.appendChild(td);
        return tr;
    };

    // ---------- detalle de un paso ----------

    FlowSteps.prototype.detailsOf = function (stepId) {
        var self = this;
        var cached = this.details[stepId];
        if (cached) return Promise.resolve(cached);

        return U.fetchJson(API + '/steps/' + encodeURIComponent(stepId))
            .then(function (payload) {
                var data = (payload && payload.data) || {};
                var detail = {
                    assigned: data.assigned || [],
                    notify: data.notify || []
                };
                self.details[stepId] = detail;
                return detail;
            });
    };

    FlowSteps.prototype.toggleDetail = function (stepId) {
        var self = this;
        var row = this.body.querySelector(
            '.adhoc-step-detail[data-detail-for="' + String(stepId).replace(/["\\]/g, '\\$&') + '"]'
        );
        if (!row) return;

        if (!row.hidden) {
            row.hidden = true;
            return;
        }

        this.detailsOf(stepId)
            .then(function (detail) {
                self.fillDetail(row, detail);
                row.hidden = false;
            })
            .catch(function (err) {
                U.showToast('No se pudo cargar el detalle del paso: ' + err.message, 'error');
            });
    };

    FlowSteps.prototype.fillDetail = function (row, detail) {
        var td = row.querySelector('[data-adhoc-step-detail-body]');
        td.textContent = '';

        var box = document.createElement('div');
        box.className = 'adhoc-step-detail-box';

        var title = document.createElement('p');
        title.className = 'adhoc-step-detail-title';
        title.textContent = 'Validadores de este paso';
        box.appendChild(title);

        if (!detail.assigned.length) {
            var empty = document.createElement('p');
            empty.className = 'adhoc-step-detail-empty';
            empty.textContent = 'Todavía no hay validadores asignados a este paso.';
            box.appendChild(empty);
        } else {
            var notify = {};
            for (var n = 0; n < detail.notify.length; n++) {
                notify[String(detail.notify[n].id)] = true;
            }

            var list = document.createElement('ul');
            list.className = 'adhoc-step-users';
            for (var i = 0; i < detail.assigned.length; i++) {
                var user = detail.assigned[i];
                var item = document.createElement('li');

                var nameEl = document.createElement('span');
                nameEl.className = 'adhoc-step-user-name';
                nameEl.textContent = user.name || ('#' + user.id);   // textContent
                item.appendChild(nameEl);

                if (notify[String(user.id)]) {
                    var flag = document.createElement('span');
                    flag.className = 'badge adhoc-badge adhoc-badge-warning';
                    flag.textContent = 'Avisar si se atrasa';
                    item.appendChild(flag);
                }
                list.appendChild(item);
            }
            box.appendChild(list);
        }

        td.appendChild(box);
    };

    // ---------- edición del diseño ----------

    FlowSteps.prototype.addSteps = function () {
        var qty = this.qtySelect ? (parseInt(this.qtySelect.value, 10) || 1) : 1;
        var order = this.body.querySelectorAll('[data-adhoc-step-row]').length;

        var frag = document.createDocumentFragment();
        for (var i = 1; i <= qty; i++) {
            frag.appendChild(this.buildRow({ name: '', days_limit: 3 }, order + i));
        }
        if (this.emptyRow) this.body.insertBefore(frag, this.emptyRow);
        else this.body.appendChild(frag);

        var inputs = this.body.querySelectorAll('[data-adhoc-step-name]');
        if (inputs.length) inputs[inputs.length - qty].focus();
    };

    FlowSteps.prototype.removeRow = function (tr) {
        var stepId = tr.getAttribute('data-step-id');
        if (stepId) {
            var detail = this.body.querySelector(
                '.adhoc-step-detail[data-detail-for="' + stepId.replace(/["\\]/g, '\\$&') + '"]'
            );
            if (detail) detail.remove();
        }
        tr.remove();
        this.renumber();
    };

    FlowSteps.prototype.renumber = function () {
        var rows = this.body.querySelectorAll('[data-adhoc-step-row]');
        for (var i = 0; i < rows.length; i++) {
            var label = rows[i].querySelector('.adhoc-step-order');
            if (label) label.textContent = String(i + 1);
        }
    };

    /** Lee la tabla en orden de DOM. Devuelve null si algo no valida. */
    FlowSteps.prototype.collect = function () {
        var rows = this.body.querySelectorAll('[data-adhoc-step-row]');
        var out = [];

        for (var i = 0; i < rows.length; i++) {
            var nameInput = rows[i].querySelector('[data-adhoc-step-name]');
            var daysInput = rows[i].querySelector('[data-adhoc-step-days]');
            var name = nameInput ? nameInput.value.trim() : '';
            var days = daysInput ? parseInt(daysInput.value, 10) : 3;

            if (!name) {
                U.showToast('El paso ' + (i + 1) + ' no tiene nombre.', 'warning');
                if (nameInput) nameInput.focus();
                return null;
            }
            if (isNaN(days) || days < 1 || days > MAX_DAYS) {
                U.showToast('Los días límite del paso ' + (i + 1) +
                            ' deben estar entre 1 y ' + MAX_DAYS + '.', 'warning');
                if (daysInput) daysInput.focus();
                return null;
            }
            out.push({ name: name, days_limit: days, step_order: i + 1 });
        }
        return out;
    };

    FlowSteps.prototype.save = function () {
        var self = this;
        var steps = this.collect();
        if (steps === null) return;

        var removed = this.steps.length - steps.length;
        var message = '¿Guardar este diseño de flujo?';
        if (removed > 0) {
            message += ' Se eliminarán ' + removed + ' paso(s); la operación se ' +
                       'rechaza si alguno está en uso por un documento o una tarea.';
        }

        U.confirmDialog({
            title: 'Guardar diseño',
            message: message,
            confirmText: 'Guardar'
        }).then(function (ok) {
            if (!ok) return null;
            var buttons = self.root.querySelectorAll('[data-adhoc-steps-save]');
            for (var i = 0; i < buttons.length; i++) busy(buttons[i], true);

            return U.fetchJson(API + '/' + encodeURIComponent(self.flowId) + '/steps', {
                method: 'PUT',
                body: JSON.stringify({ steps: steps })
            }).then(function () {
                U.showToast('Diseño del flujo guardado.', 'success');
                return self.load();
            }).catch(function (err) {
                // 409: documentos en revisión con este flujo, o un paso en uso.
                U.showToast(err.message, 'error');
            }).then(function () {
                for (var j = 0; j < buttons.length; j++) busy(buttons[j], false);
            });
        });
    };

    // ---------- modal de usuarios ----------

    FlowSteps.prototype.openUsers = function (stepId, mode) {
        var self = this;
        var config = MODES[mode];
        if (!config || !this.modal) return;

        this.mode = mode;
        this.currentStepId = stepId;

        if (this.modalTitle) {
            this.modalTitle.innerHTML = '<i class="bi ' + config.icon + ' me-2"></i>'; // estático
            this.modalTitle.appendChild(document.createTextNode(config.title));
        }
        if (this.modalHint) this.modalHint.textContent = config.hint;

        this.detailsOf(stepId)
            .then(function (detail) {
                var picker = Picker ? Picker.get(self.pickerEl) : null;
                if (picker) {
                    var chosen = detail[config.key] || [];
                    picker.setSelection(chosen.map(function (u) { return u.id; }));
                }
                self.show();
            })
            .catch(function (err) {
                U.showToast('No se pudo cargar el paso: ' + err.message, 'error');
            });
    };

    FlowSteps.prototype.saveUsers = function () {
        var self = this;
        var config = MODES[this.mode];
        var picker = Picker ? Picker.get(this.pickerEl) : null;
        if (!config || !picker) return;

        var btn = this.modal.querySelector('[data-adhoc-step-users-save]');
        busy(btn, true);

        U.fetchJson(API + '/steps/' + encodeURIComponent(this.currentStepId) + config.path, {
            method: 'PUT',
            body: JSON.stringify({ user_ids: picker.getSelection() })
        }).then(function (payload) {
            U.showToast((payload && payload.message) || config.ok, 'success');
            delete self.details[self.currentStepId];   // el cache queda rancio
            self.hide();
            return self.load();
        }).catch(function (err) {
            U.showToast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    FlowSteps.prototype.show = function () {
        if (this.modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).show();
        }
    };

    FlowSteps.prototype.hide = function () {
        if (this.modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).hide();
        }
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    FlowSteps.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-steps-add]')) {
                evt.preventDefault();
                self.addSteps();
                return;
            }
            if (evt.target.closest('[data-adhoc-steps-save]')) {
                evt.preventDefault();
                self.save();
                return;
            }

            var btn = evt.target.closest('[data-adhoc-step-action]');
            if (!btn || btn.disabled) return;
            var tr = btn.closest('[data-adhoc-step-row]');
            if (!tr) return;
            evt.preventDefault();

            var action = btn.getAttribute('data-adhoc-step-action');
            var stepId = tr.getAttribute('data-step-id');

            if (action === 'remove') { self.removeRow(tr); return; }
            if (!stepId) return;                    // paso aún sin guardar

            if (action === 'toggle') self.toggleDetail(stepId);
            else if (action === 'validators') self.openUsers(stepId, 'validators');
            else if (action === 'notify') self.openUsers(stepId, 'notify');
        });

        if (this.modal) {
            this.modal.addEventListener('click', function (evt) {
                if (!evt.target.closest('[data-adhoc-step-users-save]')) return;
                evt.preventDefault();
                self.saveUsers();
            });
        }
    };

    // ==================== API PÚBLICA ====================

    function init(scope) {
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-flow-steps]'))
            ? node
            : node.querySelector('[data-adhoc-flow-steps]');
        if (!root) return null;
        if (root.dataset.adhocFlowStepsBound === '1') return null;   // idempotente
        root.dataset.adhocFlowStepsBound = '1';

        return new FlowSteps(root).init();
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocFlowSteps = { init: init };
})();
