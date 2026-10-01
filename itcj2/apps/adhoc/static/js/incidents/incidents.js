/**
 * incidents/incidents.js — configuración de INCIDENCIAS sobre `work/work-items.js`.
 *
 * Expone SOLO `window.AdhocIncidents` (IIFE, sin globales sueltas). Toda la
 * mecánica —listar, filtrar, paginar, alta masiva, edición, borrado— vive en la
 * base compartida; aquí queda lo que distingue a una incidencia de un evento
 * de programa: nada en el formulario (los doce campos base son exactamente
 * los de una incidencia), y desde ahora sí algo en las acciones de fila:
 * **archivos adjuntos**.
 *
 * Contrato consumido (`page_data`, lo arma `pages/incidents.py`):
 *   api        = /api/adhoc/v2/incidents
 *   tasks_url  = /adhoc/incidencias/{id}/tareas
 *   query_map  = {search: 'q', date_from: 'commitment_from', date_to: 'commitment_to'}
 *   can.files / can.files_create / can.files_delete = permisos de adjuntos
 *
 * Alta masiva: `POST /incidents` con `{"items": [...]}` (JSON). El legacy
 * mandaba diez listas paralelas por formulario y las recorría por índice, con
 * un índice 1-based solo para `priorities`.
 *
 * ADJUNTOS — por qué existen aquí y por qué así
 * ----------------------------------------------
 * La app se construyó asumiendo que las incidencias no llevaban adjuntos (esa
 * suposición vivía, literal, en la versión anterior de este comentario). Era
 * falsa: el SGC legacy migró 351 adjuntos reales de `adhoc_incident_files`, 51
 * de ellos sin binario en el servidor del proveedor. El backend
 * (`GET/POST /incidents/{id}/files`, `DELETE/GET .../files/{id}[/download]`)
 * ya existe; esto es la interfaz.
 *
 * Se implementa como UN ICONO DE ACCIÓN MÁS EN LA FILA (`actions`, igual que
 * "duplicar" en programas), no como una columna de tabla con contador: el
 * listado de incidencias no tiene página de detalle a la que enlazar, así que
 * el icono de fila es el único punto de entrada natural; y a diferencia de
 * `GET /program-events` (que precarga `event.files` y expone `files_count`
 * por fila), `GET /incidents` no calcula ese conteo, así que una columna
 * dedicada mostraría un número inventado en vez de uno real.
 *
 * El modal en sí (listar/subir/borrar/descargar) es un espejo deliberado del
 * de `programs/programs.js` — mismo contrato de URLs
 * (`{api}/{id}/files`, `{api}/files/{id}[/download]`), mismos hooks
 * `data-adhoc-files-*`, misma descarga por id (nunca por nombre) — con un
 * añadido propio: 51 de los 351 adjuntos son registros migrados con
 * `is_available: false` (sin binario). Se listan igual —el expediente de una
 * no conformidad ES la evidencia— pero sin ofrecer una descarga que el
 * backend respondería con 404: icono apagado + `title` explicativo, el mismo
 * criterio que ya usa `.adhoc-file-none` en `documents/document-list.js`.
 */
(function () {
    'use strict';

    var Base = window.AdhocWorkItems;
    var U = window.AdhocUtils;

    if (!Base || typeof Base.register !== 'function') {
        console.error('[adhoc] incidents.js: falta work/work-items.js');
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
    // Espejo de `programs/programs.js::FilesModal`. Ver la cabecera del
    // archivo para por qué no se comparte una sola clase entre los dos
    // dominios (todavía): "duplicar" en programas ya demostró que ese tipo de
    // extensión vive bien en `config.actions`/`config.onAction`, y el modal de
    // archivos usa exactamente ese mismo mecanismo aquí.

    function FilesModal(ctx) {
        this.ctx = ctx;
        this.node = document.querySelector('[data-adhoc-files-modal]');
        this.list = this.node ? this.node.querySelector('[data-adhoc-files-list]') : null;
        this.input = this.node ? this.node.querySelector('[data-adhoc-files-input]') : null;
        this.item = null;
        if (this.node) this.bind();
    }

    FilesModal.prototype.open = function (item) {
        if (!this.node) return;
        this.item = item;

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
        return U.fetchJson(api + '/' + encodeURIComponent(this.item.id) + '/files')
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
            this.list.appendChild(el('p', 'adhoc-files-empty', 'Esta incidencia no tiene archivos adjuntos.'));
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

            // Adjunto migrado sin binario: se enseña igual, pero sin enlace de
            // descarga (el backend respondería 404). Icono apagado + motivo en
            // el title, nunca un enlace roto.
            if (!file.is_available) {
                var none = iconEl('fa-solid fa-file-circle-xmark adhoc-file-none',
                    'Sin archivo: se perdió al migrar el sistema anterior');
                none.setAttribute('aria-label', 'Sin archivo: se perdió al migrar el sistema anterior');
                actions.appendChild(none);
            } else if (can.files) {
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
        U.fetchJson(this.ctx.api + '/' + encodeURIComponent(this.item.id) + '/files', {
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
        });
    };

    FilesModal.prototype.remove = function (fileId, name) {
        var self = this;
        U.confirmDialog({
            title: 'Eliminar archivo',
            message: '¿Eliminar "' + name + '"? Se borra también del disco (si lo hay).',
            confirmText: 'Eliminar',
            variant: 'danger'
        }).then(function (ok) {
            if (!ok) return null;
            return U.fetchJson(self.ctx.api + '/files/' + encodeURIComponent(fileId), {
                method: 'DELETE'
            }).then(function () {
                toast('Archivo eliminado.', 'success');
                return self.load();
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

    var instances = Base.register({
        kind: 'incident',

        // Sin campos extra: los doce del formulario base son exactamente los
        // de una incidencia. `location` sigue siendo cosa de programas.
        extraFields: [],

        // La única acción de fila que no pone la base: el icono de archivos.
        // Se oculta si el usuario no puede ni ver ni subir adjuntos —mismo
        // criterio que la celda de archivos de `programs.js`—; "duplicar" no
        // aplica a una incidencia.
        actions: function (item, ctx) {
            return (ctx.can.files || ctx.can.files_create)
                ? [{ name: 'files', icon: 'fa-regular fa-folder-open',
                     title: 'Documentos Adjuntos', variant: 'adhoc-icon-doc' }]
                : [];
        },

        onAction: function (name, item, ctx) {
            if (name === 'files') filesModal(ctx).open(item);
        }
    });

    window.AdhocIncidents = { instances: instances };
})();
