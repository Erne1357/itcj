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

    // Este archivo se carga UNA vez, desde el <head> de base_adhoc.html, y ese
    // es el sitio que garantiza que no se ejecute dos veces: HTMX repone el
    // historial sobre `document.body`, asi que cualquier <script> de dentro del
    // <body> se vuelve a crear —y a ejecutar— en cada ATRAS.
    //
    // Esta guarda es el cinturon por si alguien lo devuelve al <body>: una
    // segunda ejecucion no debe SUSTITUIR a la primera. Si lo hiciera, el
    // `window.AdhocUtils` nuevo traeria su propio registro de modulos vacio
    // mientras los listeners de HTMX que siguen vivos son los de la copia
    // vieja, y los modulos que se registrasen a partir de ahi no se montarian
    // en ninguna navegacion posterior. Devolviendo el control aqui, la copia
    // que manda es siempre la primera: la que tiene los listeners.
    //
    // Mismo patron que ya usaban `reports/reports.js` y `reports/report-view.js`
    // (`if (window.AdhocReports) return;`), que son modulos de pagina y por
    // tanto SI viven dentro de la caja.
    if (window.AdhocUtils) return;

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
            // Respaldo por si la pagina no extiende el base. Lleva los mismos
            // atributos de region viva que el del shell, aunque creada asi puede
            // no anunciarse: un lector de pantalla observa las regiones que ya
            // existian al cargar. Por eso el sitio bueno es base_adhoc.html.
            el = document.createElement('div');
            el.id = TOAST_CONTAINER_ID;
            el.className = 'adhoc-toast-container';
            el.setAttribute('role', 'status');
            el.setAttribute('aria-live', 'polite');
            el.setAttribute('aria-atomic', 'false');
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
        // El anuncio lo da la region viva del contenedor, no cada aviso: dos
        // regiones anidadas hacen que algunos lectores lean el texto dos veces.
        // Solo lo que es un ERROR se marca como alerta, que es lo que lo saca
        // por delante de lo que el lector estuviera diciendo.
        if (style.css === 'adhoc-toast-error' || style.css === 'adhoc-toast-warning') {
            toast.setAttribute('role', 'alert');
        }
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
    //: Todo lo que puede recibir el foco dentro de un dialogo.
    var ENFOCABLES = [
        'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type=hidden])',
        'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    /** Los enfocables VISIBLES de `el`, en orden de tabulacion. */
    function enfocables(el) {
        var todos = el.querySelectorAll(ENFOCABLES);
        var out = [];
        for (var i = 0; i < todos.length; i++) {
            var n = todos[i];
            if (n.offsetWidth || n.offsetHeight || n.getClientRects().length) out.push(n);
        }
        return out;
    }

    function openModal(target) {
        var el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return null;

        // A quien hay que devolverle el foco al cerrar. Sin esto, cerrar un
        // dialogo con Escape dejaba el foco en el <body> y el siguiente Tab
        // empezaba desde el principio de la pagina: quien navega con teclado
        // tenia que recorrer la barra y la tabla entera para volver al boton que
        // acababa de pulsar. Los modales de Bootstrap si lo hacen, asi que
        // conviviendo las dos familias habia dos comportamientos de teclado.
        el._adhocFocoPrevio = document.activeElement;

        el.classList.add('is-open');
        el.removeAttribute('aria-hidden');
        document.body.classList.add('adhoc-modal-open');

        var candidatos = enfocables(el);
        var primero = el.querySelector('[autofocus]') || candidatos[0];
        if (primero) {
            try { primero.focus(); } catch (e) { /* sin foco, da igual */ }
        }
        return el;
    }

    /**
     * Cierra un overlay `.adhoc-modal` y devuelve el foco a donde estaba.
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
        var previo = el._adhocFocoPrevio;
        el._adhocFocoPrevio = null;
        // Solo si sigue en el documento: el intercambio de HTMX pudo llevarselo.
        if (previo && previo.focus && document.contains(previo)) {
            try { previo.focus(); } catch (e) { /* da igual */ }
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
     * Cierre de modales propios (botón, velo y Escape) y botón "Salir" de la
     * cabecera. Al colgar de `document` no hay que re-enganchar nada tras un
     * swap de HTMX. Lo llama `arrancar()`, que es quien pone la guarda de
     * "una sola vez por documento".
     */
    function bindGlobal() {
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
            var abiertos = document.querySelectorAll('.adhoc-modal.is-open');
            if (!abiertos.length) return;
            var dialogo = abiertos[abiertos.length - 1];

            if (evt.key === 'Escape') {
                closeModal(dialogo);
                return;
            }

            // Trampa de foco. Sin ella, tabular dentro de un dialogo se salia por
            // detras a la pagina de abajo —que sigue ahi, solo tapada por el
            // velo— y a partir de ahi el usuario de teclado estaba interactuando
            // con controles que no puede ver. Los modales de Bootstrap si la
            // traen, asi que las dos familias de dialogo se comportaban distinto.
            if (evt.key !== 'Tab') return;
            var lista = enfocables(dialogo);
            if (!lista.length) return;
            var primero = lista[0];
            var ultimo = lista[lista.length - 1];
            var activo = document.activeElement;

            if (evt.shiftKey && (activo === primero || !dialogo.contains(activo))) {
                evt.preventDefault();
                ultimo.focus();
            } else if (!evt.shiftKey && activo === ultimo) {
                evt.preventDefault();
                primero.focus();
            }
        });
    }

    // ==================== NAVEGACION ====================

    /**
     * Navega a una pantalla de la app SIN recargar el documento.
     *
     *   AdhocUtils.navigate('/adhoc/panel/usuarios');
     *
     * Es lo que hay que usar en lugar de `window.location.href` para cualquier
     * ruta interna. Los cinco saltos que habia en los modulos (fila de un ano ->
     * su tablero, incidencia -> sus tareas, tarea -> asignaciones, asignaciones
     * -> volver, y la recarga del tablero tras una accion de flujo) encadenaban
     * recargas duras dentro de una app que por lo demas navega con morph: el
     * ciclo tarea -> asignacion -> vuelta eran TRES seguidas.
     *
     * COMO: no llama a `htmx.ajax`, sino que fabrica un <a> real dentro de la
     * caja, deja que HTMX lo procese y le hace clic. Asi la navegacion recorre
     * EXACTAMENTE el mismo camino que la de un enlace de la plantilla —el mismo
     * target, el mismo `morph:outerHTML`, el mismo empujon al historial y la
     * misma fusion del <head> por head-support— en vez de una copia paralela que
     * habria que mantener en sintonia. Sin HTMX (o sin la caja) cae en una
     * navegacion normal, que sigue funcionando.
     *
     * @param {string} url ruta interna
     */
    function navigate(url) {
        var destino = String(url || '');
        var raiz = document.getElementById('adhoc-root');
        if (!destino) return;
        if (!window.htmx || !raiz) {
            window.location.href = destino;
            return;
        }
        var a = document.createElement('a');
        a.href = destino;
        a.hidden = true;                       // adhoc.css oculta todo [hidden]
        a.setAttribute('data-adhoc-nav', '');
        raiz.appendChild(a);
        window.htmx.process(a);                // hereda hx-boost/target/swap de la caja
        a.click();
        // El ancla se retira cuando la peticion TERMINA, no en el siguiente tick.
        // HTMX emite `htmx:afterRequest` sobre el elemento que la lanzo, y un
        // nodo ya desconectado no burbujea hasta `document`: el indicador de
        // carga se quedaba encendido para siempre porque su contador nunca
        // bajaba. Si el intercambio sale bien, el ancla se va con el (es hija de
        // la caja); esto cubre el caso en que la peticion falla.
        a.addEventListener('htmx:afterRequest', function () {
            if (a.parentNode) a.parentNode.removeChild(a);
        });
    }

    /**
     * Da de alta ante HTMX los enlaces que un modulo acaba de inyectar.
     *
     * HTMX solo boostea lo que ha procesado, y no ve nada de lo que se mete con
     * `innerHTML` o `appendChild`. Un modulo que pinte un <a> a una ruta interna
     * tiene que llamar a esto con el contenedor; si no, ese enlace recargara la
     * pagina entera. Los enlaces de DESCARGA no deben pasar por aqui (o hay que
     * marcarlos con hx-boost="false"): tienen que ser navegaciones de verdad.
     *
     * @param {Element} root contenedor recien pintado
     */
    function enlazar(root) {
        if (root && window.htmx) window.htmx.process(root);
    }

    // ==================== INDICADOR DE CARGA ====================

    /*
     * Antes no habia ninguno. Mientras la navegacion recargaba el documento, el
     * propio parpadeo del navegador hacia de senal; al quitarlo, el usuario se
     * quedo sin saber si su clic habia hecho algo.
     *
     * El retardo NO esta aqui sino en el CSS (`animation-delay`), y es
     * deliberado: la clase se pone en cuanto arranca la peticion, pero la barra
     * no se pinta hasta pasado ese retardo. En la red del ITCJ las pantallas
     * llegan muy por debajo de ese umbral, asi que en el uso normal el
     * indicador NO llega a verse nunca — solo aparece cuando de verdad hay
     * espera. Un indicador que parpadea en cada clic estorba mas de lo que
     * informa.
     */
    var _peticiones = 0;

    function bindIndicador() {
        document.addEventListener('htmx:beforeRequest', function () {
            _peticiones++;
            document.body.classList.add('adhoc-loading');
        });
        function fin() {
            _peticiones = Math.max(0, _peticiones - 1);
            if (_peticiones === 0) document.body.classList.remove('adhoc-loading');
        }
        document.addEventListener('htmx:afterRequest', fin);
        document.addEventListener('htmx:sendError', fin);
        document.addEventListener('htmx:timeout', fin);
        document.addEventListener('htmx:responseError', fin);
    }

    // ==================== NAVEGACION QUE FALLA ====================

    /*
     * Una navegacion boosted que responde 4xx/5xx no intercambia NADA. El
     * `hx-select="#adhoc-root"` de la caja busca esa caja en la respuesta, y una
     * pagina de error no la trae: HTMX descarta la respuesta y deja la pantalla
     * exactamente como estaba. Hasta ahora lo unico que escuchaba
     * `htmx:responseError` era el contador de la barra de progreso, asi que el
     * usuario sin permiso para una pantalla pulsaba el enlace y NO PASABA NADA:
     * ni error, ni pantalla nueva, ni pista de que el clic hubiera llegado al
     * servidor. Un control que no responde se lee como una app rota, y encima
     * invita a volver a pulsarlo.
     *
     * El aviso dice que fallo, en terminos de lo que el usuario intentaba hacer
     * ("abrir la pantalla"), y arrastra el codigo entre parentesis para que
     * quien reporte la incidencia pueda decirlo. No lleva nada del cuerpo de la
     * respuesta: en una navegacion es HTML, no el JSON de la API.
     */

    var AVISOS_HTTP = {
        401: 'Tu sesión expiró. Vuelve a entrar para seguir trabajando.',
        403: 'No tienes permiso para abrir esa pantalla. Pídeselo al administrador de Calidad.',
        404: 'Esa pantalla ya no existe.'
    };

    /**
     * Texto del aviso para un fallo de navegación.
     * @param {*} status código HTTP de la respuesta
     * @returns {string}
     */
    function avisoDeNavegacion(status) {
        var codigo = Number(status) || 0;
        var texto = AVISOS_HTTP[codigo];
        if (!texto) {
            texto = (codigo >= 500)
                ? 'Falló el servidor al abrir esa pantalla. Vuelve a intentarlo; si sigue igual, avisa a Sistemas.'
                : 'No se pudo abrir esa pantalla.';
        }
        return texto + ' (error ' + (codigo || 'sin código') + ')';
    }

    /** Avisos de las peticiones de HTMX que no llegan a intercambiar nada. */
    function bindAvisosDeRed() {
        document.addEventListener('htmx:responseError', function (evt) {
            var xhr = (evt && evt.detail) ? evt.detail.xhr : null;
            showToast(avisoDeNavegacion(xhr && xhr.status), 'error');
        });

        // Mismo agujero por el otro lado: sin red la peticion ni sale, y el
        // clic tampoco hacia nada.
        document.addEventListener('htmx:sendError', function () {
            showToast('No se pudo contactar con el servidor. Revisa tu conexión y vuelve a intentarlo.', 'error');
        });
    }

    // ==================== CICLO DE VIDA DE LOS MODULOS ====================

    /*
     * El problema que resuelve este bloque
     * ------------------------------------
     * El bloque `extra_js` vive DENTRO de #adhoc-root, la caja que HTMX
     * intercambia, asi que los modulos de seccion entran y salen con la
     * pantalla. Idiomorph empareja nodo a nodo, y para un <script> el
     * emparejamiento es por `id` si lo hay y por POSICION si no. Sin `id`
     * pasaba esto:
     *
     *   pantalla A (1 modulo) -> pantalla B (1 modulo)
     *      idiomorph reescribe el `src` del mismo nodo, y un <script> ya
     *      ejecutado NO se vuelve a ejecutar porque le cambien el src: B se
     *      pinta entera y se queda muerta.
     *   pantalla sin modulos -> pantalla B
     *      el <script> entra como nodo nuevo y SI se ejecuta.
     *
     * O sea: el mismo par de pantallas se comportaba distinto segun por donde
     * hubieras pasado antes. Con id="adhoc-mod-..." en cada <script> el
     * emparejamiento es por identidad y los dos caminos coinciden: si el modulo
     * cambia, el nodo se sustituye y se ejecuta; si es el mismo (los cinco
     * catalogos comparten shared/catalog-crud.js), el nodo se conserva y NO se
     * re-ejecuta -- para eso esta `onReady`, que vuelve a correr en cada
     * `htmx:afterSettle` y en cada `htmx:historyRestore`.
     *
     * Dos consecuencias que hay que sostener a mano:
     *
     *   1. Un modulo puede ejecutarse VARIAS veces por sesion. Todo registro se
     *      indexa por el modulo que lo hizo (`document.currentScript`), asi que
     *      volver a registrarse SUSTITUYE en vez de acumular. Antes cada
     *      re-ejecucion anadia un callback que no se retiraba nunca y
     *      `htmx:afterSettle` acababa recorriendo callbacks de pantallas por
     *      las que ya no estas.
     *   2. Un modulo puede DESAPARECER sin avisar. Lo que haya dejado abierto
     *      (un modal, un temporizador, una peticion en vuelo) se recoge en
     *      `onTeardown`, que corre en `htmx:beforeSwap`.
     */

    var _registros = Object.create(null);   // clave de modulo -> {ready, teardown, marca}
    var _orden = [];                        // el orden de registro, que importa
    var _htmxBound = false;
    // Generacion de intercambio. La guarda de idempotencia se ata a ESTO y no al
    // nodo: #adhoc-root sobrevive al intercambio (idiomorph lo morphea, no lo
    // sustituye), asi que una marca fija haria que el callback corriera una sola
    // vez en toda la sesion.
    var _generacion = 0;

    /**
     * Identidad del modulo que esta ejecutandose. `document.currentScript` solo
     * vale durante la ejecucion SINCRONA del script, que es justo cuando los
     * modulos llaman a onReady/onTeardown desde su IIFE.
     * @returns {string}
     */
    function claveDeModulo() {
        var sc = document.currentScript;
        if (sc) {
            if (sc.id) return sc.id;
            var src = sc.getAttribute('src');
            if (src) return src.split('?')[0];
        }
        // Fuera de la ejecucion sincrona no hay forma de saberlo: se le da una
        // clave propia para no pisar el registro de nadie.
        return 'anon-' + (_orden.length + 1);
    }

    function registro(clave) {
        if (!_registros[clave]) {
            _registros[clave] = {
                ready: [], teardown: [], marca: 'r' + _orden.length, nodo: undefined
            };
            _orden.push(clave);
        }
        var reg = _registros[clave];

        // El registro de un modulo se SUSTITUYE cuando el modulo se re-ejecuta,
        // no se acumula. Es la promesa del comentario de arriba y hasta aqui no
        // la cumplia nadie: `reg.ready.push(run)` iba anadiendo.
        //
        // Los <script> de `{% block extra_js %}` viven DENTRO de #adhoc-root y
        // por tanto dentro del elemento de historial, asi que cada ATRAS los
        // vuelve a crear y a ejecutar. Antes eso no se notaba porque este
        // archivo tambien se re-ejecutaba y el registro nacia vacio otra vez;
        // ahora que vive en el <head> el registro es el mismo de toda la sesion,
        // y sin esto la lista de callbacks de una pantalla crecia en uno por
        // cada ATRAS —cada `montar()` recorriendo N copias del mismo init, con N
        // marcas de idempotencia distintas escritas sobre el mismo nodo—.
        //
        // Se distingue "ejecucion nueva" de "el modulo llama a onReady dos veces
        // seguidas" por la IDENTIDAD del <script>: `document.currentScript` es
        // un nodo distinto en cada ejecucion y el mismo dentro de una. Fuera de
        // la ejecucion sincrona es null, y ahi `claveDeModulo()` ya devuelve una
        // clave propia (`anon-N`), asi que ese caso no entra por aqui.
        var nodo = document.currentScript || null;
        if (reg.nodo !== nodo) {
            reg.nodo = nodo;
            reg.ready.length = 0;
            reg.teardown.length = 0;
        }
        return reg;
    }

    /**
     * Ejecuta `fn` en la carga inicial Y tras cada intercambio de HTMX.
     *
     *   AdhocUtils.onReady(function (root) { ... });
     *   AdhocUtils.onReady('[data-adhoc-catalog]', function (root) { ... });
     *
     * Con selector, el callback SOLO corre si ese enganche existe en el DOM: un
     * modulo cuyo <script> se conserva entre pantallas (los catalogos comparten
     * el suyo) deja de correr en pantallas que no son la suya.
     *
     * Se ejecuta una vez por nodo y por generacion de intercambio. Enganchar dos
     * veces el MISMO elemento sigue siendo responsabilidad del modulo (guarda
     * `dataset.*Bound` sobre ese elemento). Esa guarda no hay que cambiarla: el
     * morph la retira sola en cada navegacion, y en el ATRAS —donde vuelve
     * puesta desde el cache del historial— la retira `limpiarGuardas()`.
     *
     * @param {string|Function} selector enganche obligatorio, o el propio callback
     * @param {Function} [fn] callback; recibe el elemento raiz
     */
    function onReady(selector, fn) {
        var enganche = null;
        if (typeof selector === 'function') {
            fn = selector;
        } else {
            enganche = selector;
        }
        if (typeof fn !== 'function') return;

        var reg = registro(claveDeModulo());
        var flag = 'adhocInit' + reg.marca + '_' + reg.ready.length;

        function run(root) {
            var scope = root || document.body;
            if (!scope || !scope.dataset) return;
            if (enganche) {
                var hay = (scope.matches && scope.matches(enganche)) || scope.querySelector(enganche);
                if (!hay) return;
            }
            var marca = String(_generacion);
            if (scope.dataset[flag] === marca) return;   // ya corrio en esta generacion
            scope.dataset[flag] = marca;
            try {
                fn(scope);
            } catch (e) {
                console.error('[adhoc] error en onReady:', e);
            }
        }

        reg.ready.push(run);
        bindHtmxOnce();

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () { run(document.body); });
        } else {
            run(document.body);
        }
    }

    /**
     * Registra el desmontaje del modulo. Corre en `htmx:beforeSwap`, ANTES de
     * que el intercambio se lleve el DOM de la pantalla actual, y tambien en
     * `htmx:historyRestore`, que es el ATRAS del navegador.
     *
     *   AdhocUtils.onTeardown(function () { clearTimeout(t); controlador.abort(); });
     *
     * Aqui va lo que sobrevive al DOM: temporizadores, `AbortController`,
     * intervalos, suscripciones. Lo que este colgado de un nodo que se va no
     * hace falta recogerlo.
     * @param {Function} fn
     */
    function onTeardown(fn) {
        if (typeof fn !== 'function') return;
        registro(claveDeModulo()).teardown.push(fn);
        bindHtmxOnce();
    }

    /** Estado de los registros. Para las pruebas; la app no lo usa. */
    function debugRegistros() {
        return _orden.map(function (clave) {
            return {
                clave: clave,
                ready: _registros[clave].ready.length,
                teardown: _registros[clave].teardown.length
            };
        });
    }

    /**
     * Deja el `<body>` como estaba: sin clases de bloqueo, sin el
     * `overflow`/`padding-right` en linea que pone Bootstrap y sin velos
     * huerfanos.
     *
     * Hace falta porque el nodo del modal se va con el intercambio y su
     * `closeModal()` (o el `hide()` de Bootstrap) ya no llega a correr: la
     * pantalla siguiente aparecia sin poder desplazarse.
     */
    function limpiarModales() {
        var abiertos = document.querySelectorAll('.adhoc-modal.is-open');
        for (var i = 0; i < abiertos.length; i++) closeModal(abiertos[i]);

        if (window.bootstrap && window.bootstrap.Modal) {
            var bs = document.querySelectorAll('.modal.show');
            for (var j = 0; j < bs.length; j++) {
                try {
                    var inst = window.bootstrap.Modal.getInstance(bs[j]);
                    if (inst) inst.hide();
                } catch (e) { /* el nodo ya no existe: da igual */ }
                bs[j].classList.remove('show');
                bs[j].style.removeProperty('display');
                bs[j].setAttribute('aria-hidden', 'true');
            }
        }

        var velos = document.querySelectorAll('.modal-backdrop');
        for (var k = 0; k < velos.length; k++) velos[k].remove();

        document.body.classList.remove('adhoc-modal-open');
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }

    //: La marca con la que un modulo se declara montado sobre un nodo. Quince
    //: modulos la escriben con esta forma exacta (`root.dataset.adhocXxxBound`,
    //: que en el HTML es `data-adhoc-xxx-bound`): documents, documents-panel,
    //: flows, flow-steps, board, tracking, years, color-catalog, mail, users,
    //: catalog-crud, user-picker, tasks, assignments y work-items. Todos ellos
    //: se registran ademas con `onReady`, que es lo que los vuelve a levantar.
    var RE_GUARDA = /^data-adhoc-.+-bound$/;

    /**
     * Borra esas marcas del arbol indicado.
     *
     * Solo tiene sentido llamarla cuando el DOM se ha REPUESTO desde fuera del
     * ciclo normal —es decir, al restaurar del historial—, y ahi es obligatoria:
     * ver el comentario de `htmx:historyRestore` en `bindHtmxOnce`.
     *
     * No hay selector CSS que case por NOMBRE de atributo, asi que se recorre el
     * arbol mirando los atributos de cada nodo. Es un paseo por unos pocos miles
     * de elementos y ocurre solo al pulsar ATRAS o ADELANTE.
     *
     * Nunca toca `<html>`: las banderas de "una sola vez por documento"
     * (`data-adhoc-global-bound`, `data-adhoc-tasks-htmx`...) viven ahi
     * precisamente porque ningun intercambio ni ninguna restauracion las alcanza,
     * y borrarlas duplicaria listeners globales.
     *
     * @param {Element} [raiz] por defecto `<body>`, que es lo que repone HTMX
     * @returns {number} cuantas marcas se quitaron
     */
    function limpiarGuardas(raiz) {
        var caja = raiz || document.body;
        if (!caja || !caja.querySelectorAll) return 0;
        var nodos = caja.querySelectorAll('*');
        var quitadas = 0;
        for (var i = -1; i < nodos.length; i++) {
            var nodo = (i < 0) ? caja : nodos[i];       // la propia raiz tambien
            var attrs = nodo.attributes;
            if (!attrs) continue;
            // Hacia atras: `attributes` es una lista VIVA y quitar uno la acorta.
            for (var j = attrs.length - 1; j >= 0; j--) {
                var nombre = attrs[j].name;
                if (RE_GUARDA.test(nombre)) {
                    nodo.removeAttribute(nombre);
                    quitadas++;
                }
            }
        }
        return quitadas;
    }

    /**
     * Un unico par de listeners para todos los modulos, sobre `document`, que
     * sobrevive a cualquier intercambio.
     */
    function bindHtmxOnce() {
        // Bandera de MODULO, y ahora si es suficiente. Lo fue siempre en
        // intencion y nunca en la practica: mientras este archivo se cargaba
        // desde el <body> —dentro del elemento de historial de HTMX— cada ATRAS
        // creaba una copia entera del modulo con sus variables a cero, la
        // bandera nacia en false y se sumaba OTRO juego de
        // `beforeSwap`/`afterSettle`/`historyRestore` sobre `document`. Medido:
        // tres idas y vueltas dejaban cuatro registros de cada uno, cuatro
        // contadores `_generacion` independientes y `limpiarModales()` corriendo
        // cuatro veces por navegacion, sin techo.
        //
        // Las dos patas que lo sostienen hoy, en este orden: el <script> vive en
        // el <head> (ver base_adhoc.html), asi que no hay re-ejecucion; y si
        // alguien lo devolviera al <body>, el `if (window.AdhocUtils) return;`
        // del principio del archivo corta la copia nueva antes de llegar aqui.
        // No se cuelga de `<html>` a proposito: una guarda a nivel de documento
        // frenaria a la copia nueva DESPUES de que se hubiera adueniado de
        // `window.AdhocUtils`, dejandola sin listeners y con un registro de
        // modulos que nadie monta.
        if (_htmxBound) return;
        _htmxBound = true;

        function desmontar() {
            limpiarModales();
            for (var i = 0; i < _orden.length; i++) {
                var lista = _registros[_orden[i]].teardown;
                for (var j = 0; j < lista.length; j++) {
                    try { lista[j](); } catch (e) { console.error('[adhoc] error en onTeardown:', e); }
                }
            }
        }

        /**
         * Vuelve a correr los `onReady` de todos los modulos registrados.
         * @param {Element} [target] raiz del intercambio
         */
        function montar(target) {
            _generacion++;
            var scope = (target && target.dataset) ? target : document.body;
            for (var i = 0; i < _orden.length; i++) {
                var lista = _registros[_orden[i]].ready;
                for (var j = 0; j < lista.length; j++) {
                    lista[j](scope);
                    if (scope !== document.body) lista[j](document.body);
                }
            }
        }

        document.addEventListener('htmx:beforeSwap', desmontar);
        document.addEventListener('htmx:afterSettle', function (evt) {
            montar(evt && evt.target);
        });

        // ── EL BOTON ATRAS ──────────────────────────────────────────────────
        //
        // El historial de HTMX no pasa por `beforeSwap` ni por `afterSettle`:
        // `restoreHistory()` mete el HTML del cache con `swapInnerHTML` y emite
        // un unico evento, `htmx:historyRestore`. Por eso aqui se desmonta Y se
        // vuelve a MONTAR — es lo mismo que hacen las otras dos apps con morph
        // del repo, que repiten su `activate()` en los dos eventos
        // (helpdesk/static/js/shared/base.js, core/static/js/config/shared/config-page.js).
        //
        // Mientras esto solo desmontaba, volver ATRAS dejaba muertas TODAS las
        // listas: la pantalla se pintaba entera —viene del cache— pero ningun
        // modulo arrancaba, asi que no habia filtros, ni paginacion, ni un solo
        // boton que abriera. El desmontaje si hacia falta y se conserva: sin el,
        // abrir un modal y darle a atras dejaba el `<body>` con la clase de
        // bloqueo y la pantalla restaurada sin poder desplazarse.
        //
        // Y antes de montar hay que BORRAR LAS MARCAS de los modulos. El cache
        // de historial es `body.cloneNode(true).innerHTML` guardado en
        // localStorage, asi que se lleva tal cual los `data-adhoc-*-bound` con
        // los que cada modulo se declara montado sobre un nodo. Al restaurar
        // vuelven puestos sobre nodos RECIEN CREADOS, cuyos objetos JS (la
        // instancia, el AbortController, los listeners) ya no existen: la marca
        // miente y el `init()` del modulo se cree hecho. Se limpia aqui, y no al
        // guardar el cache, por dos razones: es el unico momento que no depende
        // de que HTMX llegue a emitir `htmx:beforeHistorySave`, y cura tambien
        // las entradas que ya estaban en localStorage desde antes de este
        // arreglo (el cache sobrevive a la recarga y al despliegue).
        //
        // Las dos mitades son necesarias: HTMX re-ejecuta los <script> del HTML
        // restaurado (`htmx.config.allowScriptTags`), asi que los modulos SI
        // vuelven a llamar a su `init()` al restaurar... y salen por la marca.
        //
        // `limpiarGuardas` corre UNA sola vez por restauracion, con la bandera
        // puesta en el propio evento. Hoy solo hay un juego de listeners —el
        // archivo se carga desde el <head> y no se re-ejecuta—, asi que la
        // bandera es redundante; se conserva porque lo que protege es barato y
        // el fallo que evitaba era feo: con dos oyentes, una segunda limpieza
        // DESPUES de que la primera ya monto volveria a abrir la puerta y el
        // modulo se montaria dos veces sobre el mismo nodo.
        document.addEventListener('htmx:historyRestore', function (evt) {
            desmontar();
            if (!evt || !evt._adhocGuardasLimpias) {
                if (evt) evt._adhocGuardasLimpias = true;
                limpiarGuardas();
            }
            montar(document.body);
        });
    }

    /**
     * Los listeners que se cuelgan de `document` y valen para toda la sesion.
     *
     * La guarda vive en el dataset de `<html>`, que es el unico nodo que no
     * entra ni en el intercambio ni en la restauracion del historial. Se puso
     * cuando este archivo se cargaba desde el `<body>` y cada ATRAS creaba una
     * copia nueva del modulo con las variables a cero: una bandera de modulo no
     * lo veia y cada ATRAS sumaba otro juego de listeners globales (otro cierre
     * de modal, otro aviso de error por cada fallo).
     *
     * Desde que el <script> vive en el `<head>` no hay copias, asi que valdria
     * una bandera de modulo; se deja en `<html>` porque tambien cubre el caso de
     * dos <script> distintos apuntando al mismo archivo, y no cuesta nada.
     */
    function arrancar() {
        if (document.documentElement.dataset.adhocGlobalBound === '1') return;
        document.documentElement.dataset.adhocGlobalBound = '1';
        bindGlobal();
        bindIndicador();
        bindAvisosDeRed();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', arrancar);
    } else {
        arrancar();
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
        onReady: onReady,
        onTeardown: onTeardown,
        navigate: navigate,
        enlazar: enlazar,
        debugRegistros: debugRegistros
    };
})();
