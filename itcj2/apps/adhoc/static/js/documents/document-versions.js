/**
 * documents/document-versions.js — modal "Historial de versiones" de un
 * documento del SGC. Compartido por /adhoc/documentos (consulta) y
 * /adhoc/documentos/panel (gestión).
 *
 * Expone SOLO `window.AdhocDocumentVersions` (IIFE, sin globales sueltas).
 *
 * POR QUÉ EXISTE
 * --------------
 * El legacy tenía un bloque "Historial de Versiones Anteriores" en
 * `advanced_documents.html` que era un MOCKUP: la fecha estaba escrita a mano
 * (`<td>2025-01-15</td>`) y la versión anterior se calculaba restando 1.0 a la
 * actual. No consultaba nada, y por eso no se portó en su día (plan §4).
 *
 * Ahora hace falta de verdad: las dos listas ocultan por defecto las versiones
 * superadas —144 cadenas, 58 filas superadas—, así que tiene que existir UN
 * sitio donde se vean todas. Este es, y lee la cadena real de la base.
 *
 * CONTRATO DE API
 * ---------------
 *   GET /api/adhoc/v2/documents/{id}/versions   (adhoc.documents.api.read)
 *   → {success, data: [document_out(d), ...], total}
 *   La cadena ENTERA: la raíz primero y después las versiones por id
 *   ascendente. Da igual con qué id de la cadena se entre —raíz o hija—, la
 *   respuesta es la misma. 404 si el documento no existe.
 *
 * MARCADO QUE CONSUME (partials/_document_versions_modal.html)
 * -----------------------------------------------------------
 *   #adhoc-doc-versions-modal / [data-adhoc-versions-modal]   overlay
 *   [data-adhoc-versions-doc]                                 código y título
 *   [data-adhoc-versions-note]                                nº de versiones
 *   [data-adhoc-versions-body]                                tbody a pintar
 *   [data-adhoc-versions-empty]                               fila "sin datos"
 *
 * DEPENDE de document-list.js: reutiliza sus helpers (`statusBadge`,
 * `expiryCell`, `fileCell`, `currentBadge`) para que una versión se vea EXACTA
 * a como se ve en la tabla de la que salió. Su <script> va después.
 *
 * CÓMO SE CARGA (contrato del shell, CLAUDE.md del app §Frontend)
 * --------------------------------------------------------------
 *   {% block modals %}{% include "adhoc/partials/_document_versions_modal.html" %}{% endblock %}
 *   {% block extra_js %}
 *   <script id="adhoc-mod-documents-document-list"
 *           src="/static/adhoc/js/documents/document-list.js?v={{ sv('js/documents/document-list.js') }}"></script>
 *   <script id="adhoc-mod-documents-document-versions"
 *           src="/static/adhoc/js/documents/document-versions.js?v={{ sv('js/documents/document-versions.js') }}"></script>
 *   {% endblock %}
 *
 * El `id` del <script> NO es decorativo: idiomorph empareja los <script> por id
 * si lo tienen y POR POSICIÓN si no, y a un <script> ya ejecutado no se le
 * vuelve a ejecutar por cambiarle el `src`. Sin id, saltar de una pantalla de
 * documentos a la otra dejaba el módulo muerto.
 *
 * Cero innerHTML con datos del servidor: todo por textContent.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var List = window.AdhocDocumentList;
    var H = List ? List.helpers : null;

    var MODAL_SELECTOR = '[data-adhoc-versions-modal]';

    //: Permiso de descarga de la pantalla activa. Lo trae `page_data` de las dos
    //: páginas (`can_download`) y se relee en cada `onReady`: el módulo
    //: sobrevive al salto entre consulta y panel, y el mismo usuario puede no
    //: tener los mismos permisos en las dos.
    var canDownload = false;

    //: Petición en vuelo. Se aborta al abrir otra y al desmontar la pantalla:
    //: una respuesta que llega cuando su modal ya no está en el DOM pintaría
    //: filas dentro de un nodo huérfano.
    var enVuelo = null;

    // ==================== PINTADO ====================

    /** Marca de la punta de la cadena. La hermana ("Superada") la da el helper. */
    function currentFlag() {
        var badge = document.createElement('span');
        badge.className = 'adhoc-badge adhoc-badge-success adhoc-doc-current';
        badge.textContent = 'Vigente';
        badge.title = 'Es la versión en uso del documento';
        return badge;
    }

    /**
     * Una fila del historial: Versión · Estatus · Vigencia · Aprobación ·
     * Archivo. Mismo orden y mismas celdas que la tabla de la pantalla.
     *
     * @param {Object} doc fila de `document_out()`
     * @param {number|string} openedId documento desde el que se abrió el modal
     * @returns {HTMLTableRowElement}
     */
    function buildRow(doc, openedId) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(doc.id));

        var clases = [];
        if (doc.is_current) clases.push('adhoc-version-current');
        // La fila desde la que se abrió el historial. Sin esta marca, en una
        // cadena de cinco versiones el usuario pierde de vista cuál estaba
        // mirando en cuanto se pintan las otras cuatro.
        if (String(doc.id) === String(openedId)) {
            clases.push('adhoc-version-focus');
            tr.setAttribute('aria-current', 'true');
        }
        if (clases.length) tr.className = clases.join(' ');

        // — versión + marca de vigente/superada —
        var tdVersion = document.createElement('td');
        tdVersion.setAttribute('data-adhoc-cell', 'version');
        tdVersion.className = 'adhoc-cell-nowrap';
        var version = document.createElement('span');
        version.className = 'adhoc-doc-version';
        version.textContent = 'v' + H.text(doc.version);
        tdVersion.appendChild(version);
        var marca = doc.is_current ? currentFlag() : H.currentBadge(doc);
        if (marca) tdVersion.appendChild(marca);
        tr.appendChild(tdVersion);

        // — estatus —
        var tdStatus = document.createElement('td');
        tdStatus.setAttribute('data-adhoc-cell', 'status');
        tdStatus.className = 'adhoc-cell-nowrap';
        tdStatus.appendChild(H.statusBadge(doc.status));
        tr.appendChild(tdStatus);

        // — vigencia (fecha + badge rojo/ámbar) —
        H.expiryCell(tr, doc);

        // — aprobación —
        H.cell(tr, 'approval_date', H.isoDate(doc.approval_date) || 'Pendiente',
               'adhoc-cell-nowrap');

        // — archivo —
        var tdFile = document.createElement('td');
        tdFile.setAttribute('data-adhoc-cell', 'file');
        tdFile.className = 'adhoc-col-center';
        tdFile.appendChild(H.fileCell(doc, canDownload));
        tr.appendChild(tdFile);

        return tr;
    }

    /** Vacía el tbody conservando la fila de "sin datos". */
    function clearRows(body) {
        var rows = body.querySelectorAll('tr:not([data-adhoc-versions-empty])');
        for (var i = 0; i < rows.length; i++) rows[i].remove();
    }

    function setNote(modal, texto) {
        var note = modal.querySelector('[data-adhoc-versions-note]');
        if (!note) return;
        note.textContent = texto || '';
        note.hidden = !texto;
    }

    /** Cabecera del modal: "CÓDIGO · Título". Dato del servidor, textContent. */
    function setDoc(modal, doc) {
        var el = modal.querySelector('[data-adhoc-versions-doc]');
        if (!el) return;
        if (!doc) {
            el.textContent = '';
            el.hidden = true;
            return;
        }
        var code = H.text(doc.code);
        var title = H.text(doc.title);
        el.textContent = code ? (code + ' · ' + title) : title;
        el.hidden = false;
    }

    function render(modal, items, openedId) {
        var body = modal.querySelector('[data-adhoc-versions-body]');
        var empty = modal.querySelector('[data-adhoc-versions-empty]');
        if (!body) return;

        clearRows(body);

        var frag = document.createDocumentFragment();
        for (var i = 0; i < items.length; i++) {
            frag.appendChild(buildRow(items[i], openedId));
        }
        if (empty) body.insertBefore(frag, empty);
        else body.appendChild(frag);

        // La fila de "sin datos" solo se enseña cuando de verdad no hay nada.
        if (empty) empty.hidden = items.length > 0;

        // Tres casos, no dos. Con `items.length <= 1` el vacío caía en la rama
        // de "única versión" y el modal decía a la vez "No se encontraron
        // versiones" y "Esta es la única versión": dos frases que se
        // contradicen en la misma pantalla. Sin filas, la nota se calla y habla
        // la fila de vacío, que para eso está.
        //
        // Una sola fila no es un error ni un vacío: la mayoría de las cadenas
        // del SGC no se han versionado nunca. Se dice con todas las letras para
        // que nadie piense que el historial falló.
        if (items.length === 0) {
            setNote(modal, '');
        } else if (items.length === 1) {
            setNote(modal, 'Esta es la única versión registrada del documento.');
        } else {
            setNote(modal, items.length +
                ' versiones. La vigente está marcada; las demás quedaron superadas.');
        }
    }

    // ==================== API PÚBLICA ====================

    /**
     * Abre el historial de versiones del documento indicado.
     *
     *   AdhocDocumentVersions.open(doc.id);
     *
     * El modal se abre AL INSTANTE con su estado de carga y se rellena cuando
     * llega la respuesta: abrirlo después dejaba el clic sin efecto visible
     * durante toda la petición.
     *
     * @param {number|string} documentId cualquier id de la cadena (raíz o hija)
     * @returns {Promise|null}
     */
    function open(documentId) {
        if (!H) {
            console.error('[adhoc] document-versions: falta document-list.js');
            if (U) U.showToast('No se pudo abrir el historial de versiones.', 'error');
            return null;
        }
        if (documentId === null || documentId === undefined || documentId === '') return null;

        var modal = document.querySelector(MODAL_SELECTOR);
        if (!modal) {
            console.error('[adhoc] document-versions: falta el modal del historial');
            U.showToast('No se pudo abrir el historial de versiones.', 'error');
            return null;
        }

        var body = modal.querySelector('[data-adhoc-versions-body]');
        var empty = modal.querySelector('[data-adhoc-versions-empty]');
        if (body) clearRows(body);
        if (empty) empty.hidden = true;          // mientras carga no hay "vacío"
        setDoc(modal, null);
        setNote(modal, 'Cargando historial…');
        modal.classList.add('is-loading');
        U.openModal(modal);

        if (enVuelo) enVuelo.abort();
        var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        enVuelo = ctrl;

        return U.fetchJson('/documents/' + encodeURIComponent(documentId) + '/versions',
                           ctrl ? { signal: ctrl.signal } : undefined)
            .then(function (payload) {
                var items = (payload && payload.data) || [];
                // La cabecera describe el documento DESDE EL QUE se abrió, no la
                // raíz: el código es el mismo en toda la cadena, pero el título
                // pudo cambiar entre versiones.
                var abierto = null;
                for (var i = 0; i < items.length; i++) {
                    if (String(items[i].id) === String(documentId)) abierto = items[i];
                }
                setDoc(modal, abierto || items[0] || null);
                render(modal, items, documentId);
            })
            .catch(function (err) {
                // Abortada: o se abrió otro historial, o la pantalla se fue. No
                // hay nada que avisar y el modal ya no es de esta petición.
                if (err && err.name === 'AbortError') return;
                if (empty) empty.hidden = false;
                setDoc(modal, null);
                setNote(modal, 'No se pudo cargar el historial: ' + err.message);
                U.showToast('No se pudo cargar el historial: ' + err.message, 'error');
            })
            .then(function () {
                if (enVuelo === ctrl) enVuelo = null;
                modal.classList.remove('is-loading');
            });
    }

    /** Cierra el modal. Lo normal es el cierre delegado (`data-adhoc-modal-close`). */
    function close() {
        var modal = document.querySelector(MODAL_SELECTOR);
        if (modal) U.closeModal(modal);
    }

    // ==================== CICLO DE VIDA ====================

    if (U && typeof U.onReady === 'function') {
        // Con enganche: el módulo no hace nada en una pantalla que no incluya el
        // partial. Corre en la carga inicial y tras cada intercambio de HTMX.
        U.onReady(MODAL_SELECTOR, function () {
            var data = (typeof U.pageData === 'function') ? U.pageData() : {};
            canDownload = !!data.can_download;
        });
    }

    if (U && typeof U.onTeardown === 'function') {
        U.onTeardown(function () {
            if (enVuelo) enVuelo.abort();
            enVuelo = null;
        });
    }

    window.AdhocDocumentVersions = { open: open, close: close };
})();
