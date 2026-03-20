/**
 * maint-utils.js
 * Utilidades compartidas para la app de Mantenimiento.
 * Expone: window.MaintUtils
 *
 * API pública:
 *   MaintUtils.toast(message, type, duration)
 *   MaintUtils.confirm({ title, message, confirmLabel, cancelLabel, onConfirm, onCancel })
 *   MaintUtils.alert({ title, message, type })
 *   MaintUtils.loading.show(btn, loadingText)
 *   MaintUtils.loading.hide(btn)
 *   MaintUtils.api.fetch(url, options)
 */
'use strict';

(function () {

    // ─────────────────────────────────────────────────────────────────────────
    // CONSTANTES
    // ─────────────────────────────────────────────────────────────────────────

    var TOAST_TYPES = {
        success: { bg: 'bg-success',  icon: 'bi-check-circle-fill'  },
        error:   { bg: 'bg-danger',   icon: 'bi-x-circle-fill'      },
        warning: { bg: 'bg-warning',  icon: 'bi-exclamation-triangle-fill' },
        info:    { bg: 'bg-primary',  icon: 'bi-info-circle-fill'   },
    };

    var ALERT_TYPES = {
        success: { icon: 'bi-check-circle-fill', color: 'text-success', title: 'Listo' },
        error:   { icon: 'bi-x-circle-fill',     color: 'text-danger',  title: 'Error' },
        warning: { icon: 'bi-exclamation-triangle-fill', color: 'text-warning', title: 'Atención' },
        info:    { icon: 'bi-info-circle-fill',  color: 'text-primary', title: 'Información' },
    };

    // ─────────────────────────────────────────────────────────────────────────
    // TOAST
    // ─────────────────────────────────────────────────────────────────────────

    function _getToastContainer() {
        var el = document.getElementById('toastContainer');
        if (!el) {
            el = document.createElement('div');
            el.id = 'toastContainer';
            el.className = 'position-fixed top-0 end-0 p-3';
            el.style.zIndex = '9999';
            document.body.appendChild(el);
        }
        return el;
    }

    /**
     * Muestra un toast Bootstrap.
     * @param {string} message - Mensaje a mostrar
     * @param {string} [type='info'] - success | error | warning | info
     * @param {number} [duration=4000] - Duración en ms (0 = no se cierra solo)
     */
    function toast(message, type, duration) {
        type = type || 'info';
        duration = (duration === undefined) ? 4000 : duration;

        var cfg = TOAST_TYPES[type] || TOAST_TYPES.info;
        var id = 'mn-toast-' + Date.now();

        var el = document.createElement('div');
        el.id = id;
        el.className = 'toast align-items-center text-white border-0 ' + cfg.bg;
        el.setAttribute('role', 'alert');
        el.setAttribute('aria-live', 'assertive');
        el.setAttribute('aria-atomic', 'true');
        el.innerHTML =
            '<div class="d-flex">' +
                '<div class="toast-body d-flex align-items-center gap-2">' +
                    '<i class="bi ' + cfg.icon + '"></i>' +
                    '<span>' + _escapeHtml(message) + '</span>' +
                '</div>' +
                '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
            '</div>';

        _getToastContainer().appendChild(el);

        var bsToast = new bootstrap.Toast(el, {
            autohide: duration > 0,
            delay: duration,
        });
        bsToast.show();

        el.addEventListener('hidden.bs.toast', function () {
            el.remove();
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MODAL DE CONFIRMACIÓN
    // ─────────────────────────────────────────────────────────────────────────

    var _confirmModal = null;
    var _confirmModalEl = null;

    function _ensureConfirmModal() {
        if (_confirmModalEl) return;

        _confirmModalEl = document.createElement('div');
        _confirmModalEl.id = 'mnConfirmModal';
        _confirmModalEl.className = 'modal fade';
        _confirmModalEl.setAttribute('tabindex', '-1');
        _confirmModalEl.setAttribute('aria-modal', 'true');
        _confirmModalEl.setAttribute('role', 'dialog');
        _confirmModalEl.innerHTML =
            '<div class="modal-dialog modal-dialog-centered">' +
                '<div class="modal-content border-0 shadow">' +
                    '<div class="modal-header border-0 pb-0">' +
                        '<h5 class="modal-title fw-semibold" id="mnConfirmTitle"></h5>' +
                        '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
                    '</div>' +
                    '<div class="modal-body pt-2" id="mnConfirmBody"></div>' +
                    '<div class="modal-footer border-0 pt-0">' +
                        '<button type="button" class="btn btn-outline-secondary btn-sm" id="mnConfirmCancel" data-bs-dismiss="modal"></button>' +
                        '<button type="button" class="btn btn-sm" id="mnConfirmOk"></button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        document.body.appendChild(_confirmModalEl);
        _confirmModal = new bootstrap.Modal(_confirmModalEl, { backdrop: 'static', keyboard: false });
    }

    /**
     * Modal de confirmación (reemplaza window.confirm).
     * @param {Object} options
     * @param {string}   options.title         - Título del modal
     * @param {string}   options.message       - Cuerpo del mensaje
     * @param {string}   [options.confirmLabel='Confirmar'] - Texto del botón de confirmación
     * @param {string}   [options.cancelLabel='Cancelar']   - Texto del botón de cancelar
     * @param {string}   [options.confirmClass='btn-danger'] - Clase CSS del botón de confirmación
     * @param {Function} options.onConfirm     - Callback al confirmar
     * @param {Function} [options.onCancel]    - Callback al cancelar
     */
    function confirm(options) {
        _ensureConfirmModal();

        document.getElementById('mnConfirmTitle').textContent = options.title || '¿Confirmar acción?';
        document.getElementById('mnConfirmBody').textContent  = options.message || '';
        document.getElementById('mnConfirmCancel').textContent = options.cancelLabel  || 'Cancelar';

        var okBtn = document.getElementById('mnConfirmOk');
        okBtn.textContent = options.confirmLabel || 'Confirmar';
        okBtn.className = 'btn btn-sm ' + (options.confirmClass || 'btn-danger');

        // Reemplazar listener anterior
        var newOkBtn = okBtn.cloneNode(true);
        okBtn.parentNode.replaceChild(newOkBtn, okBtn);
        newOkBtn.addEventListener('click', function () {
            _confirmModal.hide();
            if (typeof options.onConfirm === 'function') options.onConfirm();
        });

        _confirmModalEl.addEventListener('hidden.bs.modal', function handler() {
            _confirmModalEl.removeEventListener('hidden.bs.modal', handler);
            if (typeof options.onCancel === 'function') options.onCancel();
        }, { once: true });

        _confirmModal.show();
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MODAL DE ALERTA / INFO
    // ─────────────────────────────────────────────────────────────────────────

    var _alertModal = null;
    var _alertModalEl = null;

    function _ensureAlertModal() {
        if (_alertModalEl) return;

        _alertModalEl = document.createElement('div');
        _alertModalEl.id = 'mnAlertModal';
        _alertModalEl.className = 'modal fade';
        _alertModalEl.setAttribute('tabindex', '-1');
        _alertModalEl.setAttribute('aria-modal', 'true');
        _alertModalEl.setAttribute('role', 'dialog');
        _alertModalEl.innerHTML =
            '<div class="modal-dialog modal-dialog-centered">' +
                '<div class="modal-content border-0 shadow">' +
                    '<div class="modal-header border-0 pb-0">' +
                        '<h5 class="modal-title fw-semibold d-flex align-items-center gap-2" id="mnAlertTitle">' +
                            '<i class="bi" id="mnAlertIcon"></i>' +
                            '<span id="mnAlertTitleText"></span>' +
                        '</h5>' +
                        '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
                    '</div>' +
                    '<div class="modal-body pt-2" id="mnAlertBody"></div>' +
                    '<div class="modal-footer border-0 pt-0">' +
                        '<button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Aceptar</button>' +
                    '</div>' +
                '</div>' +
            '</div>';

        document.body.appendChild(_alertModalEl);
        _alertModal = new bootstrap.Modal(_alertModalEl);
    }

    /**
     * Modal de información/alerta (reemplaza window.alert).
     * @param {Object} options
     * @param {string} options.title   - Título (si no se pone, se usa el del tipo)
     * @param {string} options.message - Mensaje
     * @param {string} [options.type='info'] - success | error | warning | info
     */
    function alert(options) {
        _ensureAlertModal();

        var type = options.type || 'info';
        var cfg  = ALERT_TYPES[type] || ALERT_TYPES.info;

        var iconEl = document.getElementById('mnAlertIcon');
        iconEl.className = 'bi ' + cfg.icon + ' ' + cfg.color;

        document.getElementById('mnAlertTitleText').textContent = options.title || cfg.title;
        document.getElementById('mnAlertBody').textContent      = options.message || '';

        _alertModal.show();
    }

    // ─────────────────────────────────────────────────────────────────────────
    // ESTADO DE CARGA EN BOTONES
    // ─────────────────────────────────────────────────────────────────────────

    var _loadingOriginals = new WeakMap();

    /**
     * Activa el estado de carga en un botón.
     * @param {HTMLButtonElement} btn
     * @param {string} [text='Procesando...']
     */
    function loadingShow(btn, text) {
        if (!btn) return;
        _loadingOriginals.set(btn, btn.innerHTML);
        btn.disabled = true;
        btn.innerHTML =
            '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
            _escapeHtml(text || 'Procesando...');
    }

    /**
     * Desactiva el estado de carga en un botón.
     * @param {HTMLButtonElement} btn
     */
    function loadingHide(btn) {
        if (!btn) return;
        btn.disabled = false;
        var original = _loadingOriginals.get(btn);
        if (original) {
            btn.innerHTML = original;
            _loadingOriginals.delete(btn);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // API FETCH WRAPPER
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Wrapper de fetch con manejo estándar de errores JSON.
     * Lanza un Error con el mensaje del servidor si la respuesta no es ok.
     * @param {string} url
     * @param {RequestInit} [options={}]
     * @returns {Promise<any>} JSON parseado
     */
    async function apiFetch(url, options) {
        options = options || {};
        var defaults = {
            credentials: 'include',
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        };

        var res = await fetch(url, Object.assign({}, defaults, options));

        var body;
        try {
            body = await res.json();
        } catch (_) {
            body = {};
        }

        if (!res.ok) {
            var msg = (body && body.detail) ? body.detail
                    : (body && body.message) ? body.message
                    : 'Error ' + res.status;
            throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }

        return body;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // UTILIDADES INTERNAS
    // ─────────────────────────────────────────────────────────────────────────

    function _escapeHtml(str) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(str)));
        return d.innerHTML;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // API PÚBLICA
    // ─────────────────────────────────────────────────────────────────────────

    window.MaintUtils = {
        toast:   toast,
        confirm: confirm,
        alert:   alert,
        loading: {
            show: loadingShow,
            hide: loadingHide,
        },
        api: {
            fetch: apiFetch,
        },
    };

})();
