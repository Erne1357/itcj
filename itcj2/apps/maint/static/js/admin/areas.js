/**
 * admin-areas.js — Gestión de áreas de especialidad de técnicos (Mantenimiento)
 * Expone: window.MaintAdminAreas (para callbacks en línea del HTML generado)
 */
'use strict';

(function () {

    var API = '/api/maint/v2';

    var AREAS = [
        { code: 'TRANSPORT',   label: 'Transporte',          icon: 'bi-truck',              color: '#1565C0', bg: '#e3f2fd' },
        { code: 'GENERAL',     label: 'Mant. General',       icon: 'bi-tools',              color: '#546E7A', bg: '#ECEFF1' },
        { code: 'ELECTRICAL',  label: 'Eléctrico',           icon: 'bi-lightning-charge',   color: '#F57F17', bg: '#fff8e1' },
        { code: 'CARPENTRY',   label: 'Carpintería',         icon: 'bi-hammer',             color: '#4E342E', bg: '#efebe9' },
        { code: 'AC',          label: 'Aire Acondicionado',  icon: 'bi-thermometer-snow',   color: '#00838F', bg: '#e0f7fa' },
        { code: 'GARDENING',   label: 'Jardinería',          icon: 'bi-flower1',            color: '#2E7D32', bg: '#e8f5e9' },
    ];

    var _AREA_MAP = {};
    AREAS.forEach(function (a) { _AREA_MAP[a.code] = a; });

    var _technicians = [];
    var _assignModal = null;

    // ── Init ──────────────────────────────────────────────────────────────────

    function init() {
        _assignModal = new bootstrap.Modal(document.getElementById('assignAreaModal'));

        document.getElementById('btnSaveArea').addEventListener('click', saveArea);

        renderLegend();
        loadTechnicians();
    }

    // ── Leyenda ───────────────────────────────────────────────────────────────

    function renderLegend() {
        var container = document.getElementById('areaLegend');
        if (!container) return;

        container.innerHTML = AREAS.map(function (a) {
            return '<span class="badge d-inline-flex align-items-center gap-1 px-2 py-1" ' +
                   'style="background:' + a.bg + ';color:' + a.color + ';border:1px solid ' + a.color + '40;font-size:0.78rem;">' +
                   '<i class="bi ' + a.icon + '"></i>' + a.label +
                   '</span>';
        }).join('');
    }

    // ── Carga y renderizado ───────────────────────────────────────────────────

    function loadTechnicians() {
        var container = document.getElementById('technicianTableContainer');
        container.innerHTML =
            '<div class="text-center py-5 text-muted">' +
            '<div class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></div>' +
            'Cargando técnicos...</div>';

        MaintUtils.api.fetch(API + '/technicians')
            .then(function (data) {
                _technicians = data.technicians || [];
                renderTable();
            })
            .catch(function () {
                container.innerHTML =
                    '<div class="alert alert-danger m-3">' +
                    '<i class="bi bi-exclamation-triangle me-2"></i>Error al cargar los técnicos.</div>';
            });
    }

    function renderTable() {
        var container = document.getElementById('technicianTableContainer');

        if (!_technicians.length) {
            container.innerHTML =
                '<div class="text-center py-5 text-muted">' +
                '<i class="bi bi-people fs-3 d-block mb-2"></i>' +
                'No hay técnicos registrados en la aplicación de mantenimiento.</div>';
            return;
        }

        var rows = _technicians.map(function (tech) {
            var areaBadges = (tech.areas && tech.areas.length)
                ? tech.areas.map(function (a) {
                    var info = _AREA_MAP[a.area_code] || { label: a.area_code, icon: 'bi-question', color: '#546E7A', bg: '#ECEFF1' };
                    var primaryStar = a.is_primary
                        ? ' <i class="bi bi-star-fill" title="Área principal" style="font-size:0.65rem;color:#F59E0B;"></i>'
                        : '';
                    return '<span class="badge d-inline-flex align-items-center gap-1 me-1 mb-1 area-badge" ' +
                           'style="background:' + info.bg + ';color:' + info.color + ';border:1px solid ' + info.color + '40;' +
                           'font-size:0.78rem;cursor:default;" ' +
                           'title="' + escHtml(info.label) + (a.is_primary ? ' (principal)' : '') + '">' +
                           '<i class="bi ' + info.icon + '"></i>' +
                           escHtml(info.label) + primaryStar +
                           '<button type="button" class="btn-close ms-1" style="font-size:0.55rem;filter:none;opacity:0.6;" ' +
                           'onclick="MaintAdminAreas.removeArea(' + tech.id + ', \'' + escHtml(a.area_code) + '\')" ' +
                           'title="Quitar área"></button>' +
                           '</span>';
                }).join('')
                : '<span class="text-muted small fst-italic">Sin áreas asignadas</span>';

            var initials = (tech.name || 'U').split(' ').slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase();

            return '<tr>' +
                '<td>' +
                    '<div class="d-flex align-items-center gap-2">' +
                        '<div class="rounded-circle d-flex align-items-center justify-content-center fw-bold text-white" ' +
                             'style="width:34px;height:34px;min-width:34px;font-size:0.75rem;background:var(--maint-primary);">' +
                             escHtml(initials) +
                        '</div>' +
                        '<span class="fw-semibold" style="color:var(--maint-primary-darker);">' + escHtml(tech.name) + '</span>' +
                    '</div>' +
                '</td>' +
                '<td>' +
                    '<div class="d-flex flex-wrap align-items-center">' +
                        areaBadges +
                    '</div>' +
                '</td>' +
                '<td style="width:110px;">' +
                    '<button class="btn btn-sm btn-outline-primary" ' +
                        'onclick="MaintAdminAreas.openAssignModal(' + tech.id + ')" ' +
                        'title="Asignar área">' +
                        '<i class="bi bi-plus-lg me-1"></i>Área' +
                    '</button>' +
                '</td>' +
            '</tr>';
        }).join('');

        container.innerHTML =
            '<div class="table-responsive">' +
            '<table class="table table-hover align-middle mb-0" style="font-size:0.88rem;">' +
            '<thead class="table-light">' +
            '<tr>' +
            '<th style="min-width:180px;">Técnico</th>' +
            '<th>Áreas de especialidad</th>' +
            '<th style="width:110px;"></th>' +
            '</tr>' +
            '</thead>' +
            '<tbody>' + rows + '</tbody>' +
            '</table>' +
            '</div>';
    }

    // ── Modal asignar ─────────────────────────────────────────────────────────

    function openAssignModal(userId) {
        var tech = _technicians.find(function (t) { return t.id === userId; });
        if (!tech) return;

        document.getElementById('assignUserId').value = userId;
        document.getElementById('assignUserName').textContent = tech.name;

        // Filtrar áreas que el técnico ya tiene
        var assignedCodes = (tech.areas || []).map(function (a) { return a.area_code; });
        var available = AREAS.filter(function (a) { return assignedCodes.indexOf(a.code) === -1; });

        var select = document.getElementById('assignAreaCode');
        if (!available.length) {
            select.innerHTML = '<option value="">— Ya tiene todas las áreas —</option>';
            document.getElementById('btnSaveArea').disabled = true;
        } else {
            document.getElementById('btnSaveArea').disabled = false;
            select.innerHTML = available.map(function (a) {
                return '<option value="' + a.code + '">' + a.label + '</option>';
            }).join('');
        }

        _assignModal.show();
    }

    function saveArea() {
        var userId   = document.getElementById('assignUserId').value;
        var areaCode = document.getElementById('assignAreaCode').value;
        var btn      = document.getElementById('btnSaveArea');

        if (!areaCode) { MaintUtils.toast('Selecciona un área', 'warning'); return; }

        MaintUtils.loading.show(btn, 'Asignando...');
        MaintUtils.api.fetch(API + '/technicians/' + userId + '/areas', {
            method: 'POST',
            body: JSON.stringify({ area_code: areaCode }),
        })
            .then(function () {
                var areaInfo = _AREA_MAP[areaCode];
                MaintUtils.toast('Área ' + (areaInfo ? areaInfo.label : areaCode) + ' asignada', 'success');
                _assignModal.hide();
                loadTechnicians();
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al asignar área', 'error');
            })
            .finally(function () {
                MaintUtils.loading.hide(btn);
            });
    }

    function removeArea(userId, areaCode) {
        var areaInfo = _AREA_MAP[areaCode];
        var areaLabel = areaInfo ? areaInfo.label : areaCode;

        MaintUtils.confirm({
            title: 'Quitar área',
            message: '¿Quitar el área "' + areaLabel + '" de este técnico?',
            confirmLabel: 'Quitar',
            confirmClass: 'btn-warning',
            onConfirm: function () {
                MaintUtils.api.fetch(API + '/technicians/' + userId + '/areas/' + areaCode, {
                    method: 'DELETE',
                })
                    .then(function () {
                        MaintUtils.toast('Área ' + areaLabel + ' removida', 'success');
                        loadTechnicians();
                    })
                    .catch(function () {
                        MaintUtils.toast('Error al quitar el área', 'error');
                    });
            },
        });
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function escHtml(str) {
        if (!str && str !== 0) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ── Público ───────────────────────────────────────────────────────────────

    window.MaintAdminAreas = {
        openAssignModal: openAssignModal,
        removeArea:      removeArea,
    };

    // ── Arranque ──────────────────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
