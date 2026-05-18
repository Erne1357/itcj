/**
 * audit_tab.js — Visor de auditoría paginado con diff para el tab #audit
 * en la página de Configuración de Mantenimiento.
 *
 * Carga lazy: window.MaintConfigAudit.init() es invocado por
 * config_main.js la primera vez que se activa el tab #audit.
 *
 * Depende de:
 *   - window.MaintUtils  (maint-utils.js)
 */

'use strict';

// === ESTADO ===
var _auditData  = [];
var _auditMeta  = { total: 0, page: 1, per_page: 25, total_pages: 1 };
var _auditFilters = {};
var _diffModal = null;
var _initialized = false;

// === CONSTANTES ===
var API_AUDIT = '/api/maint/v2/config/audit';

var ENTITY_TYPE_LABELS = {
    priority:       'Prioridad',
    category:       'Categoría',
    field_template: 'Campo de formulario',
    maint_type:     'Tipo de mantenimiento',
    service_origin: 'Origen de servicio',
    area:           'Área técnica',
    notification:   'Notificación',
};

var ACTION_LABELS = {
    create:  { label: 'Crear',    cls: 'bg-success-subtle text-success border border-success-subtle'     },
    update:  { label: 'Editar',   cls: 'bg-primary-subtle text-primary border border-primary-subtle'     },
    delete:  { label: 'Eliminar', cls: 'bg-danger-subtle text-danger border border-danger-subtle'         },
    toggle:  { label: 'Toggle',   cls: 'bg-warning-subtle text-warning border border-warning-subtle'      },
    reorder: { label: 'Reordenar',cls: 'bg-info-subtle text-info border border-info-subtle'               },
};

// === API PÚBLICA (lazy init) ===
window.MaintConfigAudit = {
    init: function () {
        if (_initialized) return;
        _initialized = true;
        _setup();
        _loadAudit(1);
    },
};

// === SETUP ===
function _setup() {
    _diffModal = new bootstrap.Modal(document.getElementById('modal-audit-diff'));

    document.getElementById('btn-audit-apply').addEventListener('click', function () {
        _loadAudit(1);
    });
    document.getElementById('btn-audit-clear').addEventListener('click', _clearFilters);

    // Delegación: ver diff en tabla + paginación
    document.getElementById('tbody-audit').addEventListener('click', _handleTableAction);
    document.getElementById('audit-pagination').addEventListener('click', _handlePagination);

    // Ver JSON crudo en modal diff
    document.getElementById('btn-audit-json').addEventListener('click', _toggleRawJson);
}

// === FILTROS ===
function _getFilters() {
    return {
        entity_type: document.getElementById('audit-filter-entity').value || '',
        action:      document.getElementById('audit-filter-action').value || '',
        user_id:     document.getElementById('audit-filter-user').value.trim() || '',
        date_from:   document.getElementById('audit-filter-from').value || '',
        date_to:     document.getElementById('audit-filter-to').value || '',
    };
}

function _clearFilters() {
    document.getElementById('audit-filter-entity').value = '';
    document.getElementById('audit-filter-action').value = '';
    document.getElementById('audit-filter-user').value   = '';
    document.getElementById('audit-filter-from').value   = '';
    document.getElementById('audit-filter-to').value     = '';
    _loadAudit(1);
}

// === CARGA DE DATOS ===
async function _loadAudit(page) {
    var tbody = document.getElementById('tbody-audit');
    tbody.innerHTML =
        '<tr><td colspan="6" class="text-center py-4 text-muted">' +
        '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
        'Cargando auditoría...</td></tr>';

    _auditFilters = _getFilters();
    var params = new URLSearchParams();
    params.set('page', page);
    params.set('per_page', 25);
    if (_auditFilters.entity_type) params.set('entity_type', _auditFilters.entity_type);
    if (_auditFilters.action)      params.set('action',      _auditFilters.action);
    if (_auditFilters.user_id)     params.set('user_id',     _auditFilters.user_id);
    if (_auditFilters.date_from)   params.set('date_from',   _auditFilters.date_from);
    if (_auditFilters.date_to)     params.set('date_to',     _auditFilters.date_to);

    try {
        var data = await MaintUtils.api.fetch(API_AUDIT + '?' + params.toString());
        _auditData  = data.data || [];
        _auditMeta  = {
            total:       data.total || 0,
            page:        data.page  || page,
            per_page:    data.per_page || 25,
            total_pages: data.total_pages || 1,
        };
        _renderTable(_auditData);
        _renderPagination(_auditMeta);
    } catch (e) {
        MaintUtils.toast(e.message || 'Error al cargar auditoría', 'error');
        tbody.innerHTML =
            '<tr><td colspan="6" class="text-center py-4 text-danger small">' +
            '<i class="fas fa-exclamation-circle me-1"></i>' +
            MaintUtils.escapeHtml(e.message || 'Error de conexión') +
            '</td></tr>';
        document.getElementById('audit-pagination').innerHTML = '';
    }
}

// === RENDER TABLA ===
function _renderTable(items) {
    var tbody = document.getElementById('tbody-audit');

    if (!items.length) {
        tbody.innerHTML =
            '<tr><td colspan="6" class="text-center py-5 text-muted">' +
            '<i class="fas fa-history fa-2x mb-3 d-block opacity-50"></i>' +
            'Sin registros de auditoría para los filtros seleccionados.' +
            '</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(function (entry) {
        var actionCfg = ACTION_LABELS[entry.action] || { label: MaintUtils.escapeHtml(entry.action), cls: 'bg-secondary-subtle text-secondary' };
        var entityLabel = ENTITY_TYPE_LABELS[entry.entity_type] || MaintUtils.escapeHtml(entry.entity_type || '—');
        var dateStr = _formatDate(entry.changed_at);
        var summary = _buildChangeSummary(entry);

        return '<tr>' +
            '<td class="text-nowrap small text-muted">' + MaintUtils.escapeHtml(dateStr) + '</td>' +
            '<td class="small">' +
                '<i class="fas fa-user fa-fw me-1 text-muted"></i>' +
                MaintUtils.escapeHtml(entry.user_name || String(entry.user_id || '—')) +
            '</td>' +
            '<td class="small">' +
                '<span class="text-muted">' + MaintUtils.escapeHtml(entityLabel) + '</span>' +
                (entry.entity_id
                    ? '<code class="ms-1 small text-muted">#' + MaintUtils.escapeHtml(String(entry.entity_id)) + '</code>'
                    : '') +
            '</td>' +
            '<td>' +
                '<span class="badge ' + actionCfg.cls + '">' + actionCfg.label + '</span>' +
            '</td>' +
            '<td class="small">' + summary + '</td>' +
            '<td class="text-end">' +
                '<button class="btn btn-outline-secondary btn-sm" ' +
                        'data-action="diff" data-id="' + entry.id + '" ' +
                        'title="Ver detalle del cambio">' +
                    '<i class="fas fa-code-branch"></i>' +
                '</button>' +
            '</td>' +
        '</tr>';
    }).join('');
}

// === RESUMEN DE CAMBIO ===
function _buildChangeSummary(entry) {
    var action = entry.action;

    if (action === 'reorder') {
        return '<span class="badge bg-info-subtle text-info border border-info-subtle">Reordenamiento</span>';
    }
    if (action === 'create') {
        return '<span class="text-muted small fst-italic">Registro creado</span>';
    }
    if (action === 'delete') {
        return '<span class="text-muted small fst-italic">Registro eliminado</span>';
    }
    if (action === 'toggle') {
        // Intentar extraer el campo cambiado del after_data (si viniera inline)
        return '<span class="badge bg-warning-subtle text-warning border border-warning-subtle">Estado cambiado</span>';
    }

    // Para update: mostrar hasta 2 campos cambiados
    var before = entry.before_data;
    var after  = entry.after_data;
    if (!before || !after || typeof before !== 'object' || typeof after !== 'object') {
        return '<span class="text-muted small fst-italic">Ver diff</span>';
    }

    var changes = [];
    var keys = Object.keys(after);
    for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        if (String(before[k]) !== String(after[k])) {
            changes.push(k);
        }
    }

    if (!changes.length) {
        return '<span class="text-muted small fst-italic">Sin cambios detectados</span>';
    }

    var shown = changes.slice(0, 2).map(function (k) {
        return '<code class="mn-audit-field">' + MaintUtils.escapeHtml(k) + '</code>';
    }).join(', ');

    var more = changes.length > 2
        ? ' <span class="badge bg-secondary-subtle text-secondary border border-secondary-subtle">+' + (changes.length - 2) + ' más</span>'
        : '';

    return shown + more;
}

// === PAGINACIÓN ===
function _renderPagination(meta) {
    var container = document.getElementById('audit-pagination');
    if (!container) return;

    var total = meta.total_pages;
    var curr  = meta.page;

    if (total <= 1) {
        container.innerHTML = '';
        return;
    }

    var pages = _buildPageWindow(curr, total);
    var items = pages.map(function (p) {
        if (p === '...') {
            return '<li class="page-item disabled"><span class="page-link">…</span></li>';
        }
        var active = (p === curr) ? ' active' : '';
        return '<li class="page-item' + active + '">' +
            '<button class="page-link" data-page="' + p + '">' + p + '</button>' +
        '</li>';
    });

    var prevDisabled = curr <= 1 ? ' disabled' : '';
    var nextDisabled = curr >= total ? ' disabled' : '';

    container.innerHTML =
        '<nav aria-label="Paginación auditoría">' +
        '<ul class="pagination pagination-sm mb-0 flex-wrap justify-content-end">' +
            '<li class="page-item' + prevDisabled + '">' +
                '<button class="page-link" data-page="' + (curr - 1) + '" ' + (curr <= 1 ? 'disabled' : '') + '>' +
                    '<i class="fas fa-chevron-left"></i>' +
                '</button>' +
            '</li>' +
            items.join('') +
            '<li class="page-item' + nextDisabled + '">' +
                '<button class="page-link" data-page="' + (curr + 1) + '" ' + (curr >= total ? 'disabled' : '') + '>' +
                    '<i class="fas fa-chevron-right"></i>' +
                '</button>' +
            '</li>' +
        '</ul>' +
        '</nav>';
}

/**
 * Ventana de páginas: curr ±2 + primera y última + elipsis.
 */
function _buildPageWindow(curr, total) {
    var pages = [];
    var window = 2;
    var start = Math.max(1, curr - window);
    var end   = Math.min(total, curr + window);

    if (start > 1) {
        pages.push(1);
        if (start > 2) pages.push('...');
    }
    for (var p = start; p <= end; p++) pages.push(p);
    if (end < total) {
        if (end < total - 1) pages.push('...');
        pages.push(total);
    }
    return pages;
}

function _handlePagination(e) {
    var btn = e.target.closest('[data-page]');
    if (!btn || btn.disabled) return;
    var page = parseInt(btn.getAttribute('data-page'), 10);
    if (!page || page < 1 || page > _auditMeta.total_pages) return;
    _loadAudit(page);
}

// === DELEGACIÓN EN TABLA ===
function _handleTableAction(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    if (btn.dataset.action === 'diff') {
        var id = parseInt(btn.dataset.id, 10);
        _openDiffModal(id, btn);
    }
}

// === MODAL DIFF ===
async function _openDiffModal(id, btn) {
    // Buscar en datos actuales primero (fast path)
    var entry = _auditData.find(function (e) { return e.id === id; });
    var needFull = !entry || entry.before_data === undefined;

    var diffBody = document.getElementById('audit-diff-body');
    diffBody.innerHTML =
        '<div class="text-center py-4 text-muted">' +
        '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Cargando...</div>';

    // Resetear JSON toggle
    var rawSection = document.getElementById('audit-raw-json');
    rawSection.classList.add('d-none');
    document.getElementById('btn-audit-json').textContent = 'Ver JSON crudo';

    _diffModal.show();

    try {
        if (needFull) {
            var data = await MaintUtils.api.fetch(API_AUDIT + '/' + id);
            entry = data.data || data;
        }
        _renderDiff(entry);
    } catch (e) {
        diffBody.innerHTML =
            '<div class="alert alert-danger m-3">' +
            '<i class="fas fa-exclamation-circle me-2"></i>' +
            MaintUtils.escapeHtml(e.message || 'Error al cargar el detalle') +
            '</div>';
    }
}

function _renderDiff(entry) {
    var diffBody   = document.getElementById('audit-diff-body');
    var rawPre     = document.getElementById('audit-raw-pre');
    var rawSection = document.getElementById('audit-raw-json');

    // Header info
    var actionCfg  = ACTION_LABELS[entry.action] || { label: entry.action, cls: 'bg-secondary-subtle text-secondary' };
    var entityLabel = ENTITY_TYPE_LABELS[entry.entity_type] || entry.entity_type || '—';

    // Actualizar título del modal
    document.getElementById('modal-audit-diff-label').innerHTML =
        '<i class="fas fa-code-branch me-2 text-primary"></i>' +
        MaintUtils.escapeHtml(entityLabel) +
        (entry.entity_id ? ' <code>#' + MaintUtils.escapeHtml(String(entry.entity_id)) + '</code>' : '') +
        ' — <span class="badge ' + actionCfg.cls + '">' + actionCfg.label + '</span>';

    var before = entry.before_data || {};
    var after  = entry.after_data  || {};

    // Unión de keys
    var allKeys = Array.from(new Set(
        Object.keys(before).concat(Object.keys(after))
    )).sort();

    if (!allKeys.length) {
        diffBody.innerHTML =
            '<p class="text-muted text-center py-4">Sin datos de cambio disponibles.</p>';
        return;
    }

    var rows = allKeys.map(function (k) {
        var bVal = before[k] !== undefined ? before[k] : null;
        var aVal = after[k]  !== undefined ? after[k]  : null;
        var bStr = _jsonVal(bVal);
        var aStr = _jsonVal(aVal);
        var changed  = bStr !== aStr;
        var onlyBefore = aVal === null && bVal !== null && !Object.prototype.hasOwnProperty.call(after, k);
        var onlyAfter  = bVal === null && aVal !== null && !Object.prototype.hasOwnProperty.call(before, k);

        var rowClass = '';
        var beforeClass = '';
        var afterClass  = '';

        if (onlyBefore) {
            rowClass    = 'table-danger';
            beforeClass = 'text-danger fw-medium';
        } else if (onlyAfter) {
            rowClass   = 'table-success';
            afterClass = 'text-success fw-medium';
        } else if (changed) {
            rowClass    = 'table-warning';
            beforeClass = 'text-danger';
            afterClass  = 'text-success fw-medium';
        }

        return '<tr class="' + rowClass + '">' +
            '<td class="small fw-medium text-muted">' + MaintUtils.escapeHtml(k) + '</td>' +
            '<td class="small ' + beforeClass + '">' + MaintUtils.escapeHtml(bStr) + '</td>' +
            '<td class="small ' + afterClass  + '">' + MaintUtils.escapeHtml(aStr) + '</td>' +
        '</tr>';
    }).join('');

    var legend =
        '<div class="d-flex flex-wrap gap-2 mb-3">' +
        '<span class="badge bg-success-subtle text-success border border-success-subtle">' +
            '<i class="fas fa-plus me-1"></i>Añadido</span>' +
        '<span class="badge bg-danger-subtle text-danger border border-danger-subtle">' +
            '<i class="fas fa-minus me-1"></i>Eliminado</span>' +
        '<span class="badge bg-warning-subtle text-warning border border-warning-subtle">' +
            '<i class="fas fa-edit me-1"></i>Modificado</span>' +
        '</div>';

    var metaInfo =
        '<p class="text-muted small mb-3">' +
        '<i class="fas fa-user fa-fw me-1"></i>' + MaintUtils.escapeHtml(entry.user_name || String(entry.user_id || '—')) +
        ' · <i class="fas fa-clock fa-fw ms-2 me-1"></i>' + MaintUtils.escapeHtml(_formatDate(entry.changed_at)) +
        (entry.ip_address ? ' · <i class="fas fa-network-wired fa-fw ms-2 me-1"></i>' + MaintUtils.escapeHtml(entry.ip_address) : '') +
        '</p>';

    diffBody.innerHTML = metaInfo + legend +
        '<div class="table-responsive">' +
        '<table class="table table-sm table-bordered align-middle mb-0">' +
        '<thead class="table-light"><tr>' +
            '<th style="width:30%">Campo</th>' +
            '<th style="width:35%"><i class="fas fa-minus text-danger me-1"></i>Antes</th>' +
            '<th style="width:35%"><i class="fas fa-plus text-success me-1"></i>Después</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
        '</table></div>';

    // Prepara JSON crudo
    rawPre.textContent = JSON.stringify({ before: before, after: after }, null, 2);
}

function _jsonVal(v) {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
}

function _toggleRawJson() {
    var rawSection = document.getElementById('audit-raw-json');
    var btn = document.getElementById('btn-audit-json');
    if (rawSection.classList.contains('d-none')) {
        rawSection.classList.remove('d-none');
        btn.textContent = 'Ocultar JSON';
    } else {
        rawSection.classList.add('d-none');
        btn.textContent = 'Ver JSON crudo';
    }
}

// === UTILIDADES ===
function _formatDate(str) {
    if (!str) return '—';
    try {
        var d = new Date(str);
        if (isNaN(d.getTime())) return String(str);
        return d.toLocaleDateString('es-MX', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
               ' ' + d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
        return String(str);
    }
}
