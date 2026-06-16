/**
 * coordinators_tab.js — Sub-tab "Coordinadores" en la página de Configuración
 * de Mantenimiento (/maint/admin/config#coordinadores).
 *
 * Carga lazy: window.MaintConfigCoordinators.init() es invocado por
 * config_main.js la primera vez que se activa el tab #coordinadores.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 *
 * API consumida:
 *   GET  /api/maint/v2/coordinators            → lista coordinadores
 *   GET  /api/maint/v2/config/areas            → catálogo de áreas (para el select)
 *   PUT  /api/maint/v2/coordinators/{id}/areas → actualiza áreas de un coordinador
 */

(function () {
    'use strict';

    // === ESTADO ===
    var _initialized = false;
    var _coordinators = [];
    var _availableAreas = [];
    var _editModal = null;
    var _editingUserId = null;

    // === CONSTANTES ===
    var API_COORDINATORS = '/api/maint/v2/coordinators';
    var API_AREAS        = '/api/maint/v2/config/areas';

    // === SETUP MODAL ===
    function _setupModal() {
        var el = document.getElementById('modal-coordinator-areas');
        if (el) {
            _editModal = new bootstrap.Modal(el);
            el.addEventListener('hidden.bs.modal', function () {
                _editingUserId = null;
            });
        }

        var saveBtn = document.getElementById('btn-save-coordinator-areas');
        if (saveBtn) {
            saveBtn.addEventListener('click', _handleSaveAreas);
        }
    }

    // === CARGA INICIAL (coordinadores + áreas en paralelo) ===
    function _loadData() {
        _showLoading();

        Promise.all([
            MaintUtils.api.fetch(API_COORDINATORS),
            MaintUtils.api.fetch(API_AREAS),
        ])
        .then(function (results) {
            _coordinators    = results[0].data || [];
            _availableAreas  = (results[1].data || []).filter(function (a) { return a.is_active; });
            _renderTable();
        })
        .catch(function (err) {
            document.getElementById('tbody-coordinators').innerHTML =
                '<tr><td colspan="4" class="text-center py-4 text-danger">' +
                '<i class="fas fa-exclamation-circle me-2"></i>' +
                MaintUtils.escapeHtml(err.message || 'Error al cargar los datos') +
                '</td></tr>';
        });
    }

    function _showLoading() {
        var tbody = document.getElementById('tbody-coordinators');
        if (tbody) {
            tbody.innerHTML =
                '<tr><td colspan="4" class="text-center py-4 text-muted">' +
                '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
                'Cargando coordinadores...</td></tr>';
        }
    }

    // URL de la gestión de usuarios del core
    var CORE_USERS_URL = '/itcj/config/users';

    // === RENDER TABLA ===
    function _renderTable() {
        var tbody = document.getElementById('tbody-coordinators');
        if (!tbody) return;

        if (!_coordinators.length) {
            tbody.innerHTML =
                '<tr><td colspan="4" class="text-center py-4 text-muted">' +
                '<i class="fas fa-users me-2 opacity-50"></i>' +
                'No hay coordinadores registrados. Asigna el rol ' +
                '<code>maint_area_coordinator</code> o <code>maint_general_coordinator</code> ' +
                'a un usuario en ' +
                '<a href="' + CORE_USERS_URL + '" class="fw-medium">Configuraci\xf3n → Usuarios</a>' +
                ' para que aparezca aqu\xed.' +
                '</td></tr>';
            return;
        }

        // Banner si hay coordinadores de área sin áreas configuradas
        var missingAreas = _coordinators.filter(function (c) {
            return !c.is_general && (!c.areas || c.areas.length === 0);
        });
        var banner = document.getElementById('coordinators-missing-areas-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'coordinators-missing-areas-banner';
            var tableWrap = tbody.closest('.table-responsive');
            if (tableWrap) tableWrap.parentNode.insertBefore(banner, tableWrap);
        }
        if (missingAreas.length) {
            banner.className = 'alert alert-warning d-flex align-items-start gap-2 mb-3 py-2';
            banner.innerHTML =
                '<i class="fas fa-exclamation-triangle mt-1 flex-shrink-0"></i>' +
                '<div class="small">' +
                '<strong>' + missingAreas.length + ' coordinador' + (missingAreas.length !== 1 ? 'es' : '') + ' de \xe1rea sin \xe1reas configuradas.</strong> ' +
                'Usa el bot\xf3n <em>Editar \xe1reas</em> en la fila correspondiente para asignarlas. ' +
                'Si necesitas otorgar el rol de coordinador a un usuario, ve a ' +
                '<a href="' + CORE_USERS_URL + '" class="alert-link fw-medium">Configuraci\xf3n → Usuarios</a>.' +
                '</div>';
        } else {
            banner.className = 'd-none';
            banner.innerHTML = '';
        }

        tbody.innerHTML = _coordinators.map(function (coord) {
            var name     = MaintUtils.escapeHtml(coord.name || '#' + coord.user_id);
            var isGen    = coord.is_general;
            var areas    = coord.areas || [];
            var typeBadge = isGen
                ? '<span class="badge bg-primary-subtle text-primary-emphasis">' +
                  '<i class="fas fa-globe me-1"></i>General</span>'
                : '<span class="badge bg-secondary-subtle text-secondary-emphasis">' +
                  '<i class="fas fa-map-marker-alt me-1"></i>\xc1rea</span>';

            var areasHtml = isGen
                ? '<span class="text-muted fst-italic small">Todas las \xe1reas</span>'
                : (areas.length
                    ? areas.map(function (a) {
                        return '<span class="badge bg-light text-secondary border me-1" style="font-size:.75rem;">' +
                               MaintUtils.escapeHtml(a) + '</span>';
                    }).join('')
                    : '<span class="badge bg-warning text-dark me-1" style="font-size:.75rem;">' +
                      '<i class="fas fa-exclamation-triangle me-1"></i>Sin \xe1reas</span>'
                  );

            var editBtn = isGen
                ? '<span class="text-muted small fst-italic">Sin configuración de área</span>'
                : '<button class="btn btn-sm btn-outline-primary" ' +
                  'onclick="MaintConfigCoordinators._openEditAreas(' + coord.user_id + ')" ' +
                  'title="Editar áreas del coordinador">' +
                  '<i class="fas fa-edit me-1"></i>' +
                  '<span class="d-none d-sm-inline">Editar áreas</span>' +
                  '</button>';

            return (
                '<tr>' +
                '<td><span class="fw-medium">' + name + '</span></td>' +
                '<td>' + typeBadge + '</td>' +
                '<td>' + areasHtml + '</td>' +
                '<td class="text-end">' + editBtn + '</td>' +
                '</tr>'
            );
        }).join('');
    }

    // === MODAL: EDITAR ÁREAS ===
    function _openEditAreas(userId) {
        var coord = null;
        for (var i = 0; i < _coordinators.length; i++) {
            if (_coordinators[i].user_id === userId) { coord = _coordinators[i]; break; }
        }
        if (!coord) return;

        _editingUserId = userId;

        // Título del modal
        var titleEl = document.getElementById('modal-coordinator-name');
        if (titleEl) titleEl.textContent = coord.name || ('#' + userId);

        // Poblar checkboxes de áreas disponibles
        var container = document.getElementById('coordinator-areas-checkboxes');
        if (!container) return;

        var currentAreas = new Set(coord.areas || []);
        if (!_availableAreas.length) {
            container.innerHTML = '<p class="text-muted small">No hay áreas activas en el catálogo.</p>';
        } else {
            container.innerHTML = _availableAreas.map(function (area) {
                var checked = currentAreas.has(area.code) ? 'checked' : '';
                return (
                    '<div class="form-check">' +
                    '<input class="form-check-input" type="checkbox" ' +
                    'id="coord-area-' + MaintUtils.escapeHtml(area.code) + '" ' +
                    'value="' + MaintUtils.escapeHtml(area.code) + '" ' + checked + '>' +
                    '<label class="form-check-label" ' +
                    'for="coord-area-' + MaintUtils.escapeHtml(area.code) + '">' +
                    MaintUtils.escapeHtml(area.label || area.code) +
                    '</label>' +
                    '</div>'
                );
            }).join('');
        }

        if (_editModal) _editModal.show();
    }

    // === GUARDAR ÁREAS ===
    function _handleSaveAreas() {
        if (!_editingUserId) return;

        var checkboxes = document.querySelectorAll('#coordinator-areas-checkboxes .form-check-input:checked');
        var areaCodes = Array.prototype.slice.call(checkboxes).map(function (cb) { return cb.value; });

        var btn = document.getElementById('btn-save-coordinator-areas');
        MaintUtils.loading.show(btn, 'Guardando...');

        MaintUtils.api.fetch(API_COORDINATORS + '/' + _editingUserId + '/areas', {
            method: 'PUT',
            body: JSON.stringify({ area_codes: areaCodes }),
        })
        .then(function (data) {
            MaintUtils.loading.hide(btn);
            if (_editModal) _editModal.hide();

            // Actualizar en memoria
            for (var i = 0; i < _coordinators.length; i++) {
                if (_coordinators[i].user_id === _editingUserId) {
                    _coordinators[i].areas = (data.data && data.data.areas) ? data.data.areas : areaCodes;
                    break;
                }
            }
            _renderTable();
            MaintUtils.toast('Áreas del coordinador actualizadas correctamente', 'success');
        })
        .catch(function (err) {
            MaintUtils.loading.hide(btn);
            MaintUtils.toast(err.message || 'Error al actualizar áreas', 'error');
        });
    }

    // === API PÚBLICA ===
    window.MaintConfigCoordinators = {
        init: function () {
            if (_initialized) return;
            _initialized = true;
            _setupModal();
            _loadData();
        },
        _openEditAreas: _openEditAreas,
        _reload: function () {
            _initialized = false;
            _loadData();
        },
    };

})();
