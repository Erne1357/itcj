/**
 * documents/documents-panel.js — administración de /adhoc/documentos/panel.
 *
 * Expone SOLO `window.AdhocDocumentsPanel` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `advanced_documents.js` del legacy (305 líneas, clase global
 * `AdminDocumentosManager`). Sus problemas, todos arreglados aquí:
 *
 *   1. `getFormTemplate()` armaba el formulario con un template literal e
 *      interpolaba `this.config.categoriasHtml` — HTML CRUDO generado por Jinja
 *      dentro de backticks. Cuatro vectores de XSS, y un nombre de catálogo con
 *      un backtick o un `${` rompía la página entera. Aquí los catálogos son
 *      JSON y cada <option> se crea con createElement + textContent.
 *   2. `mostrarAlerta`/`mostrarConfirmacion` eran dos modales caseros abiertos
 *      con `style.display='flex'`. Ahora: AdhocUtils.showToast/confirmDialog.
 *   3. El filtrado iba por índice de columna (`configMap = [2,3,…,11]`).
 *      Ahora lo hace el servidor (document-list.js).
 *   4. Cinco botones abrían un alert de "módulo en construcción" y el bloque
 *      "Historial de Versiones" era un mockup con la fecha escrita a mano.
 *      No se portan (plan §4).
 *   5. Tras iniciar un flujo hacía `window.location.reload()` con un setTimeout
 *      de 1.5 s. Aquí se recarga solo la tabla.
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   POST   /documents                  multipart, listas paralelas por índice
 *   DELETE /documents/{id}
 *   GET    /documents/{id}             detalle (incluye current_step)
 *   POST   /documents/{id}/start-flow  {"flow_id": N}
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var List = window.AdhocDocumentList;
    var H = List ? List.helpers : null;

    var TABLE_ID = 'adhoc-doc-panel-table';

    //: Estatus desde los que se puede arrancar el flujo de aprobación.
    var STARTABLE = { 'Borrador': true, 'Rechazado': true };

    // ==================== CONSTRUCTORES DE CAMPO ====================

    function labelFor(id, textValue, required) {
        var label = document.createElement('label');
        label.className = 'form-label adhoc-label';
        label.setAttribute('for', id);
        label.textContent = textValue;
        if (required) {
            var star = document.createElement('span');
            star.className = 'adhoc-required';
            star.setAttribute('aria-hidden', 'true');
            star.textContent = '*';
            label.appendChild(star);
        }
        return label;
    }

    function fieldBox(id, labelText, control, opts) {
        var o = opts || {};
        var box = document.createElement('div');
        box.className = 'adhoc-field' + (o.full ? ' adhoc-field-full' : '');
        box.appendChild(labelFor(id, labelText, o.required));
        box.appendChild(control);
        if (o.help) {
            var help = document.createElement('div');
            help.className = 'form-text adhoc-field-help';
            help.textContent = o.help;
            box.appendChild(help);
        }
        return box;
    }

    function makeInput(id, name, type, value, opts) {
        var o = opts || {};
        var input = document.createElement('input');
        input.type = type;
        input.id = id;
        input.name = name;
        input.className = 'form-control';
        if (value !== undefined && value !== null) input.value = String(value);
        if (o.maxLength) input.maxLength = o.maxLength;
        if (o.required) input.required = true;
        if (o.accept) input.accept = o.accept;
        if (o.placeholder) input.placeholder = o.placeholder;
        return input;
    }

    function makeTextarea(id, name, value, rows) {
        var area = document.createElement('textarea');
        area.id = id;
        area.name = name;
        area.className = 'form-control';
        area.rows = rows || 2;
        area.value = value ? String(value) : '';    // .value, nunca innerHTML
        return area;
    }

    /**
     * <select> de catálogo construido desde JSON.
     * El legacy inyectaba aquí `${this.config.categoriasHtml}`: HTML del
     * servidor concatenado dentro de un template literal.
     */
    function makeCatalogSelect(id, name, items, selectedId, placeholder) {
        var select = document.createElement('select');
        select.id = id;
        select.name = name;
        select.className = 'form-select';

        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = placeholder || 'Seleccionar...';
        select.appendChild(blank);

        for (var i = 0; i < (items || []).length; i++) {
            var option = document.createElement('option');
            option.value = String(items[i].id);
            option.textContent = String(items[i].name);   // textContent
            if (selectedId !== null && selectedId !== undefined &&
                String(items[i].id) === String(selectedId)) {
                option.selected = true;
            }
            select.appendChild(option);
        }
        return select;
    }

    // ==================== INSTANCIA ====================

    function Panel(root) {
        this.root = root;
        this.data = (U && typeof U.pageData === 'function') ? U.pageData() : {};

        this.canCreate = !!this.data.can_create;
        this.canDelete = !!this.data.can_delete;
        this.canDownload = !!this.data.can_download;
        this.canStartFlow = !!this.data.can_start_flow;
        this.accept = (this.data.accept || []).join(',');

        this.modal = document.querySelector('[data-adhoc-doc-modal]');
        this.form = this.modal ? this.modal.querySelector('[data-adhoc-doc-form]') : null;
        this.fields = this.modal ? this.modal.querySelector('[data-adhoc-doc-fields]') : null;
        this.qtyBox = this.modal ? this.modal.querySelector('[data-adhoc-doc-qty-box]') : null;
        this.qtySelect = this.modal ? this.modal.querySelector('[data-adhoc-doc-qty]') : null;
        this.modalTitle = this.modal ? this.modal.querySelector('[data-adhoc-doc-modal-title]') : null;

        this.flowModal = document.querySelector('[data-adhoc-flow-modal]');
        this.flowSelect = this.flowModal ? this.flowModal.querySelector('[data-adhoc-flow-select]') : null;
        this.flowDoc = this.flowModal ? this.flowModal.querySelector('[data-adhoc-flow-doc]') : null;
        this.flowDocId = null;

        this.list = null;
    }

    Panel.prototype.init = function () {
        var self = this;
        this.list = List.create(this.root, {
            tableId: TABLE_ID,
            perPage: this.data.per_page,
            buildRow: function (doc) { return self.buildRow(doc); }
        });
        this.bind();
        return this;
    };

    // ---------- fila ----------

    Panel.prototype.buildRow = function (doc) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(doc.id));

        var tdFile = document.createElement('td');
        tdFile.setAttribute('data-adhoc-cell', 'file');
        tdFile.className = 'adhoc-col-center';
        // Legacy: icono de PDF en rojo, sin pastilla (`.icon-btn-blue`).
        tdFile.appendChild(H.fileCell(doc, this.canDownload, {
            icon: 'fa-solid fa-file-pdf',
            linkClass: 'adhoc-icon-action adhoc-icon-danger'
        }));
        tr.appendChild(tdFile);

        H.cell(tr, 'code', H.text(doc.code, '—'), 'adhoc-cell-nowrap');
        H.cell(tr, 'title', H.text(doc.title));

        // — versión + estatus en una sola celda, como el legacy —
        var tdVersion = document.createElement('td');
        tdVersion.setAttribute('data-adhoc-cell', 'version');
        tdVersion.className = 'adhoc-cell-nowrap';
        var version = document.createElement('span');
        version.className = 'adhoc-doc-version';
        version.textContent = 'v' + H.text(doc.version);
        tdVersion.appendChild(version);
        tdVersion.appendChild(H.statusBadge(doc.status));
        tr.appendChild(tdVersion);

        H.cell(tr, 'category', H.named(doc.category));
        H.cell(tr, 'area', H.named(doc.area));
        H.cell(tr, 'process', H.named(doc.process));
        H.cell(tr, 'classification', H.named(doc.classification));
        H.cell(tr, 'notes', H.text(doc.notes), 'adhoc-cell-clamp');
        H.cell(tr, 'approval_date', H.isoDate(doc.approval_date) || 'Pendiente',
               'adhoc-cell-nowrap');

        var tdActions = document.createElement('td');
        tdActions.setAttribute('data-adhoc-cell', 'actions');
        tdActions.className = 'adhoc-col-end';
        tdActions.appendChild(this.buildActions(doc));
        tr.appendChild(tdActions);

        return tr;
    };

    Panel.prototype.buildActions = function (doc) {
        var box = document.createElement('div');
        box.className = 'adhoc-actions';

        if (this.canStartFlow && STARTABLE[doc.status]) {
            box.appendChild(H.iconButton('start-flow', 'fa-solid fa-stamp',
                                         'Sellar e iniciar el flujo de aprobación'));
        }
        if (doc.status === 'En Revisión') {
            box.appendChild(H.iconButton('flow-info', 'fa-solid fa-clock-rotate-left',
                                         'Ver paso actual del flujo', 'adhoc-icon-info'));
        }
        if (this.canCreate) {
            box.appendChild(H.iconButton('new-version', 'fa-solid fa-file-circle-plus',
                                         'Anexar nueva versión'));
        }
        if (this.canDelete) {
            box.appendChild(H.iconButton('delete', 'fa-solid fa-trash',
                                         'Eliminar documento', 'adhoc-icon-danger'));
        }
        return box;
    };

    // ---------- alta masiva ----------

    Panel.prototype.openNew = function () {
        if (!this.modal) return;
        if (this.modalTitle) {
            this.modalTitle.innerHTML = '<i class="fa-solid fa-file-circle-plus me-2"></i>';
            this.modalTitle.appendChild(document.createTextNode('Añadir Documento'));
        }
        if (this.qtyBox) this.qtyBox.hidden = false;
        this.buildFields();
        this.show(this.modal);
    };

    /**
     * Nueva versión de un documento existente. Comportamiento del legacy que se
     * conserva: se crea un documento NUEVO con el mismo código y título y la
     * versión incrementada en 1.0 (`advanced_documents.js:184`), no se edita el
     * original — así el histórico del SGC no se pierde.
     */
    Panel.prototype.openNewVersion = function (doc) {
        if (!this.modal) return;
        if (this.modalTitle) {
            this.modalTitle.innerHTML = '<i class="fa-solid fa-copy me-2"></i>';
            this.modalTitle.appendChild(document.createTextNode('Registrar nueva versión'));
        }
        if (this.qtyBox) this.qtyBox.hidden = true;

        var current = parseFloat(doc.version);
        var next = isNaN(current) ? '1.0' : (current + 1.0).toFixed(1);

        this.buildFields(1, {
            code: doc.code,
            title: doc.title,
            version: next,
            notes: doc.notes,
            category_id: doc.category ? doc.category.id : null,
            area_id: doc.area ? doc.area.id : null,
            process_id: doc.process ? doc.process.id : null,
            classification_id: doc.classification ? doc.classification.id : null
        });
        this.show(this.modal);
    };

    Panel.prototype.buildFields = function (count, prefill) {
        if (!this.fields) return;
        var qty = count;
        if (!qty) qty = this.qtySelect ? (parseInt(this.qtySelect.value, 10) || 1) : 1;

        this.fields.textContent = '';
        for (var i = 1; i <= qty; i++) {
            this.fields.appendChild(this.buildBlock(i, qty, prefill));
        }
        var first = this.fields.querySelector('input, select, textarea');
        if (first) first.focus();
    };

    Panel.prototype.buildBlock = function (index, total, prefill) {
        var p = prefill || {};
        var suffix = '-' + index;
        var block = document.createElement('div');
        block.className = 'adhoc-fieldset';

        if (total > 1) {
            var title = document.createElement('p');
            title.className = 'adhoc-fieldset-title';
            title.textContent = 'Registro #' + index;
            block.appendChild(title);
        }

        var grid = document.createElement('div');
        grid.className = 'adhoc-form-grid';

        grid.appendChild(fieldBox(
            'adhoc-doc-title' + suffix, 'Nombre del documento',
            makeInput('adhoc-doc-title' + suffix, 'titles', 'text', p.title || '',
                      { maxLength: 200, required: true }),
            { full: true, required: true }));

        grid.appendChild(fieldBox(
            'adhoc-doc-code' + suffix, 'Código',
            makeInput('adhoc-doc-code' + suffix, 'codes', 'text', p.code || '',
                      { maxLength: 50 })));

        grid.appendChild(fieldBox(
            'adhoc-doc-version' + suffix, 'Versión',
            makeInput('adhoc-doc-version' + suffix, 'versions', 'text', p.version || '1.0',
                      { maxLength: 10 })));

        grid.appendChild(fieldBox(
            'adhoc-doc-category' + suffix, 'Categoría',
            makeCatalogSelect('adhoc-doc-category' + suffix, 'category_ids',
                              this.data.categories, p.category_id)));

        grid.appendChild(fieldBox(
            'adhoc-doc-area' + suffix, 'Área',
            makeCatalogSelect('adhoc-doc-area' + suffix, 'area_ids',
                              this.data.areas, p.area_id)));

        grid.appendChild(fieldBox(
            'adhoc-doc-process' + suffix, 'Proceso',
            makeCatalogSelect('adhoc-doc-process' + suffix, 'process_ids',
                              this.data.processes, p.process_id)));

        grid.appendChild(fieldBox(
            'adhoc-doc-classification' + suffix, 'Clasificación',
            makeCatalogSelect('adhoc-doc-classification' + suffix, 'classification_ids',
                              this.data.classifications, p.classification_id)));

        grid.appendChild(fieldBox(
            'adhoc-doc-notes' + suffix, 'Notas',
            makeTextarea('adhoc-doc-notes' + suffix, 'notes', p.notes, 2),
            { full: true }));

        grid.appendChild(fieldBox(
            'adhoc-doc-file' + suffix, 'Archivo',
            makeInput('adhoc-doc-file' + suffix, 'files', 'file', null,
                      { accept: this.accept }),
            { full: true, help: 'Opcional. Un archivo por documento.' }));

        block.appendChild(grid);
        return block;
    };

    Panel.prototype.submitNew = function () {
        var self = this;
        var btn = this.modal.querySelector('[data-adhoc-doc-save]');
        var titles = this.form.querySelectorAll('[name="titles"]');
        var some = false;

        for (var i = 0; i < titles.length; i++) {
            if (titles[i].value.trim()) { some = true; break; }
        }
        if (!some) {
            U.showToast('Captura al menos el nombre de un documento.', 'warning');
            return;
        }

        this.busy(btn, true);
        // FormData del <form>: conserva el orden del DOM, así que las listas
        // paralelas (titles/codes/…/files) llegan alineadas por índice.
        U.fetchJson('/documents', { method: 'POST', body: new FormData(this.form) })
            .then(function (payload) {
                var total = (payload && payload.total) || 0;
                U.showToast(total + ' documento(s) registrado(s).', 'success');
                self.hide(self.modal);
                return self.list.reload();
            })
            .catch(function (err) {
                U.showToast(err.message, 'error');
            })
            .then(function () {
                self.busy(btn, false);
            });
    };

    // ---------- flujo de aprobación ----------

    Panel.prototype.openFlow = function (doc) {
        if (!this.flowModal) return;
        var flows = this.data.flows || [];
        if (!flows.length) {
            U.showToast('No hay flujos de aprobación configurados.', 'warning');
            return;
        }

        this.flowDocId = doc.id;
        if (this.flowDoc) {
            this.flowDoc.textContent =
                H.text(doc.code, 'Sin código') + ' · ' + H.text(doc.title) +
                ' (v' + H.text(doc.version) + ')';
        }
        if (this.flowSelect) {
            this.flowSelect.textContent = '';
            var blank = document.createElement('option');
            blank.value = '';
            blank.textContent = 'Selecciona el flujo...';
            this.flowSelect.appendChild(blank);
            for (var i = 0; i < flows.length; i++) {
                var option = document.createElement('option');
                option.value = String(flows[i].id);
                option.textContent = String(flows[i].name);   // textContent
                this.flowSelect.appendChild(option);
            }
        }
        this.show(this.flowModal);
    };

    Panel.prototype.startFlow = function () {
        var self = this;
        var btn = this.flowModal.querySelector('[data-adhoc-flow-start]');
        var flowId = this.flowSelect ? this.flowSelect.value : '';

        if (!flowId) {
            U.showToast('Selecciona un flujo de la lista para iniciar.', 'warning');
            return;
        }

        this.busy(btn, true);
        U.fetchJson('/documents/' + encodeURIComponent(this.flowDocId) + '/start-flow', {
            method: 'POST',
            body: JSON.stringify({ flow_id: parseInt(flowId, 10) })
        }).then(function (payload) {
            var data = (payload && payload.data) || {};
            U.showToast(data.message || 'Flujo de aprobación iniciado.', 'success');
            self.hide(self.flowModal);
            return self.list.reload();
        }).catch(function (err) {
            U.showToast(err.message, 'error');
        }).then(function () {
            self.busy(btn, false);
        });
    };

    /** Paso actual de un documento en revisión (el legacy mostraba un alert fijo). */
    Panel.prototype.showFlowInfo = function (doc) {
        U.fetchJson('/documents/' + encodeURIComponent(doc.id))
            .then(function (payload) {
                var detail = (payload && payload.data) || {};
                var step = detail.current_step;
                U.showToast(
                    step
                        ? 'En revisión. Paso actual: ' + step.name +
                          ' (' + step.days_limit + ' día(s) de límite).'
                        : 'El documento está en revisión.',
                    'info'
                );
            })
            .catch(function (err) { U.showToast(err.message, 'error'); });
    };

    // ---------- borrado ----------

    Panel.prototype.remove = function (doc) {
        var self = this;
        U.confirmDialog({
            title: 'Eliminar documento',
            message: '¿Eliminar "' + H.text(doc.title) + '"? Se borran también sus tareas ' +
                     'y su archivo adjunto. Esta acción no se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson('/documents/' + encodeURIComponent(doc.id), { method: 'DELETE' })
                .then(function (payload) {
                    U.showToast((payload && payload.message) || 'Documento eliminado.', 'success');
                    return self.list.reload();
                })
                .catch(function (err) { U.showToast(err.message, 'error'); });
        });
    };

    // ---------- utilidades de modal ----------

    Panel.prototype.show = function (modal) {
        if (modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modal).show();
        }
    };

    Panel.prototype.hide = function (modal) {
        if (modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        }
    };

    Panel.prototype.busy = function (btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    Panel.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-doc-new]')) {
                evt.preventDefault();
                self.openNew();
                return;
            }
            var btn = evt.target.closest('[data-adhoc-doc-action]');
            if (!btn) return;
            var tr = btn.closest('tr[data-id]');
            if (!tr) return;
            evt.preventDefault();

            var doc = self.list.find(tr.getAttribute('data-id'));
            if (!doc) return;

            var action = btn.getAttribute('data-adhoc-doc-action');
            if (action === 'start-flow') self.openFlow(doc);
            else if (action === 'flow-info') self.showFlowInfo(doc);
            else if (action === 'new-version') self.openNewVersion(doc);
            else if (action === 'delete') self.remove(doc);
        });

        if (this.modal) {
            this.modal.addEventListener('change', function (evt) {
                if (evt.target.closest('[data-adhoc-doc-qty]')) self.buildFields();
            });
            this.modal.addEventListener('click', function (evt) {
                if (!evt.target.closest('[data-adhoc-doc-save]')) return;
                evt.preventDefault();
                self.submitNew();
            });
        }

        if (this.flowModal) {
            this.flowModal.addEventListener('click', function (evt) {
                if (!evt.target.closest('[data-adhoc-flow-start]')) return;
                evt.preventDefault();
                self.startFlow();
            });
        }
    };

    // ==================== API PÚBLICA ====================

    function init(scope) {
        if (!List) {
            console.error('[adhoc] documents-panel: falta document-list.js');
            return null;
        }
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-doc-panel]'))
            ? node
            : node.querySelector('[data-adhoc-doc-panel]');
        if (!root) return null;
        if (root.dataset.adhocDocPanelBound === '1') return null;   // idempotente
        root.dataset.adhocDocPanelBound = '1';

        return new Panel(root).init();
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocDocumentsPanel = { init: init };
})();
