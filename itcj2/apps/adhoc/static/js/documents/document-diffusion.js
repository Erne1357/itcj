/**
 * documents/document-diffusion.js — modal "Difusión y acuses de recibo" de un
 * documento del SGC. Lo abre una acción de fila de /adhoc/documentos/panel.
 *
 * Expone SOLO `window.AdhocDocumentDiffusion` (IIFE, sin globales sueltas).
 *
 * POR QUÉ EXISTE
 * --------------
 * El ETL del SGC legacy trajo dos tablas con datos de verdad que la app no leía
 * en NINGUNA pantalla: `adhoc_document_visibility` (9 390 filas, 55 usuarios,
 * 198 de los 202 documentos) y `adhoc_document_acknowledgements` (987 acuses
 * con fecha real, del 2019-11-15 al 2025-02-12). La ISO 9001:2015 §7.5.3 exige
 * controlar la DISTRIBUCIÓN de la información documentada; esa evidencia
 * estaba en la base y en ninguna ventana.
 *
 * Es **consulta histórica y nada más**: aquí no se registra ningún acuse
 * nuevo. Esa función es otra decisión de producto y va con su propio plan.
 *
 * CONTRATO DE API
 * ---------------
 *   GET /api/adhoc/v2/documents/{id}/acknowledgements   (adhoc.documents.api.read)
 *   → {success, data: {document, summary, recipients}}
 *
 *     document    brief: {id, code, title, version, status, is_current}
 *     summary     {assigned, acknowledged, pending, coverage_pct}
 *                 + `without_access` SOLO si el servidor pudo resolver quién
 *                   entra hoy a Calidad
 *     recipients  [{user:{id,name}, acknowledged, acknowledged_at}]
 *                 + `has_app_access` con la misma condición
 *
 *   El destinatario NO trae `email`, y no es un olvido del servidor: el
 *   endpoint se sirve con `documents.api.read`, que también tiene `consult`, y
 *   con el correo dentro recorrer los 202 documentos enumeraba las 55 personas
 *   de la lista de distribución con su dirección. Aquí no se echa de menos: la
 *   pantalla no dice nada con el correo y la app no registra acuses nuevos, así
 *   que tampoco hay a quién escribirle desde esta ventana.
 *
 *   404 si el documento no existe. Un documento SIN destinatarios **no** es
 *   404 (4 de los 202 están así): devuelve `recipients: []` y el resumen en
 *   ceros.
 *
 * `has_app_access` y `without_access` se OMITEN, no viajan en `false`/`0`,
 * cuando el servidor no pudo comprobarlo. Aquí eso se lee como `undefined`
 * —falsy— y la UI se calla: **el cliente no recalcula acceso ni por
 * aproximación**. Un `false` de verdad sí llega, y ese es el dato.
 *
 * MARCADO QUE CONSUME (partials/_document_diffusion_modal.html)
 * ------------------------------------------------------------
 *   #adhoc-doc-diffusion-modal / [data-adhoc-diffusion-modal]   overlay
 *   [data-adhoc-diffusion-doc]                     código, título, versión
 *   [data-adhoc-diffusion-summary]                 tira de cifras
 *   [data-adhoc-diffusion-assigned|-acknowledged|-pending|-coverage]
 *   [data-adhoc-diffusion-noaccess] + [-noaccess-text]   aviso de sin acceso
 *   [data-adhoc-diffusion-note]                    línea de estado
 *   [data-adhoc-diffusion-body]                    tbody a pintar
 *   [data-adhoc-diffusion-empty]                   fila "sin destinatarios"
 *
 * DEPENDE de document-list.js: reutiliza `text`, `isoDate`, `cell`,
 * `statusBadge` y `currentBadge` para que el documento del encabezado se vea
 * EXACTO a como se ve en la fila desde la que se abrió. Su <script> va después.
 *
 * CÓMO SE CARGA (contrato del shell, CLAUDE.md del app §Frontend)
 * --------------------------------------------------------------
 *   {% block modals %}{% include "adhoc/partials/_document_diffusion_modal.html" %}{% endblock %}
 *   {% block extra_js %}
 *   <script id="adhoc-mod-documents-document-list" ...></script>
 *   <script id="adhoc-mod-documents-document-diffusion" ...></script>
 *   {% endblock %}
 *
 * El `id` del <script> NO es decorativo: idiomorph empareja los <script> por id
 * si lo tienen y POR POSICIÓN si no, y a un <script> ya ejecutado no se le
 * vuelve a ejecutar por cambiarle el `src`. Sin id, saltar entre pantallas de
 * documentos dejaba el módulo muerto.
 *
 * Cero innerHTML: aquí no se construye ni markup estático. Todo por
 * textContent y createElement.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var List = window.AdhocDocumentList;
    var H = List ? List.helpers : null;

    var MODAL_SELECTOR = '[data-adhoc-diffusion-modal]';

    //: Petición en vuelo. Se aborta al abrir otra y al desmontar la pantalla:
    //: una respuesta que llega cuando su modal ya no está en el DOM pintaría
    //: 47 nombres dentro de un nodo huérfano.
    var enVuelo = null;

    /**
     * ¿Esta respuesta ya no pinta nada? Dos motivos, y los dos dejan el modal
     * como estaba:
     *
     *   · mandó otra petición (se abrió la difusión de otro documento);
     *   · el modal se cerró mientras la respuesta volaba.
     *
     * El segundo es el que no cubría nada. El cierre habitual —botón, velo,
     * Escape— es el delegado de `adhoc-utils.js`, que no aborta nada: la
     * respuesta llegaba después y pintaba la lista completa de destinatarios
     * dentro de un diálogo ya cerrado, donde se quedaba hasta la siguiente
     * apertura. Es exactamente la fuga que el enganche de `onReady` evita en el
     * ATRÁS y que el cierre normal dejaba abierta.
     *
     * @param {AbortController|null} ctrl el de ESTA petición
     * @param {HTMLElement} modal
     * @returns {boolean}
     */
    function obsoleta(ctrl, modal) {
        if (enVuelo !== ctrl) return true;
        if (!modal.classList.contains('is-open')) {
            reset(modal);
            return true;
        }
        return false;
    }

    // ==================== ORDEN ====================

    //: Los tres cubos, de lo accionable a lo cerrado.
    //:
    //: El SERVIDOR ordena por apellido (el mismo orden que los pickers y el
    //: selector de validadores) y ese orden se conserva DENTRO de cada cubo.
    //: Lo que se antepone aquí es lo que todavía se puede perseguir:
    //:
    //:   0  pendiente y con acceso   → se le puede pedir el acuse HOY
    //:   1  pendiente y sin acceso   → falta la evidencia y ya no se completa
    //:   2  acusado                  → consta, no hay nada que hacer
    //:
    //: El argumento del servidor para NO ordenar por acuse —"una persona
    //: cambiaría de sitio cada vez que alguien acusa"— no aplica en esta
    //: pantalla: la app no registra acuses nuevos, así que la lista es un
    //: histórico congelado y el orden no se mueve entre dos aperturas.
    //:
    //: Sin `has_app_access` (el servidor no pudo resolverlo) los cubos 0 y 1
    //: se funden en el 0 y quedan dos: pendientes y acusados. Es la
    //: degradación correcta — nunca se supone que alguien no tiene acceso.
    function cubo(fila) {
        if (fila && fila.acknowledged) return 2;
        return (fila && fila.has_app_access === false) ? 1 : 0;
    }

    /**
     * Ordena por cubo conservando el orden del servidor dentro de cada uno.
     *
     * La estabilidad va DECORADA con la posición original y no confiada al
     * `sort` del navegador: es estable desde ES2019, pero de esto depende que
     * el orden alfabético del servidor sobreviva, y una garantía de la que
     * depende algo se escribe.
     *
     * @param {Array} items filas de `recipients`
     * @returns {Array} copia ordenada; `items` no se toca
     */
    function ordenar(items) {
        var decorado = [];
        for (var i = 0; i < items.length; i++) {
            decorado.push({ fila: items[i], cubo: cubo(items[i]), pos: i });
        }
        decorado.sort(function (a, b) {
            return (a.cubo - b.cubo) || (a.pos - b.pos);
        });
        var out = [];
        for (var j = 0; j < decorado.length; j++) out.push(decorado[j].fila);
        return out;
    }

    // ==================== PINTADO ====================

    /** Marca de quien ya no puede entrar a Calidad. Dato del servidor, no cálculo. */
    function noAccessBadge() {
        var badge = document.createElement('span');
        badge.className = 'adhoc-badge adhoc-badge-muted adhoc-diffusion-noaccess-badge';
        badge.textContent = 'Sin acceso';
        badge.title = 'Ya no tiene acceso a Calidad: no se le puede pedir el acuse';
        return badge;
    }

    /**
     * Estado del acuse como pastilla.
     *
     * "Pendiente" va en el tono APAGADO y no en el ámbar de aviso: 141 de los
     * 198 documentos con lista de distribución no tienen ni un acuse, así que
     * el ámbar teñiría de alarma casi toda la pantalla. Y un documento de 2019
     * cuyos destinatarios nunca acusaron es historia, no una alerta que
     * atender hoy.
     */
    function ackBadge(fila) {
        var badge = document.createElement('span');
        if (fila && fila.acknowledged) {
            badge.className = 'adhoc-badge adhoc-badge-success';
            badge.textContent = 'Acusado';
        } else {
            badge.className = 'adhoc-badge adhoc-badge-muted';
            badge.textContent = 'Pendiente';
        }
        return badge;
    }

    /**
     * Una fila: Destinatario · Acuse · Fecha.
     *
     * El badge y la fecha dicen lo mismo a propósito: el badge se ESCANEA
     * —cuántos faltan de un vistazo— y la fecha se CITA —es el dato que va al
     * informe de auditoría—. La fecha se recorta a día; la marca completa
     * (`2019-12-06T09:44:00`) queda en el `title`, que es donde hace falta si
     * alguien discute a qué hora se difundió algo.
     *
     * @param {Object} fila entrada de `recipients`
     * @param {boolean} corte si arranca aquí el bloque de los que ya acusaron
     * @returns {HTMLTableRowElement}
     */
    function buildRow(fila, corte) {
        var tr = document.createElement('tr');
        var user = (fila && fila.user) || {};
        if (user.id !== null && user.id !== undefined) {
            tr.setAttribute('data-id', String(user.id));
        }

        var clases = [];
        if (fila && fila.has_app_access === false) clases.push('adhoc-diffusion-stale');
        if (corte) clases.push('adhoc-diffusion-cut');
        if (clases.length) tr.className = clases.join(' ');

        // — destinatario (+ marca de sin acceso) —
        var tdUser = document.createElement('td');
        tdUser.setAttribute('data-adhoc-cell', 'user');
        var nombre = document.createElement('span');
        nombre.className = 'adhoc-diffusion-name';
        nombre.textContent = H.text(user.name, 'Sin nombre');
        tdUser.appendChild(nombre);
        if (fila && fila.has_app_access === false) tdUser.appendChild(noAccessBadge());
        tr.appendChild(tdUser);

        // — acuse —
        var tdAck = document.createElement('td');
        tdAck.setAttribute('data-adhoc-cell', 'acknowledged');
        tdAck.className = 'adhoc-cell-nowrap';
        tdAck.appendChild(ackBadge(fila));
        tr.appendChild(tdAck);

        // — fecha —
        var marca = H.text(fila ? fila.acknowledged_at : null);
        var tdDate = H.cell(tr, 'acknowledged_at', marca ? H.isoDate(marca) : '—',
                            marca ? 'adhoc-cell-nowrap' : 'adhoc-cell-nowrap adhoc-diffusion-none');
        tdDate.title = marca ? marca.replace('T', ' ') : 'Sin acuse registrado';

        return tr;
    }

    /** Vacía el tbody conservando la fila de "sin datos". */
    function clearRows(body) {
        var rows = body.querySelectorAll('tr:not([data-adhoc-diffusion-empty])');
        for (var i = 0; i < rows.length; i++) rows[i].remove();
    }

    function setNote(modal, texto) {
        var note = modal.querySelector('[data-adhoc-diffusion-note]');
        if (!note) return;
        note.textContent = texto || '';
        note.hidden = !texto;
    }

    /**
     * Encabezado: "CÓDIGO · Título", la versión y el estatus, con las mismas
     * pastillas que la fila del panel. Datos del servidor, todo textContent.
     */
    function setDoc(modal, doc) {
        var el = modal.querySelector('[data-adhoc-diffusion-doc]');
        if (!el) return;
        while (el.firstChild) el.removeChild(el.firstChild);
        if (!doc) {
            el.hidden = true;
            return;
        }
        var code = H.text(doc.code);
        var title = H.text(doc.title);
        el.appendChild(document.createTextNode(code ? (code + ' · ' + title) : title));

        var version = document.createElement('span');
        version.className = 'adhoc-doc-version adhoc-diffusion-version';
        version.textContent = 'v' + H.text(doc.version);
        el.appendChild(version);
        el.appendChild(H.statusBadge(doc.status));

        // "Superada" cuando no es la punta de su cadena. Importa aquí más que
        // en ningún sitio: leer la difusión de una versión que ya no está
        // vigente y creer que es la del documento en uso es el error caro.
        var superada = H.currentBadge(doc);
        if (superada) el.appendChild(superada);

        el.hidden = false;
    }

    function setValue(modal, clave, valor) {
        var el = modal.querySelector('[data-adhoc-diffusion-' + clave + ']');
        if (el) el.textContent = String(valor);
    }

    /** "53.2 %" del número del servidor. La división ya viene hecha de allí. */
    function porcentaje(valor) {
        return (typeof valor === 'number') ? (valor + ' %') : '—';
    }

    /**
     * La tira de cifras. Se ESCONDE ENTERA cuando no hay destinatarios, y esa
     * es la mitad de cómo se distinguen los dos vacíos de esta pantalla:
     *
     *   · sin lista de distribución (4 documentos) → no hay denominador, así
     *     que no hay porcentaje que enseñar. Un "0 %" ahí se leería como
     *     "nadie acusó", que es una acusación falsa: no es que no acusaran, es
     *     que a nadie se le asignó el documento. Habla la fila de vacío.
     *   · con lista y sin un solo acuse (141 documentos) → el denominador
     *     existe, el "0 %" significa exactamente lo que dice y la tabla se
     *     llena de "Pendiente".
     */
    function setSummary(modal, resumen) {
        var box = modal.querySelector('[data-adhoc-diffusion-summary]');
        if (!box) return;
        if (!resumen || !resumen.assigned) {
            box.hidden = true;
            return;
        }
        setValue(modal, 'assigned', resumen.assigned);
        setValue(modal, 'acknowledged', resumen.acknowledged);
        setValue(modal, 'pending', resumen.pending);
        setValue(modal, 'coverage', porcentaje(resumen.coverage_pct));
        box.hidden = false;
    }

    /**
     * Aviso de cuántos destinatarios ya no entran a Calidad.
     *
     * Solo con un número MAYOR QUE CERO. Con `undefined` (el servidor omitió
     * la clave porque no pudo comprobarlo) callarse es obligatorio; con `0`
     * también, porque esto es una MARCA y una marca que dice "0" es ruido: lo
     * que aporta ya lo dice que no salga ni una pastilla "Sin acceso" en la
     * tabla.
     */
    function setNoAccess(modal, resumen) {
        var box = modal.querySelector('[data-adhoc-diffusion-noaccess]');
        if (!box) return;
        var n = resumen ? resumen.without_access : undefined;
        if (typeof n !== 'number' || n <= 0) {
            box.hidden = true;
            return;
        }
        var texto = box.querySelector('[data-adhoc-diffusion-noaccess-text]');
        if (texto) {
            texto.textContent = (n === 1)
                ? '1 de los destinatarios ya no tiene acceso a Calidad. Sigue en la ' +
                  'lista porque la difusión se le hizo: ocultarlo falsearía la evidencia.'
                : n + ' de los destinatarios ya no tienen acceso a Calidad. Siguen en la ' +
                  'lista porque la difusión se les hizo: ocultarlos falsearía la evidencia.';
        }
        box.hidden = false;
    }

    /** Vuelve a dejar el modal como nace: sin filas, sin cifras y sin texto. */
    function reset(modal) {
        if (!modal) return;
        var body = modal.querySelector('[data-adhoc-diffusion-body]');
        var empty = modal.querySelector('[data-adhoc-diffusion-empty]');
        if (body) clearRows(body);
        if (empty) empty.hidden = true;
        setDoc(modal, null);
        setSummary(modal, null);
        setNoAccess(modal, null);
        setNote(modal, '');
        modal.classList.remove('is-loading');
    }

    function render(modal, data) {
        var resumen = (data && data.summary) || {};
        var items = (data && data.recipients) || [];

        setDoc(modal, data ? data.document : null);
        setSummary(modal, resumen);
        setNoAccess(modal, resumen);

        var body = modal.querySelector('[data-adhoc-diffusion-body]');
        var empty = modal.querySelector('[data-adhoc-diffusion-empty]');
        if (!body) return;

        clearRows(body);

        var ordenados = ordenar(items);
        var frag = document.createDocumentFragment();
        var yaHuboAcuse = false;
        for (var i = 0; i < ordenados.length; i++) {
            // La línea de corte va en la PRIMERA fila del bloque de acusados, y
            // solo si antes hubo alguna pendiente: separa lo que falta de lo que
            // consta. Sin filas pendientes delante no separa nada y no se pinta.
            var esAcuse = cubo(ordenados[i]) === 2;
            var corte = esAcuse && !yaHuboAcuse && i > 0;
            if (esAcuse) yaHuboAcuse = true;
            frag.appendChild(buildRow(ordenados[i], corte));
        }
        if (empty) body.insertBefore(frag, empty);
        else body.appendChild(frag);

        // La fila de vacío solo se enseña cuando de verdad no hay a quién
        // enseñar. Nunca en un error: ver el `catch` de `open()`.
        if (empty) empty.hidden = items.length > 0;

        // Cuatro casos, y los dos primeros son los dos vacíos que esta pantalla
        // tiene que separar (lección del modal de versiones: con una condición
        // que los junta, el diálogo acaba diciendo dos frases que se
        // contradicen).
        var asignados = (typeof resumen.assigned === 'number') ? resumen.assigned : items.length;
        var acusados = (typeof resumen.acknowledged === 'number') ? resumen.acknowledged : 0;

        if (items.length === 0) {
            // Habla la fila de vacío, que para eso está.
            setNote(modal, '');
        } else if (acusados === 0) {
            setNote(modal, 'Ninguno de los ' + asignados + ' destinatarios acusó recibo. ' +
                           'La distribución consta; la evidencia de recepción, no.');
        } else if (acusados >= asignados) {
            setNote(modal, 'Los ' + asignados + ' destinatarios acusaron recibo.');
        } else {
            setNote(modal, acusados + ' de ' + asignados + ' acusaron recibo. ' +
                           'Arriba, los que faltan.');
        }
    }

    // ==================== API PÚBLICA ====================

    /**
     * Abre el panel de difusión del documento indicado.
     *
     *   AdhocDocumentDiffusion.open(doc.id);
     *
     * El modal se abre AL INSTANTE con su estado de carga y se rellena cuando
     * llega la respuesta: abrirlo después dejaba el clic sin efecto visible
     * durante toda la petición.
     *
     * @param {number|string} documentId
     * @returns {Promise|null}
     */
    function open(documentId) {
        if (!H) {
            console.error('[adhoc] document-diffusion: falta document-list.js');
            if (U) U.showToast('No se pudo abrir la difusión del documento.', 'error');
            return null;
        }
        if (documentId === null || documentId === undefined || documentId === '') return null;

        var modal = document.querySelector(MODAL_SELECTOR);
        if (!modal) {
            console.error('[adhoc] document-diffusion: falta el modal de difusión');
            U.showToast('No se pudo abrir la difusión del documento.', 'error');
            return null;
        }

        reset(modal);
        setNote(modal, 'Cargando difusión…');
        modal.classList.add('is-loading');
        U.openModal(modal);

        if (enVuelo) enVuelo.abort();
        var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        enVuelo = ctrl;

        return U.fetchJson('/documents/' + encodeURIComponent(documentId) + '/acknowledgements',
                           ctrl ? { signal: ctrl.signal } : undefined)
            .then(function (payload) {
                if (obsoleta(ctrl, modal)) return;
                render(modal, (payload && payload.data) || null);
            })
            .catch(function (err) {
                // Abortada: o se abrió otra difusión, o la pantalla se fue. No
                // hay nada que avisar y el modal ya no es de esta petición.
                if (err && err.name === 'AbortError') return;
                if (obsoleta(ctrl, modal)) return;
                // Aquí la fila de vacío se queda ESCONDIDA, al revés que en el
                // modal de versiones. Su texto afirma algo muy concreto sobre el
                // SGC —"a este documento no se le asignó ningún destinatario"— y
                // enseñarlo cuando lo que ha fallado es la petición convierte un
                // error de red en evidencia de auditoría falsa. Lo que pasó lo
                // cuenta la línea de estado, y solo eso.
                setNote(modal, 'No se pudo cargar la difusión: ' + err.message);
                U.showToast('No se pudo cargar la difusión: ' + err.message, 'error');
            })
            .then(function () {
                // DENTRO del guard, no al lado. Fuera de él, el `.then` de una
                // petición abortada le quitaba `is-loading` al modal que ya
                // pertenece a la petición NUEVA: a los 400 ms el diálogo se veía
                // "cargado" —sin atenuar y con los clics devueltos— con la tabla
                // vacía y la nota todavía en "Cargando difusión…".
                if (enVuelo !== ctrl) return;
                enVuelo = null;
                modal.classList.remove('is-loading');
            });
    }

    /**
     * Cierra el modal y cancela lo que estuviera en vuelo.
     *
     * Lo normal es el cierre DELEGADO (`data-adhoc-modal-close`, el velo,
     * Escape), que vive en `adhoc-utils.js` y no pasa por aquí: por eso la
     * guarda que de verdad cubre las tres salidas es `obsoleta()`, no esta
     * función. Esta cancela además la petición, que es lo único que el guard no
     * puede hacer desde el `.then`.
     */
    function close() {
        var modal = document.querySelector(MODAL_SELECTOR);
        if (enVuelo) {
            enVuelo.abort();
            enVuelo = null;
        }
        if (modal) {
            U.closeModal(modal);
            reset(modal);
        }
    }

    // ==================== CICLO DE VIDA ====================

    if (U && typeof U.onReady === 'function') {
        // Con enganche: el módulo no hace nada en una pantalla que no incluya el
        // partial. Corre en la carga inicial, tras cada intercambio de HTMX y en
        // el ATRÁS.
        //
        // Y lo que hace es DEJARLO VACÍO. En el ATRÁS el DOM no lo pinta el
        // servidor: HTMX lo repone desde su caché de historial, así que el modal
        // vuelve con los destinatarios de la última consulta —nombres y correos
        // de hasta 51 personas— ya pintados dentro. `open()` los limpiaría al
        // abrirse otra vez, pero solo si alguien lo abre; mientras tanto son
        // datos del SGC colgando de una pantalla que ya no los está enseñando.
        U.onReady(MODAL_SELECTOR, function () {
            reset(document.querySelector(MODAL_SELECTOR));
        });
    }

    if (U && typeof U.onTeardown === 'function') {
        U.onTeardown(function () {
            if (enVuelo) enVuelo.abort();
            enVuelo = null;
        });
    }

    window.AdhocDocumentDiffusion = { open: open, close: close };
})();
