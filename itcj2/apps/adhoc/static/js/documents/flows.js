/**
 * documents/flows.js — CRUD de flujos de aprobación (/adhoc/documentos/flujos).
 *
 * Expone SOLO `window.AdhocFlows` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `documents_flows.js` del legacy (clase global `FlujosManager`):
 *   - abría el modal con `style.display='flex'` y lo cerraba escuchando clics
 *     en el overlay;
 *   - borraba con el diálogo nativo del navegador dentro de un handler
 *     síncrono, con el `e.preventDefault()` invertido;
 *   - abría un diálogo nativo de "módulo en construcción" para un botón que
 *     nunca tuvo backend;
 *   - editaba al pulsar la fila entera, así que cada botón necesitaba
 *     `stopPropagation()`;
 *   - guardaba con `<form method="POST">` y `formaction` reescrito a mano, o
 *     sea recarga completa de página por cada cambio.
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   GET    /approval-flows        → {success, data: [{id, name, description, step_count}], total}
 *   POST   /approval-flows        → {success, data}
 *   PATCH  /approval-flows/{id}   → {success, data}
 *   DELETE /approval-flows/{id}   → {success, message} · 409 si hay documentos
 *                                    o tareas que usan sus pasos
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var TABLE_ID = 'adhoc-flows-table';
    var API = '/approval-flows';
    var STEPS_URL = '/adhoc/documentos/flujos/';

    // ==================== HELPERS ====================

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    function iconButton(action, icon, label, variant) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm ' + (variant || 'btn-outline-secondary') + ' adhoc-btn-icon';
        btn.setAttribute('data-adhoc-flow-action', action);
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.innerHTML = '<i class="bi ' + icon + '"></i>';   // markup estático
        return btn;
    }

    // ==================== INSTANCIA ====================

    function Flows(root) {
        this.root = root;
        this.data = (U && typeof U.pageData === 'function') ? U.pageData() : {};

        this.canCreate = !!this.data.can_create;
        this.canUpdate = !!this.data.can_update;
        this.canDelete = !!this.data.can_delete;

        this.table = root.querySelector('#' + TABLE_ID);
        this.body = root.querySelector('#' + TABLE_ID + '-body');
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;

        this.modal = document.querySelector('[data-adhoc-flow-modal]');
        this.modalTitle = this.modal ? this.modal.querySelector('[data-adhoc-flow-modal-title]') : null;
        this.inputName = document.getElementById('adhoc-flow-name');
        this.inputDescription = document.getElementById('adhoc-flow-description');

        this.items = [];
        this.editingId = null;
    }

    Flows.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] flows: falta el cuerpo de la tabla');
            return this;
        }
        this.bind();
        this.load();
        return this;
    };

    // ---------- carga y pintado ----------

    Flows.prototype.load = function () {
        var self = this;
        return U.fetchJson(API)
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                self.items = [];
                self.render();
                U.showToast('No se pudieron cargar los flujos: ' + err.message, 'error');
            });
    };

    Flows.prototype.render = function () {
        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.items.length; i++) {
            frag.appendChild(this.buildRow(this.items[i]));
        }

        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) this.body.insertBefore(frag, this.emptyRow);
        else this.body.appendChild(frag);

        if (window.AdhocTableFilter && this.table) {
            window.AdhocTableFilter.apply(this.table);
        }
    };

    Flows.prototype.buildRow = function (flow) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(flow.id));

        var tdName = document.createElement('td');
        tdName.setAttribute('data-adhoc-cell', 'name');
        tdName.className = 'adhoc-flow-name';
        tdName.textContent = flow.name || '';       // textContent, nunca innerHTML
        tr.appendChild(tdName);

        var tdDescription = document.createElement('td');
        tdDescription.setAttribute('data-adhoc-cell', 'description');
        tdDescription.className = 'adhoc-cell-clamp';
        tdDescription.textContent = flow.description || '';
        tr.appendChild(tdDescription);

        var tdSteps = document.createElement('td');
        tdSteps.setAttribute('data-adhoc-cell', 'steps');
        tdSteps.className = 'adhoc-col-center';
        var count = document.createElement('span');
        var total = parseInt(flow.step_count, 10) || 0;
        count.className = 'badge adhoc-badge adhoc-badge-' + (total ? 'info' : 'danger');
        count.textContent = total ? (total + ' paso(s)') : 'Sin pasos';
        tdSteps.appendChild(count);
        tr.appendChild(tdSteps);

        var tdActions = document.createElement('td');
        tdActions.setAttribute('data-adhoc-cell', 'actions');
        tdActions.className = 'adhoc-col-end';
        tdActions.appendChild(this.buildActions(flow));
        tr.appendChild(tdActions);

        return tr;
    };

    Flows.prototype.buildActions = function (flow) {
        var box = document.createElement('div');
        box.className = 'adhoc-actions';

        // Enlace real: se puede abrir en otra pestaña. El legacy hacía
        // window.location.href dentro de un listener.
        var steps = document.createElement('a');
        steps.className = 'btn btn-sm btn-outline-primary adhoc-btn-icon';
        steps.href = STEPS_URL + encodeURIComponent(flow.id) + '/pasos';
        steps.title = 'Configurar pasos';
        steps.setAttribute('aria-label', 'Configurar pasos');
        steps.innerHTML = '<i class="bi bi-list-ol"></i>';   // markup estático
        box.appendChild(steps);

        if (this.canUpdate) {
            box.appendChild(iconButton('edit', 'bi-pencil', 'Editar flujo'));
        }
        if (this.canDelete) {
            box.appendChild(iconButton('delete', 'bi-trash', 'Eliminar flujo',
                                       'btn-outline-danger'));
        }
        return box;
    };

    Flows.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    // ---------- alta y edición ----------

    Flows.prototype.openNew = function () {
        this.editingId = null;
        this.setTitle('Nuevo flujo');
        if (this.inputName) this.inputName.value = '';
        if (this.inputDescription) this.inputDescription.value = '';
        this.show();
    };

    Flows.prototype.openEdit = function (flow) {
        this.editingId = flow.id;
        this.setTitle('Editar flujo');
        if (this.inputName) this.inputName.value = flow.name || '';
        if (this.inputDescription) this.inputDescription.value = flow.description || '';
        this.show();
    };

    Flows.prototype.setTitle = function (textValue) {
        if (!this.modalTitle) return;
        this.modalTitle.innerHTML = '<i class="bi bi-diagram-3 me-2"></i>';  // estático
        this.modalTitle.appendChild(document.createTextNode(textValue));
    };

    Flows.prototype.save = function () {
        var self = this;
        var btn = this.modal.querySelector('[data-adhoc-flow-save]');
        var name = this.inputName ? this.inputName.value.trim() : '';
        var description = this.inputDescription ? this.inputDescription.value.trim() : '';

        if (!name) {
            U.showToast('El nombre del flujo no puede quedar vacío.', 'warning');
            if (this.inputName) this.inputName.focus();
            return;
        }

        var editing = this.editingId !== null && this.editingId !== undefined;
        var url = editing ? (API + '/' + encodeURIComponent(this.editingId)) : API;

        busy(btn, true);
        U.fetchJson(url, {
            method: editing ? 'PATCH' : 'POST',
            body: JSON.stringify({ name: name, description: description || null })
        }).then(function () {
            U.showToast(editing ? 'Flujo actualizado.' : 'Flujo creado.', 'success');
            self.hide();
            return self.load();
        }).catch(function (err) {
            U.showToast(err.message, 'error');
        }).then(function () {
            busy(btn, false);
        });
    };

    // ---------- borrado ----------

    Flows.prototype.remove = function (flow) {
        var self = this;
        U.confirmDialog({
            title: 'Eliminar flujo',
            message: '¿Eliminar "' + (flow.name || '') + '" y todos sus pasos? ' +
                     'No se puede si algún documento ya lo está usando.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson(API + '/' + encodeURIComponent(flow.id), { method: 'DELETE' })
                .then(function (payload) {
                    U.showToast((payload && payload.message) || 'Flujo eliminado.', 'success');
                    return self.load();
                })
                .catch(function (err) {
                    // 409: hay documentos en revisión o tareas colgando de sus pasos.
                    U.showToast(err.message, 'error');
                });
        });
    };

    // ---------- modal ----------

    Flows.prototype.show = function () {
        if (this.modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).show();
        }
    };

    Flows.prototype.hide = function () {
        if (this.modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.modal).hide();
        }
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    Flows.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-flow-new]')) {
                evt.preventDefault();
                self.openNew();
                return;
            }
            var btn = evt.target.closest('[data-adhoc-flow-action]');
            if (!btn) return;
            var tr = btn.closest('tr[data-id]');
            if (!tr) return;
            evt.preventDefault();

            var flow = self.find(tr.getAttribute('data-id'));
            if (!flow) return;

            var action = btn.getAttribute('data-adhoc-flow-action');
            if (action === 'edit') self.openEdit(flow);
            else if (action === 'delete') self.remove(flow);
        });

        if (this.modal) {
            this.modal.addEventListener('click', function (evt) {
                if (!evt.target.closest('[data-adhoc-flow-save]')) return;
                evt.preventDefault();
                self.save();
            });
            this.modal.addEventListener('keydown', function (evt) {
                if (evt.key !== 'Enter') return;
                if (!evt.target.matches('#adhoc-flow-name')) return;
                evt.preventDefault();
                self.save();
            });
        }
    };

    // ==================== API PÚBLICA ====================

    function init(scope) {
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-flows]'))
            ? node
            : node.querySelector('[data-adhoc-flows]');
        if (!root) return null;
        if (root.dataset.adhocFlowsBound === '1') return null;   // idempotente
        root.dataset.adhocFlowsBound = '1';

        return new Flows(root).init();
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocFlows = { init: init };
})();
