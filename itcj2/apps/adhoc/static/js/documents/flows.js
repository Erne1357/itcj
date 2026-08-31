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
 *
 * CONTRATO DE `page_data`
 * -----------------------
 *   {can_create, can_update, can_delete, document_counts: {"<id de flujo>": N}}
 *
 * `document_counts` lo cuenta el SERVIDOR (`pages/documents.py`) con el guard
 * PRINCIPAL de `delete_flow` (documentos con ese `flow_id`). Aquí no se deduce:
 * la lista de `GET /approval-flows` no sabe nada de documentos, así que sin
 * este mapa la papelera se pintaba viva en los 43 flujos y en 21 de ellos el
 * único camino era pulsar, confirmar y recibir un 409. Los otros dos motivos de
 * rechazo del servidor (un documento posicionado en un paso, una tarea colgando
 * de él) NO viajan en el mapa: hoy no le pasan a ningún flujo real y se siguen
 * resolviendo con el 409 que `remove()` recoge.
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

    /**
      * Icono de acción de fila. Aspecto del legacy `.icon-btn`: icono pelado del
      * color de la marca, sin recuadro, que crece al pasar el ratón. `icon` es
      * la clase COMPLETA de Font Awesome.
      */
    function iconButton(action, icon, label, variant) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'adhoc-icon-action' + (variant ? ' ' + variant : '');
        btn.setAttribute('data-adhoc-flow-action', action);
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.innerHTML = '<i class="' + icon + '"></i>';   // markup estático
        return btn;
    }

    // ==================== INSTANCIA ====================

    function Flows(root) {
        this.root = root;
        this.data = (U && typeof U.pageData === 'function') ? U.pageData() : {};

        this.canCreate = !!this.data.can_create;
        this.canUpdate = !!this.data.can_update;
        this.canDelete = !!this.data.can_delete;
        // {"<id de flujo>": nº de documentos que lo usan}. Ausente = {}, y un
        // flujo que no está en el mapa cuenta como cero: es el caso del que se
        // acaba de crear en esta misma pantalla, que documentos no tiene.
        this.documentCounts = this.data.document_counts || {};

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

        // El enlace "Configurar pasos" lo pinta este modulo, asi que HTMX no lo
        // ve hasta que se le da de alta: sin esto recargaria la pagina entera.
        U.enlazar(this.body);
    };

    Flows.prototype.buildRow = function (flow) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(flow.id));

        var nombre = flow.name || '';
        var tdName = document.createElement('td');
        tdName.setAttribute('data-adhoc-cell', 'name');
        // El filtro de la columna se queda con el NOMBRE y nada más. Sin este
        // override `cellText()` lee el textContent entero de la celda, así que
        // teclear "documento" en "Buscar flujo..." dejaría en pie las 21 filas
        // que llevan la línea de uso y ninguna se llama así.
        tdName.setAttribute('data-adhoc-value', nombre);
        tdName.className = 'adhoc-flow-name';

        var etiqueta = document.createElement('span');
        etiqueta.className = 'adhoc-flow-name-text';
        etiqueta.textContent = nombre;              // textContent, nunca innerHTML
        tdName.appendChild(etiqueta);
        tdName.appendChild(this.usageLine(flow));
        tr.appendChild(tdName);

        var tdDescription = document.createElement('td');
        tdDescription.setAttribute('data-adhoc-cell', 'description');
        tdDescription.className = 'adhoc-cell-clamp';
        // El clamp vive en el hijo: un <td> no puede ser -webkit-box.
        var descBox = document.createElement('div');
        descBox.className = 'adhoc-clamp-text';
        descBox.textContent = flow.description || '';
        if (flow.description) tdDescription.title = flow.description;
        tdDescription.appendChild(descBox);
        tr.appendChild(tdDescription);

        var tdSteps = document.createElement('td');
        tdSteps.setAttribute('data-adhoc-cell', 'steps');
        tdSteps.className = 'adhoc-col-center';
        // El legacy no tenía esta columna: se pinta como TEXTO, no como
        // pastilla, para no meter un color que el original no usa.
        var count = document.createElement('span');
        var total = parseInt(flow.step_count, 10) || 0;
        count.className = total ? 'adhoc-flow-steps-count' : 'adhoc-flow-steps-none';
        count.textContent = total ? (total + ' paso(s)') : 'Sin pasos';
        tdSteps.appendChild(count);
        tr.appendChild(tdSteps);

        var tdActions = document.createElement('td');
        tdActions.setAttribute('data-adhoc-cell', 'actions');
        tdActions.className = 'adhoc-col-center';
        tdActions.appendChild(this.buildActions(flow));
        tr.appendChild(tdActions);

        return tr;
    };

    /**
     * Cuántos documentos del SGC usan este flujo, según el servidor.
     *
     * El mapa llega por `page_data` y las claves son strings (así viaja un
     * objeto en JSON), de ahí el `String(flow.id)`. Lo que no está en el mapa
     * es un cero de verdad: el servidor emite una entrada por cada flujo que
     * tenga al menos un documento, así que la ausencia significa "ninguno", no
     * "no se sabe". Un valor raro (null, texto) también acaba en cero: el
     * defecto es dejar la papelera viva y que el servidor decida, nunca apagar
     * un botón por un dato que no se entendió.
     */
    Flows.prototype.usage = function (flow) {
        var total = parseInt(this.documentCounts[String(flow.id)], 10);
        return total > 0 ? total : 0;
    };

    /**
     * Línea bajo el nombre del flujo con su uso real.
     *
     * Va en la celda del nombre y no en una columna nueva porque es un dato
     * DEL flujo, como su descripción, y porque la cabecera de la tabla la
     * declara la plantilla: una columna más obligaría a tocarla.
     *
     * Los dos estados se pintan, también el vacío. El de al lado hace lo mismo
     * ("Sin pasos"), y una fila muda no se distingue de una fila cuyo dato no
     * llegó — que es justo lo que hay que poder distinguir cuando la papelera
     * de la fila está apagada por ese número.
     */
    Flows.prototype.usageLine = function (flow) {
        var total = this.usage(flow);
        var linea = document.createElement('span');
        linea.className = 'adhoc-flow-usage';
        if (!total) {
            linea.textContent = 'Sin documentos';
        } else {
            linea.textContent = total === 1
                ? 'En uso por 1 documento'
                : 'En uso por ' + total + ' documentos';
        }
        return linea;
    };

    /**
     * Papelera de la fila, deshabilitada cuando el flujo ya está en uso.
     *
     * `delete_flow` cuenta los documentos con este `flow_id` en CUALQUIER
     * estado, así que un flujo que se usó una vez hace diez años no se borra
     * nunca: son 21 de los 43 de hoy. Ofrecer la papelera en esas filas era
     * ofrecer un diálogo de confirmación que sólo lleva a un 409, y el guard
     * del servidor no se toca —el histórico documental del SGC no se borra en
     * cascada—, así que lo que se retira es la oferta.
     *
     * Deshabilitada de verdad (`disabled` + `aria-disabled`) y no sólo
     * apagada con CSS, y con el motivo en `title` y `aria-label` a la vez: un
     * botón `disabled` no recibe foco, así que el `title` no le llega nunca a
     * un lector de pantalla. Mismo patrón que "Editar documento"
     * (`documents-panel.js`) y que el aviso de atasco de `work/tasks.js`.
     *
     * El texto dice el número y qué hacer en su lugar. "No se puede eliminar"
     * a secas deja al usuario probando otra vez desde otro navegador.
     */
    Flows.prototype.deleteButton = function (flow) {
        var total = this.usage(flow);
        if (!total) {
            return iconButton('delete', 'fa-solid fa-trash', 'Eliminar flujo',
                              'adhoc-icon-danger');
        }

        var motivo = 'No se puede eliminar: ' +
                     (total === 1 ? '1 documento usa este flujo'
                                  : total + ' documentos usan este flujo') +
                     '. Edítalo (nombre, descripción y pasos) o deja de elegirlo ' +
                     'al arrancar flujos nuevos.';

        var btn = iconButton('delete', 'fa-solid fa-trash', motivo, 'adhoc-icon-muted');
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
        return btn;
    };

    Flows.prototype.buildActions = function (flow) {
        var box = document.createElement('div');
        box.className = 'adhoc-actions';

        // Enlace real: se puede abrir en otra pestaña. El legacy hacía
        // window.location.href dentro de un listener.
        // Lo pinta el JS, así que HTMX no lo ve hasta que el módulo llama a
        // `AdhocUtils.enlazar()` sobre el cuerpo de la tabla (ver render()).
        var steps = document.createElement('a');
        steps.className = 'adhoc-icon-action';
        steps.href = STEPS_URL + encodeURIComponent(flow.id) + '/pasos';
        steps.title = 'Configurar Pasos';
        steps.setAttribute('aria-label', 'Configurar Pasos');
        steps.innerHTML = '<i class="fa-solid fa-stamp"></i>';   // markup estático
        box.appendChild(steps);

        if (this.canUpdate) {
            box.appendChild(iconButton('edit', 'fa-solid fa-pen-to-square', 'Editar flujo'));
        }
        if (this.canDelete) {
            box.appendChild(this.deleteButton(flow));
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
        this.setTitle('Nuevo Flujo');
        if (this.inputName) this.inputName.value = '';
        if (this.inputDescription) this.inputDescription.value = '';
        this.show();
    };

    Flows.prototype.openEdit = function (flow) {
        this.editingId = flow.id;
        this.setTitle('Editar Flujo');
        if (this.inputName) this.inputName.value = flow.name || '';
        if (this.inputDescription) this.inputDescription.value = flow.description || '';
        this.show();
    };

    Flows.prototype.setTitle = function (textValue) {
        if (!this.modalTitle) return;
        this.modalTitle.innerHTML = '<i class="fa-solid fa-diagram-project me-2"></i>';  // estático
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

    /**
     * Sólo se llega aquí desde una papelera VIVA, o sea desde un flujo sin
     * documentos: el aviso de "no se puede si alguno lo usa" se cae del
     * diálogo porque ya lo dice el botón de las filas donde pasa, y un aviso
     * que sale siempre —también cuando no aplica— se deja de leer.
     *
     * El `catch` del 409 se queda: el servidor rechaza además si alguna tarea
     * cuelga de un paso de este flujo (`_assert_steps_unreferenced`), y eso no
     * viaja en `document_counts`.
     */
    Flows.prototype.remove = function (flow) {
        var self = this;
        U.confirmDialog({
            title: 'Eliminar flujo',
            message: '¿Eliminar "' + (flow.name || '') + '" y todos sus pasos? ' +
                     'Ningún documento lo está usando.',
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
            // "Filtrar" del legacy: reaplica el filtro de la tabla. No es
            // decorativo — es la misma pasada que dispara el input.
            if (evt.target.closest('[data-adhoc-flow-apply]')) {
                evt.preventDefault();
                if (window.AdhocTableFilter && self.table) {
                    window.AdhocTableFilter.apply(self.table);
                }
                return;
            }
            var btn = evt.target.closest('[data-adhoc-flow-action]');
            if (!btn) return;
            // La papelera se pinta en TODAS las filas, deshabilitada donde el
            // flujo ya está en uso. Un botón `disabled` no dispara `click` en
            // ningún navegador, pero la hoja de esta pantalla le devuelve los
            // eventos de ratón para que se pueda leer su `title` —el motivo—,
            // así que la guarda se escribe en vez de darse por supuesta (mismo
            // criterio que `documents-panel.js`).
            if (btn.disabled) return;
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
