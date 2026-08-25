/**
 * panel/mail.js — interruptor global del correo de Calidad.
 *
 * Expone SOLO `window.AdhocPanelMail` (IIFE; el legacy dejaba
 * `class MailConfigManager` en el scope global).
 *
 * QUÉ ARREGLA respecto de `js/control_panel/mail.js`
 * -------------------------------------------------
 *  · El `alert()` del manejador de error → toast con el mensaje real de la API.
 *  · El modal casero de éxito (`style.display='flex'` sobre `.modal-success`)
 *    → toast.
 *  · Las URLs `/api/mail/config` con verbo POST y payload `{enabled}` →
 *    `GET`/`PUT /api/adhoc/v2/mail-config` con `{is_enabled}`.
 *  · El contrato de error: el legacy leía `data.success` de una respuesta 200;
 *    aquí un fallo es un status HTTP real y `fetchJson` lo convierte en Error.
 *
 * CONTRATO DE API CONSUMIDO
 * -------------------------
 *   GET {api} → {success, data: {is_enabled, updated_at}}
 *               503 si el DML de la app no se ha corrido (mensaje accionable).
 *   PUT {api} → {success, data: {is_enabled, updated_at}}
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    // Textos del legacy (js/control_panel/mail.js): el interruptor rotula el
    // SERVICIO, no la acción.
    var LABEL_ON = 'Servicio Activo';
    var LABEL_OFF = 'Servicio Desactivado';
    var LABEL_LOADING = 'Consultando estado...';

    function bool(value) {
        return value === '1' || value === 'true' || value === true;
    }

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    function MailPanel(root) {
        var d = root.dataset;

        this.root = root;
        this.api = d.adhocApi || '/api/adhoc/v2/mail-config';
        this.canUpdate = bool(d.adhocCanUpdate);

        this.toggle = root.querySelector('[data-adhoc-mail-toggle]');
        this.status = root.querySelector('[data-adhoc-mail-status]');
        this.saveBtn = root.querySelector('[data-adhoc-mail-save]');
        this.saveLabel = root.querySelector('[data-adhoc-mail-save-label]');

        this.saved = null;   // último valor confirmado por el servidor
    }

    MailPanel.prototype.init = function () {
        if (!this.toggle) {
            console.error('[adhoc] panel/mail: falta el interruptor');
            return;
        }
        this.bind();
        this.load();
    };

    MailPanel.prototype.setStatus = function (text) {
        if (this.status) this.status.textContent = text;
    };

    MailPanel.prototype.paint = function () {
        this.setStatus(this.toggle.checked ? LABEL_ON : LABEL_OFF);
    };

    MailPanel.prototype.load = function () {
        var self = this;
        this.setStatus(LABEL_LOADING);
        this.toggle.disabled = true;

        return U.fetchJson(this.api)
            .then(function (payload) {
                var data = (payload && payload.data) || {};
                self.saved = !!data.is_enabled;
                self.toggle.checked = self.saved;
                self.paint();
            })
            .catch(function (err) {
                // 503 = la fila singleton no está sembrada. El mensaje de la API
                // dice exactamente qué correr; se muestra tal cual.
                self.setStatus('No se pudo leer el estado del correo');
                toast(err.message, 'error');
            })
            .then(function () {
                self.toggle.disabled = !self.canUpdate;
            });
    };

    MailPanel.prototype.save = function () {
        var self = this;
        if (!this.canUpdate) return;

        var value = !!this.toggle.checked;

        this.setBusy(true);
        U.fetchJson(this.api, {
            method: 'PUT',
            body: JSON.stringify({ is_enabled: value })
        }).then(function (payload) {
            var data = (payload && payload.data) || {};
            self.saved = data.is_enabled === undefined ? value : !!data.is_enabled;
            self.toggle.checked = self.saved;
            self.paint();
            toast(self.saved
                ? 'El envío de correo quedó activado.'
                : 'El envío de correo quedó desactivado.', 'success');
        }).catch(function (err) {
            // Se revierte el interruptor al último valor confirmado: dejarlo en
            // la posición nueva mentiría sobre el estado real del sistema.
            if (self.saved !== null) {
                self.toggle.checked = self.saved;
                self.paint();
            }
            toast(err.message, 'error');
        }).then(function () {
            self.setBusy(false);
        });
    };

    MailPanel.prototype.setBusy = function (isBusy) {
        if (this.saveBtn) {
            this.saveBtn.disabled = !!isBusy;
            this.saveBtn.classList.toggle('disabled', !!isBusy);
        }
        if (this.saveLabel) {
            this.saveLabel.textContent = isBusy ? 'Guardando...' : 'Guardar cambios';
        }
        if (this.toggle) this.toggle.disabled = !!isBusy || !this.canUpdate;
    };

    MailPanel.prototype.bind = function () {
        var self = this;

        this.toggle.addEventListener('change', function () {
            self.paint();
        });

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-mail-save]')) {
                evt.preventDefault();
                self.save();
            }
        });
    };

    // ==================== API PÚBLICA ====================

    function init(root) {
        var node = root || document.querySelector('[data-adhoc-mail]');
        if (!node) return null;
        if (node.dataset.adhocMailBound === '1') return null;   // idempotente
        node.dataset.adhocMailBound = '1';

        var instance = new MailPanel(node);
        instance.init();
        return instance;
    }

    function initAll(scope) {
        var node = scope || document;
        var out = [];
        var made;

        if (node.matches && node.matches('[data-adhoc-mail]')) {
            made = init(node);
            if (made) out.push(made);
        }

        var roots = node.querySelectorAll('[data-adhoc-mail]');
        for (var i = 0; i < roots.length; i++) {
            made = init(roots[i]);
            if (made) out.push(made);
        }
        return out;
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { initAll(root || document); });
    }

    window.AdhocPanelMail = { init: init, initAll: initAll };
})();
