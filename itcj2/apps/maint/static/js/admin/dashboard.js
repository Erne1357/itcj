/**
 * dashboard.js — Dashboard Departamental de Mantenimiento
 * Detecta nivel de acceso (full / summary) e intenta /full primero;
 * si recibe 403 cae a /summary. Puebla KPIs, tablas operativas y
 * (en full) gráficas por estado / categoría, tabla por técnico y SLA.
 */
'use strict';

// === CONSTANTES ===
var API_BASE    = '/api/maint/v2/dashboard';
var TICKETS_URL = '/maint/tickets/';

// === ESTADO ===
var _currentDeptId = null;
var _dashLevel     = null;   // 'full' | 'summary'
var _charts        = {};

// === COLORES ===
var STATUS_COLORS = {
    PENDING:          '#f59e0b',
    ASSIGNED:         '#0891b2',
    IN_PROGRESS:      '#546E7A',
    RESOLVED_SUCCESS: '#10b981',
    RESOLVED_FAILED:  '#dc2626',
    CLOSED:           '#607D8B',
    CANCELED:         '#9ca3af',
};

var STATUS_LABELS = {
    PENDING:          'Pendiente',
    ASSIGNED:         'Asignado',
    IN_PROGRESS:      'En progreso',
    RESOLVED_SUCCESS: 'Resuelto (éxito)',
    RESOLVED_FAILED:  'Resuelto (fallo)',
    CLOSED:           'Cerrado',
    CANCELED:         'Cancelado',
};

var PRIORITY_COLORS = {
    BAJA:    'success',
    MEDIA:   'warning',
    ALTA:    'danger',
    URGENTE: 'purple',
};

// === INICIALIZACIÓN ===
document.addEventListener('DOMContentLoaded', function () {
    loadDepartments();
    setupEventListeners();
    loadUnratedSection();
});

// === SETUP ===
function setupEventListeners() {
    var sel = document.getElementById('deptSelector');
    if (sel) {
        sel.addEventListener('change', function () {
            _currentDeptId = this.value || null;
            loadDashboard(_currentDeptId);
        });
    }

    var btnRefresh = document.getElementById('btnRefresh');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', function () {
            loadDashboard(_currentDeptId);
        });
    }
}

// === CARGA DE DEPARTAMENTOS ===
function loadDepartments() {
    MaintUtils.api.fetch(API_BASE + '/me/departments')
        .then(function (resp) {
            var depts      = (resp && resp.data)         || [];
            var isAdminGlb = (resp && resp.is_admin_global) || false;

            var sel  = document.getElementById('deptSelector');
            var wrap = document.getElementById('deptSelectorWrap');

            if (depts.length === 0 && !isAdminGlb) {
                // Sin departamentos — el usuario solo ve su propio dept implícito
                _currentDeptId = null;
                loadDashboard(null);
                return;
            }

            if (depts.length === 1 && !isAdminGlb) {
                // Un solo departamento: no mostrar selector, usar directo
                _currentDeptId = depts[0].id;
                loadDashboard(_currentDeptId);
                return;
            }

            // Varios departamentos o admin global: mostrar selector
            sel.innerHTML = '';

            // Opción "Todos" siempre disponible cuando hay multi-dept.
            // Admin global → "Todos los departamentos" (ITCJ).
            // User multi-dept → "Todos mis departamentos" (sumar los suyos).
            var optAll = document.createElement('option');
            optAll.value = '';
            optAll.textContent = isAdminGlb
                ? 'Todos los departamentos'
                : 'Todos mis departamentos';
            sel.appendChild(optAll);

            depts.forEach(function (d) {
                var opt = document.createElement('option');
                opt.value = d.id;
                opt.textContent = escapeHtml(d.name) + (d.code ? ' (' + escapeHtml(d.code) + ')' : '');
                sel.appendChild(opt);
            });

            if (wrap) wrap.classList.remove('d-none');

            _currentDeptId = sel.value || null;
            loadDashboard(_currentDeptId);
        })
        .catch(function (err) {
            MaintUtils.toast((err && err.message) || 'Error al cargar departamentos', 'error');
            // Intentar cargar igual sin dept
            loadDashboard(null);
        });
}

// === CARGA PRINCIPAL DEL DASHBOARD ===
function loadDashboard(deptId) {
    showLoading(true);

    var qs = deptId ? ('?dept=' + encodeURIComponent(deptId)) : '';

    MaintUtils.api.fetch(API_BASE + '/full' + qs)
        .then(function (resp) {
            _dashLevel = 'full';
            renderDashboard(resp.data || {}, 'full');
        })
        .catch(function (err) {
            // Si es 403 → intentar summary
            var status = err && err.status;
            if (status === 403 || (err && err.message && err.message.indexOf('403') !== -1)) {
                MaintUtils.api.fetch(API_BASE + '/summary' + qs)
                    .then(function (resp2) {
                        _dashLevel = 'summary';
                        renderDashboard(resp2.data || {}, 'summary');
                    })
                    .catch(function (err2) {
                        showLoading(false);
                        MaintUtils.toast((err2 && err2.message) || 'Error al cargar dashboard', 'error');
                    });
            } else {
                showLoading(false);
                MaintUtils.toast((err && err.message) || 'Error al cargar dashboard', 'error');
            }
        });
}

// === RENDER COMPLETO ===
function renderDashboard(data, level) {
    renderKpis(data.kpis || {}, level);
    // U3: pasar el KPI real de "sin asignar" para que el badge
    // no muestre el largo de la lista truncada (máx 10), sino el total real.
    renderUnassigned(data.unassigned_tickets || [], (data.kpis || {}).unassigned);
    renderRecentOpen(data.recent_open || [], (data.kpis || {}).open_total);

    var fullSection = document.getElementById('fullSection');
    var levelBadge  = document.getElementById('levelBadge');

    if (level === 'full') {
        if (fullSection) fullSection.classList.remove('d-none');
        renderOverdue(data.overdue_tickets || [], (data.kpis || {}).overdue);
        renderByStatus(data.by_status || {});
        renderByCategory(data.by_category || []);
        // "Por técnico" oculto si la API no la entrega (caso dh: reservado a admins maint).
        var techWrap = document.getElementById('byTechnicianWrap');
        if (data.by_technician) {
            if (techWrap) techWrap.classList.remove('d-none');
            renderByTechnician(data.by_technician);
        } else {
            if (techWrap) techWrap.classList.add('d-none');
        }
        renderSLA(data.sla_breakdown || {});
        if (levelBadge) {
            levelBadge.classList.remove('d-none');
            levelBadge.innerHTML = '<i class="fas fa-eye me-1"></i>Vista completa';
            levelBadge.classList.remove('mn-dash-level-badge--summary');
            levelBadge.classList.add('mn-dash-level-badge--full');
        }
    } else {
        if (fullSection) fullSection.classList.add('d-none');
        // Ocultar KPIs solo de full
        hideFullKpis();
        if (levelBadge) {
            levelBadge.classList.remove('d-none');
            levelBadge.innerHTML = '<i class="fas fa-eye me-1"></i>Vista resumen';
            levelBadge.classList.remove('mn-dash-level-badge--full');
            levelBadge.classList.add('mn-dash-level-badge--summary');
        }
    }

    showLoading(false);
}

// === KPIs ===
function renderKpis(kpis, level) {
    setKpiCount('kpiOpenTotal',    kpis.open_total);
    setKpiCount('kpiUnassigned',   kpis.unassigned);
    setKpiCount('kpiInProgress',   kpis.in_progress);
    setKpiCount('kpiOverdue',      kpis.overdue);
    setKpiCount('kpiResolvedWeek', kpis.resolved_this_week);

    var avgCol   = document.getElementById('kpiAvgResCol');
    var ratedCol = document.getElementById('kpiRatedCol');

    if (level === 'full') {
        if (avgCol) {
            avgCol.classList.remove('d-none');
            var avgHrs = kpis.avg_resolution_hours;
            var avgEl  = document.getElementById('kpiAvgRes');
            if (avgEl) {
                avgEl.textContent = (avgHrs !== null && avgHrs !== undefined)
                    ? (avgHrs >= 1 ? fmtNum(avgHrs) + ' h' : fmtNum(avgHrs * 60) + ' min')
                    : '—';
            }
        }
        if (ratedCol) {
            ratedCol.classList.remove('d-none');
            var ratedEl = document.getElementById('kpiRatedPct');
            if (ratedEl) {
                var pct = kpis.rated_pct;
                ratedEl.textContent = (pct !== null && pct !== undefined) ? fmtPct(pct) : '—';
            }
        }
    } else {
        if (avgCol)   avgCol.classList.add('d-none');
        if (ratedCol) ratedCol.classList.add('d-none');
    }
}

function hideFullKpis() {
    var avgCol   = document.getElementById('kpiAvgResCol');
    var ratedCol = document.getElementById('kpiRatedCol');
    if (avgCol)   avgCol.classList.add('d-none');
    if (ratedCol) ratedCol.classList.add('d-none');
}

// === TABLA: SIN ASIGNAR (alcance: Departamento) ===
// U3 fix: el badge usa el KPI real (kpiTotal), no tickets.length,
// ya que la API devuelve máximo ~10 tickets en la lista pero el total
// puede ser mayor. El KPI viene de data.kpis.unassigned.
function renderUnassigned(tickets, kpiTotal) {
    var tbody   = document.getElementById('unassignedBody');
    var countEl = document.getElementById('unassignedCount');

    var realTotal = (kpiTotal !== null && kpiTotal !== undefined) ? kpiTotal : tickets.length;
    if (countEl) countEl.textContent = realTotal;

    if (!tickets.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">' +
            '<i class="fas fa-check-circle text-success me-1"></i>Sin tickets sin asignar</td></tr>';
        return;
    }

    tbody.innerHTML = tickets.map(function (t) {
        return '<tr class="mn-dash-row-clickable" onclick="goTicket(' + t.id + ')" style="cursor:pointer;">' +
            '<td><span class="fw-semibold text-primary small">' + escapeHtml(t.ticket_number || ('#' + t.id)) + '</span>' +
            '<br><span class="text-muted" style="font-size:0.78rem;">' + escapeHtml(truncate(t.title, 40)) + '</span></td>' +
            '<td>' + priorityBadge(t.priority) + '</td>' +
            '<td class="d-none d-md-table-cell small">' + escapeHtml(t.category_name || '—') + '</td>' +
            '<td class="d-none d-sm-table-cell small">' + escapeHtml(t.requester_name || '—') + '</td>' +
            '<td class="small text-muted text-nowrap">' + ageLabel(t.created_at) + '</td>' +
        '</tr>';
    }).join('');
}

// === TABLA: ÚLTIMOS ABIERTOS (alcance: Departamento) ===
// El segundo argumento kpiTotal no se muestra como badge aquí (no hay countEl
// para "Últimos abiertos"), pero se recibe por consistencia de firma.
function renderRecentOpen(tickets, kpiTotal) {
    var tbody = document.getElementById('recentOpenBody');

    if (!tickets.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">Sin tickets abiertos</td></tr>';
        return;
    }

    tbody.innerHTML = tickets.map(function (t) {
        return '<tr class="mn-dash-row-clickable" onclick="goTicket(' + t.id + ')" style="cursor:pointer;">' +
            '<td><span class="fw-semibold text-primary small">' + escapeHtml(t.ticket_number || ('#' + t.id)) + '</span>' +
            '<br><span class="text-muted" style="font-size:0.78rem;">' + escapeHtml(truncate(t.title, 40)) + '</span></td>' +
            '<td>' + statusBadge(t.status) + '</td>' +
            '<td class="d-none d-md-table-cell small">' + escapeHtml(t.category_name || '—') + '</td>' +
            '<td class="d-none d-sm-table-cell small">' + escapeHtml(t.requester_name || '—') + '</td>' +
            '<td class="small text-muted text-nowrap">' + ageLabel(t.created_at) + '</td>' +
        '</tr>';
    }).join('');
}

// === SECCIÓN: PENDIENTES DE EVALUAR (Mi cuenta personal) ===
// M12: carga el conteo de tickets resueltos sin calificar del usuario actual
// usando ?unrated=1&per_page=1 (fetch liviano) y muestra el enlace a la vista filtrada.
function loadUnratedSection() {
    var container = document.getElementById('unratedSection');
    if (!container) return;

    var countEl = document.getElementById('unratedCount');
    var linkEl  = document.getElementById('unratedLink');

    fetch('/api/maint/v2/tickets?unrated=1&per_page=1', { credentials: 'include' })
        .then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
        })
        .then(function (data) {
            var total = (data.total !== undefined) ? data.total : 0;
            if (countEl) countEl.textContent = total;
            if (total > 0) {
                container.classList.remove('d-none');
                if (linkEl) linkEl.href = '/maint/tickets?unrated=1';
            } else {
                // Ocultar si no hay pendientes
                container.classList.add('d-none');
            }
        })
        .catch(function () {
            // Si falla no mostrar la sección
            container.classList.add('d-none');
        });
}

// === TABLA: VENCIDOS (solo full, alcance: Departamento) ===
// U3 fix: badge usa el KPI real (kpis.overdue), no tickets.length.
function renderOverdue(tickets, kpiTotal) {
    var tbody   = document.getElementById('overdueBody');
    var countEl = document.getElementById('overdueCount');

    var realTotal = (kpiTotal !== null && kpiTotal !== undefined) ? kpiTotal : tickets.length;
    if (countEl) countEl.textContent = realTotal;

    if (!tickets.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">' +
            '<i class="fas fa-check-circle text-success me-1"></i>Sin vencidos</td></tr>';
        return;
    }

    tbody.innerHTML = tickets.map(function (t) {
        return '<tr class="mn-dash-row-clickable" onclick="goTicket(' + t.id + ')" style="cursor:pointer;">' +
            '<td><span class="fw-semibold text-primary small">' + escapeHtml(t.ticket_number || ('#' + t.id)) + '</span>' +
            '<br><span class="text-muted" style="font-size:0.78rem;">' + escapeHtml(truncate(t.title, 40)) + '</span></td>' +
            '<td>' + priorityBadge(t.priority) + '</td>' +
            '<td class="d-none d-md-table-cell">' + statusBadge(t.status) + '</td>' +
            '<td class="d-none d-sm-table-cell small">' + escapeHtml(t.requester_name || '—') + '</td>' +
            '<td class="small text-danger text-nowrap fw-semibold">' + ageLabel(t.created_at) + '</td>' +
        '</tr>';
    }).join('');
}

// === CHART: POR ESTADO (doughnut) ===
function renderByStatus(byStatus) {
    destroyChart('status');
    var canvas = document.getElementById('chartByStatus');
    if (!canvas) return;

    var keys    = Object.keys(byStatus).filter(function (k) { return byStatus[k] > 0; });
    if (!keys.length) {
        canvas.parentNode.innerHTML = '<p class="text-muted text-center small py-3">Sin datos</p>';
        return;
    }

    _charts.status = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels:   keys.map(function (k) { return STATUS_LABELS[k] || k; }),
            datasets: [{
                data:            keys.map(function (k) { return byStatus[k]; }),
                backgroundColor: keys.map(function (k) { return STATUS_COLORS[k] || '#607D8B'; }),
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 11, font: { size: 11 } } } },
        },
    });
}

// === CHART: POR CATEGORÍA (bar horizontal) ===
function renderByCategory(categories) {
    destroyChart('category');
    var canvas = document.getElementById('chartByCategory');
    if (!canvas) return;

    if (!categories.length) {
        canvas.parentNode.innerHTML = '<p class="text-muted text-center small py-3">Sin datos</p>';
        return;
    }

    var sorted = categories.slice().sort(function (a, b) { return b.count - a.count; });

    _charts.category = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: sorted.map(function (c) { return escapeHtml(c.name || c.code || '?'); }),
            datasets: [{
                label: 'Tickets',
                data:  sorted.map(function (c) { return c.count; }),
                backgroundColor: '#546E7A',
                borderRadius: 4,
            }],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } },
        },
    });
}

// === TABLA: POR TÉCNICO ===
function renderByTechnician(technicians) {
    var tbody = document.getElementById('byTechBody');
    if (!tbody) return;

    if (!technicians.length) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">Sin técnicos activos</td></tr>';
        return;
    }

    var sorted = technicians.slice().sort(function (a, b) {
        return (b.active_count || 0) - (a.active_count || 0);
    });

    tbody.innerHTML = sorted.map(function (t) {
        return '<tr>' +
            '<td class="fw-semibold small">' + escapeHtml(t.name || 'Técnico ' + t.user_id) + '</td>' +
            '<td class="text-center"><span class="badge bg-primary bg-opacity-75">' + (t.active_count || 0) + '</span></td>' +
            '<td class="text-center"><span class="badge bg-success bg-opacity-75">' + (t.resolved_count || 0) + '</span></td>' +
        '</tr>';
    }).join('');
}

// === SLA ===
function renderSLA(sla) {
    var container = document.getElementById('slaContent');
    if (!container) return;

    var total = (sla.on_time || 0) + (sla.overdue_open || 0) + (sla.overdue_resolved || 0);

    var items = [
        { label: 'A tiempo',            value: sla.on_time         || 0, cls: 'bg-success' },
        { label: 'Vencidos (abiertos)', value: sla.overdue_open    || 0, cls: 'bg-danger'  },
        { label: 'Vencidos (resueltos)',value: sla.overdue_resolved || 0, cls: 'bg-warning' },
    ];

    container.innerHTML = items.map(function (item) {
        var pct = total ? Math.round(item.value / total * 100) : 0;
        return '<div class="mn-dash-sla-row">' +
            '<div class="d-flex justify-content-between mb-1">' +
                '<span class="small">' + escapeHtml(item.label) + '</span>' +
                '<span class="small fw-bold">' + item.value + ' <span class="text-muted">(' + pct + '%)</span></span>' +
            '</div>' +
            '<div class="progress" style="height:8px;">' +
                '<div class="progress-bar ' + item.cls + '" style="width:' + pct + '%;" role="progressbar"></div>' +
            '</div>' +
        '</div>';
    }).join('');
}

// === NAVEGACIÓN ===
function goTicket(id) {
    window.location.href = TICKETS_URL + id;
}

// === UTILIDADES UI ===
function showLoading(show) {
    var loading = document.getElementById('dashLoadingState');
    var content = document.getElementById('dashContent');
    if (show) {
        if (loading) loading.classList.remove('d-none');
        if (content) content.classList.add('d-none');
    } else {
        if (loading) loading.classList.add('d-none');
        if (content) content.classList.remove('d-none');
    }
}

function destroyChart(key) {
    if (_charts[key]) {
        _charts[key].destroy();
        _charts[key] = null;
    }
}

function setKpiCount(id, num) {
    var el = document.getElementById(id);
    if (!el) return;
    var n = (num === null || num === undefined) ? null : Number(num);
    if (n === null || !isFinite(n)) {
        el.textContent = '—';
        return;
    }
    if (window.MaintUtils && MaintUtils.animate && MaintUtils.animate.countUp) {
        el.classList.add('mn-counter');
        MaintUtils.animate.countUp(el, n, { duration: 600 });
    } else {
        el.textContent = fmtNum(n);
    }
}

// === HELPERS DE FORMATO ===
function priorityBadge(priority) {
    if (!priority) return '<span class="badge bg-secondary">—</span>';
    var map = {
        BAJA:    { cls: 'bg-success',  label: 'Baja'    },
        MEDIA:   { cls: 'bg-warning text-dark', label: 'Media'   },
        ALTA:    { cls: 'bg-danger',   label: 'Alta'    },
        URGENTE: { cls: 'mn-badge-urgente', label: 'Urgente' },
    };
    var cfg = map[priority] || { cls: 'bg-secondary', label: escapeHtml(priority) };
    return '<span class="badge ' + cfg.cls + '">' + cfg.label + '</span>';
}

function statusBadge(status) {
    if (!status) return '<span class="badge bg-secondary">—</span>';
    var map = {
        PENDING:          'bg-warning text-dark',
        ASSIGNED:         'bg-info text-white',
        IN_PROGRESS:      'bg-primary',
        RESOLVED_SUCCESS: 'bg-success',
        RESOLVED_FAILED:  'bg-danger',
        CLOSED:           'bg-secondary',
        CANCELED:         'bg-secondary',
    };
    var cls   = map[status] || 'bg-secondary';
    var label = STATUS_LABELS[status] || escapeHtml(status);
    return '<span class="badge ' + cls + '" style="font-size:0.7rem;">' + label + '</span>';
}

function ageLabel(isoDateStr) {
    if (!isoDateStr) return '—';
    var created = new Date(isoDateStr);
    if (isNaN(created.getTime())) return '—';
    var diffMs  = Date.now() - created.getTime();
    var diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 60)  return diffMin + ' min';
    var diffH = Math.floor(diffMin / 60);
    if (diffH < 24)    return diffH + ' h';
    var diffD = Math.floor(diffH / 24);
    return diffD + ' d';
}

function truncate(str, maxLen) {
    if (!str) return '';
    var s = String(str);
    return s.length > maxLen ? s.slice(0, maxLen) + '…' : s;
}

function fmtNum(n) {
    if (n === null || n === undefined) return '—';
    return Number(n).toLocaleString('es-MX', { maximumFractionDigits: 1 });
}

function fmtPct(n) {
    if (n === null || n === undefined) return '—';
    return Number(n).toLocaleString('es-MX', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
}

function escapeHtml(str) {
    if (!str && str !== 0) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
