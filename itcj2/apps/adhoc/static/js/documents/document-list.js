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

    // ==================== INSTANCIA ====================

    /**
     * @param {HTMLElement} root  contenedor de la pantalla
     * @param {{tableId:string, perPage:number, buildRow:Function,
     *          afterRender:Function}} opts
     */
    function DocumentList(root, opts) {
        var o = opts || {};

        this.root = root;
        this.tableId = o.tableId;
        this.perPage = parseInt(o.perPage, 10) || DEFAULT_PER_PAGE;
        this.buildRow = o.buildRow;
        this.afterRender = o.afterRender || null;

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
        this.load();
        return this;
    };

    // ---------- filtros ----------

    DocumentList.prototype.filters = function () {
        var nodes = this.root.querySelectorAll('[data-adhoc-doc-filter]');
        var out = {};
        for (var i = 0; i < nodes.length; i++) {
            var key = nodes[i].getAttribute('data-adhoc-doc-filter');
            var value = (nodes[i].value || '').trim();
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

    DocumentList.prototype.clearFilters = function () {
        var nodes = this.root.querySelectorAll('[data-adhoc-doc-filter]');
        for (var i = 0; i < nodes.length; i++) nodes[i].value = '';
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

        // Los <select> recargan al instante; el texto, con rebote.
        this.root.addEventListener('change', function (evt) {
            if (!evt.target.matches('select[data-adhoc-doc-filter]')) return;
            self.reload();
        });

        this.root.addEventListener('input', function (evt) {
            if (!evt.target.matches('input[data-adhoc-doc-filter]')) return;
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
        helpers: {
            text: text,
            isoDate: isoDate,
            named: named,
            cell: cell,
            clampCell: clampCell,
            statusBadge: statusBadge,
            fileCell: fileCell,
            iconButton: iconButton
        }
    };
})();
