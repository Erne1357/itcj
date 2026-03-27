/**
 * ticket-assignment.js — Gestión de técnicos asignados en el detalle del ticket
 * Expone: window.MaintAssignment
 */
'use strict';

(function () {

    var API_BASE = '/api/maint/v2';
    var ctx = window.TICKET_CTX || {};
    var _ticket = null;
    var _onReload = null;
    var _allTechnicians = [];
    var _selectedTechIds = [];

    // ── API pública ───────────────────────────────────────────────────────────

    window.MaintAssignment = {
        bind: function (ticket, onReload) {
            _ticket = ticket;
            _onReload = onReload;
            _bindTabButtons();
        },
    };

    function _bindTabButtons() {
        // Botón "Asignar técnico" en la pestaña de técnicos
        var openBtn = document.getElementById('openAssignBtn');
        if (openBtn) {
            openBtn.addEventListener('click', function () {
                _openAssignModal();
            });
        }

        // Botones "Remover técnico"
        document.querySelectorAll('.unassign-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var uid = btn.dataset.uid;
                var name = btn.dataset.name;
                _confirmUnassign(uid, name);
            });
        });
    }

    // ── Modal: Asignar ────────────────────────────────────────────────────────

    function _openAssignModal() {
        _selectedTechIds = [];
        var modalEl = document.getElementById('assignTechModal');
        var modal = new bootstrap.Modal(modalEl);

        var listContainer = document.getElementById('technicianList');
        listContainer.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-secondary"></div></div>';

        modal.show();

        _loadTechnicians()
            .then(function (technicians) {
                _allTechnicians = technicians;
                _renderTechList(technicians);
            })
            .catch(function () {
                listContainer.innerHTML = '<div class="text-danger small">No se pudieron cargar los técnicos.</div>';
            });

        // Filtro de búsqueda
        document.getElementById('techSearchInput').value = '';
        document.getElementById('techSearchInput').oninput = function () {
            var q = this.value.toLowerCase();
            var filtered = _allTechnicians.filter(function (t) {
                return t.name.toLowerCase().includes(q);
            });
            _renderTechList(filtered);
        };

        // Botón confirmar
        document.getElementById('confirmAssignBtn').onclick = function () {
            if (_selectedTechIds.length === 0) {
                MaintUtils.toast('Selecciona al menos un técnico', 'warning');
                return;
            }
            var notes = (document.getElementById('assignNotes').value || '').trim();
            _assignTechnicians(_selectedTechIds, notes, modal);
        };
    }

    function _loadTechnicians() {
        return MaintUtils.api.fetch(API_BASE + '/technicians')
            .then(function (data) { return data.technicians || []; });
    }

    function _renderTechList(technicians) {
        var container = document.getElementById('technicianList');

        // IDs ya activamente asignados en el ticket
        var activeIds = (_ticket.technicians || [])
            .filter(function (tc) { return tc.is_active; })
            .map(function (tc) { return tc.user_id; });

        if (technicians.length === 0) {
            container.innerHTML = '<div class="text-muted small text-center py-2">Sin resultados</div>';
            return;
        }

        var html = '';
        technicians.forEach(function (tech) {
            var isAlreadyAssigned = activeIds.indexOf(tech.id) !== -1;
            var isSelected = _selectedTechIds.indexOf(tech.id) !== -1;
            var areasTags = (tech.areas || []).map(function (a) {
                return '<span class="badge bg-light text-secondary border" style="font-size:0.65rem;">' + _esc(a.area_code) + '</span>';
            }).join(' ');

            html += '<div class="d-flex align-items-center p-2 rounded mb-1 tech-item' +
                (isAlreadyAssigned ? ' opacity-50' : '') + '" ' +
                'data-tech-id="' + tech.id + '" style="cursor:' + (isAlreadyAssigned ? 'default' : 'pointer') + ';' +
                (isSelected ? 'background:var(--maint-primary-light);' : '') + '">' +
                '<div class="form-check mb-0 me-2">' +
                    '<input class="form-check-input tech-checkbox" type="checkbox" id="tech_' + tech.id + '" ' +
                    'value="' + tech.id + '"' +
                    (isAlreadyAssigned ? ' disabled checked' : (isSelected ? ' checked' : '')) + '>' +
                '</div>' +
                '<div class="flex-grow-1">' +
                    '<div class="fw-medium small">' + _esc(tech.name) +
                        (isAlreadyAssigned ? ' <span class="badge bg-success ms-1" style="font-size:0.6rem;">Asignado</span>' : '') +
                    '</div>' +
                    (areasTags ? '<div class="mt-1">' + areasTags + '</div>' : '') +
                '</div>' +
            '</div>';
        });

        container.innerHTML = html;

        // Bind checkboxes
        container.querySelectorAll('.tech-checkbox:not([disabled])').forEach(function (cb) {
            cb.addEventListener('change', function () {
                var id = parseInt(this.value, 10);
                if (this.checked) {
                    if (_selectedTechIds.indexOf(id) === -1) _selectedTechIds.push(id);
                } else {
                    _selectedTechIds = _selectedTechIds.filter(function (x) { return x !== id; });
                }
                // Actualizar fondo del item
                var item = container.querySelector('[data-tech-id="' + id + '"]');
                if (item) item.style.background = this.checked ? 'var(--maint-primary-light)' : '';
            });
        });

        // Click en la fila completa
        container.querySelectorAll('.tech-item:not(.opacity-50)').forEach(function (row) {
            row.addEventListener('click', function (e) {
                if (e.target.classList.contains('form-check-input')) return;
                var cb = row.querySelector('.tech-checkbox');
                if (cb && !cb.disabled) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change'));
                }
            });
        });
    }

    function _assignTechnicians(userIds, notes, modal) {
        var btn = document.getElementById('confirmAssignBtn');
        MaintUtils.loading.show(btn, 'Asignando...');

        MaintUtils.api.fetch(API_BASE + '/tickets/' + ctx.ticketId + '/assign', {
            method: 'POST',
            body: JSON.stringify({ user_ids: userIds, notes: notes || null }),
        })
            .then(function () {
                modal.hide();
                MaintUtils.toast('Técnico(s) asignado(s) correctamente', 'success');
                if (_onReload) _onReload();
            })
            .catch(function (err) {
                MaintUtils.loading.hide(btn);
                MaintUtils.toast(err.message, 'error');
            });
    }

    // ── Remover técnico ───────────────────────────────────────────────────────

    function _confirmUnassign(userId, techName) {
        MaintUtils.confirm({
            title: 'Remover técnico',
            message: '¿Remover a ' + techName + ' de este ticket?',
            confirmLabel: 'Remover',
            confirmClass: 'btn-danger',
            onConfirm: function () {
                MaintUtils.api.fetch(
                    API_BASE + '/tickets/' + ctx.ticketId + '/unassign',
                    { method: 'POST', body: JSON.stringify({ user_id: parseInt(userId, 10), reason: null }) }
                )
                    .then(function () {
                        MaintUtils.toast('Técnico removido', 'info');
                        if (_onReload) _onReload();
                    })
                    .catch(function (err) { MaintUtils.toast(err.message, 'error'); });
            },
        });
    }

    function _esc(s) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(String(s || '')));
        return d.innerHTML;
    }

})();
