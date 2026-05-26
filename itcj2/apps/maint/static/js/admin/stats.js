/**
 * stats.js — Página de Estadísticas de Mantenimiento
 * Tabs: Global | Técnicos | Categorías | Tiempos | Calificaciones | Mapa de Calor
 */
'use strict';

(function () {

    var API = '/api/maint/v2/stats';

    // ── Estado ────────────────────────────────────────────────────────────────

    var _dateRange  = null;
    var _activeTab  = 'global';
    var _loaded     = {};
    var _heatmapGroupBy = 'location';
    var _heatmapChart   = null;

    var _charts = {};

    // ── Helpers ───────────────────────────────────────────────────────────────

    function _esc(str) {
        if (!str && str !== 0) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _fmt(n) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('es-MX', { maximumFractionDigits: 1 });
    }

    function _pct(n) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('es-MX', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
    }

    function _stars(rating) {
        if (rating === null || rating === undefined) return '—';
        var r = Math.round(Number(rating));
        var full  = Math.min(r, 5);
        var empty = 5 - full;
        return '<span class="mn-stars">' +
            '★'.repeat(full) + '<span style="opacity:.3;">' + '★'.repeat(empty) + '</span>' +
        '</span> <small class="text-muted">' + _fmt(rating) + '</small>';
    }

    function _range() {
        if (_dateRange) return _dateRange.getRange();
        return { from: '', to: '' };
    }

    function _qs(extra) {
        var r = _range();
        var q = [];
        if (r.from) q.push('from=' + r.from);
        if (r.to)   q.push('to='   + r.to);
        if (extra) Object.keys(extra).forEach(function (k) { q.push(k + '=' + extra[k]); });
        return q.length ? '?' + q.join('&') : '';
    }

    function _destroyChart(key) {
        if (_charts[key]) { _charts[key].destroy(); _charts[key] = null; }
    }

    var MAINT_COLORS = [
        '#546E7A', '#78909C', '#37474F', '#90A4AE', '#263238',
        '#B0BEC5', '#455A64', '#607D8B', '#CFD8DC', '#ECEFF1',
    ];

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
        BAJA:    '#10b981',
        MEDIA:   '#f59e0b',
        ALTA:    '#ef4444',
        URGENTE: '#7c3aed',
    };

    // ── Init ──────────────────────────────────────────────────────────────────

    function init() {
        _dateRange = window.MaintDateRange.init('#statsDateRange', {
            onChange: function () {
                _loaded = {};
                _destroyHeatmap();
                _loadActiveTab();
            },
        });

        // Tab switching
        document.querySelectorAll('#statsTabs .nav-link').forEach(function (link) {
            link.addEventListener('shown.bs.tab', function (e) {
                _activeTab = e.target.getAttribute('href').replace('#tab-', '');
                _loadActiveTab();
                // Animar entrada del tab-pane activado
                var paneId = e.target.getAttribute('href');
                var pane = document.querySelector(paneId);
                if (pane) {
                    pane.classList.remove('mn-tab-enter');
                    void pane.offsetWidth;
                    pane.classList.add('mn-tab-enter');
                }
            });
        });

        // Heatmap group-by toggle
        document.querySelectorAll('#heatmapGroupBtns [data-group]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var g = this.dataset.group;
                if (g === _heatmapGroupBy) return;
                _heatmapGroupBy = g;
                document.querySelectorAll('#heatmapGroupBtns [data-group]').forEach(function (b) {
                    var active = b.dataset.group === g;
                    b.classList.toggle('active', active);
                    b.style.background  = active ? 'var(--maint-primary)' : '';
                    b.style.borderColor = active ? 'var(--maint-primary)' : '';
                    b.style.color       = active ? '#fff' : '';
                });
                var titleEl = document.getElementById('heatmapTitle');
                if (titleEl) titleEl.textContent = g === 'location'
                    ? 'Mapa de calor — Ubicación × Categoría'
                    : 'Mapa de calor — Edificio × Mes';
                delete _loaded.heatmap;
                loadHeatmap();
            });
        });

        _loadActiveTab();
    }

    function _loadActiveTab() {
        if (_loaded[_activeTab]) return;
        switch (_activeTab) {
            case 'global':    loadGlobal();    break;
            case 'tech':      loadTech();      break;
            case 'cat':       loadCat();       break;
            case 'times':     loadTimes();     break;
            case 'ratings':   loadRatings();   break;
            case 'heatmap':   loadHeatmap();   break;
        }
    }

    // ── TAB: GLOBAL ───────────────────────────────────────────────────────────

    function loadGlobal() {
        ['kpiTotal', 'kpiOpen', 'kpiResolved', 'kpiCanceled'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.textContent = '…';
        });

        MaintUtils.api.fetch(API + '/global' + _qs())
            .then(function (data) {
                renderGlobal(data.data || {});
                _loaded.global = true;
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al cargar estadísticas globales', 'error');
            });
    }

    function renderGlobal(d) {
        var bs = d.by_status || {};
        var bp = d.by_priority || {};
        var bc = d.by_category || [];

        var open     = (bs.PENDING || 0) + (bs.ASSIGNED || 0) + (bs.IN_PROGRESS || 0);
        var resolved = (bs.RESOLVED_SUCCESS || 0) + (bs.RESOLVED_FAILED || 0) + (bs.CLOSED || 0);
        var canceled = bs.CANCELED || 0;

        _setKpiCount('kpiTotal',    Number(d.total) || 0);
        _setKpiCount('kpiOpen',     open);
        _setKpiCount('kpiResolved', resolved);
        _setKpiCount('kpiCanceled', canceled);

        // Status pie
        var statusLabels = Object.keys(bs).filter(function (k) { return bs[k] > 0; });
        _destroyChart('status');
        _charts.status = new Chart(document.getElementById('chartStatus'), {
            type: 'doughnut',
            data: {
                labels: statusLabels.map(function (k) { return STATUS_LABELS[k] || k; }),
                datasets: [{
                    data: statusLabels.map(function (k) { return bs[k]; }),
                    backgroundColor: statusLabels.map(function (k) { return STATUS_COLORS[k] || '#607D8B'; }),
                    borderWidth: 2,
                    borderColor: '#fff',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } },
            },
        });

        // Priority bar
        var prioKeys = ['BAJA', 'MEDIA', 'ALTA', 'URGENTE'];
        _destroyChart('priority');
        _charts.priority = new Chart(document.getElementById('chartPriority'), {
            type: 'bar',
            data: {
                labels: prioKeys,
                datasets: [{
                    label: 'Tickets',
                    data: prioKeys.map(function (k) { return bp[k] || 0; }),
                    backgroundColor: prioKeys.map(function (k) { return PRIORITY_COLORS[k]; }),
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } },
            },
        });

        // Category bar
        var catSorted = bc.slice().sort(function (a, b) { return b.count - a.count; });
        _destroyChart('catGlobal');
        _charts.catGlobal = new Chart(document.getElementById('chartCategoryGlobal'), {
            type: 'bar',
            data: {
                labels: catSorted.map(function (c) { return c.category_name; }),
                datasets: [{
                    label: 'Tickets',
                    data: catSorted.map(function (c) { return c.count; }),
                    backgroundColor: '#546E7A',
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    function _setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function _setKpiCount(id, num) {
        var el = document.getElementById(id);
        if (!el) return;
        if (typeof num !== 'number' || !isFinite(num)) {
            el.textContent = (num === null || num === undefined) ? '—' : String(num);
            return;
        }
        if (window.MaintUtils && MaintUtils.animate) {
            el.classList.add('mn-counter');
            MaintUtils.animate.countUp(el, num, { duration: 700 });
        } else {
            el.textContent = _fmt(num);
        }
    }

    // ── TAB: TÉCNICOS ─────────────────────────────────────────────────────────

    function loadTech() {
        var tbody = document.getElementById('techStatsBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Cargando...</td></tr>';

        MaintUtils.api.fetch(API + '/by-technician' + _qs())
            .then(function (data) {
                renderTechStats(data.data || []);
                _loaded.tech = true;
            })
            .catch(function (err) {
                if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="text-center py-3 text-danger">' +
                    _esc((err && err.message) || 'Error') + '</td></tr>';
            });
    }

    function renderTechStats(rows) {
        // Top 10 horizontal bar chart
        var top = rows.slice(0, 10).sort(function (a, b) { return (b.resolved_count || 0) - (a.resolved_count || 0); });
        _destroyChart('techTop');
        var topCanvas = document.getElementById('chartTechTop');
        if (topCanvas && top.length) {
            _charts.techTop = new Chart(topCanvas, {
                type: 'bar',
                data: {
                    labels: top.map(function (r) { return r.name; }),
                    datasets: [{
                        label: 'Resueltos',
                        data: top.map(function (r) { return r.resolved_count || 0; }),
                        backgroundColor: '#546E7A',
                        borderRadius: 4,
                    }],
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { x: { beginAtZero: true } },
                },
            });
        }

        // Table
        var tbody = document.getElementById('techStatsBody');
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Sin datos en el período</td></tr>';
            return;
        }

        var sorted = rows.slice().sort(function (a, b) { return (b.resolved_count || 0) - (a.resolved_count || 0); });

        tbody.innerHTML = sorted.map(function (r, i) {
            var slaCls = r.pct_sla_cumplido === null ? '' :
                         r.pct_sla_cumplido >= 90 ? 'text-success fw-semibold' :
                         r.pct_sla_cumplido >= 70 ? 'text-warning fw-semibold' : 'text-danger fw-semibold';

            return '<tr>' +
                '<td class="text-muted">' + (i + 1) + '</td>' +
                '<td class="fw-semibold">' + _esc(r.name) + '</td>' +
                '<td class="text-center">' + _fmt(r.assigned_count) + '</td>' +
                '<td class="text-center">' + _fmt(r.resolved_count) + '</td>' +
                '<td class="text-center d-none d-md-table-cell">' + _fmt(r.avg_time_invested_minutes) + '</td>' +
                '<td class="text-center d-none d-md-table-cell">' + _fmt(r.avg_rating_attention) + '</td>' +
                '<td class="text-center d-none d-md-table-cell">' + _fmt(r.avg_rating_speed) + '</td>' +
                '<td class="text-center d-none d-sm-table-cell ' + slaCls + '">' + _pct(r.pct_sla_cumplido) + '</td>' +
            '</tr>';
        }).join('');
    }

    // ── TAB: CATEGORÍAS ───────────────────────────────────────────────────────

    function loadCat() {
        var tbody = document.getElementById('catStatsBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Cargando...</td></tr>';

        MaintUtils.api.fetch(API + '/by-category' + _qs())
            .then(function (data) {
                renderCatStats(data.data || []);
                _loaded.cat = true;
            })
            .catch(function (err) {
                if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-danger">' +
                    _esc((err && err.message) || 'Error') + '</td></tr>';
            });
    }

    function renderCatStats(rows) {
        var catCanvas = document.getElementById('chartCatStats');
        if (catCanvas && rows.length) {
            var sorted = rows.slice().sort(function (a, b) { return b.total - a.total; });
            _destroyChart('catStats');
            _charts.catStats = new Chart(catCanvas, {
                type: 'bar',
                data: {
                    labels: sorted.map(function (r) { return r.category_name; }),
                    datasets: [
                        { label: 'Abiertos',  data: sorted.map(function (r) { return r.open; }),     backgroundColor: '#0891b2', borderRadius: 3 },
                        { label: 'Resueltos', data: sorted.map(function (r) { return r.resolved; }), backgroundColor: '#10b981', borderRadius: 3 },
                        { label: 'Cancelados',data: sorted.map(function (r) { return r.canceled; }), backgroundColor: '#9ca3af', borderRadius: 3 },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'top' } },
                    scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
                },
            });
        }

        var tbody = document.getElementById('catStatsBody');
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">Sin datos en el período</td></tr>';
            return;
        }

        var sortedRows = rows.slice().sort(function (a, b) { return b.total - a.total; });
        tbody.innerHTML = sortedRows.map(function (r) {
            var cancelCls = r.cancellation_rate > 30 ? 'text-danger' : r.cancellation_rate > 15 ? 'text-warning' : '';
            return '<tr>' +
                '<td class="fw-semibold">' + _esc(r.category_name) + '</td>' +
                '<td class="text-center">' + _fmt(r.total) + '</td>' +
                '<td class="text-center d-none d-sm-table-cell">' + _fmt(r.open) + '</td>' +
                '<td class="text-center d-none d-sm-table-cell">' + _fmt(r.resolved) + '</td>' +
                '<td class="text-center">' + _fmt(r.canceled) + '</td>' +
                '<td class="text-center ' + cancelCls + '">' + _pct(r.cancellation_rate) + '</td>' +
            '</tr>';
        }).join('');
    }

    // ── TAB: TIEMPOS ──────────────────────────────────────────────────────────

    function loadTimes() {
        var container = document.getElementById('timeBreakdownContent');
        if (container) container.innerHTML =
            '<div class="d-flex align-items-center justify-content-center py-5">' +
            '<span class="mn-skeleton d-block" style="width:90%;height:120px;"></span></div>';

        MaintUtils.api.fetch(API + '/time-breakdown' + _qs())
            .then(function (data) {
                renderTimes(data.data || {});
                _loaded.times = true;
            })
            .catch(function (err) {
                var container2 = document.getElementById('timeBreakdownContent');
                if (container2) container2.innerHTML =
                    '<div class="alert alert-danger py-2 small">' + _esc((err && err.message) || 'Error') + '</div>';
            });
    }

    function renderTimes(d) {
        var transitions = [
            {
                key: 'pending_to_assigned_minutes',
                label: 'PENDIENTE → ASIGNADO',
                color: '#f59e0b',
                icon: 'fa-dot-circle',
            },
            {
                key: 'assigned_to_in_progress_minutes',
                label: 'ASIGNADO → EN PROGRESO',
                color: '#0891b2',
                icon: 'fa-dot-circle',
            },
            {
                key: 'in_progress_to_resolved_minutes',
                label: 'EN PROGRESO → RESUELTO',
                color: '#10b981',
                icon: 'fa-dot-circle',
            },
        ];

        var values = transitions.map(function (t) { return d[t.key] || 0; });
        var maxVal = Math.max.apply(null, values) || 1;

        var container = document.getElementById('timeBreakdownContent');
        if (!container) return;

        container.innerHTML = transitions.map(function (t, i) {
            var val  = d[t.key];
            var pct  = val !== null && val !== undefined ? Math.round(val / maxVal * 100) : 0;
            var disp = val !== null && val !== undefined
                ? (val >= 60 ? _fmt(val / 60) + ' h' : _fmt(val) + ' min')
                : 'Sin datos';

            return '<div class="mb-3">' +
                '<div class="d-flex justify-content-between align-items-center mb-1">' +
                    '<span class="small fw-semibold" style="color:' + t.color + ';">' +
                        '<i class="fas ' + t.icon + ' me-1"></i>' + t.label +
                    '</span>' +
                    '<span class="small fw-bold">' + disp + '</span>' +
                '</div>' +
                '<div class="mn-time-bar">' +
                    '<div class="mn-time-bar-fill" style="width:' + pct + '%;background:' + t.color + ';">' +
                        (pct > 20 ? '<span class="mn-time-bar-label">' + disp + '</span>' : '') +
                    '</div>' +
                '</div>' +
            '</div>';
        }).join('');
    }

    // ── TAB: CALIFICACIONES ───────────────────────────────────────────────────

    function loadRatings() {
        ['ratingTotal', 'ratingRated', 'ratingUnrated', 'ratingEfficiency'].forEach(function (id) {
            _setText(id, '…');
        });

        MaintUtils.api.fetch(API + '/ratings-detail' + _qs())
            .then(function (data) {
                renderRatings(data.data || {});
                _loaded.ratings = true;
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al cargar calificaciones', 'error');
            });
    }

    function renderRatings(d) {
        _setKpiCount('ratingTotal',   Number(d.total_resolved) || 0);
        _setKpiCount('ratingRated',   Number(d.total_rated)    || 0);
        _setKpiCount('ratingUnrated', Number(d.total_unrated)  || 0);
        _setText('ratingEfficiency', d.pct_rating_efficiency_true !== null && d.pct_rating_efficiency_true !== undefined
            ? _pct(d.pct_rating_efficiency_true) : '—');

        var ratingLabels = ['1★', '2★', '3★', '4★', '5★'];
        var attDist = d.rating_attention_distribution || {};
        var spdDist = d.rating_speed_distribution     || {};

        _destroyChart('ratingAtt');
        var attCanvas = document.getElementById('chartRatingAtt');
        if (attCanvas) {
            _charts.ratingAtt = new Chart(attCanvas, {
                type: 'bar',
                data: {
                    labels: ratingLabels,
                    datasets: [{
                        label: 'Atención',
                        data: [1,2,3,4,5].map(function (k) { return attDist[k] || 0; }),
                        backgroundColor: '#546E7A',
                        borderRadius: 4,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
                },
            });
        }

        _destroyChart('ratingSpd');
        var spdCanvas = document.getElementById('chartRatingSpd');
        if (spdCanvas) {
            _charts.ratingSpd = new Chart(spdCanvas, {
                type: 'bar',
                data: {
                    labels: ratingLabels,
                    datasets: [{
                        label: 'Velocidad',
                        data: [1,2,3,4,5].map(function (k) { return spdDist[k] || 0; }),
                        backgroundColor: '#78909C',
                        borderRadius: 4,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
                },
            });
        }

        // Efficiency donut
        _destroyChart('efficiency');
        var effCanvas = document.getElementById('chartEfficiency');
        if (effCanvas && d.with_efficiency_count) {
            var effYes = d.efficient_count || 0;
            var effNo  = (d.with_efficiency_count || 0) - effYes;
            _charts.efficiency = new Chart(effCanvas, {
                type: 'doughnut',
                data: {
                    labels: ['Eficiente', 'No eficiente'],
                    datasets: [{
                        data: [effYes, effNo],
                        backgroundColor: ['#10b981', '#ECEFF1'],
                        borderWidth: 2,
                        borderColor: '#fff',
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom' },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    var total = effYes + effNo;
                                    return ctx.label + ': ' + ctx.raw + ' (' + (total ? Math.round(ctx.raw / total * 100) : 0) + '%)';
                                },
                            },
                        },
                    },
                },
            });
        }
    }

    // ── TAB: HEATMAP ──────────────────────────────────────────────────────────

    function _destroyHeatmap() {
        if (_heatmapChart) {
            _heatmapChart.destroy();
            _heatmapChart = null;
        }
    }

    function loadHeatmap() {
        var container = document.getElementById('heatmapContainer');
        if (container) container.innerHTML =
            '<div class="d-flex align-items-center justify-content-center" style="min-height:300px;">' +
            '<span class="mn-skeleton d-block" style="width:100%;height:260px;"></span></div>';

        _destroyHeatmap();

        MaintUtils.api.fetch(API + '/heatmap' + _qs({ group_by: _heatmapGroupBy }))
            .then(function (data) {
                renderHeatmap(data);
                _loaded.heatmap = true;
            })
            .catch(function (err) {
                if (container) container.innerHTML =
                    '<div class="alert alert-danger py-2 small m-3">' + _esc((err && err.message) || 'Error') + '</div>';
            });
    }

    function renderHeatmap(data) {
        var container = document.getElementById('heatmapContainer');
        if (!container) return;

        var xLabels = (data.axes && data.axes.x) || [];
        var yLabels = (data.axes && data.axes.y) || [];
        var matrix  = data.matrix || [];

        if (!xLabels.length || !yLabels.length) {
            container.innerHTML = '<div class="text-center text-muted py-5"><i class="fas fa-th fa-2x mb-2 d-block opacity-25"></i>Sin datos para el período</div>';
            return;
        }

        container.innerHTML = '';

        // Build ApexCharts series: each series = one row (y label), data = [{x: col, y: count}]
        var series = yLabels.map(function (yLabel, yi) {
            return {
                name: yLabel,
                data: xLabels.map(function (xLabel, xi) {
                    return { x: xLabel, y: (matrix[yi] && matrix[yi][xi]) || 0 };
                }),
            };
        });

        var options = {
            series: series,
            chart: {
                type: 'heatmap',
                height: Math.max(300, yLabels.length * 28 + 80),
                toolbar: { show: false },
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif",
            },
            dataLabels: { enabled: false },
            colors: ['#546E7A'],
            plotOptions: {
                heatmap: {
                    shadeIntensity: 0.6,
                    colorScale: {
                        ranges: [
                            { from: 0, to: 0, name: '0', color: '#ECEFF1' },
                            { from: 1, to: 999999, name: '>0', color: '#546E7A' },
                        ],
                    },
                },
            },
            tooltip: {
                y: {
                    formatter: function (val, opts) {
                        return val + ' tickets';
                    },
                },
            },
            xaxis: { type: 'category' },
            legend: { show: false },
        };

        _heatmapChart = new ApexCharts(container, options);
        _heatmapChart.render();
    }

    // ── Arranque ──────────────────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
