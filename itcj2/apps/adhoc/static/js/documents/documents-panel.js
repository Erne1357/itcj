/**
 * documents/documents-panel.js — administración de /adhoc/documentos/panel.
 *
 * Expone SOLO `window.AdhocDocumentsPanel` (IIFE, sin globales sueltas).
 *
 * QUÉ SUSTITUYE
 * -------------
 * `advanced_documents.js` del legacy (305 líneas, clase global
 * `AdminDocumentosManager`). Sus problemas, todos arreglados aquí:
 *
 *   1. `getFormTemplate()` armaba el formulario con un template literal e
 *      interpolaba `this.config.categoriasHtml` — HTML CRUDO generado por Jinja
 *      dentro de backticks. Cuatro vectores de XSS, y un nombre de catálogo con
 *      un backtick o un `${` rompía la página entera. Aquí los catálogos son
 *      JSON y cada <option> se crea con createElement + textContent.
 *   2. `mostrarAlerta`/`mostrarConfirmacion` eran dos modales caseros abiertos
 *      con `style.display='flex'`. Ahora: AdhocUtils.showToast/confirmDialog.
 *   3. El filtrado iba por índice de columna (`configMap = [2,3,…,11]`).
 *      Ahora lo hace el servidor (document-list.js).
 *   4. Cinco botones abrían un alert de "módulo en construcción" y el bloque
 *      "Historial de Versiones" era un mockup con la fecha escrita a mano.
 *      No se portan (plan §4).
 *   5. Tras iniciar un flujo hacía `window.location.reload()` con un setTimeout
 *      de 1.5 s. Aquí se recarga solo la tabla.
 *
 * CONTRATO DE API (plan §3)
 * -------------------------
 *   POST   /documents                  multipart, listas paralelas por índice
 *                                      (+ expiration_dates, + parent_ids)
 *   PATCH  /documents/{id}             multipart, campos SINGULARES (code,
 *                                      title, version, notes,
 *                                      expiration_date, los cuatro *_id, file)
 *   DELETE /documents/{id}
 *   GET    /documents/{id}             detalle (incluye current_step)
 *   GET    /documents/{id}/versions    la cadena entera (lo pide el modal
 *                                      compartido document-versions.js)
 *   POST   /documents/{id}/start-flow  {"flow_id": N}
 *
 * LO QUE AÑADE LA CADENA DE VERSIONES
 * -----------------------------------
 * Anexar una versión no edita el documento: crea uno NUEVO con `parent_ids`
 * apuntando a la versión desde la que se anexa. El servidor resuelve solo la
 * RAÍZ de la cadena (la estructura es plana, profundidad 1) y deja al resto de
 * la cadena con `is_current=false` y `status='Obsoleto'`. Es una operación con
 * consecuencia visible para todo el SGC —el documento que hasta ese momento
 * era el vigente deja de serlo—, así que el modal lo dice ANTES de guardar y
 * el toast dice después qué versión quedó vigente.
 *
 * LO QUE AÑADE LA EDICIÓN (hallazgo A14)
 * --------------------------------------
 * Los 202 documentos del SGC no se podían editar desde NINGUNA pantalla: el
 * `PATCH /documents/{id}` existía, tenía su propio permiso concedido a admin y
 * a supervisor_doc, y no lo llamaba ni un solo archivo JS. Un título mal
 * escrito o un área mal asignada solo se arreglaba borrando el documento y
 * volviéndolo a subir, lo que se llevaba por delante sus tareas y su archivo.
 *
 * El formulario es el MISMO modal del alta en modo edición
 * (`buildFields(1, prefill)`), igual que ya hacía "Anexar nueva versión": no
 * hay pantalla nueva ni edición en línea. Lo que cambia es a dónde va el
 * submit y con qué nombres —el alta manda listas paralelas (`titles`, `codes`,
 * `files`…) y el PATCH campos singulares (`title`, `code`, `file`)—, y esa
 * traducción vive en `PATCH_FIELDS`, en un solo sitio.
 *
 * Qué fila se puede editar NO lo decide este archivo: llega resuelto por el
 * servidor en cada documento (`is_editable` y `file_replaceable` de
 * `document_out`). Un documento que ya pasó por el flujo de aprobación es
 * inmutable —se corrige anexando una versión nueva— y una versión superada no
 * se edita nunca. El botón deshabilitado es comodidad: quien impone la regla
 * es `AdhocDocumentService.update`, que responde 409, y ese 409 se enseña TAL
 * CUAL. Es la lección que dejó la vigencia documental: `DOCUMENT_STATUSES_
 * STARTABLE` solo la respetaba este JS, así que la API dejaba arrancar un
 * flujo sobre un documento obsoleto. Una regla que solo vive en el navegador
 * no es una regla.
 */
(function () {
    'use strict';

    var U = window.AdhocUtils;
    var List = window.AdhocDocumentList;
    var H = List ? List.helpers : null;

    var TABLE_ID = 'adhoc-doc-panel-table';

    //: Estatus desde los que se puede arrancar el flujo de aprobación.
    //: 'Obsoleto' es TERMINAL: una version superada no vuelve a flujo, se crea
    //: una version nueva. Espeja DOCUMENT_STATUSES_STARTABLE de constants.py.
    var STARTABLE = { 'Borrador': true, 'Rechazado': true };

    //: Traducción de los `name` del formulario a los del PATCH. El modal es el
    //: mismo en alta y en edición, pero los dos endpoints NO comparten
    //: contrato: `POST /documents` recibe listas paralelas por índice
    //: (`titles`, `codes`, `files`…) y `PATCH /documents/{id}` recibe el campo
    //: en SINGULAR (`title`, `code`, `file`).
    //: Mandarle al PATCH los nombres del alta no da un error legible: el
    //: endpoint no reconocería ni un campo, contestaría 400 "No se envió ningún
    //: cambio" y parecería un fallo del servidor.
    //: `notes` es el único que ya coincide —el textarea del alta se llama así,
    //: en singular—, y aun así se lista: una tabla con una excepción implícita
    //: es una excepción que alguien reintroduce.
    //: NO están aquí `status` ni `parent_ids`, a propósito: el estatus lo mueve
    //: el motor de flujo (el PATCH solo admite los de DOCUMENT_STATUSES_VIA_
    //: PATCH y esta pantalla no lo edita) y la cadena de versiones solo la
    //: mueve el POST al anexar.
    var PATCH_FIELDS = [
        ['titles', 'title'],
        ['codes', 'code'],
        ['versions', 'version'],
        ['notes', 'notes'],
        ['expiration_dates', 'expiration_date'],
        ['category_ids', 'category_id'],
        ['area_ids', 'area_id'],
        ['process_ids', 'process_id'],
        ['classification_ids', 'classification_id']
    ];

    // ==================== CONSTRUCTORES DE CAMPO ====================

    function labelFor(id, textValue, required) {
        var label = document.createElement('label');
        label.className = 'form-label adhoc-label';
        label.setAttribute('for', id);
        label.textContent = textValue;
        if (required) {
            var star = document.createElement('span');
            star.className = 'adhoc-required';
            star.setAttribute('aria-hidden', 'true');
            star.textContent = '*';
            label.appendChild(star);
        }
        return label;
    }

    function fieldBox(id, labelText, control, opts) {
        var o = opts || {};
        var box = document.createElement('div');
        box.className = 'adhoc-field' + (o.full ? ' adhoc-field-full' : '');
        box.appendChild(labelFor(id, labelText, o.required));
        // `warn` va ENTRE el rótulo y el control, no debajo con la ayuda: es
        // una consecuencia irreversible (el archivo anterior se borra del
        // disco), y una consecuencia se lee ANTES de actuar sobre el campo, no
        // después de haber elegido el fichero.
        if (o.warn) box.appendChild(o.warn);
        box.appendChild(control);
        if (o.help) {
            var help = document.createElement('div');
            help.className = 'form-text adhoc-field-help';
            help.textContent = o.help;
            box.appendChild(help);
        }
        return box;
    }

    /**
     * Párrafo de aviso con icono, todo por textContent.
     * Lo usan los dos estados del campo de archivo en edición: el aviso ámbar
     * de "esto borra el anterior" y la nota apagada de "aquí no se sustituye".
     * Comparte forma con el aviso de versión superada del modal, que ya vive en
     * la plantilla, para que las dos consecuencias de esta pantalla se lean
     * igual.
     */
    function noteBox(cssClass, icon, message) {
        var box = document.createElement('p');
        box.className = cssClass;
        var glyph = document.createElement('i');
        glyph.className = icon;
        glyph.setAttribute('aria-hidden', 'true');
        box.appendChild(glyph);
        var text = document.createElement('span');
        text.textContent = message;
        box.appendChild(text);
        return box;
    }

    function makeInput(id, name, type, value, opts) {
        var o = opts || {};
        var input = document.createElement('input');
        input.type = type;
        input.id = id;
        input.name = name;
        input.className = 'form-control';
        if (value !== undefined && value !== null) input.value = String(value);
        if (o.maxLength) input.maxLength = o.maxLength;
        if (o.required) input.required = true;
        if (o.accept) input.accept = o.accept;
        if (o.placeholder) input.placeholder = o.placeholder;
        return input;
    }

    function makeTextarea(id, name, value, rows) {
        var area = document.createElement('textarea');
        area.id = id;
        area.name = name;
        area.className = 'form-control';
        area.rows = rows || 2;
        area.value = value ? String(value) : '';    // .value, nunca innerHTML
        return area;
    }

    /**
     * <select> de catálogo construido desde JSON.
     * El legacy inyectaba aquí `${this.config.categoriasHtml}`: HTML del
     * servidor concatenado dentro de un template literal.
     *
     * `selected` es el objeto anidado que ya trae la fila (`doc.area`,
     * `doc.category`… de `document_out`: `{id, name}`), no un id pelado. Se pide
     * el objeto entero por el caso de abajo: si el valor guardado NO está entre
     * las opciones, hay que pintarlo igualmente, y para eso hace falta su
     * nombre. Un id suelto también se acepta —el alta no tiene valor previo—,
     * pero entonces la opción conservada solo puede rotularse con el número.
     *
     * Es el gotcha 22 de la app, otra vez: un <select> que se llena de un
     * catálogo FILTRADO borra lo que no esté en él. `_document_catalogs` solo
     * manda las áreas con `is_active`, mientras que la relación del documento
     * resuelve igual —dar de baja un área no la desengancha de sus documentos—,
     * así que un documento con el área dada de baja abría el modal en el
     * placeholder y al guardar mandaba `area_id=''`, que en este PATCH significa
     * "limpia la columna". El área se perdía sin que nadie la hubiera tocado.
     * Pasó ya con `responsible_id` en 145 de 276 incidencias; el arreglo es el
     * mismo que hace `WorkItems.fillSelect`.
     */
    function makeCatalogSelect(id, name, items, selected, placeholder) {
        var select = document.createElement('select');
        select.id = id;
        select.name = name;
        select.className = 'form-select';

        // Admite `{id, name}` o un id pelado.
        var selectedId = (selected && typeof selected === 'object')
            ? selected.id : selected;
        var chosen = (selectedId === null || selectedId === undefined)
            ? '' : String(selectedId);
        var matched = false;

        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = placeholder || 'Seleccionar...';
        select.appendChild(blank);

        for (var i = 0; i < (items || []).length; i++) {
            var option = document.createElement('option');
            option.value = String(items[i].id);
            option.textContent = String(items[i].name);   // textContent
            if (chosen && option.value === chosen) {
                option.selected = true;
                matched = true;
            }
            select.appendChild(option);
        }

        // El valor guardado ya no está en el catálogo (área dada de baja, o un
        // catálogo que cambió después de renderizar la página). Se conserva como
        // opción propia para que editar el documento no lo borre, y se rotula
        // para que el usuario vea que ESO es lo que tiene, no un hueco. Sigue
        // siendo posible vaciarlo a mano eligiendo el placeholder, que es la
        // semántica que `editFormData` quiere preservar.
        if (chosen && !matched) {
            var kept = document.createElement('option');
            kept.value = chosen;
            var label = (selected && typeof selected === 'object' && selected.name)
                ? String(selected.name) : ('#' + chosen);
            kept.textContent = label + ' (fuera del catálogo)';
            kept.selected = true;
            select.appendChild(kept);
        }
        return select;
    }

    // ==================== INSTANCIA ====================

    function Panel(root) {
        this.root = root;
        this.data = (U && typeof U.pageData === 'function') ? U.pageData() : {};

        this.canCreate = !!this.data.can_create;
        //: Permiso `adhoc.documents.api.update`. Enciende el botón "Editar";
        //: que ESA fila se pueda editar lo dice `doc.is_editable`, que viene
        //: del servidor. Los dos hacen falta: el permiso es de la persona, la
        //: regla es del documento.
        this.canUpdate = !!this.data.can_update;
        this.canDelete = !!this.data.can_delete;
        this.canDownload = !!this.data.can_download;
        this.canStartFlow = !!this.data.can_start_flow;
        this.accept = (this.data.accept || []).join(',');

        this.modal = document.querySelector('[data-adhoc-doc-modal]');
        this.form = this.modal ? this.modal.querySelector('[data-adhoc-doc-form]') : null;
        this.fields = this.modal ? this.modal.querySelector('[data-adhoc-doc-fields]') : null;
        this.qtyBox = this.modal ? this.modal.querySelector('[data-adhoc-doc-qty-box]') : null;
        this.qtySelect = this.modal ? this.modal.querySelector('[data-adhoc-doc-qty]') : null;
        this.modalTitle = this.modal ? this.modal.querySelector('[data-adhoc-doc-modal-title]') : null;
        this.versionWarning = this.modal
            ? this.modal.querySelector('[data-adhoc-doc-version-warning]') : null;
        this.versionWarningDoc = this.modal
            ? this.modal.querySelector('[data-adhoc-doc-version-warning-doc]') : null;

        //: Documento del que se está anexando una versión, o null en el alta
        //: normal. Decide el aviso del modal y el texto del toast final.
        this.versionSource = null;

        //: Modo del modal compartido: 'new' (alta masiva), 'version' (anexar) o
        //: 'edit'. Decide el destino del submit, el campo de archivo y el
        //: rótulo del botón de guardar. Vive en la instancia y no en el DOM
        //: porque el modal es UN nodo reutilizado por los tres.
        this.mode = 'new';
        //: Id del documento en edición, o null fuera de ese modo.
        this.editingId = null;

        this.flowModal = document.querySelector('[data-adhoc-flow-modal]');
        this.flowSelect = this.flowModal ? this.flowModal.querySelector('[data-adhoc-flow-select]') : null;
        this.flowDoc = this.flowModal ? this.flowModal.querySelector('[data-adhoc-flow-doc]') : null;
        this.flowDocId = null;

        this.list = null;
    }

    Panel.prototype.init = function () {
        var self = this;
        // Los filtros que vengan en la URL (el enlace del contador de vencidos
        // del dashboard, p. ej.) los vuelca `document-list.js` sobre la barra
        // antes de su primera consulta: es el mismo volcado que en la pantalla
        // de consulta, así que vive con el resto del contrato de la barra —qué
        // nodos son filtros, cómo se lee una casilla— y no una copia por
        // pantalla que diverge sin que nadie se entere.
        this.list = List.create(this.root, {
            tableId: TABLE_ID,
            perPage: this.data.per_page,
            initialFilters: this.data.initial_filters,
            buildRow: function (doc) { return self.buildRow(doc); }
        });
        this.bind();
        return this;
    };

    // ---------- fila ----------

    Panel.prototype.buildRow = function (doc) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-id', String(doc.id));

        var tdFile = document.createElement('td');
        tdFile.setAttribute('data-adhoc-cell', 'file');
        tdFile.className = 'adhoc-col-center';
        // Legacy: icono de PDF en rojo, sin pastilla (`.icon-btn-blue`).
        tdFile.appendChild(H.fileCell(doc, this.canDownload, {
            icon: 'fa-solid fa-file-pdf',
            linkClass: 'adhoc-icon-action adhoc-icon-danger'
        }));
        tr.appendChild(tdFile);

        H.cell(tr, 'code', H.text(doc.code, '—'), 'adhoc-cell-nowrap');

        // El título va ACOTADO a dos líneas, no suelto: con doce columnas es la
        // única celda de texto libre que puede reclamar ancho sin techo, y un
        // título del SGC de 120 caracteres empujaba la mitad de la tabla fuera
        // de la pantalla. El texto íntegro queda en el `title` del <td>.
        H.clampCell(tr, 'title', H.text(doc.title));

        // — versión + estatus en una sola celda, como el legacy —
        var tdVersion = document.createElement('td');
        tdVersion.setAttribute('data-adhoc-cell', 'version');
        tdVersion.className = 'adhoc-cell-nowrap';
        var version = document.createElement('span');
        version.className = 'adhoc-doc-version';
        version.textContent = 'v' + H.text(doc.version);
        tdVersion.appendChild(version);
        tdVersion.appendChild(H.statusBadge(doc.status));
        // "Superada" solo aparece con la casilla "Ver versiones anteriores"
        // marcada: por defecto la lista trae únicamente la punta de cada
        // cadena y el badge no tendría a quién distinguir.
        var superada = H.currentBadge(doc);
        if (superada) tdVersion.appendChild(superada);
        tr.appendChild(tdVersion);

        // Vigencia: la fecha y, detrás, el badge rojo o ámbar. El tono lo
        // decide el servidor con `expiry_state`; aquí no se hace aritmética de
        // fechas contra el reloj del cliente.
        H.expiryCell(tr, doc);

        H.cell(tr, 'category', H.named(doc.category));
        H.cell(tr, 'area', H.named(doc.area));
        H.cell(tr, 'process', H.named(doc.process));
        H.cell(tr, 'classification', H.named(doc.classification));
        H.clampCell(tr, 'notes', H.text(doc.notes));
        H.cell(tr, 'approval_date', H.isoDate(doc.approval_date) || 'Pendiente',
               'adhoc-cell-nowrap');

        var tdActions = document.createElement('td');
        tdActions.setAttribute('data-adhoc-cell', 'actions');
        tdActions.className = 'adhoc-col-end';
        tdActions.appendChild(this.buildActions(doc));
        tr.appendChild(tdActions);

        return tr;
    };

    Panel.prototype.buildActions = function (doc) {
        var box = document.createElement('div');
        box.className = 'adhoc-actions';

        if (this.canStartFlow && STARTABLE[doc.status]) {
            box.appendChild(H.iconButton('start-flow', 'fa-solid fa-stamp',
                                         'Sellar e iniciar el flujo de aprobación'));
        }
        if (doc.status === 'En Revisión') {
            box.appendChild(H.iconButton('flow-info', 'fa-solid fa-clock-rotate-left',
                                         'Ver paso actual del flujo', 'adhoc-icon-info'));
        }
        // El historial se pinta SIEMPRE, también en un documento de una sola
        // versión: la fila no sabe si tiene hijos (`parent_id` solo dice si
        // ella es hija) y averiguarlo por fila serían 25 peticiones por página.
        // Es el propio modal el que dice "es la única versión" cuando toca.
        box.appendChild(H.versionButton(doc));

        // "Editar" va ANTES de "Anexar versión" porque es la acción menor de
        // las dos: corregir una errata no cambia cuál es el documento vigente,
        // anexar sí. Leídas de izquierda a derecha, las acciones de la fila van
        // de menos a más consecuencia y acaban en el rojo del borrado.
        if (this.canUpdate) {
            box.appendChild(this.editButton(doc));
        }
        if (this.canCreate) {
            box.appendChild(H.iconButton('new-version', 'fa-solid fa-file-circle-plus',
                                         'Anexar nueva versión'));
        }
        if (this.canDelete) {
            box.appendChild(H.iconButton('delete', 'fa-solid fa-trash',
                                         'Eliminar documento', 'adhoc-icon-danger'));
        }
        return box;
    };

    /**
     * Botón "Editar" de la fila, habilitado o no según lo que diga el servidor.
     *
     * Se pinta SIEMPRE que el usuario tenga el permiso, también sobre los 198
     * documentos que hoy no se pueden editar, y ahí está la decisión: un botón
     * que desaparece deja al usuario buscándolo —"¿esta fila no tiene editar o
     * es que no puedo?"— y la respuesta real, que es una regla del SGC, no se
     * cuenta en ninguna parte. Deshabilitado, la pantalla dice a la vez que la
     * acción existe y por qué no está disponible AQUÍ.
     *
     * `disabled` no recibe foco, así que el `title` no llega a un lector de
     * pantalla: `H.iconButton` pone el mismo texto en `aria-label`. Y la hoja
     * del panel le devuelve los eventos de ratón (la base los anula con
     * `pointer-events: none`) para que ese `title` se pueda leer al pasar por
     * encima, que es como se descubre el motivo con el ratón.
     *
     * @param {Object} doc fila de `document_out()`
     * @returns {HTMLButtonElement}
     */
    Panel.prototype.editButton = function (doc) {
        if (doc.is_editable) {
            return H.iconButton('edit', 'fa-solid fa-pen-to-square',
                                'Editar documento');
        }

        // Dos motivos distintos, dos textos distintos. Decirle "no se puede
        // editar" a secas a quien está mirando un 'Aprobado' y a quien mira una
        // versión superada esconde que la salida es la misma —anexar una
        // versión— pero el porqué no lo es.
        var motivo = (doc.is_current === false)
            ? 'Es una versión superada: el histórico no se edita'
            : 'Un documento en estado ' + H.text(doc.status, 'no editable') +
              ' no se edita; anexa una versión nueva';

        var btn = H.iconButton('edit', 'fa-solid fa-pen-to-square', motivo,
                               'adhoc-icon-muted');
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
        return btn;
    };

    // ---------- alta masiva ----------

    Panel.prototype.openNew = function () {
        if (!this.modal) return;
        if (this.modalTitle) {
            this.modalTitle.innerHTML = '<i class="fa-solid fa-file-circle-plus me-2"></i>';
            this.modalTitle.appendChild(document.createTextNode('Añadir Documento'));
        }
        if (this.qtyBox) this.qtyBox.hidden = false;
        // Alta normal: no hay cadena, así que el hidden `parent_ids` va vacío y
        // el servidor lo coacciona a None. El aviso de "quedará obsoleta" no
        // aplica y se apaga: el modal es el MISMO nodo en los tres modos, así
        // que cada uno deja el estado como se lo encontró.
        this.mode = 'new';
        this.editingId = null;
        this.setSaveLabel('Aceptar');
        this.versionSource = null;
        this.setVersionWarning(null);
        this.buildFields();
        this.show(this.modal);
    };

    /**
     * Rótulo del botón de guardar, conservando su icono.
     *
     * El disquete es el icono de "guardar" en toda la app y lo pone la
     * plantilla; aquí se reaprovecha el nodo en vez de reescribir el innerHTML,
     * que dejaría el markup del icono escrito en dos sitios y a la espera de
     * divergir. El texto va por textContent.
     */
    Panel.prototype.setSaveLabel = function (label) {
        var btn = this.modal ? this.modal.querySelector('[data-adhoc-doc-save]') : null;
        if (!btn) return;
        var glyph = btn.querySelector('i');
        btn.textContent = '';
        if (glyph) btn.appendChild(glyph);
        btn.appendChild(document.createTextNode(' ' + label));
    };

    /**
     * Enciende o apaga el aviso de consecuencia del modal.
     * Solo se reescribe el <strong>, con textContent: el resto de la frase es
     * markup de la plantilla y no se toca.
     */
    Panel.prototype.setVersionWarning = function (doc) {
        if (!this.versionWarning) return;
        this.versionWarning.hidden = !doc;
        if (!doc || !this.versionWarningDoc) return;

        var quien = H.text(doc.code) || H.text(doc.title, 'este documento');
        this.versionWarningDoc.textContent =
            'la versión ' + H.text(doc.version, 'actual') + ' de ' + quien;
    };

    /**
     * Nueva versión de un documento existente. Comportamiento del legacy que se
     * conserva: se crea un documento NUEVO con el mismo código y título y la
     * versión incrementada en 1.0 (`advanced_documents.js:184`), no se edita el
     * original — así el histórico del SGC no se pierde.
     *
     * Lo que el legacy NO hacía: enlazar las dos. Ahora el alta viaja con
     * `parent_ids = doc.id` y es el servidor quien resuelve la RAÍZ de la
     * cadena y apaga la anterior (`is_current=false`, `status='Obsoleto'`).
     * Desde aquí se manda el id del documento del que se anexa y nada más: la
     * jerarquía no se calcula en el navegador.
     *
     * La fecha de vigencia se arrastra como propuesta, no como copia ciega: una
     * versión nueva casi siempre renueva la vigencia, y llegar con la fecha
     * anterior ya escrita hace evidente que hay que moverla. Vacío se vería
     * como "este documento no caduca", que es justo lo contrario.
     */
    Panel.prototype.openNewVersion = function (doc) {
        if (!this.modal) return;
        if (this.modalTitle) {
            this.modalTitle.innerHTML = '<i class="fa-solid fa-copy me-2"></i>';
            this.modalTitle.appendChild(document.createTextNode('Registrar nueva versión'));
        }
        if (this.qtyBox) this.qtyBox.hidden = true;

        this.mode = 'version';
        this.editingId = null;
        this.setSaveLabel('Aceptar');

        var current = parseFloat(doc.version);
        var next = isNaN(current) ? '1.0' : (current + 1.0).toFixed(1);

        this.versionSource = doc;
        this.setVersionWarning(doc);

        this.buildFields(1, {
            code: doc.code,
            title: doc.title,
            version: next,
            notes: doc.notes,
            parent_id: doc.id,
            expiration_date: doc.expiration_date,
            // Los objetos enteros, no sus ids: ver `makeCatalogSelect`. Aquí el
            // valor perdido solo se perdería en la COPIA, pero se pierde igual.
            category: doc.category,
            area: doc.area,
            process: doc.process,
            classification: doc.classification
        });
        this.show(this.modal);
    };

    /**
     * Corrección en sitio de un documento (hallazgo A14).
     *
     * Reutiliza el modal del alta con un solo bloque y los valores actuales
     * dentro (`buildFields(1, prefill)`), igual que "Anexar nueva versión": son
     * el mismo formulario con distinto destino, y duplicarlo habría dejado dos
     * rejillas de campos que se desincronizan en cuanto se añada uno.
     *
     * Lo que NO viaja en el prefill es `parent_id`: editar no toca la cadena de
     * versiones. El hidden `parent_ids` sale vacío y, además, el PATCH ni
     * siquiera lo lee (`PATCH_FIELDS`).
     *
     * `file_replaceable` y `has_file` no son campos del formulario: le dicen a
     * `fileField` si pintar el input de archivo o la nota de que ahí no se
     * sustituye nada. Los dos vienen del servidor.
     */
    Panel.prototype.openEdit = function (doc) {
        if (!this.modal) return;
        if (this.modalTitle) {
            this.modalTitle.innerHTML = '<i class="fa-solid fa-pen-to-square me-2"></i>';
            this.modalTitle.appendChild(document.createTextNode('Editar documento'));
        }
        if (this.qtyBox) this.qtyBox.hidden = true;

        this.mode = 'edit';
        this.editingId = doc.id;
        this.setSaveLabel('Guardar cambios');
        // Editar no supera ninguna versión: el aviso ámbar del anexado se apaga.
        this.versionSource = null;
        this.setVersionWarning(null);

        this.buildFields(1, {
            code: doc.code,
            title: doc.title,
            version: doc.version,
            notes: doc.notes,
            expiration_date: doc.expiration_date,
            // Los objetos anidados de `document_out`, no sus ids: si el valor
            // guardado ya no está en el catálogo, `makeCatalogSelect` necesita
            // su nombre para conservarlo. Con el id pelado el desplegable caía
            // al placeholder y el PATCH mandaba '' —que aquí significa "limpia
            // la columna"—, así que corregir una errata del título borraba el
            // área del documento sin avisar.
            category: doc.category,
            area: doc.area,
            process: doc.process,
            classification: doc.classification,
            file_replaceable: !!doc.file_replaceable,
            has_file: !!doc.has_file
        });
        this.show(this.modal);
    };

    Panel.prototype.buildFields = function (count, prefill) {
        if (!this.fields) return;
        var qty = count;
        if (!qty) qty = this.qtySelect ? (parseInt(this.qtySelect.value, 10) || 1) : 1;

        this.fields.textContent = '';
        for (var i = 1; i <= qty; i++) {
            this.fields.appendChild(this.buildBlock(i, qty, prefill));
        }
        var first = this.fields.querySelector('input, select, textarea');
        if (first) first.focus();
    };

    Panel.prototype.buildBlock = function (index, total, prefill) {
        var p = prefill || {};
        var suffix = '-' + index;
        var block = document.createElement('div');
        block.className = 'adhoc-fieldset';

        if (total > 1) {
            var title = document.createElement('p');
            title.className = 'adhoc-fieldset-title';
            title.textContent = 'Registro #' + index;
            block.appendChild(title);
        }

        var grid = document.createElement('div');
        grid.className = 'adhoc-form-grid';

        grid.appendChild(fieldBox(
            'adhoc-doc-title' + suffix, 'Nombre del documento',
            makeInput('adhoc-doc-title' + suffix, 'titles', 'text', p.title || '',
                      { maxLength: 200, required: true }),
            { full: true, required: true }));

        grid.appendChild(fieldBox(
            'adhoc-doc-code' + suffix, 'Código',
            makeInput('adhoc-doc-code' + suffix, 'codes', 'text', p.code || '',
                      { maxLength: 50 })));

        grid.appendChild(fieldBox(
            'adhoc-doc-version' + suffix, 'Versión',
            makeInput('adhoc-doc-version' + suffix, 'versions', 'text', p.version || '1.0',
                      { maxLength: 10 })));

        grid.appendChild(fieldBox(
            'adhoc-doc-expiration' + suffix, 'Vigencia hasta',
            makeInput('adhoc-doc-expiration' + suffix, 'expiration_dates', 'date',
                      H.isoDate(p.expiration_date)),
            { help: 'Opcional. Pasada esta fecha el documento aparece como vencido.' }));

        grid.appendChild(fieldBox(
            'adhoc-doc-category' + suffix, 'Categoría',
            makeCatalogSelect('adhoc-doc-category' + suffix, 'category_ids',
                              this.data.categories, p.category)));

        grid.appendChild(fieldBox(
            'adhoc-doc-area' + suffix, 'Área',
            makeCatalogSelect('adhoc-doc-area' + suffix, 'area_ids',
                              this.data.areas, p.area)));

        grid.appendChild(fieldBox(
            'adhoc-doc-process' + suffix, 'Proceso',
            makeCatalogSelect('adhoc-doc-process' + suffix, 'process_ids',
                              this.data.processes, p.process)));

        grid.appendChild(fieldBox(
            'adhoc-doc-classification' + suffix, 'Clasificación',
            makeCatalogSelect('adhoc-doc-classification' + suffix, 'classification_ids',
                              this.data.classifications, p.classification)));

        grid.appendChild(fieldBox(
            'adhoc-doc-notes' + suffix, 'Notas',
            makeTextarea('adhoc-doc-notes' + suffix, 'notes', p.notes, 2),
            { full: true }));

        grid.appendChild(this.fileField(suffix, p));

        block.appendChild(grid);

        // Cadena de versiones. Va OCULTO y siempre presente —también en el alta
        // normal, donde viaja vacío— porque `parent_ids` es una de las listas
        // paralelas del multipart: si un bloque no lo emitiera, el índice de
        // todos los siguientes se desplazaría y cada versión acabaría colgando
        // de la cadena equivocada. La cadena no se elige a mano: no lleva label
        // ni id, solo el name que espera la API.
        var parent = document.createElement('input');
        parent.type = 'hidden';
        parent.name = 'parent_ids';
        parent.value = (p.parent_id === null || p.parent_id === undefined)
            ? '' : String(p.parent_id);
        block.appendChild(parent);

        return block;
    };

    /**
     * El campo "Archivo" del bloque, que no es el mismo en los tres modos.
     *
     * En alta y al anexar una versión va siempre: son documentos nuevos y no
     * hay nada que destruir. En EDICIÓN depende de `file_replaceable`, que trae
     * la fila del servidor y es más estrecho que `is_editable`: solo un
     * 'Borrador' admite que le cambien el binario debajo. Un 'Rechazado' acepta
     * que le corrijan el título, pero no el PDF, porque sus validadores
     * rechazaron ESE archivo y la decisión quedó escrita en
     * `adhoc_task_approvals`.
     *
     * Cuando no se puede sustituir, el hueco NO se deja vacío: se explica. Un
     * formulario al que le falta un campo sin decir por qué se lee como un
     * error de la pantalla.
     *
     * El aviso de borrado va aquí y no en un `confirmDialog`: la consecuencia
     * hay que leerla mientras se elige el archivo, no en un sí/no que se cierra
     * en dos segundos con el fichero ya seleccionado.
     */
    Panel.prototype.fileField = function (suffix, p) {
        var id = 'adhoc-doc-file' + suffix;

        if (this.mode !== 'edit') {
            return fieldBox(id, 'Archivo',
                makeInput(id, 'files', 'file', null, { accept: this.accept }),
                { full: true, help: 'Opcional. Un archivo por documento.' });
        }

        if (p.file_replaceable) {
            return fieldBox(id, 'Archivo',
                makeInput(id, 'files', 'file', null, { accept: this.accept }),
                {
                    full: true,
                    help: 'Déjalo vacío y el archivo actual no se toca.',
                    warn: noteBox(
                        'adhoc-doc-file-warning',
                        'fa-solid fa-triangle-exclamation',
                        p.has_file
                            ? 'Al guardar, el archivo que elijas SUSTITUYE al ' +
                              'actual: el anterior se BORRA DEL DISCO y no se ' +
                              'puede recuperar. Para conservar los dos, anexa ' +
                              'una versión nueva en lugar de editar esta.'
                            : 'Este documento todavía no tiene archivo. El que ' +
                              'elijas queda como suyo al guardar; a partir de ' +
                              'ahí, sustituirlo BORRA DEL DISCO el anterior y ' +
                              'no se puede recuperar.')
                });
        }

        var box = document.createElement('div');
        box.className = 'adhoc-field adhoc-field-full';
        // Rótulo en <span> y no en <label>: no hay control al que apuntar, y un
        // `for` que no resuelve es peor que no tenerlo.
        var caption = document.createElement('span');
        caption.className = 'form-label adhoc-label';
        caption.textContent = 'Archivo';
        box.appendChild(caption);
        box.appendChild(noteBox(
            'adhoc-doc-file-locked', 'fa-solid fa-lock',
            'El archivo de un documento que ya pasó por el flujo de aprobación ' +
            'no se sustituye: sus validadores revisaron ese archivo. Para ' +
            'cambiarlo, anexa una versión nueva.'));
        return box;
    };

    // ---------- envío del modal (alta, versión y edición) ----------

    /**
     * Único submit del modal, para los tres modos.
     *
     * Lo que cambia entre alta y edición es la PETICIÓN (verbo, URL, cuerpo) y
     * la frase del toast; todo lo demás —validar que hay título, deshabilitar el
     * botón mientras vuela, cerrar, recargar la tabla y enseñar el error— es
     * idéntico, así que se escribe una vez. Cada modo devuelve su "plan" y este
     * método lo ejecuta: un segundo submit copiado habría divergido en el primer
     * arreglo que se aplicara solo a uno de los dos.
     *
     * `plan` es `null` cuando falla la validación de cliente; el aviso ya lo dio
     * quien lo construyó.
     */
    Panel.prototype.submit = function () {
        var self = this;
        var btn = this.modal.querySelector('[data-adhoc-doc-save]');

        var plan = (this.mode === 'edit') ? this.editRequest() : this.createRequest();
        if (!plan) return;

        this.busy(btn, true);
        U.fetchJson(plan.url, plan.options)
            .then(function (payload) {
                U.showToast(plan.done(payload), 'success');
                self.hide(self.modal);
                return self.list.reload();
            })
            .catch(function (err) {
                // El 409 del gate de edición llega aquí con el texto del
                // SERVIDOR (`extractError` lo saca de {"error": ...}) y se
                // enseña TAL CUAL, sin traducir ni resumir: la regla la conoce
                // `AdhocDocumentService.update` —qué estados admiten edición,
                // por qué el archivo es más estrecho que el resto— y una segunda
                // redacción en el navegador se queda vieja el día que cambie.
                U.showToast(err.message, 'error');
            })
            .then(function () {
                self.busy(btn, false);
            });
    };

    /** Alta masiva y anexado de versión: POST multipart con listas paralelas. */
    Panel.prototype.createRequest = function () {
        var titles = this.form.querySelectorAll('[name="titles"]');
        var some = false;

        for (var i = 0; i < titles.length; i++) {
            if (titles[i].value.trim()) { some = true; break; }
        }
        if (!some) {
            U.showToast('Captura al menos el nombre de un documento.', 'warning');
            return null;
        }

        // Se captura ANTES del envío: `hide()` no lo borra, pero el usuario
        // puede volver a abrir el modal en modo alta mientras vuela la petición.
        var origen = this.versionSource;

        return {
            url: '/documents',
            // FormData del <form>: conserva el orden del DOM, así que las listas
            // paralelas (titles/codes/…/files/expiration_dates/parent_ids)
            // llegan alineadas por índice.
            options: { method: 'POST', body: new FormData(this.form) },
            done: function (payload) {
                var total = (payload && payload.total) || 0;
                var creado = ((payload && payload.data) || [])[0] || {};
                if (!origen) return total + ' documento(s) registrado(s).';
                // El aviso del modal decía lo que IBA a pasar; este dice lo que
                // pasó, y con números: cuál manda ahora y cuál dejó de mandar.
                // Sin esto, la fila anterior simplemente desaparece de la tabla
                // (la lista oculta las superadas) y parece que se ha borrado.
                return 'Versión ' + H.text(creado.version, 'nueva') + ' de ' +
                    (H.text(creado.code) || H.text(creado.title, 'el documento')) +
                    ' registrada: es la vigente. La versión ' +
                    H.text(origen.version, 'anterior') + ' quedó como Obsoleta.';
            }
        };
    };

    /** Corrección en sitio: PATCH multipart con los campos en singular. */
    Panel.prototype.editRequest = function () {
        var id = this.editingId;
        if (!id) return null;

        var title = this.form.querySelector('[name="titles"]');
        if (!title || !title.value.trim()) {
            // El servidor lo rechaza igual (400 "El título del documento no
            // puede quedar vacío"); avisarlo aquí ahorra el viaje y deja el
            // formulario tal como estaba, con lo escrito dentro.
            U.showToast('El nombre del documento no puede quedar vacío.', 'warning');
            return null;
        }

        return {
            url: '/documents/' + encodeURIComponent(id),
            options: { method: 'PATCH', body: this.editFormData() },
            done: function (payload) {
                var doc = (payload && payload.data) || {};
                return 'Cambios guardados en ' +
                    (H.text(doc.code) || H.text(doc.title, 'el documento')) + '.';
            }
        };
    };

    /**
     * Cuerpo del PATCH: un campo por control, con el nombre SINGULAR que espera
     * la API (`PATCH_FIELDS`).
     *
     * No se reaprovecha `new FormData(this.form)` como en el alta porque ese
     * atajo mandaría los nombres en plural y el endpoint no reconocería ni uno:
     * contestaría 400 "No se envió ningún cambio" con el formulario lleno.
     *
     * El valor VACÍO sí se manda. En este PATCH `''` significa "limpia la
     * columna" y ausente significa "no la toques" —el endpoint declara sus Form
     * como listas justo para poder distinguirlos—, así que filtrar los vacíos
     * dejaría campos que desde la UI no habría forma de borrar: quitarle la
     * vigencia a un documento que dejó de caducar, por ejemplo.
     *
     * El archivo es la única excepción: sin fichero elegido NO se manda su
     * parte, porque mandarla vacía sería pedir el reemplazo del actual. Ese
     * input solo existe si el servidor dijo `file_replaceable`.
     */
    Panel.prototype.editFormData = function () {
        var body = new FormData();

        for (var i = 0; i < PATCH_FIELDS.length; i++) {
            var control = this.form.querySelector('[name="' + PATCH_FIELDS[i][0] + '"]');
            if (!control) continue;
            body.append(PATCH_FIELDS[i][1], control.value);
        }

        var file = this.form.querySelector('input[type="file"][name="files"]');
        if (file && file.files && file.files.length) {
            body.append('file', file.files[0]);
        }
        return body;
    };

    // ---------- flujo de aprobación ----------

    Panel.prototype.openFlow = function (doc) {
        if (!this.flowModal) return;
        var flows = this.data.flows || [];
        if (!flows.length) {
            U.showToast('No hay flujos de aprobación configurados.', 'warning');
            return;
        }

        this.flowDocId = doc.id;
        if (this.flowDoc) {
            this.flowDoc.textContent =
                H.text(doc.code, 'Sin código') + ' · ' + H.text(doc.title) +
                ' (v' + H.text(doc.version) + ')';
        }
        if (this.flowSelect) {
            this.flowSelect.textContent = '';
            var blank = document.createElement('option');
            blank.value = '';
            blank.textContent = 'Selecciona el flujo...';
            this.flowSelect.appendChild(blank);
            for (var i = 0; i < flows.length; i++) {
                var option = document.createElement('option');
                option.value = String(flows[i].id);
                option.textContent = String(flows[i].name);   // textContent
                this.flowSelect.appendChild(option);
            }
        }
        this.show(this.flowModal);
    };

    Panel.prototype.startFlow = function () {
        var self = this;
        var btn = this.flowModal.querySelector('[data-adhoc-flow-start]');
        var flowId = this.flowSelect ? this.flowSelect.value : '';

        if (!flowId) {
            U.showToast('Selecciona un flujo de la lista para iniciar.', 'warning');
            return;
        }

        this.busy(btn, true);
        U.fetchJson('/documents/' + encodeURIComponent(this.flowDocId) + '/start-flow', {
            method: 'POST',
            body: JSON.stringify({ flow_id: parseInt(flowId, 10) })
        }).then(function (payload) {
            var data = (payload && payload.data) || {};
            U.showToast(data.message || 'Flujo de aprobación iniciado.', 'success');
            self.hide(self.flowModal);
            return self.list.reload();
        }).catch(function (err) {
            U.showToast(err.message, 'error');
        }).then(function () {
            self.busy(btn, false);
        });
    };

    /** Paso actual de un documento en revisión (el legacy mostraba un alert fijo). */
    Panel.prototype.showFlowInfo = function (doc) {
        U.fetchJson('/documents/' + encodeURIComponent(doc.id))
            .then(function (payload) {
                var detail = (payload && payload.data) || {};
                var step = detail.current_step;
                U.showToast(
                    step
                        ? 'En revisión. Paso actual: ' + step.name +
                          ' (' + step.days_limit + ' día(s) de límite).'
                        : 'El documento está en revisión.',
                    'info'
                );
            })
            .catch(function (err) { U.showToast(err.message, 'error'); });
    };

    // ---------- historial de versiones ----------

    /**
     * Abre el modal compartido (partials/_document_versions_modal.html). El
     * módulo se carga en la misma página, así que faltar solo puede faltar si
     * alguien quita su <script>: se avisa en vez de romper el clic en silencio.
     */
    Panel.prototype.openVersions = function (doc) {
        var mod = window.AdhocDocumentVersions;
        if (!mod || typeof mod.open !== 'function') {
            U.showToast('No se pudo abrir el historial de versiones.', 'error');
            return;
        }
        mod.open(doc.id);
    };

    // ---------- borrado ----------

    Panel.prototype.remove = function (doc) {
        var self = this;
        U.confirmDialog({
            title: 'Eliminar documento',
            message: '¿Eliminar "' + H.text(doc.title) + '"? Se borran también sus tareas ' +
                     'y su archivo adjunto. Esta acción no se puede deshacer.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson('/documents/' + encodeURIComponent(doc.id), { method: 'DELETE' })
                .then(function (payload) {
                    U.showToast((payload && payload.message) || 'Documento eliminado.', 'success');
                    return self.list.reload();
                })
                .catch(function (err) { U.showToast(err.message, 'error'); });
        });
    };

    // ---------- utilidades de modal ----------

    Panel.prototype.show = function (modal) {
        if (modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modal).show();
        }
    };

    Panel.prototype.hide = function (modal) {
        if (modal && window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        }
    };

    Panel.prototype.busy = function (btn, isBusy) {
        if (!btn) return;
        btn.disabled = !!isBusy;
        btn.classList.toggle('disabled', !!isBusy);
    };

    // ---------- listeners (delegados, cero onclick inline) ----------

    Panel.prototype.bind = function () {
        var self = this;

        this.root.addEventListener('click', function (evt) {
            if (evt.target.closest('[data-adhoc-doc-new]')) {
                evt.preventDefault();
                self.openNew();
                return;
            }
            var btn = evt.target.closest('[data-adhoc-doc-action]');
            if (!btn) return;
            // "Editar" se pinta también sobre las filas que no se pueden
            // editar, deshabilitado. Un botón `disabled` no dispara `click` en
            // ningún navegador, pero la hoja del panel le devuelve los eventos
            // de ratón para que se pueda leer su `title` —el motivo—, así que
            // la guarda se escribe en vez de darse por supuesta.
            if (btn.disabled) return;
            var tr = btn.closest('tr[data-id]');
            if (!tr) return;
            evt.preventDefault();

            var doc = self.list.find(tr.getAttribute('data-id'));
            if (!doc) return;

            var action = btn.getAttribute('data-adhoc-doc-action');
            if (action === 'start-flow') self.openFlow(doc);
            else if (action === 'flow-info') self.showFlowInfo(doc);
            else if (action === 'versions') self.openVersions(doc);
            else if (action === 'edit') self.openEdit(doc);
            else if (action === 'new-version') self.openNewVersion(doc);
            else if (action === 'delete') self.remove(doc);
        });

        if (this.modal) {
            this.modal.addEventListener('change', function (evt) {
                if (evt.target.closest('[data-adhoc-doc-qty]')) self.buildFields();
            });
            this.modal.addEventListener('click', function (evt) {
                if (!evt.target.closest('[data-adhoc-doc-save]')) return;
                evt.preventDefault();
                self.submit();
            });
        }

        if (this.flowModal) {
            this.flowModal.addEventListener('click', function (evt) {
                if (!evt.target.closest('[data-adhoc-flow-start]')) return;
                evt.preventDefault();
                self.startFlow();
            });
        }
    };

    // ==================== API PÚBLICA ====================

    function init(scope) {
        if (!List) {
            console.error('[adhoc] documents-panel: falta document-list.js');
            return null;
        }
        var node = scope || document;
        var root = (node.matches && node.matches('[data-adhoc-doc-panel]'))
            ? node
            : node.querySelector('[data-adhoc-doc-panel]');
        if (!root) return null;
        if (root.dataset.adhocDocPanelBound === '1') return null;   // idempotente
        root.dataset.adhocDocPanelBound = '1';

        return new Panel(root).init();
    }

    if (U && typeof U.onReady === 'function') {
        U.onReady(function (root) { init(root || document); });
    }

    window.AdhocDocumentsPanel = { init: init };
})();
