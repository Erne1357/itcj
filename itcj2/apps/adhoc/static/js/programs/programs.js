/**
 * programs/programs.js — configuración de EVENTOS DE PROGRAMA sobre
 * `work/work-items.js`, más lo único que incidencias no tiene: **ubicación**,
 * **adjuntos** y **duplicar**.
 *
 * Expone SOLO `window.AdhocPrograms` (IIFE, sin globales sueltas).
 *
 * QUÉ ARREGLA DEL LEGACY (`programs/programs.js`, clase `ProgramasManager`)
 * -----------------------------------------------------------------------
 *  · Su `filtrarTabla()` era una copia mal pegada de la de incidencias:
 *    usaba `cells[index]` donde el original usaba `cells[index + 1]`, así que
 *    cada filtro se aplicaba a la columna equivocada. Aquí el filtrado es de
 *    servidor y va por nombre de parámetro.
 *  · El modal de archivos pintaba `${archivo.nombre}` dentro de `innerHTML` —
 *    nombre de fichero controlado por quien sube— y construía la URL de
 *    descarga concatenando ese nombre **sin `encodeURIComponent`**: cualquier
 *    adjunto con espacio, `#` o acento daba 404. Ahora la lista se construye
 *    con `textContent` y la descarga va por **id de archivo**
 *    (`GET /program-events/files/{file_id}/download`).
 *  · La lista de archivos se leía de `os.listdir` y respondía `{archivos: [...]}`
 *    sin `success`; hoy sale de `adhoc_program_event_files`.
 *  · `confirm('¿Duplicar este programa?')` y `confirm('¿Borrar programa...')`
 *    → `AdhocUtils.confirmDialog()`.
 *  · Los adjuntos del alta iban en `support_files_{i+1}[]` (1-based), que
 *    desalineaba archivo y fila en cuanto una fila del lote venía vacía. Aquí
 *    van en `files` + `file_indexes` (0-based, paralelos).
 */
(function () {
    'use strict';

    var Base = window.AdhocWorkItems;
    var U = window.AdhocUtils;

    if (!Base || typeof Base.register !== 'function') {
        console.error('[adhoc] programs.js: falta work/work-items.js');
        return;
    }

    var el = Base.el;
    var iconEl = Base.iconEl;

    function toast(message, type) {
        if (U && typeof U.showToast === 'function') U.showToast(message, type);
    }

    function humanSize(bytes) {
        if (!bytes && bytes !== 0) return '';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    // ==================== MODAL DE ARCHIVOS ====================

    function FilesModal(ctx) {
        this.ctx = ctx;
        this.node = document.querySelector('[data-adhoc-files-modal]');
        this.list = this.node ? this.node.querySelector('[data-adhoc-files-list]') : null;
        this.input = this.node ? this.node.querySelector('[data-adhoc-files-input]') : null;
        this.event = null;
        if (this.node) this.bind();
    }

    FilesModal.prototype.open = function (item) {
        if (!this.node) return;
        this.event = item;

        var title = this.node.querySelector('[data-adhoc-files-title]');
        if (title) title.textContent = 'Archivos de: ' + (item.title || item.folio || '');
        if (this.input) this.input.value = '';

        this.list.textContent = '';
        this.list.appendChild(el('p', 'adhoc-files-empty', 'Cargando archivos...'));

        if (window.bootstrap && window.bootstrap.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(this.node).show();
        }
        this.load();
    };

    FilesModal.prototype.load = function () {
        var self = this;
        var api = this.ctx.api;
        return U.fetchJson(api + '/' + encodeURIComponent(this.event.id) + '/files')
            .then(function (payload) {
                self.render((payload && payload.data) || []);
            })
            .catch(function (err) {
                self.list.textContent = '';
                self.list.appendChild(el('p', 'adhoc-files-error', err.message));
            });
    };

    FilesModal.prototype.render = function (files) {
        var can = this.ctx.can || {};
        this.list.textContent = '';

        if (!files.length) {
            this.list.appendChild(el('p', 'adhoc-files-empty', 'Este evento no tiene archivos adjuntos.'));
            return;
        }

        var ul = el('ul', 'adhoc-files-items');
        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var li = el('li', 'adhoc-files-item');

            var info = el('span', 'adhoc-files-info');
            info.appendChild(iconEl('fa-regular fa-file-lines'));
            // textContent: el nombre lo elige quien sube el archivo.
            info.appendChild(el('span', 'adhoc-files-name', file.original_name || ''));
            var meta = humanSize(file.size_bytes);
            if (meta) info.appendChild(el('span', 'adhoc-files-meta', meta));
            li.appendChild(info);

            var actions = el('span', 'adhoc-actions');

            if (can.files) {
                var link = el('a', 'adhoc-icon-btn adhoc-icon-primary');
                // Descarga por ID, no por nombre: sin concatenar nada del usuario.
                link.href = this.ctx.api + '/files/' + encodeURIComponent(file.id) + '/download';
                link.setAttribute('title', 'Descargar');
                link.setAttribute('aria-label', 'Descargar');
                link.appendChild(iconEl('fa-solid fa-download'));
                actions.appendChild(link);
            }

            if (can.files_delete) {
                var del = el('button', 'adhoc-icon-btn adhoc-icon-trash');
                del.type = 'button';
                del.setAttribute('data-adhoc-files-delete', String(file.id));
                del.setAttribute('data-adhoc-files-name', file.original_name || '');
                del.setAttribute('title', 'Eliminar');
                del.setAttribute('aria-label', 'Eliminar');
                del.appendChild(iconEl('fa-solid fa-trash'));
                actions.appendChild(del);
            }

            li.appendChild(actions);
            ul.appendChild(li);
        }
        this.list.appendChild(ul);
    };

    FilesModal.prototype.upload = function (button) {
        var self = this;
        if (!this.input || !this.input.files || !this.input.files.length) {
            toast('Elige al menos un archivo.', 'warning');
            return;
        }

        var form = new FormData();
        for (var i = 0; i < this.input.files.length; i++) {
            form.append('files', this.input.files[i]);
        }

        button.disabled = true;
        U.fetchJson(this.ctx.api + '/' + encodeURIComponent(this.event.id) + '/files', {
            method: 'POST',
            body: form
        }).then(function (payload) {
            toast(((payload && payload.total) || 0) + ' archivo(s) subido(s).', 'success');
            self.input.value = '';
            return self.load();
        }).catch(function (err) {
            toast(err.message, 'error');
        }).then(function () {
            button.disabled = false;
            return self.ctx.load();
        });
    };

    FilesModal.prototype.remove = function (fileId, name) {
        var self = this;
        U.confirmDialog({
            title: 'Eliminar archivo',
            message: '¿Eliminar "' + name + '"? Se borra también del disco.',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson(self.ctx.api + '/files/' + encodeURIComponent(fileId), {
                method: 'DELETE'
            }).then(function () {
                toast('Archivo eliminado.', 'success');
                return self.load();
            }).then(function () {
                return self.ctx.load();
            }).catch(function (err) {
                toast(err.message, 'error');
            });
        });
    };

    FilesModal.prototype.bind = function () {
        var self = this;
        this.node.addEventListener('click', function (evt) {
            var up = evt.target.closest('[data-adhoc-files-upload]');
            if (up) {
                evt.preventDefault();
                self.upload(up);
                return;
            }
            var del = evt.target.closest('[data-adhoc-files-delete]');
            if (del) {
                evt.preventDefault();
                self.remove(del.getAttribute('data-adhoc-files-delete'),
                            del.getAttribute('data-adhoc-files-name') || '');
            }
        });
    };

    // ==================== CONFIGURACIÓN DEL DOMINIO ====================

    var _files = null;

    function filesModal(ctx) {
        if (!_files || _files.ctx !== ctx) _files = new FilesModal(ctx);
        return _files;
    }

    function duplicate(item, ctx) {
        U.confirmDialog({
            title: 'Duplicar evento',
            message: '¿Crear una copia de "' + (item.title || item.folio || '') + '"? ' +
                     'Se copian los datos, no los adjuntos ni las tareas.',
            confirmText: 'Duplicar'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson(ctx.api + '/' + encodeURIComponent(item.id) + '/duplicate', {
                method: 'POST'
            }).then(function () {
                toast('Evento duplicado.', 'success');
                return ctx.load();
            }).catch(function (err) {
                toast(err.message, 'error');
            });
        });
    }

    var instances = Base.register({
        kind: 'program',

        // Lo único que un evento tiene y una incidencia no.
        extraFields: [
            { name: 'location', label: 'Ubicación', type: 'text', maxLength: 100,
              after: 'process_id' },
            { name: 'files', label: 'Archivos adjuntos', type: 'file', full: true,
              createOnly: true,
              help: 'Solo al dar de alta. Para gestionar los adjuntos de un evento existente usa el botón de la columna Archivos.' }
        ],

        cells: {
            files: function (item, ctx) {
                if (!ctx.can.files && !ctx.can.files_create) return '—';
                var btn = Base.actionButton('files', 'fa-regular fa-folder-open', 'Documentos Adjuntos', 'adhoc-icon-doc');
                var count = item.files_count;
                if (typeof count === 'number') {
                    btn.appendChild(document.createTextNode(' '));
                    btn.appendChild(el('span', 'adhoc-count-pill', String(count)));
                }
                return btn;
            }
        },

        actions: function (item, ctx) {
            return ctx.can.duplicate
                ? [{ name: 'duplicate', icon: 'fa-regular fa-copy', title: 'Copiar Registro' }]
                : [];
        },

        onAction: function (name, item, ctx) {
            if (name === 'files') filesModal(ctx).open(item);
            else if (name === 'duplicate') duplicate(item, ctx);
        },

        /**
         * `POST /program-events` es multipart: `payload` con el JSON de los
         * eventos, más `files` y `file_indexes` PARALELOS (0-based). El legacy
         * usaba `support_files_{i+1}[]`, 1-based y por nombre de campo, lo que
         * desalineaba archivo y fila si una fila del lote venía vacía.
         */
        buildCreate: function (records, formRoot, ctx) {
            var form = new FormData();
            form.append('payload', JSON.stringify({ events: records }));

            var blocks = formRoot.querySelectorAll('[data-adhoc-record]');
            for (var i = 0; i < blocks.length; i++) {
                var input = blocks[i].querySelector('input[type="file"][data-adhoc-field]');
                if (!input || !input.files) continue;
                for (var j = 0; j < input.files.length; j++) {
                    form.append('files', input.files[j]);
                    form.append('file_indexes', String(i));
                }
            }

            return { url: ctx.api, options: { method: 'POST', body: form } };
        }
    });

    window.AdhocPrograms = { instances: instances };
})();
