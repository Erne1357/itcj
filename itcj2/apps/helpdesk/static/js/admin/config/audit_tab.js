/**
 * audit_tab.js
 * Tab "Auditoría" del panel de Configuración.
 *
 * Responsabilidades:
 *  - Tabla paginada del log de cambios de configuración.
 *  - Filtros: entity_type, action, user_id, date_from, date_to.
 *  - Exportar a CSV (descarga directa via window.location).
 *  - Modal de detalle con diff visual lado-a-lado (before/after).
 *  - Toggle vista diff / JSON crudo en el modal de detalle.
 *  - Lazy init: carga datos solo la primera vez que el tab es visible.
 */
(function () {
    'use strict';

    // === ESTADO ===
    let initialized = false;
    let currentPage = 1;
    let totalPages = 1;
    let totalLogs = 0;
    const PER_PAGE = 50;

    // Filtros activos (solo los que tienen valor)
    let activeFilters = {};

    // === CONSTANTES ===
    const API_BASE = '/api/help-desk/v2/config/audit';

    const ENTITY_TYPE_OPTIONS = [
        { value: '',                        label: 'Todos los tipos' },
        { value: 'category',                label: 'Categoría de ticket' },
        { value: 'inventory_category',      label: 'Categoría de inventario' },
        { value: 'field_template',          label: 'Plantilla de campos' },
        { value: 'priority',                label: 'Prioridad' },
        { value: 'status',                  label: 'Estado' },
        { value: 'status_transition',       label: 'Transición de estado' },
        { value: 'status_transition_matrix','label': 'Matriz de transiciones' },
        { value: 'area',                    label: 'Área' },
        { value: 'notification_template',   label: 'Plantilla de notificación' },
    ];

    const ACTION_OPTIONS = [
        { value: '',            label: 'Todas las acciones' },
        { value: 'create',      label: 'Crear' },
        { value: 'update',      label: 'Actualizar' },
        { value: 'delete',      label: 'Eliminar' },
        { value: 'toggle',      label: 'Toggle activo' },
        { value: 'reorder',     label: 'Reordenar' },
        { value: 'bulk_update', label: 'Actualización masiva' },
    ];

    // Badge Bootstrap class por action
    const ACTION_BADGE = {
        create:      'bg-success',
        update:      'bg-primary',
        delete:      'bg-danger',
        toggle:      'bg-warning text-dark',
        reorder:     'bg-info text-dark',
        bulk_update: 'bg-secondary',
    };

    // Etiqueta legible por entity_type
    const ENTITY_LABELS = {
        category:                 'Categoría ticket',
        inventory_category:       'Cat. inventario',
        field_template:           'Plantilla campos',
        priority:                 'Prioridad',
        status:                   'Estado',
        status_transition:        'Transición',
        status_transition_matrix: 'Matriz transic.',
        area:                     'Área',
        notification_template:    'Notificación',
    };

    // === HELPERS ===
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /**
     * Produce un resumen inline legible del diff entre before y after.
     * Para reorder/bulk_update con shape {items:[...]} muestra un resumen especial.
     * Devuelve HTML listo para insertar (valores ya escapados).
     */
    function summarizeDiff(before, after, action) {
        // Acciones estructurales — shape diferente al CRUD normal
        if (action === 'reorder') {
            var count = 0;
            if (after && Array.isArray(after.items)) count = after.items.length;
            else if (before && Array.isArray(before.items)) count = before.items.length;
            return '<span class="badge bg-info bg-opacity-25 text-info border border-info">' +
                   (count ? count + ' items reordenados' : 'reordenados') + '</span>';
        }
        if (action === 'bulk_update') {
            var cnt = 0;
            if (after && Array.isArray(after.items)) cnt = after.items.length;
            else if (before && Array.isArray(before.items)) cnt = before.items.length;
            return '<span class="badge bg-secondary bg-opacity-25 text-secondary border">' +
                   (cnt ? cnt + ' items actualizados' : 'actualización masiva') + '</span>';
        }

        if (!before && !after) return '<span class="text-muted small">—</span>';
        if (!before) return '<span class="badge bg-success bg-opacity-25 text-success border border-success">creado</span>';
        if (!after)  return '<span class="badge bg-danger bg-opacity-25 text-danger border border-danger">eliminado</span>';

        var SKIP = { updated_at: true, created_at: true };
        var changes = [];
        var allKeys = new Set(Object.keys(before).concat(Object.keys(after)));
        allKeys.forEach(function (k) {
            if (SKIP[k]) return;
            var b = before[k];
            var a = after[k];
            if (JSON.stringify(b) !== JSON.stringify(a)) {
                changes.push({ key: k, b: b, a: a });
            }
        });

        if (changes.length === 0) return '<span class="text-muted small">sin diff</span>';

        var MAX = 2;
        var formatVal = function (v) {
            if (v === null || v === undefined) return '—';
            if (typeof v === 'object') return '{…}';
            var s = String(v);
            return s.length > 20 ? s.slice(0, 18) + '…' : s;
        };

        var html = changes.slice(0, MAX).map(function (c) {
            return '<div class="audit-summary-row small lh-sm">' +
                '<span class="text-muted font-monospace">' + escapeHtml(c.key) + ':</span> ' +
                '<span class="text-danger text-decoration-line-through">' + escapeHtml(formatVal(c.b)) + '</span>' +
                '<i class="fas fa-arrow-right text-muted mx-1" style="font-size:0.65rem;"></i>' +
                '<span class="text-success">' + escapeHtml(formatVal(c.a)) + '</span>' +
            '</div>';
        }).join('');

        if (changes.length > MAX) {
            html += '<div class="text-muted small">+' + (changes.length - MAX) + ' más</div>';
        }
        return html;
    }

    async function apiErrorMsg(res, fallback) {
        try {
            const d = await res.json();
            const v = d.error || d.message || d.detail;
            if (typeof v === 'string' && v) return v;
            if (Array.isArray(v)) {
                return v.map(function (e) { return (e && e.msg) ? e.msg : String(e); }).join('; ') || fallback;
            }
            return fallback;
        } catch (_) {
            return fallback + ' (HTTP ' + res.status + ')';
        }
    }

    /**
     * Formatea una fecha ISO a formato local legible.
     * "2026-05-11T10:30:00" → "11/05/2026 10:30"
     */
    function formatDateTime(isoStr) {
        if (!isoStr) return '—';
        try {
            const d = new Date(isoStr);
            if (isNaN(d.getTime())) return escapeHtml(isoStr);
            const pad = function (n) { return String(n).padStart(2, '0'); };
            return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear() +
                   ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
        } catch (_) {
            return escapeHtml(isoStr);
        }
    }

    /**
     * Construye URLSearchParams a partir de los filtros activos más el paginado.
     */
    function buildQueryParams(page) {
        const params = new URLSearchParams();
        if (activeFilters.entity_type) params.set('entity_type', activeFilters.entity_type);
        if (activeFilters.entity_id)   params.set('entity_id',   activeFilters.entity_id);
        if (activeFilters.action)      params.set('action',      activeFilters.action);
        if (activeFilters.user_id)     params.set('user_id',     activeFilters.user_id);
        if (activeFilters.date_from)   params.set('date_from',   activeFilters.date_from);
        if (activeFilters.date_to)     params.set('date_to',     activeFilters.date_to);
        params.set('page',     String(page || 1));
        params.set('per_page', String(PER_PAGE));
        return params;
    }

    // === INIT ===
    document.addEventListener('config:tab-shown', function (e) {
        if (e.detail && e.detail.tab === '#audit') {
            if (!initialized) {
                initialized = true;
                initAuditTab();
            }
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        const hash = window.location.hash || '';
        if (hash === '#audit') {
            if (!initialized) {
                initialized = true;
                initAuditTab();
            }
        }
        bindDetailModal();
    });

    function initAuditTab() {
        renderShell();
        loadLogs(1);
    }

    // === RENDER SHELL ===
    function renderShell() {
        const root = document.getElementById('audit-root');
        if (!root) return;

        const entityOpts = ENTITY_TYPE_OPTIONS.map(function (o) {
            return '<option value="' + escapeHtml(o.value) + '">' + escapeHtml(o.label) + '</option>';
        }).join('');

        const actionOpts = ACTION_OPTIONS.map(function (o) {
            return '<option value="' + escapeHtml(o.value) + '">' + escapeHtml(o.label) + '</option>';
        }).join('');

        root.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                <h5 class="mb-0 fw-semibold">
                    <i class="fas fa-history me-2 text-secondary"></i>Auditoría de Cambios
                </h5>
                <button class="btn btn-sm btn-outline-success" id="btn-audit-export" title="Exportar a CSV con filtros activos">
                    <i class="fas fa-file-csv me-1"></i><span class="d-none d-sm-inline">Exportar CSV</span>
                </button>
            </div>

            <!-- Barra de filtros -->
            <div class="audit-filters-bar">
                <div class="row g-2 align-items-end">
                    <div class="col-12 col-sm-6 col-lg-3">
                        <label for="audit-filter-entity" class="form-label form-label-sm fw-semibold mb-1">
                            Tipo de entidad
                        </label>
                        <select class="form-select form-select-sm" id="audit-filter-entity">
                            ${entityOpts}
                        </select>
                    </div>
                    <div class="col-12 col-sm-6 col-lg-2">
                        <label for="audit-filter-action" class="form-label form-label-sm fw-semibold mb-1">
                            Acción
                        </label>
                        <select class="form-select form-select-sm" id="audit-filter-action">
                            ${actionOpts}
                        </select>
                    </div>
                    <div class="col-12 col-sm-6 col-lg-2">
                        <label for="audit-filter-user" class="form-label form-label-sm fw-semibold mb-1">
                            ID de usuario
                        </label>
                        <input type="number" class="form-control form-control-sm" id="audit-filter-user"
                               placeholder="ej: 42" min="1" step="1">
                    </div>
                    <div class="col-12 col-sm-6 col-lg-2">
                        <label for="audit-filter-from" class="form-label form-label-sm fw-semibold mb-1">
                            Desde
                        </label>
                        <input type="date" class="form-control form-control-sm" id="audit-filter-from">
                    </div>
                    <div class="col-12 col-sm-6 col-lg-2">
                        <label for="audit-filter-to" class="form-label form-label-sm fw-semibold mb-1">
                            Hasta
                        </label>
                        <input type="date" class="form-control form-control-sm" id="audit-filter-to">
                    </div>
                    <div class="col-12 col-sm-6 col-lg-1 d-flex gap-1 justify-content-end justify-content-lg-start">
                        <button class="btn btn-sm btn-primary flex-fill" id="btn-audit-apply" title="Aplicar filtros">
                            <i class="fas fa-filter me-1"></i><span class="d-none d-sm-inline">Aplicar</span>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" id="btn-audit-clear" title="Limpiar filtros">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Contador de resultados -->
            <div id="audit-result-info" class="text-muted small mb-2"></div>

            <!-- Tabla -->
            <div class="table-responsive" id="audit-table-wrapper">
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando registros...
                </div>
            </div>

            <!-- Paginación -->
            <div id="audit-pagination" class="mt-3"></div>
        `;

        // Bind filtros y botones
        const root2 = document.getElementById('audit-root');

        root2.querySelector('#btn-audit-apply').addEventListener('click', function () {
            applyFilters();
        });

        root2.querySelector('#btn-audit-clear').addEventListener('click', function () {
            clearFilters();
        });

        root2.querySelector('#btn-audit-export').addEventListener('click', function () {
            handleExport();
        });

        // Aplicar filtros también con Enter en inputs de texto
        root2.querySelectorAll('#audit-filter-user, #audit-filter-from, #audit-filter-to').forEach(function (inp) {
            inp.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') applyFilters();
            });
        });
    }

    // === FILTROS ===
    function readFiltersFromUI() {
        const filters = {};
        const entityVal = (document.getElementById('audit-filter-entity') || {}).value;
        const actionVal = (document.getElementById('audit-filter-action') || {}).value;
        const userVal   = ((document.getElementById('audit-filter-user')  || {}).value || '').trim();
        const fromVal   = ((document.getElementById('audit-filter-from')  || {}).value || '').trim();
        const toVal     = ((document.getElementById('audit-filter-to')    || {}).value || '').trim();

        if (entityVal) filters.entity_type = entityVal;
        if (actionVal) filters.action      = actionVal;
        if (userVal)   filters.user_id     = userVal;
        if (fromVal)   filters.date_from   = fromVal;
        if (toVal)     filters.date_to     = toVal;
        return filters;
    }

    function applyFilters() {
        activeFilters = readFiltersFromUI();
        currentPage = 1;
        loadLogs(1);
    }

    function clearFilters() {
        activeFilters = {};
        const ids = ['audit-filter-entity', 'audit-filter-action', 'audit-filter-user', 'audit-filter-from', 'audit-filter-to'];
        ids.forEach(function (id) {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        currentPage = 1;
        loadLogs(1);
    }

    // === EXPORTAR CSV ===
    function handleExport() {
        const filters = readFiltersFromUI();
        const params = new URLSearchParams();
        if (filters.entity_type) params.set('entity_type', filters.entity_type);
        if (filters.entity_id)   params.set('entity_id',   filters.entity_id);
        if (filters.action)      params.set('action',      filters.action);
        if (filters.user_id)     params.set('user_id',     filters.user_id);
        if (filters.date_from)   params.set('date_from',   filters.date_from);
        if (filters.date_to)     params.set('date_to',     filters.date_to);

        const url = API_BASE + '/export.csv?' + params.toString();

        // Usar fetch para capturar error 400 (too_many_rows) antes de redirigir
        fetch(url, { method: 'HEAD' }).then(function (res) {
            if (res.status === 400) {
                return res.json().then(function (d) {
                    const msg = (d && (d.error || d.message || d.detail)) || 'Demasiados registros para exportar. Aplica filtros más restrictivos.';
                    HelpdeskUtils.showToast(String(msg), 'error');
                }).catch(function () {
                    HelpdeskUtils.showToast('Demasiados registros para exportar. Aplica filtros más restrictivos.', 'error');
                });
            }
            // Si OK (200), descargar
            window.location = url;
        }).catch(function () {
            // En caso de error de red también iniciamos la descarga
            window.location = url;
        });
    }

    // === CARGA DE DATOS ===
    async function loadLogs(page) {
        currentPage = page;

        const wrapper = document.getElementById('audit-table-wrapper');
        const infoEl  = document.getElementById('audit-result-info');
        if (wrapper) {
            wrapper.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando registros...
                </div>`;
        }
        if (infoEl) infoEl.textContent = '';

        const params = buildQueryParams(page);

        try {
            const res = await fetch(API_BASE + '?' + params.toString());
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cargar el log de auditoría');
                HelpdeskUtils.showToast(msg, 'error');
                if (wrapper) {
                    wrapper.innerHTML = '<div class="text-danger small p-2"><i class="fas fa-exclamation-circle me-1"></i>Error al cargar registros.</div>';
                }
                return;
            }

            const data = await res.json();
            const logs    = data.logs     || [];
            const total   = data.total    || 0;
            const pages   = data.pages    || 1;

            totalLogs  = total;
            totalPages = pages;

            renderTable(logs);
            renderResultInfo(total, page, pages);
            renderPagination(page, pages);
        } catch (err) {
            console.error('audit_tab: loadLogs error', err);
            HelpdeskUtils.showToast('Error de conexión al cargar auditoría', 'error');
            if (wrapper) {
                wrapper.innerHTML = '<div class="text-danger small p-2"><i class="fas fa-exclamation-circle me-1"></i>Error de conexión.</div>';
            }
        }
    }

    // === RENDER TABLA ===
    function renderTable(logs) {
        const wrapper = document.getElementById('audit-table-wrapper');
        if (!wrapper) return;

        if (!logs.length) {
            wrapper.innerHTML = `
                <div class="text-center py-5 text-muted">
                    <i class="fas fa-history fa-3x mb-3 opacity-50"></i>
                    <p class="mb-1 fw-semibold">Sin registros</p>
                    <p class="small mb-0">No se encontraron entradas con los filtros aplicados.</p>
                </div>`;
            return;
        }

        const rows = logs.map(function (log) {
            return renderLogRow(log);
        }).join('');

        wrapper.innerHTML = `
            <table class="table table-sm table-hover audit-table align-middle mb-0">
                <thead class="table-light">
                    <tr>
                        <th style="min-width:130px">Fecha</th>
                        <th style="min-width:130px">Usuario</th>
                        <th style="min-width:160px">Entidad</th>
                        <th style="min-width:110px">Acción</th>
                        <th class="d-none d-md-table-cell" style="min-width:180px">Resumen</th>
                        <th class="d-none d-md-table-cell" style="min-width:110px">IP</th>
                        <th style="width:60px"></th>
                    </tr>
                </thead>
                <tbody id="audit-tbody">
                    ${rows}
                </tbody>
            </table>`;

        // Bind botones de detalle
        const tbody = document.getElementById('audit-tbody');
        if (tbody) {
            tbody.querySelectorAll('.btn-audit-detail').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const logId = parseInt(btn.dataset.id, 10);
                    openDetailModal(logId);
                });
            });
        }
    }

    function renderLogRow(log) {
        const dateStr    = formatDateTime(log.changed_at);
        const userName   = (log.user && log.user.full_name) ? escapeHtml(log.user.full_name) : ('Usuario #' + (log.user_id || '?'));
        const entityType = log.entity_type || '';
        const entityId   = log.entity_id   != null ? log.entity_id : '?';
        const action     = log.action      || '';
        const ip         = log.ip_address  || '—';

        const entityLabel = escapeHtml(ENTITY_LABELS[entityType] || entityType);
        const entityChip  = `<span class="badge bg-light text-dark border me-1">${entityLabel}</span>` +
                            `<span class="badge bg-secondary font-monospace">#${escapeHtml(String(entityId))}</span>`;

        const badgeCls   = ACTION_BADGE[action] || 'bg-secondary';
        const actionBadge = `<span class="badge ${escapeHtml(badgeCls)}">${escapeHtml(action)}</span>`;

        const diffSummary = summarizeDiff(log.before_data || null, log.after_data || null, action);

        return `
            <tr>
                <td class="text-nowrap small">${dateStr}</td>
                <td class="small">${userName}</td>
                <td>${entityChip}</td>
                <td>${actionBadge}</td>
                <td class="d-none d-md-table-cell">${diffSummary}</td>
                <td class="d-none d-md-table-cell small text-muted font-monospace">${escapeHtml(ip)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-secondary btn-audit-detail"
                            data-id="${log.id}" title="Ver detalle del cambio">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            </tr>`;
    }

    // === RENDER INFO DE RESULTADOS ===
    function renderResultInfo(total, page, pages) {
        const infoEl = document.getElementById('audit-result-info');
        if (!infoEl) return;

        if (total === 0) {
            infoEl.textContent = 'Sin resultados';
            return;
        }

        const from = ((page - 1) * PER_PAGE) + 1;
        const to   = Math.min(page * PER_PAGE, total);
        infoEl.textContent = 'Mostrando ' + from + '–' + to + ' de ' + total + ' registros';
    }

    // === PAGINACIÓN ===
    function renderPagination(page, pages) {
        const container = document.getElementById('audit-pagination');
        if (!container) return;

        if (pages <= 1) {
            container.innerHTML = '';
            return;
        }

        // Páginas a mostrar: anterior, hasta 5 centrales, siguiente
        const items = [];

        // Botón anterior
        const prevDisabled = page <= 1 ? ' disabled' : '';
        items.push(
            '<li class="page-item' + prevDisabled + '">' +
            '<button class="page-link" data-page="' + (page - 1) + '"' + (page <= 1 ? ' tabindex="-1" aria-disabled="true"' : '') + '>' +
            '<i class="fas fa-chevron-left"></i></button></li>'
        );

        // Rango de páginas
        let rangeStart = Math.max(1, page - 2);
        let rangeEnd   = Math.min(pages, page + 2);

        if (rangeStart > 1) {
            items.push('<li class="page-item"><button class="page-link" data-page="1">1</button></li>');
            if (rangeStart > 2) {
                items.push('<li class="page-item disabled"><span class="page-link">…</span></li>');
            }
        }

        for (let p = rangeStart; p <= rangeEnd; p++) {
            const active = (p === page) ? ' active' : '';
            items.push(
                '<li class="page-item' + active + '">' +
                '<button class="page-link" data-page="' + p + '">' + p + '</button></li>'
            );
        }

        if (rangeEnd < pages) {
            if (rangeEnd < pages - 1) {
                items.push('<li class="page-item disabled"><span class="page-link">…</span></li>');
            }
            items.push('<li class="page-item"><button class="page-link" data-page="' + pages + '">' + pages + '</button></li>');
        }

        // Botón siguiente
        const nextDisabled = page >= pages ? ' disabled' : '';
        items.push(
            '<li class="page-item' + nextDisabled + '">' +
            '<button class="page-link" data-page="' + (page + 1) + '"' + (page >= pages ? ' tabindex="-1" aria-disabled="true"' : '') + '>' +
            '<i class="fas fa-chevron-right"></i></button></li>'
        );

        container.innerHTML = '<ul class="pagination pagination-sm justify-content-center flex-wrap mb-0">' + items.join('') + '</ul>';

        container.querySelectorAll('.page-link[data-page]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const p = parseInt(btn.dataset.page, 10);
                if (!isNaN(p) && p >= 1 && p <= totalPages && p !== currentPage) {
                    loadLogs(p);
                }
            });
        });
    }

    // === MODAL DE DETALLE ===

    /**
     * Construye el diff entre before y after.
     * Devuelve array de { key, before, after, status }
     * status: 'unchanged' | 'modified' | 'added' | 'removed'
     */
    function renderDiff(before, after) {
        before = before || {};
        after  = after  || {};
        const allKeys = new Set(Object.keys(before).concat(Object.keys(after)));
        return Array.from(allKeys).sort().map(function (key) {
            const b = before[key];
            const a = after[key];
            let status = 'unchanged';
            if (!(key in before))                              status = 'added';
            else if (!(key in after))                          status = 'removed';
            else if (JSON.stringify(b) !== JSON.stringify(a))  status = 'modified';
            return { key: key, before: b, after: a, status: status };
        });
    }

    /**
     * Renderiza el valor de una celda del diff.
     * Valores primitivos: texto escapado.
     * Valores complejos (objeto/array): <pre> con JSON formateado.
     */
    function renderDiffValue(val) {
        if (val === null || val === undefined) {
            return '<span class="text-muted fst-italic">null</span>';
        }
        if (typeof val === 'object') {
            return '<pre class="diff-value-complex mb-0">' + escapeHtml(JSON.stringify(val, null, 2)) + '</pre>';
        }
        if (typeof val === 'boolean') {
            return '<span class="badge ' + (val ? 'bg-success' : 'bg-secondary') + '">' + String(val) + '</span>';
        }
        return escapeHtml(String(val));
    }

    /**
     * Construye las tablas HTML de diff para before y after.
     * Devuelve { beforeHtml, afterHtml }
     */
    function buildDiffTables(diffItems) {
        var beforeRows = '';
        var afterRows  = '';

        diffItems.forEach(function (item) {
            var trCls = '';
            if (item.status === 'modified') trCls = ' class="diff-modified"';
            if (item.status === 'added')    trCls = ' class="diff-added"';
            if (item.status === 'removed')  trCls = ' class="diff-removed"';

            var tooltip = '';
            if (item.status === 'modified') tooltip = ' title="Modificado"';

            var keyCell = '<td' + tooltip + '>' + escapeHtml(item.key) + '</td>';

            if (item.status === 'added') {
                // Solo presente en after
                beforeRows += '<tr' + trCls + '>' + keyCell + '<td class="text-muted fst-italic">—</td></tr>';
                afterRows  += '<tr' + trCls + '>' + keyCell + '<td>' + renderDiffValue(item.after) + '</td></tr>';
            } else if (item.status === 'removed') {
                // Solo presente en before
                beforeRows += '<tr' + trCls + '>' + keyCell + '<td>' + renderDiffValue(item.before) + '</td></tr>';
                afterRows  += '<tr' + trCls + '>' + keyCell + '<td class="text-muted fst-italic">—</td></tr>';
            } else {
                // unchanged o modified: ambas columnas muestran el valor
                beforeRows += '<tr' + trCls + '>' + keyCell + '<td>' + renderDiffValue(item.before) + '</td></tr>';
                afterRows  += '<tr' + trCls + '>' + keyCell + '<td>' + renderDiffValue(item.after)  + '</td></tr>';
            }
        });

        const wrapTable = function (rows) {
            if (!rows) {
                return '<div class="text-muted fst-italic small p-2">Sin datos</div>';
            }
            return '<table class="diff-table table table-borderless mb-0"><tbody>' + rows + '</tbody></table>';
        };

        return {
            beforeHtml: wrapTable(beforeRows),
            afterHtml:  wrapTable(afterRows),
        };
    }

    async function openDetailModal(logId) {
        const modal = document.getElementById('modal-audit-detail');
        if (!modal) return;

        // Resetear contenido
        const bodyEl = modal.querySelector('#audit-detail-body');
        if (bodyEl) {
            bodyEl.innerHTML = `
                <div class="text-center py-4 text-muted small">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    Cargando detalle...
                </div>`;
        }

        // Limpiar header dinámico
        const headerMeta = modal.querySelector('#audit-detail-header-meta');
        if (headerMeta) headerMeta.innerHTML = '';

        bootstrap.Modal.getOrCreateInstance(modal).show();

        try {
            const res = await fetch(API_BASE + '/' + logId);
            if (!res.ok) {
                const msg = await apiErrorMsg(res, 'Error al cargar el detalle');
                if (bodyEl) {
                    bodyEl.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle me-1"></i>' + escapeHtml(msg) + '</div>';
                }
                return;
            }

            const log = await res.json();
            renderDetailModal(modal, log);
        } catch (err) {
            console.error('audit_tab: openDetailModal error', err);
            if (bodyEl) {
                bodyEl.innerHTML = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle me-1"></i>Error de conexión.</div>';
            }
        }
    }

    function renderDetailModal(modal, log) {
        const action      = log.action      || '';
        const entityType  = log.entity_type || '';
        const entityId    = log.entity_id   != null ? log.entity_id : '?';
        const changedAt   = formatDateTime(log.changed_at);
        const userName    = (log.user && log.user.full_name) ? log.user.full_name : ('Usuario #' + (log.user_id || '?'));
        const badgeCls    = ACTION_BADGE[action] || 'bg-secondary';
        const entityLabel = ENTITY_LABELS[entityType] || entityType;

        // Header dinámico
        const headerMeta = modal.querySelector('#audit-detail-header-meta');
        if (headerMeta) {
            headerMeta.innerHTML =
                '<span class="badge ' + escapeHtml(badgeCls) + ' me-2">' + escapeHtml(action) + '</span>' +
                '<span class="me-2">' + escapeHtml(entityLabel) + ' <strong>#' + escapeHtml(String(entityId)) + '</strong></span>' +
                '<span class="text-muted small me-2"><i class="fas fa-clock me-1"></i>' + changedAt + '</span>' +
                '<span class="text-muted small"><i class="fas fa-user me-1"></i>' + escapeHtml(userName) + '</span>';
        }

        const before = log.before_data || null;
        const after  = log.after_data  || null;
        const diffItems = renderDiff(before, after);
        const tables    = buildDiffTables(diffItems);

        const beforeIsEmpty = !before || Object.keys(before).length === 0;
        const afterIsEmpty  = !after  || Object.keys(after).length  === 0;

        // Construir raw JSON
        const rawJson = JSON.stringify({ before_data: before, after_data: after }, null, 2);

        const bodyEl = modal.querySelector('#audit-detail-body');
        if (!bodyEl) return;

        bodyEl.innerHTML = `
            <!-- Vista diff (por defecto) -->
            <div id="audit-diff-view">
                <div class="row g-3">
                    <div class="col-md-6">
                        <div class="diff-column">
                            <div class="diff-column-header">
                                <i class="fas fa-arrow-left me-1 text-danger"></i>Antes
                                ${beforeIsEmpty ? '<span class="badge bg-secondary ms-2 small">vacío</span>' : ''}
                            </div>
                            <div>${tables.beforeHtml}</div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="diff-column">
                            <div class="diff-column-header">
                                <i class="fas fa-arrow-right me-1 text-success"></i>Después
                                ${afterIsEmpty ? '<span class="badge bg-secondary ms-2 small">vacío</span>' : ''}
                            </div>
                            <div>${tables.afterHtml}</div>
                        </div>
                    </div>
                </div>

                <div class="mt-3">
                    <div class="d-flex flex-wrap gap-2 align-items-center">
                        <span class="small text-muted fw-semibold">Leyenda:</span>
                        <span class="badge diff-legend-added">Campo nuevo</span>
                        <span class="badge diff-legend-removed">Campo eliminado</span>
                        <span class="badge diff-legend-modified">Campo modificado</span>
                        <span class="badge diff-legend-unchanged">Sin cambios</span>
                    </div>
                </div>
            </div>

            <!-- Vista JSON cruda (oculta por defecto) -->
            <div id="audit-raw-view" class="d-none">
                <pre class="audit-raw-json p-3 rounded bg-light border" style="font-size:0.8rem;max-height:400px;overflow:auto;">${escapeHtml(rawJson)}</pre>
            </div>
        `;

        // Bind botón toggle diff/raw
        const btnToggle = modal.querySelector('#btn-audit-toggle-view');
        if (btnToggle) {
            // Limpiar listeners anteriores clonando el nodo
            const newBtn = btnToggle.cloneNode(true);
            btnToggle.parentNode.replaceChild(newBtn, btnToggle);
            newBtn.addEventListener('click', function () {
                const diffView = document.getElementById('audit-diff-view');
                const rawView  = document.getElementById('audit-raw-view');
                if (!diffView || !rawView) return;
                const showing = !rawView.classList.contains('d-none');
                if (showing) {
                    rawView.classList.add('d-none');
                    diffView.classList.remove('d-none');
                    newBtn.innerHTML = '<i class="fas fa-code me-1"></i>Ver JSON crudo';
                } else {
                    diffView.classList.add('d-none');
                    rawView.classList.remove('d-none');
                    newBtn.innerHTML = '<i class="fas fa-table me-1"></i>Ver diff visual';
                }
            });
        }
    }

    // === BIND MODAL DETALLE (solo una vez en DOMContentLoaded) ===
    function bindDetailModal() {
        const modal = document.getElementById('modal-audit-detail');
        if (!modal) return;
        if (modal.dataset.auditBound) return;
        modal.dataset.auditBound = '1';

        // Al ocultar el modal, resetear el botón de toggle
        modal.addEventListener('hidden.bs.modal', function () {
            const btn = modal.querySelector('#btn-audit-toggle-view');
            if (btn) btn.innerHTML = '<i class="fas fa-code me-1"></i>Ver JSON crudo';
            const diffView = document.getElementById('audit-diff-view');
            const rawView  = document.getElementById('audit-raw-view');
            if (diffView) diffView.classList.remove('d-none');
            if (rawView)  rawView.classList.add('d-none');
        });
    }

})();
