/**
 * adhoc-utils.js — utilidades compartidas de Calidad (app `adhoc`).
 *
 * Módulo IIFE: expone SOLO `window.AdhocUtils`. Ninguna función interna es global
 * (el legacy dejaba 28 clases ES6 sueltas en el scope global).
 *
 * PROHIBIDO en toda la app: alert(), confirm(), prompt(). Usa showToast() y
 * confirmDialog(), que devuelven UI de Bootstrap 5.3 y no bloquean el hilo.
 */
(function () {
    'use strict';

    var API_BASE = '/api/adhoc/v2';
    var TOAST_CONTAINER_ID = 'adhoc-toast-container';

    // ==================== ESCAPE ====================

    /**
     * Escapa texto antes de meterlo en innerHTML. Obligatorio para CUALQUIER
     * dato que venga del servidor (el legacy tenía XSS almacenado en los
     * comentarios de tarea).
     * @param {*} str
     * @returns {string}
     */
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ==================== TOASTS ====================

    function toastContainer() {
        var el = document.getElementById(TOAST_CONTAINER_ID);
        if (!el) {
            el = document.createElement('div');
            el.id = TOAST_CONTAINER_ID;
            el.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(el);
        }
        return el;
    }

    var TOAST_STYLE = {
        success: { bg: 'bg-success', icon: 'bi-check-circle-fill', dark: false },
        error:   { bg: 'bg-danger',  icon: 'bi-exclamation-octagon-fill', dark: false },
        danger:  { bg: 'bg-danger',  icon: 'bi-exclamation-octagon-fill', dark: false },
        warning: { bg: 'bg-warning', icon: 'bi-exclamation-triangle-fill', dark: true },
        info:    { bg: 'bg-info',    icon: 'bi-info-circle-fill', dark: true }
    };

    /**
     * Muestra un toast de Bootstrap. Crea el contenedor si no existe.
     * @param {string} message  texto plano (se escapa)
     * @param {string} [type]   success | error | warning | info
     */
    function showToast(message, type) {
        var style = TOAST_STYLE[type] || TOAST_STYLE.success;
        var container = toastContainer();

        var toast = document.createElement('div');
        toast.className = 'toast align-items-center border-0 ' + style.bg + ' ' +
            (style.dark ? 'text-dark' : 'text-white');
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.innerHTML =
            '<div class="d-flex align-items-center">' +
              '<div class="toast-body flex-grow-1 d-flex align-items-center gap-2">' +
                '<i class="bi ' + style.icon + '"></i>' +
                '<span>' + escapeHtml(message) + '</span>' +
              '</div>' +
              '<button type="button" class="btn-close ' + (style.dark ? '' : 'btn-close-white') +
                ' me-2" data-bs-dismiss="toast" aria-label="Cerrar"></button>' +
            '</div>';

        container.appendChild(toast);

        if (window.bootstrap && window.bootstrap.Toast) {
            var bsToast = new window.bootstrap.Toast(toast, { delay: 5000 });
            toast.addEventListener('hidden.bs.toast', function () { toast.remove(); });
            bsToast.show();
        } else {
            // Sin el bundle de Bootstrap todavía cargado: al menos que se vea.
            toast.classList.add('show');
            setTimeout(function () { toast.remove(); }, 5000);
        }
    }

    // ==================== CONFIRMACIÓN ====================

    var CONFIRM_VARIANTS = {
        primary: 'btn-primary',
        danger: 'btn-danger',
        warning: 'btn-warning',
        success: 'btn-success'
    };

    /**
     * Diálogo de confirmación con bootstrap.Modal. Sustituye a confirm().
     * Crea el modal en el DOM al vuelo y lo destruye al cerrarse.
     *
     *   if (await AdhocUtils.confirmDialog({ title: 'Eliminar', message: 'Se borra', variant: 'danger' })) { ... }
     *
     * @param {{title?:string,message?:string,confirmText?:string,cancelText?:string,variant?:string}} [opts]
     * @returns {Promise<boolean>}
     */
    function confirmDialog(opts) {
        var o = opts || {};
        var title = o.title || 'Confirmar';
        var message = o.message || 'Deseas continuar?';
        var confirmText = o.confirmText || 'Confirmar';
        var cancelText = o.cancelText || 'Cancelar';
        var btnClass = CONFIRM_VARIANTS[o.variant] || CONFIRM_VARIANTS.primary;

        return new Promise(function (resolve) {
            var modal = document.createElement('div');
            modal.className = 'modal fade';
            modal.setAttribute('tabindex', '-1');
            modal.setAttribute('aria-hidden', 'true');
            modal.innerHTML =
                '<div class="modal-dialog modal-dialog-centered">' +
                  '<div class="modal-content">' +
                    '<div class="modal-header">' +
                      '<h5 class="modal-title">' + escapeHtml(title) + '</h5>' +
                      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>' +
                    '</div>' +
                    '<div class="modal-body">' + escapeHtml(message) + '</div>' +
                    '<div class="modal-footer">' +
                      '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">' +
                        escapeHtml(cancelText) + '</button>' +
                      '<button type="button" class="btn ' + btnClass + '" data-adhoc-role="confirm">' +
                        escapeHtml(confirmText) + '</button>' +
                    '</div>' +
                  '</div>' +
                '</div>';

            // El modal se cuelga de <body> a propósito: fuera de cualquier
            // contenedor con transform, que rompería su position:fixed.
            document.body.appendChild(modal);

            if (!window.bootstrap || !window.bootstrap.Modal) {
                modal.remove();
                resolve(false);
                return;
            }

            var bsModal = window.bootstrap.Modal.getOrCreateInstance(modal);
            var answer = false;

            modal.querySelector('[data-adhoc-role="confirm"]').addEventListener('click', function () {
                answer = true;
                bsModal.hide();
            });
            modal.addEventListener('hidden.bs.modal', function () {
                modal.remove();
                resolve(answer);
            });

            bsModal.show();
        });
    }

    // ==================== ERRORES ====================

    /**
     * Extrae texto legible del cuerpo de error. El handler global del proyecto
     * (itcj2/main.py) responde {"error": <detail>, "status": N}, donde `detail`
     * puede ser un string o un objeto {error, message}. También se tolera
     * {"detail": ...} de FastAPI crudo, el array de validación de 422 y
     * {"message": ...}.
     * @param {*} payload
     * @returns {string}
     */
    function extractError(payload) {
        if (payload === null || payload === undefined) return 'Error desconocido';
        if (typeof payload === 'string') return payload || 'Error desconocido';

        var candidates = [payload.error, payload.detail, payload.message];
        for (var i = 0; i < candidates.length; i++) {
            var c = candidates[i];
            if (typeof c === 'string' && c.trim()) return c;
            if (Array.isArray(c) && c.length) {
                // 422 de FastAPI: detail es un array de errores de validación.
                var first = c[0];
                if (first && typeof first.msg === 'string') return first.msg;
                if (typeof first === 'string') return first;
            } else if (c && typeof c === 'object') {
                if (typeof c.message === 'string' && c.message.trim()) return c.message;
                if (typeof c.error === 'string' && c.error.trim()) return c.error;
            }
        }
        return 'Error desconocido';
    }

    // ==================== FETCH ====================

    /**
     * fetch + JSON. Lanza Error(mensaje legible) si la respuesta no es ok.
     * El error lleva `.status` y `.payload` para quien necesite el detalle.
     *
     * Una ruta que empieza por "/" y no es ya /api/... ni /adhoc/... se resuelve
     * contra /api/adhoc/v2, así los módulos escriben fetchJson('/documents').
     *
     * @param {string} url
     * @param {RequestInit} [options]
     * @returns {Promise<*>} el cuerpo JSON parseado
     */
    async function fetchJson(url, options) {
        var target = String(url || '');
        if (target.charAt(0) === '/' && target.indexOf('/api/') !== 0 && target.indexOf('/adhoc/') !== 0) {
            target = API_BASE + target;
        }

        var opts = options || {};
        var hasBody = opts.body !== undefined && opts.body !== null;
        var isFormData = (typeof FormData !== 'undefined') && (opts.body instanceof FormData);
        var headers = Object.assign({}, opts.headers);
        if (hasBody && !isFormData && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }

        var res = await fetch(target, Object.assign({}, opts, { headers: headers }));

        var payload = null;
        var text = await res.text();
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch (e) {
                payload = text;
            }
        }

        if (!res.ok) {
            var err = new Error(extractError(payload) || ('HTTP ' + res.status));
            err.status = res.status;
            err.payload = payload;
            throw err;
        }
        return payload;
    }

    // ==================== CONSTANTES JINJA → JS ====================

    /**
     * Lee el bloque <script type="application/json"> que emiten los templates
     * (plan 6.2: el único script inline permitido). Devuelve {} si falta o si el
     * JSON es inválido — nunca revienta la página.
     * @param {string} [id]
     * @returns {Object}
     */
    function pageData(id) {
        var el = document.getElementById(id || 'adhoc-page-data');
        if (!el) return {};
        try {
            return JSON.parse(el.textContent) || {};
        } catch (e) {
            console.error('[adhoc] page-data inválido:', e);
            return {};
        }
    }

    // ==================== INIT IDEMPOTENTE ====================

    var _readyCounter = 0;

    /**
     * Ejecuta `fn` en la carga inicial Y tras cada swap de HTMX
     * (htmx:afterSettle), que es cuando la navegación morph reemplaza el DOM.
     * La guarda por `dataset` evita enganchar listeners dos veces sobre el mismo
     * nodo cuando el morph conserva elementos.
     *
     *   AdhocUtils.onReady(function (root) { ... });
     *
     * @param {Function} fn recibe el elemento raíz (document.body o el target del swap)
     */
    function onReady(fn) {
        if (typeof fn !== 'function') return;
        var flag = 'adhocInit' + (++_readyCounter);

        function run(root) {
            var scope = root || document.body;
            if (!scope || !scope.dataset) return;
            if (scope.dataset[flag] === '1') return;   // ya inicializado en este nodo
            scope.dataset[flag] = '1';
            try {
                fn(scope);
            } catch (e) {
                console.error('[adhoc] error en onReady:', e);
            }
        }

        function bindHtmx() {
            document.body.addEventListener('htmx:afterSettle', function (evt) {
                var target = (evt && evt.target && evt.target.dataset) ? evt.target : document.body;
                run(target);
            });
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () {
                run(document.body);
                bindHtmx();
            });
        } else {
            run(document.body);
            bindHtmx();
        }
    }

    // ==================== EXPORT ====================

    window.AdhocUtils = {
        API_BASE: API_BASE,
        escapeHtml: escapeHtml,
        showToast: showToast,
        confirmDialog: confirmDialog,
        fetchJson: fetchJson,
        extractError: extractError,
        pageData: pageData,
        onReady: onReady
    };
})();
