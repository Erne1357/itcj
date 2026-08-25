/**
 * indicators/board.js — tablero (fichas de indicador) de un año.
 *
 * Página: /adhoc/indicadores/{year_id}/tablero
 * Expone SOLO `window.AdhocIndicatorBoard` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `app_prueba/js/indicators/indicators_board.js` (clase `IndicatorsBoardManager`
 * suelta en el scope global). Sus problemas, uno por uno:
 *
 *   1. `getTemplate()` interpolaba DIECISÉIS campos del servidor dentro de un
 *      template literal sin escapar (`${d.objetivo}`, `${d.crit}`, `${d.planb}`…):
 *      un apóstrofo rompía el formulario y una etiqueta lo convertía en XSS.
 *      Aquí todo pasa por `AdhocUtils.escapeHtml()`.
 *   2. `${this.config.htmlProcesos}` era HTML crudo generado en Jinja. Aquí los
 *      procesos vienen como JSON en `page_data` y el <select> se construye aquí.
 *   3. Los cuatro umbrales salían de `d.planned.split('-')`, así que cualquier
 *      meta con guion ("1-2 días", "-5%") corrompía las cuatro celdas. Aquí son
 *      cuatro campos independientes, como las cuatro columnas de la tabla.
 *   4. El <select> de frecuencia NO ofrecía 'Semanal', aunque el render de
 *      seguimiento sí la reconocía (52 periodos): era un valor inalcanzable.
 *      Las tres frecuencias vienen de `page_data.frequencies`.
 *   5. Guardaba con `form.action = …` + submit clásico (navegación completa y
 *      `redirect(request.referrer)` del lado servidor). Aquí es fetch multipart.
 *   6. El botón "Eliminar" era un `formaction` en un <button type="submit">, sin
 *      confirmación de ningún tipo. Aquí: `AdhocUtils.confirmDialog()`.
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   GET    /indicators?year_id=N   → {success, data: [IndicatorOut], total}
 *   POST   /indicators             → multipart: year_id, payload(JSON), files[], file_indexes[]
 *   PATCH  /indicators/{id}        → multipart: payload(JSON parcial), file
 *   DELETE /indicators/{id}        → {success, message}
 *   GET    /indicators/{id}/download
 *   error                          → {"error": "texto", "status": N}
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var TABLE_ID = 'adhoc-indicator-board';

    //: Clase de estado (adhoc.css) de cada umbral, en el orden de la ficha.
    var THRESHOLDS = [
        { key: 'planned_white',  tag: 'Estándar',   tone: 'white',  cls: 'adhoc-state-white',  ph: 'Base' },
        { key: 'planned_red',    tag: 'Rechazado',  tone: 'red',    cls: 'adhoc-state-red',    ph: '< 70%' },
        { key: 'planned_yellow', tag: 'Preventivo', tone: 'yellow', cls: 'adhoc-state-yellow', ph: '70% - 85%' },
        { key: 'planned_green',  tag: 'Aprobado',   tone: 'green',  cls: 'adhoc-state-green',  ph: '> 85%' }
    ];

    //: Campos de texto del formulario, en orden de captura.
    var FIELDS = [
        { key: 'responsible',   label: 'Responsable principal', type: 'text',     required: true,  ph: 'Nombre del responsable...' },
        { key: 'objective',     label: 'Objetivo / indicador asociado', type: 'text', required: true, full: true, ph: 'Ej. Reducir el tiempo de atención...' },
        { key: 'prev_results',  label: 'Resultados del año anterior', type: 'text', ph: 'Ej. 85% de eficiencia' },
        { key: 'unit_calc',     label: 'Unidad de medida y cálculo', type: 'text', ph: 'Ej. (Resueltos / Totales) * 100' },
        { key: 'facilitator',   label: 'Facilitador de información', type: 'text', ph: '¿Quién provee los datos?' },
        { key: 'source',        label: 'Registro de datos (fuente)', type: 'text', ph: 'Ej. Sistema ERP, Excel...' },
        { key: 'strategic_rel', label: 'Relación con objetivos estratégicos', type: 'textarea', full: true, ph: '¿Cómo impacta a la organización?' },
        { key: 'criteria',      label: 'Criterios de cumplimiento', type: 'textarea', ph: 'Detalle los criterios de evaluación...' },
        { key: 'plan_b',        label: 'Plan B (acciones correctivas)', type: 'textarea', ph: '¿Qué hacer si el indicador es rojo?' }
    ];

    //: Claves que viajan en el payload JSON, en el orden de IndicatorCreate.
    var PAYLOAD_KEYS = ['process_id', 'frequency']
        .concat(THRESHOLDS.map(function (t) { return t.key; }))
        .concat(FIELDS.map(function (f) { return f.key; }));

    // ==================== HELPERS ====================

    var esc = function (value) { return U.escapeHtml(value); };

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    function toast(message, type) {
        if (U && U.showToast) U.showToast(message, type);
    }

    function truncate(text, max) {
        var value = text === null || text === undefined ? '' : String(text);
        return value.length > max ? value.slice(0, max) + '…' : value;
    }

    // ==================== MÓDULO ====================

    function Board(root) {
        this.root = root;
        this.data = U.pageData();
        this.year = this.data.year || {};
        this.items = this.data.indicators || [];
        this.processes = this.data.processes || [];
        this.frequencies = this.data.frequencies || [];
        this.api = (this.data.api && this.data.api.indicators) || '/api/adhoc/v2/indicators';

        this.canCreate = !!this.data.can_create;
        this.canUpdate = !!this.data.can_update;
        this.canDelete = !!this.data.can_delete;
        this.canDownload = !!this.data.can_download;

        this.table = document.getElementById(TABLE_ID);
        this.body = document.getElementById(TABLE_ID + '-body');
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;

        this.modalEl = document.getElementById('adhoc-board-modal');
        this.modal = (this.modalEl && window.bootstrap)
            ? window.bootstrap.Modal.getOrCreateInstance(this.modalEl)
            : null;
        this.forms = this.modalEl ? this.modalEl.querySelector('[data-adhoc-board-forms]') : null;
        // El <select> de cantidad esta en los controles inferiores de la pagina,
        // como en el legacy: se elige ANTES de abrir el modal.
        this.qty = document.querySelector('[data-adhoc-board-qty]');
        this.qtyWrap = document.querySelector('[data-adhoc-board-qty-wrap]');
        this.label = this.modalEl ? this.modalEl.querySelector('[data-adhoc-board-modal-label]') : null;
        this.deleteBtn = this.modalEl ? this.modalEl.querySelector('[data-adhoc-board-delete]') : null;

        this.editingId = null;
    }

    Board.prototype.init = function () {
        this.render();
        this.bind();
    };

    // ---------- render de la tabla ----------

    Board.prototype.render = function () {
        if (!this.body) return;

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

    Board.prototype.buildRow = function (item) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(item.id));
        if (this.canUpdate) tr.classList.add('adhoc-row-click');

        // — Proceso: muestra de color + nombre. El color va por .style desde JS
        //   porque en las plantillas está prohibido style="…"; aquí es un valor
        //   controlado (columna String(7) validada por el schema).
        var tdProcess = document.createElement('td');
        tdProcess.setAttribute('data-adhoc-cell', 'process');
        tdProcess.setAttribute('data-adhoc-value', item.process_name || '');
        var wrap = document.createElement('span');
        wrap.className = 'adhoc-board-process';
        var dot = document.createElement('span');
        dot.className = 'adhoc-swatch adhoc-board-dot';
        dot.style.backgroundColor = item.process_color || '#b2bec3';
        wrap.appendChild(dot);
        var name = document.createElement('span');
        name.textContent = item.process_name || 'Sin proceso';
        wrap.appendChild(name);
        tdProcess.appendChild(wrap);
        tr.appendChild(tdProcess);

        tr.appendChild(this.responsibleCell(item.responsible || '—'));

        // — Frecuencia
        var tdFreq = document.createElement('td');
        tdFreq.setAttribute('data-adhoc-cell', 'frequency');
        tdFreq.setAttribute('data-adhoc-value', item.frequency || '');
        var badge = document.createElement('span');
        badge.className = 'adhoc-board-freq' + (item.frequency ? '' : ' adhoc-board-freq-none');
        badge.textContent = item.frequency || 'Sin definir';
        tdFreq.appendChild(badge);
        tr.appendChild(tdFreq);

        // — Objetivo (recortado en pantalla, completo en el title y en el filtro)
        var tdObj = document.createElement('td');
        tdObj.setAttribute('data-adhoc-cell', 'objective');
        tdObj.setAttribute('data-adhoc-value', item.objective || '');
        tdObj.className = 'adhoc-board-objective';
        tdObj.title = item.objective || '';
        tdObj.textContent = truncate(item.objective || '—', 70);
        tr.appendChild(tdObj);

        // — Los cuatro umbrales, cada uno con su color de estado.
        var tdPlanned = document.createElement('td');
        tdPlanned.setAttribute('data-adhoc-cell', 'planned');
        var chips = document.createElement('span');
        chips.className = 'adhoc-board-planned';
        for (var i = 0; i < THRESHOLDS.length; i++) {
            var chip = document.createElement('span');
            chip.className = 'adhoc-board-planned-chip ' + THRESHOLDS[i].cls;
            chip.title = THRESHOLDS[i].tag;
            chip.textContent = item[THRESHOLDS[i].key] || '—';
            chips.appendChild(chip);
        }
        tdPlanned.appendChild(chips);
        tr.appendChild(tdPlanned);

        // — Evidencia (endpoint NUEVO: el legacy no permitía recuperarla)
        var tdDoc = document.createElement('td');
        tdDoc.setAttribute('data-adhoc-cell', 'evidence');
        tdDoc.className = 'adhoc-col-center';
        tdDoc.appendChild(this.evidenceNode(item));
        tr.appendChild(tdDoc);

        // — Acciones
        var tdActions = document.createElement('td');
        tdActions.className = 'adhoc-col-center';
        var box = document.createElement('div');
        box.className = 'adhoc-actions adhoc-board-actions';
        var html = '';
        if (this.canUpdate) {
            html += '<button type="button" class="adhoc-board-icon adhoc-board-icon-edit" ' +
                    'data-adhoc-action="edit" title="Editar" aria-label="Editar">' +
                    '<i class="fa-solid fa-pen-to-square"></i></button>';
        }
        if (this.canDelete) {
            html += '<button type="button" class="adhoc-board-icon adhoc-board-icon-delete" ' +
                    'data-adhoc-action="delete" title="Eliminar" aria-label="Eliminar">' +
                    '<i class="fa-solid fa-trash"></i></button>';
        }
        box.innerHTML = html;   // markup estático, sin datos del servidor
        tdActions.appendChild(box);
        tr.appendChild(tdActions);

        return tr;
    };

    Board.prototype.responsibleCell = function (value) {
        var td = document.createElement('td');
        td.setAttribute('data-adhoc-cell', 'responsible');
        td.setAttribute('data-adhoc-value', value);
        var icon = document.createElement('i');
        icon.className = 'fa-solid fa-user-tie adhoc-board-resp-icon';
        td.appendChild(icon);
        td.appendChild(document.createTextNode(' ' + value));
        return td;
    };

    Board.prototype.textCell = function (key, value) {
        var td = document.createElement('td');
        td.setAttribute('data-adhoc-cell', key);
        td.textContent = value;
        return td;
    };

    Board.prototype.downloadUrl = function (id) {
        return this.api + '/' + encodeURIComponent(id) + '/download';
    };

    Board.prototype.evidenceNode = function (item) {
        if (!item.has_document) {
            var none = document.createElement('span');
            none.className = 'adhoc-board-evidence-none';
            none.textContent = '—';
            return none;
        }
        if (!this.canDownload) {
            var lock = document.createElement('i');
            lock.className = 'fa-solid fa-paperclip';
            lock.title = 'Hay evidencia, pero no tienes permiso de descarga';
            return lock;
        }
        var link = document.createElement('a');
        link.className = 'adhoc-board-evidence-link';
        link.href = this.downloadUrl(item.id);
        link.title = 'Descargar evidencia';
        link.setAttribute('data-adhoc-action', 'download');
        link.innerHTML = '<i class="fa-solid fa-paperclip"></i>';   // markup estático
        return link;
    };

    // ---------- formulario ----------

    Board.prototype.processOptions = function (selected) {
        var html = '<option value="">-- Elija un proceso --</option>';
        for (var i = 0; i < this.processes.length; i++) {
            var p = this.processes[i];
            var sel = (String(p.id) === String(selected)) ? ' selected' : '';
            html += '<option value="' + esc(p.id) + '"' + sel + '>' + esc(p.name) + '</option>';
        }
        return html;
    };

    Board.prototype.frequencyOptions = function (selected) {
        var html = '<option value="">-- Seleccione frecuencia --</option>';
        for (var i = 0; i < this.frequencies.length; i++) {
            var f = this.frequencies[i];
            var sel = (String(f) === String(selected)) ? ' selected' : '';
            html += '<option value="' + esc(f) + '"' + sel + '>' + esc(f) + '</option>';
        }
        return html;
    };

    Board.prototype.buildForm = function (index, item) {
        var d = item || {};
        var uid = 'adhoc-board-' + index;
        var html =
            '<section class="adhoc-board-form" data-adhoc-board-form="' + index + '"' +
                (d.id ? ' data-id="' + esc(d.id) + '"' : '') + '>' +
              '<h6 class="adhoc-board-form-title">' +
                '<i class="fa-solid fa-chart-pie"></i> Ficha de indicador #' + (index + 1) +
              '</h6>' +
              '<div class="adhoc-form-grid">' +
                '<div class="adhoc-field">' +
                  '<label class="form-label adhoc-label" for="' + uid + '-process">' +
                    'Proceso<span class="adhoc-required" aria-hidden="true">*</span></label>' +
                  '<select class="form-select" id="' + uid + '-process" data-adhoc-field="process_id" required>' +
                    this.processOptions(d.process_id) +
                  '</select>' +
                '</div>' +
                '';

        // El <select> de frecuencia va donde lo ponia el legacy: en la misma
        // fila que "Resultados del anio anterior", no pegado al de proceso (si
        // no, "Responsable principal" se queda solo en su fila con un hueco).
        var freqField =
            '<div class="adhoc-field">' +
              '<label class="form-label adhoc-label" for="' + uid + '-frequency">' +
                'Frecuencia de seguimiento</label>' +
              '<select class="form-select" id="' + uid + '-frequency" data-adhoc-field="frequency">' +
                this.frequencyOptions(d.frequency) +
              '</select>' +
            '</div>';

        for (var i = 0; i < FIELDS.length; i++) {
            html += this.buildField(uid, FIELDS[i], d);
            if (FIELDS[i].key === 'prev_results') html += freqField;
        }

        html +=
                '<div class="adhoc-field adhoc-field-full">' +
                  '<span class="form-label adhoc-label d-block">' +
                    'Valor planificado del periodo (métricas de aceptación)</span>' +
                  '<div class="adhoc-board-thresholds">' + this.buildThresholds(uid, d) + '</div>' +
                '</div>' +
                '<div class="adhoc-field adhoc-field-full">' +
                  '<label class="form-label adhoc-label" for="' + uid + '-file">' +
                    '<i class="fa-solid fa-paperclip"></i> Documento estándar (evidencia)</label>' +
                  '<input type="file" class="form-control" id="' + uid + '-file" data-adhoc-file>' +
                  '<div class="adhoc-board-evidence">' + this.currentEvidence(d) + '</div>' +
                '</div>' +
              '</div>' +
            '</section>';
        return html;
    };

    Board.prototype.buildField = function (uid, field, d) {
        var id = uid + '-' + field.key;
        var value = d[field.key] === null || d[field.key] === undefined ? '' : d[field.key];
        var req = field.required ? ' required' : '';
        var star = field.required
            ? '<span class="adhoc-required" aria-hidden="true">*</span>' : '';
        var control = (field.type === 'textarea')
            ? '<textarea class="form-control" id="' + id + '" rows="3" ' +
              'data-adhoc-field="' + esc(field.key) + '" placeholder="' + esc(field.ph || '') + '"' + req + '>' +
              esc(value) + '</textarea>'
            : '<input type="text" class="form-control" id="' + id + '" ' +
              'data-adhoc-field="' + esc(field.key) + '" value="' + esc(value) + '" ' +
              'placeholder="' + esc(field.ph || '') + '"' + req + '>';

        return '<div class="adhoc-field' + (field.full ? ' adhoc-field-full' : '') + '">' +
                 '<label class="form-label adhoc-label" for="' + id + '">' +
                   esc(field.label) + star + '</label>' +
                 control +
               '</div>';
    };

    Board.prototype.buildThresholds = function (uid, d) {
        var html = '';
        for (var i = 0; i < THRESHOLDS.length; i++) {
            var t = THRESHOLDS[i];
            var id = uid + '-' + t.key;
            var value = d[t.key] === null || d[t.key] === undefined ? '' : d[t.key];
            html +=
                '<div>' +
                  '<label class="adhoc-board-threshold-tag adhoc-board-threshold-tag-' + t.tone + '" ' +
                    'for="' + id + '">' + esc(t.tag) + '</label>' +
                  '<input type="text" class="adhoc-board-threshold-input ' + t.cls + '" id="' + id + '" ' +
                    'data-adhoc-field="' + esc(t.key) + '" value="' + esc(value) + '" ' +
                    'maxlength="50" placeholder="' + esc(t.ph) + '">' +
                '</div>';
        }
        return html;
    };

    Board.prototype.currentEvidence = function (d) {
        if (!d.has_document) {
            return '<span class="adhoc-board-evidence-none">Sin evidencia cargada.</span>';
        }
        if (!this.canDownload) {
            return '<span class="adhoc-board-evidence-none">Hay evidencia cargada.</span>';
        }
        return '<a class="adhoc-board-evidence-link" href="' + esc(this.downloadUrl(d.id)) + '">' +
               '<i class="fa-solid fa-download"></i> Descargar la actual</a>' +
               '<span class="adhoc-board-evidence-none">Subir un archivo reemplaza la anterior.</span>';
    };

    // ---------- lectura del formulario ----------

    Board.prototype.readForm = function (section) {
        var row = {};
        var controls = section.querySelectorAll('[data-adhoc-field]');
        for (var i = 0; i < controls.length; i++) {
            row[controls[i].getAttribute('data-adhoc-field')] = controls[i].value;
        }
        var payload = {};
        for (var k = 0; k < PAYLOAD_KEYS.length; k++) {
            var key = PAYLOAD_KEYS[k];
            payload[key] = row[key] === undefined ? '' : row[key];
        }
        var file = section.querySelector('[data-adhoc-file]');
        return {
            payload: payload,
            file: (file && file.files && file.files.length) ? file.files[0] : null,
            section: section
        };
    };

    Board.prototype.validate = function (form) {
        if (!form.payload.process_id) {
            toast('Elige el proceso de cada ficha.', 'warning');
            var select = form.section.querySelector('[data-adhoc-field="process_id"]');
            if (select) select.focus();
            return false;
        }
        if (!String(form.payload.objective || '').trim()) {
            toast('El objetivo es obligatorio.', 'warning');
            return false;
        }
        return true;
    };

    // ---------- alta / edición ----------

    Board.prototype.openNew = function () {
        if (!this.modal || !this.forms) return;
        this.editingId = null;
        if (this.label) this.label.textContent = 'Alta de Nuevos Procesos';
        if (this.qtyWrap) this.qtyWrap.hidden = false;
        if (this.deleteBtn) this.deleteBtn.hidden = true;
        this.buildForms();
        this.modal.show();
    };

    Board.prototype.buildForms = function () {
        if (!this.forms) return;
        var count = parseInt(this.qty ? this.qty.value : '1', 10) || 1;
        var html = '';
        for (var i = 0; i < count; i++) html += this.buildForm(i, null);
        this.forms.innerHTML = html;
    };

    Board.prototype.openEdit = function (id) {
        if (!this.modal || !this.forms) return;
        var item = this.find(id);
        if (!item) return;
        this.editingId = item.id;
        if (this.label) this.label.textContent = 'Editar Proceso Existente';
        if (this.qtyWrap) this.qtyWrap.hidden = true;
        if (this.deleteBtn) this.deleteBtn.hidden = !this.canDelete;
        this.forms.innerHTML = this.buildForm(0, item);
        this.modal.show();
    };

    Board.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    Board.prototype.save = function (btn) {
        var sections = this.forms
            ? this.forms.querySelectorAll('[data-adhoc-board-form]') : [];
        if (!sections.length) return;

        var forms = [];
        for (var i = 0; i < sections.length; i++) {
            var form = this.readForm(sections[i]);
            if (!this.validate(form)) return;
            forms.push(form);
        }

        if (this.editingId !== null) this.update(btn, forms[0]);
        else this.create(btn, forms);
    };

    Board.prototype.create = function (btn, forms) {
        var self = this;
        var fd = new FormData();
        fd.append('year_id', String(this.year.id));
        fd.append('payload', JSON.stringify({
            indicators: forms.map(function (f) { return f.payload; })
        }));
        // `files` y `file_indexes` son listas PARALELAS: el índice dice a qué
        // ficha pertenece cada archivo. Se mandan solo si hay adjuntos.
        forms.forEach(function (f, index) {
            if (!f.file) return;
            fd.append('files', f.file);
            fd.append('file_indexes', String(index));
        });

        busy(btn, true);
        U.fetchJson(this.api, { method: 'POST', body: fd })
            .then(function (payload) {
                var total = (payload && payload.total) || 0;
                toast(total + ' indicador(es) creado(s)', 'success');
                if (self.modal) self.modal.hide();
                return self.reload();
            })
            .catch(function (err) {
                toast('No se pudo guardar: ' + err.message, 'error');
            })
            .then(function () { busy(btn, false); });
    };

    Board.prototype.update = function (btn, form) {
        var self = this;
        var id = this.editingId;
        var fd = new FormData();
        fd.append('payload', JSON.stringify(form.payload));
        if (form.file) fd.append('file', form.file);

        busy(btn, true);
        U.fetchJson(this.api + '/' + encodeURIComponent(id), { method: 'PATCH', body: fd })
            .then(function () {
                toast('Indicador actualizado', 'success');
                if (self.modal) self.modal.hide();
                return self.reload();
            })
            .catch(function (err) {
                toast('No se pudo actualizar: ' + err.message, 'error');
            })
            .then(function () { busy(btn, false); });
    };

    Board.prototype.remove = function (id, btn) {
        var self = this;
        var item = this.find(id);
        var what = item && item.process_name ? ' de "' + item.process_name + '"' : '';

        return U.confirmDialog({
            title: 'Eliminar indicador',
            message: 'Se eliminará la ficha' + what + ', su seguimiento y su evidencia. ' +
                     'Esta acción no se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return;
            busy(btn, true);
            return U.fetchJson(self.api + '/' + encodeURIComponent(id), { method: 'DELETE' })
                .then(function (payload) {
                    toast((payload && payload.message) || 'Indicador eliminado', 'success');
                    if (self.modal && self.editingId !== null) self.modal.hide();
                    self.editingId = null;
                    return self.reload();
                })
                .catch(function (err) {
                    toast('No se pudo eliminar: ' + err.message, 'error');
                })
                .then(function () { busy(btn, false); });
        });
    };

    Board.prototype.reload = function () {
        var self = this;
        return U.fetchJson(this.api + '?year_id=' + encodeURIComponent(this.year.id))
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                toast('No se pudo refrescar el tablero: ' + err.message, 'error');
            });
    };

    // ---------- eventos ----------

    Board.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-board-new]')) { self.openNew(); return; }

            // "Filtrar" del legacy: el filtrado ya es en vivo, el boton lo reaplica.
            if (evt.target.closest('[data-adhoc-board-filter]')) {
                if (window.AdhocTableFilter && self.table) window.AdhocTableFilter.apply(self.table);
                return;
            }

            // La descarga es un <a> real: no se intercepta.
            if (evt.target.closest('[data-adhoc-action="download"]')) return;

            var del = evt.target.closest('[data-adhoc-action="delete"]');
            if (del) {
                evt.preventDefault();
                evt.stopPropagation();
                var delRow = del.closest('tr[data-id]');
                if (delRow) self.remove(delRow.getAttribute('data-id'), del);
                return;
            }

            var edit = evt.target.closest('[data-adhoc-action="edit"]');
            var row = evt.target.closest('tr[data-id]');
            if ((edit || row) && self.canUpdate && row) {
                evt.preventDefault();
                self.openEdit(row.getAttribute('data-id'));
            }
        });

        if (this.qty) {
            this.qty.addEventListener('change', function () { self.buildForms(); });
        }

        if (this.modalEl) {
            this.modalEl.addEventListener('click', function (evt) {
                var save = evt.target.closest('[data-adhoc-board-save]');
                if (save) { self.save(save); return; }
                var del = evt.target.closest('[data-adhoc-board-delete]');
                if (del && self.editingId !== null) self.remove(self.editingId, del);
            });
        }
    };

    // ==================== INIT ====================

    function init(scope) {
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-indicator-board]'))
            ? node
            : node.querySelector('[data-adhoc-indicator-board]');
        if (!root) return null;
        if (root.dataset.adhocBoardBound === '1') return null;   // idempotente
        root.dataset.adhocBoardBound = '1';

        var instance = new Board(root);
        instance.init();
        return instance;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocIndicatorBoard = { init: init };
})();
