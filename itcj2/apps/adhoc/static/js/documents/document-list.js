/**
 * documents/document-list.js — tabla de documentos filtrada y paginada EN EL
 * SERVIDOR. Base común de /adhoc/documentos y /adhoc/documentos/panel.
 *
 * Expone SOLO `window.AdhocDocumentList` (IIFE, sin globales sueltas).
 *
 * POR QUÉ EXISTE
 * --------------
 * Las dos pantallas de documentos del legacy repetían el mismo filtrado a mano
 * con distinto mapa de índices (`documents.js:8-17` y
 * `advanced_documents.js:118`), y las dos se rompían al añadir una columna.
 * Aquí la consulta, la paginación y los listeners viven una sola vez; cada
 * pantalla aporta únicamente cómo se pinta una fila (`buildRow`).
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   GET /api/adhoc/v2/documents?page&per_page&q&status&category_id&area_id
 *                              &process_id&classification_id
 *   → {success, data: [...], total, page, per_page, total_pages}
 *   error → {"error": "texto", "status": N}   (lo traduce AdhocUtils.fetchJson)
 *
 * MARCADO QUE CONSUME
 * -------------------
 *   [data-adhoc-doc-filter="q|status|category_id|…"]   inputs y selects
 *   [data-adhoc-doc-filter] sobre <input type="checkbox">, con
 *       [data-adhoc-checked-value] / [data-adhoc-unchecked-value]   banderas
 *   [data-adhoc-doc-apply] / [data-adhoc-doc-clear]    botones
 *   #{tableId}-body                                    tbody a pintar
 *   [data-adhoc-doc-count]                             "N documento(s)"
 *   [data-adhoc-pager] [data-adhoc-page="prev|next"] [data-adhoc-page-info]
 *
 * Ninguna celda se llena con innerHTML de datos del servidor: `helpers.cell`
 * usa textContent y el único innerHTML es markup estático de iconos.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;

    var DEFAULT_PER_PAGE = 25;

    //: Colores del LEGACY (advanced_documents.html, líneas 77-89): Borrador y
    //: Rechazado en rojo, En Revisión en azul, Aprobado en verde. El estatus se
    //: pinta como TEXTO de color, nunca como pastilla sólida.
    //: 'Obsoleto' (version superada por otra mas nueva) va en gris apagado:
    //: no es un error, solo dejo de estar vigente.
    var STATUS_TONE = {
        'Borrador': 'danger',
        'En Revisión': 'info',
        'Aprobado': 'success',
        'Rechazado': 'danger',
        'Obsoleto': 'muted'
    };

    // ==================== HELPERS ====================

    function text(value, fallback) {
        if (value === null || value === undefined || value === '') {
            return fallback === undefined ? '' : fallback;
        }
        return String(value);
    }

    /** "2026-08-25T10:00:00" → "2026-08-25". Nunca revienta con basura. */
    function isoDate(value) {
        var raw = text(value);
        return raw ? raw.slice(0, 10) : '';
    }

    /** Nombre de un catálogo anidado ({id, name}) o "N/A". */
    function named(obj) {
        return (obj && obj.name) ? String(obj.name) : 'N/A';
    }

    /** <td> con textContent y su `data-adhoc-cell` para el filtrado por clave. */
    function cell(row, key, value, extraClass) {
        var td = document.createElement('td');
        td.setAttribute('data-adhoc-cell', key);
        if (extraClass) td.className = extraClass;
        td.textContent = value;
        row.appendChild(td);
        return td;
    }

    /**
     * <td> con el texto acotado a 2 lineas.
     *
     * El clamp NO puede ir en el <td>: un <td> no acepta `display:-webkit-box`,
     * el navegador lo revierte a `table-cell` y `-webkit-line-clamp` se ignora.
     * Va en un hijo bloque (`.adhoc-clamp-text`), y el texto completo queda en
     * el `title` para que lo truncado siga siendo alcanzable.
     */
    function clampCell(row, key, value) {
        var td = cell(row, key, '', 'adhoc-cell-clamp');
        var box = document.createElement('div');
        box.className = 'adhoc-clamp-text';
        box.textContent = value;
        if (value) td.title = value;
        td.appendChild(box);
        return td;
    }

    /** Estatus como texto de color (legacy `.rev-container` + span en línea). */
    function statusBadge(status) {
        var badge = document.createElement('span');
        badge.className = 'adhoc-badge adhoc-status adhoc-doc-status adhoc-badge-' +
            (STATUS_TONE[status] || 'neutral');
        badge.textContent = text(status);
        return badge;
    }

    /**
     * Enlace de descarga, o un icono apagado si no hay archivo o falta el
     * permiso. En el legacy la descarga era una ruta ANÓNIMA con el id en la
     * URL: bastaba iterar para bajarse el SGC completo.
     */
    function fileCell(doc, canDownload, opts) {
        var o = opts || {};
        var icon = o.icon || 'fa-solid fa-link';
        if (!doc.has_file) {
            var none = document.createElement('i');
            none.className = 'fa-solid fa-file-excel adhoc-file-none';
            none.title = 'Sin archivo';
            none.setAttribute('aria-label', 'Sin archivo');
            return none;
        }
        if (!canDownload) {
            var locked = document.createElement('i');
            locked.className = 'fa-solid fa-file-circle-xmark adhoc-file-none';
            locked.title = 'Sin permiso para descargar';
            locked.setAttribute('aria-label', 'Sin permiso para descargar');
            return locked;
        }
        var link = document.createElement('a');
        link.className = o.linkClass || 'adhoc-file-link';
        link.href = U.API_BASE + '/documents/' + encodeURIComponent(doc.id) + '/download';
        link.title = 'Descargar archivo';
        link.setAttribute('aria-label', 'Descargar archivo');
        link.rel = 'noopener';
        link.target = '_blank';
        link.innerHTML = '<i class="' + icon + '"></i>';   // markup estático
        return link;
    }

    /**
     * Icono de acción de fila. Aspecto del legacy `.icon-btn-blue`: icono
     * pelado del color de la marca, sin recuadro, que crece al pasar el ratón.
     * `icon` es la clase COMPLETA de Font Awesome; `variant` una de las clases
     * de color de documents.css (adhoc-icon-danger, -warning, -muted...).
     */
    function iconButton(action, icon, label, variant) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'adhoc-icon-action' + (variant ? ' ' + variant : '');
        btn.setAttribute('data-adhoc-doc-action', action);
        btn.title = label;
        btn.setAttribute('aria-label', label);
        btn.innerHTML = '<i class="' + icon + '"></i>';   // markup estático
        return btn;
    }

    // ---------- vigencia y cadena de versiones ----------

    //: Tono del badge de vigencia por `expiry_state`. Los tres cubos los define
    //: el SERVIDOR (utils/constants.DOCUMENT_EXPIRY_SOON_DAYS = 30): aquí no se
    //: vuelve a hacer aritmética de fechas. Si se hiciera, se haría contra el
    //: reloj del cliente, y un equipo con la zona horaria mal puesta pintaría de
    //: rojo un documento que no ha vencido. 'vigente' no lleva badge: la fecha
    //: sola ya lo dice.
    var EXPIRY_TONE = {
        'vencido': 'adhoc-badge-danger',
        'por_vencer': 'adhoc-badge-warning'
    };

    /**
     * Etiqueta corta del badge de vigencia. `days_to_expire` viene del servidor
     * y es NEGATIVO cuando ya venció.
     */
    function expiryLabel(doc) {
        var dias = doc ? doc.days_to_expire : null;
        if (doc && doc.expiry_state === 'vencido') {
            return (typeof dias === 'number' && dias < 0)
                ? 'Vencido hace ' + Math.abs(dias) + ' d'
                : 'Vencido';
        }
        if (typeof dias !== 'number') return 'Por vencer';
        return dias === 0 ? 'Vence hoy' : 'Vence en ' + dias + ' d';
    }

    /**
     * <td data-adhoc-cell="expiration"> de la columna "Vigencia": la fecha en
     * texto y, si el documento está vencido o le quedan 30 días o menos, un
     * badge rojo o ámbar detrás.
     *
     * Un documento del SGC sin fecha de vigencia NO es un error —5 de los 202
     * no la traen— así que se dice "Sin fecha" en tono apagado en vez de dejar
     * la celda vacía, que se lee como "falta el dato".
     *
     * Cero innerHTML: fecha y etiqueta van por textContent.
     *
     * @param {HTMLTableRowElement} row fila a la que se añade la celda
     * @param {Object} doc fila de `document_out()`
     * @returns {HTMLTableCellElement}
     */
    function expiryCell(row, doc) {
        var td = cell(row, 'expiration', '', 'adhoc-cell-nowrap');
        var fecha = isoDate(doc ? doc.expiration_date : null);

        if (!fecha) {
            var vacio = document.createElement('span');
            vacio.className = 'adhoc-doc-expiry-none';
            vacio.textContent = 'Sin fecha';
            td.appendChild(vacio);
            return td;
        }

        var texto = document.createElement('span');
        texto.className = 'adhoc-doc-expiry-date';
        texto.textContent = fecha;
        td.appendChild(texto);

        var tono = EXPIRY_TONE[doc.expiry_state];
        if (tono) {
            var badge = document.createElement('span');
            badge.className = 'adhoc-badge adhoc-doc-expiry-badge ' + tono;
            badge.textContent = expiryLabel(doc);
            td.appendChild(badge);
        }
        return td;
    }

    /**
     * Botón de fila que abre el historial de versiones
     * (`AdhocDocumentVersions.open`). Es un `iconButton` con la acción
     * 'versions', así que lo recoge la MISMA delegación que el resto de
     * acciones (`[data-adhoc-doc-action]`).
     *
     * Se pinta SIEMPRE, también en un documento de una sola versión: la fila no
     * sabe si tiene hijos —`parent_id` solo dice si ella es hija— y consultarlo
     * por fila serían 25 peticiones por página. El modal es el que dice "Esta es
     * la única versión" cuando la cadena trae una sola.
     *
     * @param {Object} doc fila de `document_out()`
     * @returns {HTMLButtonElement}
     */
    function versionButton(doc) {
        // Sin variante de color: es el violeta de marca, el mismo de las otras
        // acciones neutras de la fila. El azul queda reservado para 'flow-info'
        // y el rojo para 'delete', que es lo que hace legible una barra de
        // cuatro iconos de un vistazo.
        var btn = iconButton('versions', 'fa-solid fa-code-branch',
                             'Historial de versiones');
        if (doc && doc.id !== null && doc.id !== undefined) {
            btn.setAttribute('data-adhoc-doc-id', String(doc.id));
        }
        return btn;
    }

    /**
     * Marca "Superada" de una versión que ya no es la punta de su cadena.
     * Devuelve `null` cuando el documento SÍ es el vigente, para que quien lo
     * llama pueda hacer `var b = currentBadge(doc); if (b) td.appendChild(b);`
     * sin preguntar dos veces por lo mismo.
     *
     * Solo se ve con la casilla "Ver versiones anteriores" marcada o dentro del
     * modal de historial: por defecto las dos listas ocultan las superadas.
     *
     * @param {Object} doc fila de `document_out()`
     * @returns {HTMLElement|null}
     */
    function currentBadge(doc) {
        if (!doc || doc.is_current !== false) return null;
        var badge = document.createElement('span');
        badge.className = 'adhoc-badge adhoc-badge-muted adhoc-doc-superseded';
        badge.textContent = 'Superada';
        badge.title = 'Versión superada por otra más reciente';
        return badge;
    }

    // ==================== INSTANCIA ====================

    /**
     * @param {HTMLElement} root  contenedor de la pantalla
     * @param {{tableId:string, perPage:number, buildRow:Function,
     *          afterRender:Function, initialFilters:Object}} opts
     */
    function DocumentList(root, opts) {
        var o = opts || {};

        this.root = root;
        this.tableId = o.tableId;
        this.perPage = parseInt(o.perPage, 10) || DEFAULT_PER_PAGE;
        this.buildRow = o.buildRow;
        this.afterRender = o.afterRender || null;
        //: Bloque `initial_filters` de page_data (o null). Lo vuelca `init()`
        //: sobre la barra ANTES de la primera consulta.
        this.initialFilters = o.initialFilters || null;

        this.table = root.querySelector('#' + this.tableId);
        this.body = root.querySelector('#' + this.tableId + '-body');
        this.emptyRow = this.body ? this.body.querySelector('[data-adhoc-empty]') : null;
        this.pager = root.querySelector('[data-adhoc-pager]');
        this.pagerInfo = root.querySelector('[data-adhoc-page-info]');
        this.countLabel = root.querySelector('[data-adhoc-doc-count]');

        this.items = [];
        this.page = 1;
        this.totalPages = 1;
        this.total = 0;
        this.loading = false;
        this.debounce = null;
    }

    DocumentList.prototype.init = function () {
        if (!this.body) {
            console.error('[adhoc] document-list: falta el cuerpo de', this.tableId);
            return this;
        }
        this.bind();
        this.applyInitialFilters();
        this.load();
        return this;
    };

    // ---------- filtros ----------

    /** `true` si el nodo es una casilla: su valor NO se lee de `.value`. */
    function esCasilla(node) {
        return node.tagName === 'INPUT' && node.type === 'checkbox';
    }

    /**
     * Valor que una casilla aporta a la query.
     *
     * POR QUÉ NO VALE `.value`: un <input type="checkbox"> SIEMPRE tiene
     * `.value` —el atributo si lo trae, y "on" si no—, así que leerlo como se
     * lee un <input type="search"> emitía la clave estuviera marcada o no. La
     * casilla "Ver versiones anteriores" habría mandado `only_current` con el
     * mismo valor en los dos estados: el filtro no habría hecho nada nunca.
     *
     * Los dos valores los declara el propio input, porque el sentido de la
     * casilla no siempre coincide con el del parámetro: "Ver versiones
     * anteriores" MARCADA significa `only_current=false`. Sin los atributos el
     * par por defecto es "true"/"", y la cadena vacía no se emite — que es lo
     * que deja al servidor aplicar SU default.
     */
    function valorDeCasilla(node) {
        var attr = node.checked ? 'data-adhoc-checked-value' : 'data-adhoc-unchecked-value';
        var declarado = node.getAttribute(attr);
        if (declarado !== null) return declarado;
        return node.checked ? 'true' : '';
    }

    /**
     * Vuelca `page_data.initial_filters` sobre la barra de filtros, ANTES de la
     * primera consulta.
     *
     * Vive aquí y no en cada pantalla porque el resto del contrato de la barra
     * —qué nodos son filtros, cómo se lee una casilla, cómo se limpia— ya vive
     * aquí: cuando `documents.js` y `documents-panel.js` tenían cada uno su
     * copia, las dos ya habían divergido (una descartaba la cadena vacía y
     * validaba la clave con un regex, la otra no), así que un filtro nuevo podía
     * comportarse distinto en /adhoc/documentos que en /adhoc/documentos/panel
     * sin que nada avisara.
     *
     * Se recorren los nodos que declara el MARCADO, no una lista escrita en JS:
     * un filtro nuevo en la plantilla funciona sin tocar este archivo. Una clave
     * que no venga en `initial_filters` deja su control como estaba.
     *
     * El valor que manda el servidor es el MISMO string que el control volverá a
     * enviar (`"vencidos"`, `"false"`), así que aquí no se traduce nada: a un
     * <select> se le asigna y a una casilla se le compara con el valor que ella
     * declara para "marcada". Un valor que no case con ninguna opción deja el
     * <select> en el placeholder, que es lo correcto: el servidor ya descartó
     * los inventados (`pages/documents.py::_initial_filters`).
     *
     * El orden importa: `init()` arranca pidiendo datos, así que aplicarlo
     * después haría dos peticiones —la primera sin el filtro— y quien llega
     * desde el contador de vencidos del dashboard vería parpadear la lista
     * completa antes de la que pidió.
     */
    DocumentList.prototype.applyInitialFilters = function () {
        var initial = this.initialFilters;
        if (!initial) return this;

        var nodes = this.root.querySelectorAll('[data-adhoc-doc-filter]');
        for (var i = 0; i < nodes.length; i++) {
            var node = nodes[i];
            var key = node.getAttribute('data-adhoc-doc-filter');
            if (!Object.prototype.hasOwnProperty.call(initial, key)) continue;

            var value = initial[key];
            // `null` es "el parámetro no venía en la URL": el servidor manda
            // siempre las dos claves para que el JS no tenga que preguntar si
            // existen.
            if (value === null || value === undefined) continue;
            value = String(value);

            if (esCasilla(node)) {
                var marcado = node.getAttribute('data-adhoc-checked-value');
                node.checked = (marcado !== null) ? (value === marcado) : (value === 'true');
            } else {
                node.value = value;
            }
        }
        return this;
    };

    DocumentList.prototype.filters = function () {
        var nodes = this.root.querySelectorAll('[data-adhoc-doc-filter]');
        var out = {};
        for (var i = 0; i < nodes.length; i++) {
            var node = nodes[i];
            var key = node.getAttribute('data-adhoc-doc-filter');
            var value = esCasilla(node)
                ? valorDeCasilla(node)
                : (node.value || '').trim();
            if (value) out[key] = value;
        }
        return out;
    };

    DocumentList.prototype.query = function () {
        var params = new URLSearchParams();
        params.set('page', String(this.page));
        params.set('per_page', String(this.perPage));
        var filters = this.filters();
        for (var key in filters) {
            if (Object.prototype.hasOwnProperty.call(filters, key)) {
                params.set(key, filters[key]);
            }
        }
        return params.toString();
    };

    /**
     * Deja la barra de filtros como al entrar. Una casilla se limpia
     * DESMARCÁNDOLA: `.value = ''` no la desmarca —solo le cambia el valor que
     * enviaría—, así que "Limpiar" dejaba encendida la casilla de ver versiones
     * anteriores mientras el resto de la barra sí se vaciaba.
     */
    DocumentList.prototype.clearFilters = function () {
        var nodes = this.root.querySelectorAll('[data-adhoc-doc-filter]');
        for (var i = 0; i < nodes.length; i++) {
            if (esCasilla(nodes[i])) nodes[i].checked = false;
            else nodes[i].value = '';
        }
        return this.reload();
    };

    // ---------- carga ----------

    /** Recarga desde la página 1 (tras crear, borrar o arrancar un flujo). */
    DocumentList.prototype.reload = function () {
        this.page = 1;
        return this.load();
    };

    DocumentList.prototype.load = function () {
        var self = this;
        if (this.loading) return null;
        this.loading = true;
        this.root.classList.add('is-loading');

        return U.fetchJson('/documents?' + this.query())
            .then(function (payload) {
                self.render(payload || {});
            })
            .catch(function (err) {
                self.render({ data: [], total: 0, page: 1, total_pages: 1 });
                U.showToast('No se pudieron cargar los documentos: ' + err.message, 'error');
            })
            .then(function () {
                self.loading = false;
                self.root.classList.remove('is-loading');
            });
    };

    // ---------- pintado ----------

    DocumentList.prototype.render = function (payload) {
        this.items = payload.data || [];

        var frag = document.createDocumentFragment();
        for (var i = 0; i < this.items.length; i++) {
            frag.appendChild(this.buildRow(this.items[i]));
        }

        // Se vacía el tbody conservando la fila de "sin resultados".
        var rows = this.body.querySelectorAll('tr:not([data-adhoc-empty])');
        for (var j = 0; j < rows.length; j++) rows[j].remove();

        if (this.emptyRow) this.body.insertBefore(frag, this.emptyRow);
        else this.body.appendChild(frag);

        this.page = parseInt(payload.page, 10) || 1;
        this.totalPages = parseInt(payload.total_pages, 10) || 1;
        this.total = parseInt(payload.total, 10) || 0;
        this.renderPager();

        if (this.afterRender) this.afterRender(this.items);
    };

    DocumentList.prototype.renderPager = function () {
        if (this.countLabel) {
            this.countLabel.textContent = this.total
                ? (this.total + ' documento(s)')
                : 'Sin documentos';
        }
        if (!this.pager) return;

        this.pager.hidden = this.totalPages <= 1;
        if (this.pagerInfo) {
            this.pagerInfo.textContent = 'Página ' + this.page + ' de ' + this.totalPages;
        }
        var prev = this.pager.querySelector('[data-adhoc-page="prev"]');
        var next = this.pager.querySelector('[data-adhoc-page="next"]');
        if (prev) prev.disabled = this.page <= 1;
        if (next) next.disabled = this.page >= this.totalPages;
    };

    /** El documento de una fila, por su `data-id`. */
    DocumentList.prototype.find = function (id) {
        for (var i = 0; i < this.items.length; i++) {
            if (String(this.items[i].id) === String(id)) return this.items[i];
        }
        return null;
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    DocumentList.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-doc-apply]')) {
                evt.preventDefault();
                self.reload();
                return;
            }
            if (evt.target.closest('[data-adhoc-doc-clear]')) {
                evt.preventDefault();
                self.clearFilters();
                return;
            }
            var pageBtn = evt.target.closest('[data-adhoc-page]');
            if (!pageBtn) return;
            evt.preventDefault();
            var dir = pageBtn.getAttribute('data-adhoc-page');
            var target = dir === 'prev' ? self.page - 1 : self.page + 1;
            if (target < 1 || target > self.totalPages) return;
            self.page = target;
            self.load();
        });

        // Los <select> y las casillas recargan al instante; el texto, con rebote.
        this.root.addEventListener('change', function (evt) {
            if (!evt.target.matches('select[data-adhoc-doc-filter]') &&
                !evt.target.matches('input[type="checkbox"][data-adhoc-doc-filter]')) return;
            self.reload();
        });

        this.root.addEventListener('input', function (evt) {
            if (!evt.target.matches('input[data-adhoc-doc-filter]')) return;
            // Una casilla emite `input` ADEMÁS de `change`: sin esta salida se
            // recargaría dos veces por clic, la segunda 350 ms más tarde.
            if (esCasilla(evt.target)) return;
            clearTimeout(self.debounce);
            self.debounce = setTimeout(function () { self.reload(); }, 350);
        });

        this.root.addEventListener('keydown', function (evt) {
            if (evt.key !== 'Enter') return;
            if (!evt.target.matches('[data-adhoc-doc-filter]')) return;
            evt.preventDefault();
            clearTimeout(self.debounce);
            self.reload();
        });
    };

    // ==================== API PÚBLICA ====================

    /**
     * Crea y arranca una tabla de documentos.
     * @returns {DocumentList}
     */
    function create(root, opts) {
        return new DocumentList(root, opts).init();
    }

    window.AdhocDocumentList = {
        create: create,
        STATUS_TONE: STATUS_TONE,
        EXPIRY_TONE: EXPIRY_TONE,
        helpers: {
            text: text,
            isoDate: isoDate,
            named: named,
            cell: cell,
            clampCell: clampCell,
            statusBadge: statusBadge,
            fileCell: fileCell,
            iconButton: iconButton,
            expiryLabel: expiryLabel,
            expiryCell: expiryCell,
            versionButton: versionButton,
            currentBadge: currentBadge
        }
    };
})();
