/**
 * adhoc-utils.js — utilidades compartidas de Calidad (app `adhoc`).
 *
 * Módulo IIFE: expone SOLO `window.AdhocUtils`. Ninguna función interna es global
 * (el legacy dejaba 28 clases ES6 sueltas en el scope global).
 *
 * PROHIBIDO en toda la app: alert(), confirm(), prompt(). Usa showToast() y
 * confirmDialog(), que pintan el overlay propio (el del legacy) y no bloquean
 * el hilo. Desde el porte visual este archivo NO depende de Bootstrap: el
 * diálogo, el toast y la apertura/cierre de modales son propios.
 */
(function () {
    'use strict';

    var API_BASE = '/api/adhoc/v2';
    var TOAST_CONTAINER_ID = 'adhoc-toast-container';
    var LOADER_ID = 'adhoc-loader';
    var LOGOUT_URL = '/api/core/v2/auth/logout';
    var LOGIN_URL = '/itcj/login';

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
            el.className = 'adhoc-toast-container';
            document.body.appendChild(el);
        }
        return el;
    }

    var TOAST_STYLE = {
        success: { css: 'adhoc-toast-success', icon: 'fa-solid fa-circle-check' },
        error:   { css: 'adhoc-toast-error',   icon: 'fa-solid fa-circle-exclamation' },
        danger:  { css: 'adhoc-toast-error',   icon: 'fa-solid fa-circle-exclamation' },
        warning: { css: 'adhoc-toast-warning', icon: 'fa-solid fa-triangle-exclamation' },
        info:    { css: 'adhoc-toast-info',    icon: 'fa-solid fa-circle-info' }
    };

    /**
     * Muestra un aviso flotante. Crea el contenedor si no existe.
     * @param {string} message  texto plano (se escapa)
     * @param {string} [type]   success | error | warning | info
     */
    function showToast(message, type) {
        var style = TOAST_STYLE[type] || TOAST_STYLE.success;
        var container = toastContainer();

        var toast = document.createElement('div');
        toast.className = 'adhoc-toast ' + style.css;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.innerHTML =
            '<i class="' + style.icon + '"></i>' +
            '<span>' + escapeHtml(message) + '</span>';

        container.appendChild(toast);
        // Un frame de retraso para que la transición de entrada se vea.
        requestAnimationFrame(function () { toast.classList.add('is-visible'); });

        setTimeout(function () {
            toast.classList.remove('is-visible');
            setTimeout(function () { toast.remove(); }, 250);
        }, 5000);
    }

    // ==================== MODALES ====================

    /**
     * Abre un overlay `.adhoc-modal`. Sustituye a bootstrap.Modal para todo lo
     * que ya está migrado; los modales de sección que aún llevan el markup
     * `modal fade` los sigue abriendo bootstrap.Modal (mismo aspecto: adhoc.css
     * viste las dos familias de clases igual).
     * @param {HTMLElement|string} target elemento o id
     * @returns {HTMLElement|null}
     */
    function openModal(target) {
        var el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return null;
        el.classList.add('is-open');
        el.removeAttribute('aria-hidden');
        document.body.classList.add('adhoc-modal-open');
        var focusable = el.querySelector('[autofocus], input, select, textarea, button');
        if (focusable) {
            try { focusable.focus(); } catch (e) { /* sin foco, da igual */ }
        }
        return el;
    }

    /**
     * Cierra un overlay `.adhoc-modal`.
     * @param {HTMLElement|string} target elemento o id
     */
    function closeModal(target) {
        var el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return;
        el.classList.remove('is-open');
        el.setAttribute('aria-hidden', 'true');
        if (!document.querySelector('.adhoc-modal.is-open')) {
            document.body.classList.remove('adhoc-modal-open');
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
     * Diálogo de confirmación. Sustituye a confirm(). Crea el overlay al vuelo
     * y lo destruye al cerrarse. Misma firma de siempre.
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
            modal.className = 'adhoc-modal';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.innerHTML =
                '<div class="adhoc-modal-dialog">' +
                  '<div class="adhoc-modal-content">' +
                    '<div class="adhoc-modal-header">' +
                      '<h2 class="adhoc-modal-title">' + escapeHtml(title) + '</h2>' +
                      '<button type="button" class="btn-close" data-adhoc-role="cancel" aria-label="Cerrar"></button>' +
                    '</div>' +
                    '<div class="adhoc-modal-body">' + escapeHtml(message) + '</div>' +
                    '<div class="adhoc-modal-footer">' +
                      '<button type="button" class="btn btn-secondary" data-adhoc-role="cancel">' +
                        escapeHtml(cancelText) + '</button>' +
                      '<button type="button" class="btn ' + btnClass + '" data-adhoc-role="confirm">' +
                        escapeHtml(confirmText) + '</button>' +
                    '</div>' +
                  '</div>' +
                '</div>';

            // El overlay se cuelga de <body> a propósito: fuera de cualquier
            // contenedor con transform, que rompería su position:fixed.
            document.body.appendChild(modal);

            function finish(answer) {
                closeModal(modal);
                modal.remove();
                document.removeEventListener('keydown', onKey);
                resolve(answer);
            }

            function onKey(evt) {
                if (evt.key === 'Escape') finish(false);
            }

            modal.addEventListener('click', function (evt) {
                var role = evt.target.closest ? evt.target.closest('[data-adhoc-role]') : null;
                if (role) {
                    finish(role.getAttribute('data-adhoc-role') === 'confirm');
                    return;
                }
                if (evt.target === modal) finish(false);   // clic en el velo
            });
            document.addEventListener('keydown', onKey);

            openModal(modal);
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

    // ==================== SALIR ====================

    /**
     * Cierra la sesión con el overlay de engranes del legacy y manda al login.
     * El botón vive en la cabecera del base (`[data-adhoc-logout]`), así que el
     * listener es delegado: sobrevive a los swaps de HTMX.
     */
    async function logout() {
        var loader = document.getElementById(LOADER_ID);
        if (loader) loader.classList.add('is-visible');
        try {
            await fetch(LOGOUT_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin'
            });
        } catch (e) {
            console.error('[adhoc] error de red al cerrar sesión:', e);
        }
        window.location.href = LOGIN_URL;
    }

    // ==================== LISTENERS GLOBALES ====================

    /**
     * Se instalan UNA sola vez sobre `document`: cierre de modales propios
     * (botón, velo y Escape) y el botón "Salir" de la cabecera. Al colgar de
     * `document` no hay que re-enganchar nada tras un swap de HTMX.
     */
    function bindGlobal() {
        if (document.documentElement.dataset.adhocGlobalBound === '1') return;
        document.documentElement.dataset.adhocGlobalBound = '1';

        document.addEventListener('click', function (evt) {
            var t = evt.target;
            if (!t || !t.closest) return;

            if (t.closest('[data-adhoc-logout]')) {
                evt.preventDefault();
                logout();
                return;
            }

            var closer = t.closest('[data-adhoc-modal-close]');
            if (closer) {
                evt.preventDefault();
                closeModal(closer.closest('.adhoc-modal'));
                return;
            }

            // Clic en el velo (el overlay en sí, no su diálogo).
            if (t.classList && t.classList.contains('adhoc-modal')) {
                closeModal(t);
            }
        });

        document.addEventListener('keydown', function (evt) {
            if (evt.key !== 'Escape') return;
            var open = document.querySelectorAll('.adhoc-modal.is-open');
            if (open.length) closeModal(open[open.length - 1]);
        });
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindGlobal);
    } else {
        bindGlobal();
    }

    // ==================== EXPORT ====================

    window.AdhocUtils = {
        API_BASE: API_BASE,
        escapeHtml: escapeHtml,
        showToast: showToast,
        confirmDialog: confirmDialog,
        openModal: openModal,
        closeModal: closeModal,
        logout: logout,
        fetchJson: fetchJson,
        extractError: extractError,
        pageData: pageData,
        onReady: onReady
    };
})();
