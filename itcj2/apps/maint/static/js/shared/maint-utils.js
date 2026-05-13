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
    // ANIMACIONES (entrada, stagger, observer)
    // ─────────────────────────────────────────────────────────────────────────

    function _prefersReducedMotion() {
        return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    /**
     * Aplica una clase de animación de entrada a los elementos.
     * @param {HTMLElement|NodeList|Array} target
     * @param {string} [klass='mn-fade-in-up']
     */
    function animateIn(target, klass) {
        klass = klass || 'mn-fade-in-up';
        var els = _toArray(target);
        if (_prefersReducedMotion()) return;
        els.forEach(function (el) {
            el.classList.remove(klass);
            // force reflow so re-add restarts
            void el.offsetWidth;
            el.classList.add(klass);
        });
    }

    /**
     * Stagger: aplica animación a hijos con retraso incremental.
     * Si el contenedor ya tiene .mn-stagger en CSS, basta con poner .mn-fade-in-up en los hijos;
     * esta función se usa para casos dinámicos (después de render JS).
     */
    function stagger(container, options) {
        options = options || {};
        var klass = options.klass || 'mn-fade-in-up';
        var step  = options.step  || 50;
        var max   = options.maxDelay || 440;
        if (_prefersReducedMotion()) return;
        if (!container) return;
        var children = container.children;
        for (var i = 0; i < children.length; i++) {
            var c = children[i];
            c.style.animationDelay = Math.min(i * step, max) + 'ms';
            c.classList.add(klass);
        }
    }

    /**
     * Highlight pulse para un elemento recién insertado vía Socket.IO.
     */
    function highlightNew(el) {
        if (!el || _prefersReducedMotion()) return;
        el.classList.remove('mn-highlight-new');
        void el.offsetWidth;
        el.classList.add('mn-highlight-new');
    }

    /**
     * Tween numérico para KPIs. Anima de start → end en duration ms.
     * @param {HTMLElement} el
     * @param {number} end
     * @param {Object} [options]
     */
    function countUp(el, end, options) {
        if (!el) return;
        options = options || {};
        var start    = options.start    !== undefined ? options.start    : 0;
        var duration = options.duration !== undefined ? options.duration : 700;
        var decimals = options.decimals !== undefined ? options.decimals : 0;
        var suffix   = options.suffix   || '';
        var prefix   = options.prefix   || '';

        if (_prefersReducedMotion() || duration <= 0) {
            el.textContent = prefix + Number(end).toFixed(decimals) + suffix;
            return;
        }
        var startTime = null;
        var diff = end - start;
        function frame(ts) {
            if (!startTime) startTime = ts;
            var p = Math.min((ts - startTime) / duration, 1);
            // easeOutCubic
            var eased = 1 - Math.pow(1 - p, 3);
            var value = start + diff * eased;
            el.textContent = prefix + value.toFixed(decimals) + suffix;
            if (p < 1) requestAnimationFrame(frame);
            else el.textContent = prefix + Number(end).toFixed(decimals) + suffix;
        }
        requestAnimationFrame(frame);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // SKELETONS — generadores HTML que coinciden con layouts finales
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Genera el HTML de N skeletons del tipo indicado.
     * @param {string} type - 'ticket-card' | 'table-row' | 'kpi' | 'chart' | 'comment' | 'list-row'
     * @param {number} count
     * @param {Object} [extra] - p.ej. { columns: 5 } para table-row
     * @returns {string}
     */
    function skeletonHtml(type, count, extra) {
        count = count || 1;
        extra = extra || {};
        var out = [];
        for (var i = 0; i < count; i++) {
            out.push(_skelTemplate(type, extra));
        }
        return out.join('');
    }

    function _skelTemplate(type, extra) {
        switch (type) {
            case 'ticket-card':
                return '' +
                    '<div class="mn-skel-card mb-3">' +
                        '<div class="d-flex justify-content-between align-items-center mb-2">' +
                            '<span class="mn-skel mn-skel-line w-25" style="margin:0;"></span>' +
                            '<span class="mn-skel mn-skel-pill"></span>' +
                        '</div>' +
                        '<span class="mn-skel mn-skel-line mn-skel-lg w-75"></span>' +
                        '<span class="mn-skel mn-skel-line w-90"></span>' +
                        '<div class="d-flex gap-2 mt-2">' +
                            '<span class="mn-skel mn-skel-pill" style="width:4rem;"></span>' +
                            '<span class="mn-skel mn-skel-pill" style="width:5.5rem;"></span>' +
                            '<span class="mn-skel mn-skel-pill" style="width:4.5rem;"></span>' +
                        '</div>' +
                    '</div>';
            case 'table-row':
                var cols = extra.columns || 5;
                var tds = '';
                for (var k = 0; k < cols; k++) {
                    tds += '<td><span class="mn-skel mn-skel-line w-75" style="margin:0;"></span></td>';
                }
                return '<tr>' + tds + '</tr>';
            case 'kpi':
                return '' +
                    '<div class="card border-0 shadow-sm h-100"><div class="card-body">' +
                        '<span class="mn-skel mn-skel-line w-50"></span>' +
                        '<span class="mn-skel mn-skel-line mn-skel-lg w-40" style="height:1.8rem; margin-top:0.6rem;"></span>' +
                        '<span class="mn-skel mn-skel-line w-60 mt-2"></span>' +
                    '</div></div>';
            case 'chart':
                return '<div class="mn-skel mn-skel-chart"></div>';
            case 'bars':
                var bars = '';
                var n = extra.bars || 7;
                for (var b = 0; b < n; b++) {
                    var h = 30 + Math.floor(Math.random() * 65);
                    bars += '<span class="mn-skel" style="height:' + h + '%;"></span>';
                }
                return '<div class="mn-skel-bars">' + bars + '</div>';
            case 'comment':
                return '' +
                    '<div class="d-flex gap-2 mb-3">' +
                        '<span class="mn-skel mn-skel-circle"></span>' +
                        '<div class="flex-grow-1">' +
                            '<span class="mn-skel mn-skel-line w-25"></span>' +
                            '<span class="mn-skel mn-skel-line w-90"></span>' +
                            '<span class="mn-skel mn-skel-line w-75"></span>' +
                        '</div>' +
                    '</div>';
            case 'list-row':
                return '' +
                    '<div class="d-flex align-items-center gap-2 py-2 border-bottom">' +
                        '<span class="mn-skel mn-skel-circle mn-skel-sm"></span>' +
                        '<span class="mn-skel mn-skel-line w-50" style="margin:0;"></span>' +
                        '<span class="mn-skel mn-skel-pill ms-auto"></span>' +
                    '</div>';
            default:
                return '<span class="mn-skel mn-skel-line w-75"></span>';
        }
    }

    /**
     * Inserta skeletons dentro de un contenedor.
     */
    function skeletonShow(container, type, count, extra) {
        if (typeof container === 'string') container = document.querySelector(container);
        if (!container) return;
        container.innerHTML = skeletonHtml(type, count, extra);
    }

    /**
     * Limpia skeletons (deja el contenedor vacío para el render real).
     */
    function skeletonHide(container) {
        if (typeof container === 'string') container = document.querySelector(container);
        if (!container) return;
        container.innerHTML = '';
    }

    // ─────────────────────────────────────────────────────────────────────────
    // UTILIDADES INTERNAS
    // ─────────────────────────────────────────────────────────────────────────

    function _escapeHtml(str) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(str)));
        return d.innerHTML;
    }

    function _toArray(target) {
        if (!target) return [];
        if (target instanceof HTMLElement) return [target];
        if (target instanceof NodeList || Array.isArray(target)) return Array.prototype.slice.call(target);
        return [];
    }

    // Aplica entrada sutil al <main> al cargar la página
    document.addEventListener('DOMContentLoaded', function () {
        var main = document.querySelector('main');
        if (main && !_prefersReducedMotion()) {
            main.classList.add('mn-page-enter');
        }
        // Activar modales con scale-in suave: añadir clase al dialog en show
        document.addEventListener('show.bs.modal', function (ev) {
            var dlg = ev.target && ev.target.querySelector('.modal-dialog');
            if (dlg) dlg.classList.add('mn-modal-enter');
        });
    });

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
        animate: {
            in: animateIn,
            stagger: stagger,
            highlight: highlightNew,
            countUp: countUp,
            prefersReducedMotion: _prefersReducedMotion,
        },
        skeleton: {
            html: skeletonHtml,
            show: skeletonShow,
            hide: skeletonHide,
        },
        escapeHtml: _escapeHtml,
    };

})();
