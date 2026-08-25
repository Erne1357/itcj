/**
 * indicators/tracking.js — rejilla de seguimiento por colores de un año.
 *
 * Página: /adhoc/indicadores/{year_id}/seguimiento
 * Expone SOLO `window.AdhocIndicatorTracking` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `app_prueba/js/indicators/indicators_tracking.js`, el único módulo del legacy
 * sin clase: todo colgaba del callback de DOMContentLoaded, con listeners
 * enganchados uno a uno a cada celda (52 × N indicadores). Sus problemas:
 *
 *   1. Dependencia dura de `TRACKING_CONFIG` sin guarda `typeof`: si el bloque
 *      inline faltaba, ReferenceError en runtime. Aquí se lee con
 *      `AdhocUtils.pageData()`, que devuelve {} si el bloque no está.
 *   2. `.catch(error => console.error(error))`: si el guardado fallaba, el
 *      usuario veía su valor en pantalla y creía que estaba guardado. Aquí el
 *      fallo se avisa con un toast y la celda se marca.
 *   3. Las clases de color se construían con `` `bg-${color}` `` — las
 *      `.bg-blanco/.bg-rojo/…` colisionan con las utilidades `.bg-` de
 *      Bootstrap 5.3. Aquí el mapa color → clase viene en `page_data`.
 *   4. Localizaba el <select> con `this.nextElementSibling` (y el input con
 *      `previousElementSibling`), así que cualquier nodo intermedio lo rompía.
 *      Aquí se busca dentro de la celda por `data-adhoc-*`.
 *   5. La edición estaba SIEMPRE habilitada porque la vista pasaba
 *      `is_admin=True` hardcodeado. Aquí `page_data.can_edit` viene del permiso
 *      real `adhoc.indicators.api.tracking` y, sin él, la plantilla ni siquiera
 *      pinta los <select>.
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   PUT /api/adhoc/v2/indicator-trackings
 *       body {indicator_id, period_index, real_value, color}
 *       → {success, data: {id, indicator_id, period_index, real_value, color}}
 *   error → {"error": "texto", "status": N}
 *
 * El upsert es por (indicator_id, period_index) sobre el UNIQUE nuevo, así que
 * reenviar la misma celda es idempotente. `period_index` es 1..N, la misma
 * numeración que ve el usuario en la cabecera.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var DEBOUNCE_MS = 700;
    var SAVED_MS = 2000;

    var STATE_CLASSES = [
        'adhoc-state-white', 'adhoc-state-red', 'adhoc-state-yellow', 'adhoc-state-green'
    ];

    function toast(message, type) {
        if (U && U.showToast) U.showToast(message, type);
    }

    // ==================== MÓDULO ====================

    function Tracking(root) {
        this.root = root;
        this.data = U.pageData();
        this.canEdit = !!this.data.can_edit;
        this.api = (this.data.api && this.data.api.trackings) || '/api/adhoc/v2/indicator-trackings';
        this.colorClasses = this.data.color_classes || {};
        this.timers = {};
        this.savedTimers = {};
    }

    Tracking.prototype.init = function () {
        this.paintSwatches();
        if (this.canEdit) this.bind();
    };

    /**
     * Aplica el color de cada proceso a su muestra. El color no puede venir en
     * un style="…" desde la plantilla (regla dura del plan §6.2), así que viaja
     * en data-adhoc-color y se aplica aquí.
     */
    Tracking.prototype.paintSwatches = function () {
        var nodes = this.root.querySelectorAll('[data-adhoc-color]');
        for (var i = 0; i < nodes.length; i++) {
            var color = nodes[i].getAttribute('data-adhoc-color');
            if (color) nodes[i].style.backgroundColor = color;
        }
    };

    // ---------- celdas ----------

    Tracking.prototype.cellOf = function (el) {
        var box = el.closest('.adhoc-tracking-cell-box');
        if (!box) return null;
        return {
            box: box,
            input: box.querySelector('[data-adhoc-tracking-input]'),
            select: box.querySelector('[data-adhoc-tracking-color]'),
            indicatorId: el.getAttribute('data-adhoc-indicator'),
            periodIndex: el.getAttribute('data-adhoc-period')
        };
    };

    Tracking.prototype.applyColor = function (cell, color) {
        var cls = this.colorClasses[color] || this.colorClasses.blanco || 'adhoc-state-white';
        var nodes = [cell.input, cell.select];
        for (var i = 0; i < nodes.length; i++) {
            if (!nodes[i]) continue;
            for (var j = 0; j < STATE_CLASSES.length; j++) {
                nodes[i].classList.remove(STATE_CLASSES[j]);
            }
            nodes[i].classList.add(cls);
        }
    };

    Tracking.prototype.flagSaved = function (indicatorId) {
        var el = this.root.querySelector('[data-adhoc-saved="' + indicatorId + '"]');
        if (!el) return;
        el.hidden = false;
        if (this.savedTimers[indicatorId]) clearTimeout(this.savedTimers[indicatorId]);
        this.savedTimers[indicatorId] = setTimeout(function () { el.hidden = true; }, SAVED_MS);
    };

    // ---------- guardado ----------

    Tracking.prototype.save = function (cell) {
        var self = this;
        if (!cell || !cell.indicatorId || !cell.periodIndex) return;

        var body = {
            indicator_id: parseInt(cell.indicatorId, 10),
            period_index: parseInt(cell.periodIndex, 10),
            real_value: cell.input ? cell.input.value : null,
            color: cell.select ? cell.select.value : 'blanco'
        };

        return U.fetchJson(this.api, { method: 'PUT', body: JSON.stringify(body) })
            .then(function (payload) {
                var saved = (payload && payload.data) || {};
                if (cell.input) cell.input.classList.remove('is-invalid');
                if (saved.color) self.applyColor(cell, saved.color);
                self.flagSaved(cell.indicatorId);
            })
            .catch(function (err) {
                // El legacy se comía el error con un console.error: el usuario
                // veía su valor en pantalla y lo daba por guardado.
                if (cell.input) cell.input.classList.add('is-invalid');
                toast('No se pudo guardar el periodo ' + cell.periodIndex + ': ' + err.message, 'error');
            });
    };

    Tracking.prototype.saveDebounced = function (cell) {
        var self = this;
        var key = cell.indicatorId + ':' + cell.periodIndex;
        if (this.timers[key]) clearTimeout(this.timers[key]);
        this.timers[key] = setTimeout(function () {
            delete self.timers[key];
            self.save(cell);
        }, DEBOUNCE_MS);
    };

    Tracking.prototype.flush = function (cell) {
        var key = cell.indicatorId + ':' + cell.periodIndex;
        if (this.timers[key]) {
            clearTimeout(this.timers[key]);
            delete this.timers[key];
        }
        return this.save(cell);
    };

    // ---------- eventos (delegados: un listener, no 52 × N) ----------

    Tracking.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('input', function (evt) {
            if (!evt.target.matches('[data-adhoc-tracking-input]')) return;
            var cell = self.cellOf(evt.target);
            if (cell) self.saveDebounced(cell);
        });

        this.root.addEventListener('change', function (evt) {
            if (!evt.target.matches('[data-adhoc-tracking-color]')) return;
            var cell = self.cellOf(evt.target);
            if (!cell) return;
            self.applyColor(cell, evt.target.value);
            self.flush(cell);
        });

        // Salir de la celda guarda ya, sin esperar al debounce: si el usuario
        // cierra la pestaña justo después, el valor no se pierde.
        this.root.addEventListener('focusout', function (evt) {
            if (!evt.target.matches('[data-adhoc-tracking-input]')) return;
            var cell = self.cellOf(evt.target);
            if (!cell) return;
            var key = cell.indicatorId + ':' + cell.periodIndex;
            if (self.timers[key]) self.flush(cell);
        });
    };

    // ==================== INIT ====================

    function init(scope) {
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-indicator-tracking]'))
            ? node
            : node.querySelector('[data-adhoc-indicator-tracking]');
        if (!root) return null;
        if (root.dataset.adhocTrackingBound === '1') return null;   // idempotente
        root.dataset.adhocTrackingBound = '1';

        var instance = new Tracking(root);
        instance.init();
        return instance;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocIndicatorTracking = { init: init };
})();
