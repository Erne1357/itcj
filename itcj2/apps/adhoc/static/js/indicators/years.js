/**
 * indicators/years.js — lista de años del tablero de indicadores.
 *
 * Página: /adhoc/indicadores?mode=config|tracking
 * Expone SOLO `window.AdhocIndicatorYears` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `app_prueba/js/indicators/indicators_year.js` (clase `IndicadoresAniosManager`
 * suelta en el scope global). Sus tres problemas:
 *
 *   1. Borrado con el diálogo nativo del navegador (síncrono) que, al aceptar,
 *      fabricaba un <form> y hacía `submit()` contra una ruta con doble prefijo
 *      (`/api/api/indicators/years/delete/<id>`). Aquí: `confirmDialog()` +
 *      `DELETE /api/adhoc/v2/indicator-years/{id}`.
 *   2. La URL de destino de la fila se armaba en Jinja como
 *      `url_for(..., id=0)` + `.replace('/0','/')`, con un `{% if %}` DENTRO de
 *      la cadena JS. Aquí viene resuelta en `page_data.target_base/suffix`.
 *   3. El alta pintaba 71 <option> por cada campo con innerHTML. Aquí es un
 *      <input type="number"> acotado al rango que valida el schema.
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   GET    /indicator-years        → {success, data: [{id, year, indicators_count}], total}
 *   POST   /indicator-years        → 201 {success, data, total, skipped, message}
 *   DELETE /indicator-years/{id}   → {success, message}
 *   error                          → {"error": "texto", "status": N}
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var API = '/api/adhoc/v2/indicator-years';
    var YEAR_MIN = 2000;      // == _YEAR_MIN de schemas/indicators.py
    var YEAR_MAX = 2100;      // == _YEAR_MAX
    var TABLE_ID = 'adhoc-indicator-years';

    // ==================== HELPERS ====================

    function busy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    }

    function toast(message, type) {
        if (U && U.showToast) U.showToast(message, type);
    }

    // ==================== MÓDULO ====================

    function Years(root) {
        this.root = root;
        this.data = U.pageData();
        this.items = this.data.years || [];
        this.canCreate = !!this.data.can_create;
        this.canDelete = !!this.data.can_delete;
        this.targetBase = this.data.target_base || '';
        this.targetSuffix = this.data.target_suffix || '';

        this.table = document.getElementById(TABLE_ID);
        this.body = document.getElementById(TABLE_ID + '-body');
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;

        this.modalEl = document.getElementById('adhoc-years-modal');
        this.modal = (this.modalEl && window.bootstrap)
            ? window.bootstrap.Modal.getOrCreateInstance(this.modalEl)
            : null;
        this.fields = this.modalEl ? this.modalEl.querySelector('[data-adhoc-years-fields]') : null;
        // El <select> de cantidad esta en los controles inferiores de la pagina,
        // como en el legacy: se elige ANTES de abrir el modal.
        this.qty = document.querySelector('[data-adhoc-years-qty]');
    }

    Years.prototype.init = function () {
        this.render();
        this.bind();
    };

    // ---------- render ----------

    Years.prototype.href = function (id) {
        if (!this.targetBase) return '';
        return this.targetBase + id + this.targetSuffix;
    };

    Years.prototype.render = function () {
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

    Years.prototype.buildRow = function (item) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(item.id));

        var href = this.href(item.id);
        if (href) {
            tr.classList.add('adhoc-row-click');
            tr.setAttribute('tabindex', '0');
            tr.setAttribute('role', 'link');
        }

        // Año — textContent, nunca innerHTML (aunque sea un entero del servidor).
        var tdYear = document.createElement('td');
        tdYear.setAttribute('data-adhoc-cell', 'year');
        tdYear.className = 'adhoc-years-value';
        tdYear.textContent = String(item.year);
        tr.appendChild(tdYear);

        var tdCount = document.createElement('td');
        tdCount.setAttribute('data-adhoc-cell', 'indicators_count');
        tdCount.className = 'adhoc-col-center adhoc-years-count';
        tdCount.textContent = String(item.indicators_count || 0);
        tr.appendChild(tdCount);

        var tdActions = document.createElement('td');
        tdActions.className = 'adhoc-col-center';
        var box = document.createElement('div');
        box.className = 'adhoc-actions adhoc-years-actions';
        if (this.canDelete) {
            // Markup estático: ningún dato del servidor entra en este innerHTML.
            box.innerHTML =
                '<button type="button" class="adhoc-years-icon" ' +
                'data-adhoc-action="delete" title="Eliminar año" aria-label="Eliminar año">' +
                '<i class="fa-solid fa-trash"></i></button>';
        }
        tdActions.appendChild(box);
        tr.appendChild(tdActions);

        return tr;
    };

    // ---------- datos ----------

    Years.prototype.reload = function () {
        var self = this;
        return U.fetchJson(API)
            .then(function (payload) {
                self.items = (payload && payload.data) || [];
                self.render();
            })
            .catch(function (err) {
                toast('No se pudieron cargar los años: ' + err.message, 'error');
            });
    };

    Years.prototype.remove = function (tr) {
        var self = this;
        var id = tr.getAttribute('data-id');
        var item = null;
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) { item = this.items[i]; break; }
        }
        var year = item ? item.year : id;
        var count = item ? (item.indicators_count || 0) : 0;

        var message = 'Se eliminará el año ' + year +
            (count ? ' y sus ' + count + ' indicador(es), con todo su seguimiento.'
                   : ' y todo su seguimiento.') +
            ' Esta acción no se puede deshacer.';

        return U.confirmDialog({
            title: 'Eliminar año',
            message: message,
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return;
            return U.fetchJson(API + '/' + encodeURIComponent(id), { method: 'DELETE' })
                .then(function (payload) {
                    toast((payload && payload.message) || 'Año eliminado', 'success');
                    return self.reload();
                })
                .catch(function (err) {
                    toast('No se pudo eliminar: ' + err.message, 'error');
                });
        });
    };

    // ---------- alta ----------

    Years.prototype.openNew = function () {
        if (!this.modal) return;
        this.buildFields();
        this.modal.show();
    };

    Years.prototype.buildFields = function () {
        if (!this.fields) return;
        var count = parseInt(this.qty ? this.qty.value : '1', 10) || 1;
        var current = new Date().getFullYear();
        var html = '';
        for (var i = 0; i < count; i++) {
            var id = 'adhoc-years-input-' + i;
            var value = Math.min(YEAR_MAX, current + i);
            html +=
                '<div class="adhoc-field">' +
                  '<label class="form-label adhoc-label" for="' + id + '">Año #' + (i + 1) + '</label>' +
                  '<input type="number" class="form-control" id="' + id + '" ' +
                    'data-adhoc-years-input min="' + YEAR_MIN + '" max="' + YEAR_MAX + '" ' +
                    'step="1" value="' + value + '" required>' +
                '</div>';
        }
        this.fields.innerHTML = html;   // markup estático + enteros calculados
        var first = this.fields.querySelector('[data-adhoc-years-input]');
        if (first) first.focus();
    };

    Years.prototype.submitNew = function (btn) {
        var self = this;
        if (!this.fields) return;

        var inputs = this.fields.querySelectorAll('[data-adhoc-years-input]');
        var years = [];
        for (var i = 0; i < inputs.length; i++) {
            var raw = (inputs[i].value || '').trim();
            if (!raw) continue;
            var value = parseInt(raw, 10);
            if (isNaN(value) || value < YEAR_MIN || value > YEAR_MAX) {
                toast('Año fuera de rango (' + YEAR_MIN + '-' + YEAR_MAX + '): ' + raw, 'warning');
                inputs[i].focus();
                return;
            }
            years.push(value);
        }
        if (!years.length) {
            toast('Captura al menos un año.', 'warning');
            return;
        }

        busy(btn, true);
        U.fetchJson(API, { method: 'POST', body: JSON.stringify({ years: years }) })
            .then(function (payload) {
                toast((payload && payload.message) || 'Años guardados', 'success');
                if (self.modal) self.modal.hide();
                return self.reload();
            })
            .catch(function (err) {
                toast('No se pudo guardar: ' + err.message, 'error');
            })
            .then(function () { busy(btn, false); });
    };

    // ---------- eventos ----------

    Years.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            var newBtn = evt.target.closest('[data-adhoc-years-new]');
            if (newBtn) { self.openNew(); return; }

            if (evt.target.closest('[data-adhoc-years-filter]')) {
                if (window.AdhocTableFilter && self.table) window.AdhocTableFilter.apply(self.table);
                return;
            }

            var del = evt.target.closest('[data-adhoc-action="delete"]');
            if (del) {
                evt.preventDefault();
                evt.stopPropagation();
                var row = del.closest('tr[data-id]');
                if (row) self.remove(row);
                return;
            }

            var tr = evt.target.closest('tr[data-id]');
            if (tr && self.targetBase) {
                window.location.href = self.href(tr.getAttribute('data-id'));
            }
        });

        // La fila es role="link": Enter/Espacio la abren, como un <a>.
        this.root.addEventListener('keydown', function (evt) {
            if (evt.key !== 'Enter' && evt.key !== ' ') return;
            var tr = evt.target.closest ? evt.target.closest('tr[data-id]') : null;
            if (!tr || !self.targetBase) return;
            evt.preventDefault();
            window.location.href = self.href(tr.getAttribute('data-id'));
        });

        if (this.qty) {
            this.qty.addEventListener('change', function () { self.buildFields(); });
        }
        if (this.modalEl) {
            this.modalEl.addEventListener('click', function (evt) {
                var save = evt.target.closest('[data-adhoc-years-save]');
                if (save) self.submitNew(save);
            });
            this.modalEl.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && evt.target.matches('[data-adhoc-years-input]')) {
                    evt.preventDefault();
                    self.submitNew(self.modalEl.querySelector('[data-adhoc-years-save]'));
                }
            });
        }
    };

    // ==================== INIT ====================

    function init(scope) {
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-indicator-years]'))
            ? node
            : node.querySelector('[data-adhoc-indicator-years]');
        if (!root) return null;
        if (root.dataset.adhocYearsBound === '1') return null;   // idempotente
        root.dataset.adhocYearsBound = '1';

        var instance = new Years(root);
        instance.init();
        return instance;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocIndicatorYears = { init: init };
})();
