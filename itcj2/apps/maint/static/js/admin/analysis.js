/**
 * analysis.js — Página de Análisis de Mantenimiento
 * Tabs: Outliers | Clusters (K-means) | Distribución | Tendencias
 */
'use strict';

(function () {

    var API = '/api/maint/v2/analysis';

    // ── Estado ────────────────────────────────────────────────────────────────

    var _dateRange       = null;
    var _activeTab       = 'outliers';
    var _loaded          = {};

    var _outlierMetric   = 'time_invested';
    var _distMetric      = 'time_invested';
    var _distBins        = 10;
    var _trendsGranularity = 'week';

    var _charts  = {};
    var _scatter = null;   // ApexCharts scatter

    // ── Helpers ───────────────────────────────────────────────────────────────

    function _esc(str) {
        if (!str && str !== 0) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _fmt(n, dec) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('es-MX', { maximumFractionDigits: dec !== undefined ? dec : 2 });
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

    function _destroyScatter() {
        if (_scatter) { _scatter.destroy(); _scatter = null; }
    }

    var CLUSTER_COLORS = ['#546E7A', '#10b981', '#f59e0b', '#dc2626', '#7c3aed'];

    var METRIC_LABELS = {
        time_invested:    'Tiempo invertido (min)',
        rating_attention: 'Calificación de atención',
        rating_speed:     'Calificación de velocidad',
    };

    // ── Init ──────────────────────────────────────────────────────────────────

    function init() {
        _dateRange = window.MaintDateRange.init('#analysisDateRange', {
            onChange: function () {
                _loaded = {};
                _destroyScatter();
                _loadActiveTab();
            },
        });

        // Tab switching
        document.querySelectorAll('#analysisTabs .nav-link').forEach(function (link) {
            link.addEventListener('shown.bs.tab', function (e) {
                _activeTab = e.target.getAttribute('href').replace('#tab-', '');
                _loadActiveTab();
            });
        });

        // Outlier metric buttons
        document.querySelectorAll('#outlierMetricBtns [data-metric]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                _outlierMetric = this.dataset.metric;
                document.querySelectorAll('#outlierMetricBtns [data-metric]').forEach(function (b) {
                    var active = b.dataset.metric === _outlierMetric;
                    b.classList.toggle('active', active);
                });
                delete _loaded.outliers;
                loadOutliers();
            });
        });

        // K-means run button
        var kBtn = document.getElementById('btnRunKmeans');
        if (kBtn) kBtn.addEventListener('click', runKmeans);

        // Distribution controls
        var distMetricSel = document.getElementById('distMetricSelect');
        var distBinsSel   = document.getElementById('distBinsSelect');
        var distBtn       = document.getElementById('btnLoadDist');

        if (distMetricSel) distMetricSel.addEventListener('change', function () {
            _distMetric = this.value;
        });
        if (distBinsSel) distBinsSel.addEventListener('change', function () {
            _distBins = parseInt(this.value, 10) || 10;
        });
        if (distBtn) distBtn.addEventListener('click', function () {
            delete _loaded.dist;
            loadDist();
        });

        // Trends granularity buttons
        document.querySelectorAll('#trendsGranularityBtns [data-granularity]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                _trendsGranularity = this.dataset.granularity;
                document.querySelectorAll('#trendsGranularityBtns [data-granularity]').forEach(function (b) {
                    var active = b.dataset.granularity === _trendsGranularity;
                    b.classList.toggle('active', active);
                    b.style.background  = active ? 'var(--maint-primary)' : '';
                    b.style.borderColor = active ? 'var(--maint-primary)' : '';
                    b.style.color       = active ? '#fff' : '';
                });
                delete _loaded.trends;
                loadTrends();
            });
        });

        _loadActiveTab();
    }

    function _loadActiveTab() {
        if (_loaded[_activeTab]) return;
        switch (_activeTab) {
            case 'outliers': loadOutliers(); break;
            case 'clusters': /* manual trigger */ break;
            case 'dist':     loadDist();     break;
            case 'trends':   loadTrends();   break;
        }
    }

    // ── TAB: OUTLIERS ─────────────────────────────────────────────────────────

    function loadOutliers() {
        ['outQ1', 'outQ3', 'outLower', 'outUpper'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.textContent = '…';
        });
        var tbody = document.getElementById('outlierTableBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="3" class="text-center py-4 text-muted">' +
            '<i class="fas fa-spinner fa-spin me-2"></i>Cargando...</td></tr>';

        MaintUtils.api.fetch(API + '/outliers' + _qs({ metric: _outlierMetric }))
            .then(function (data) {
                renderOutliers(data.data || {});
                _loaded.outliers = true;
            })
            .catch(function (err) {
                if (tbody) tbody.innerHTML = '<tr><td colspan="3" class="text-center py-3 text-danger">' +
                    _esc((err && err.message) || 'Error') + '</td></tr>';
            });
    }

    function renderOutliers(d) {
        var setText = function (id, val) {
            var el = document.getElementById(id);
            if (el) el.textContent = val;
        };

        setText('outQ1',    _fmt(d.q1));
        setText('outQ3',    _fmt(d.q3));
        setText('outLower', _fmt(d.lower_fence));
        setText('outUpper', _fmt(d.upper_fence));

        var above = d.outliers_above || [];
        var below = d.outliers_below || [];

        var badge = document.getElementById('outlierCountBadge');
        if (badge) badge.textContent = d.count_above || 0;

        var title = document.getElementById('outlierTableTitle');
        if (title) title.textContent = 'Tickets por encima del fence superior (' + (d.count_above || 0) + ')';

        var tbody = document.getElementById('outlierTableBody');
        if (!above.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-4">Sin outliers detectados por encima del fence</td></tr>';
        } else {
            tbody.innerHTML = above.map(function (t) {
                return '<tr>' +
                    '<td><a href="/maint/tickets/' + t.id + '" target="_blank" class="fw-semibold" style="color:var(--maint-primary);">' +
                        _esc(t.ticket_number) +
                    '</a></td>' +
                    '<td class="text-center fw-bold text-danger">' + _fmt(t.value) + '</td>' +
                    '<td class="text-center d-none d-sm-table-cell"><span class="badge bg-danger">' + _esc(METRIC_LABELS[_outlierMetric] || _outlierMetric) + '</span></td>' +
                '</tr>';
            }).join('');
        }

        // Below fence section
        var belowSection = document.getElementById('outlierBelowSection');
        var belowBody    = document.getElementById('outlierBelowBody');
        if (belowSection && belowBody) {
            belowSection.style.display = below.length ? '' : 'none';
            if (below.length) {
                belowBody.innerHTML = below.map(function (t) {
                    return '<tr>' +
                        '<td><a href="/maint/tickets/' + t.id + '" target="_blank" style="color:var(--maint-primary);">' + _esc(t.ticket_number) + '</a></td>' +
                        '<td class="text-center text-warning fw-bold">' + _fmt(t.value) + '</td>' +
                    '</tr>';
                }).join('');
            }
        }
    }

    // ── TAB: CLUSTERS ─────────────────────────────────────────────────────────

    function runKmeans() {
        var kSel = document.getElementById('kSelect');
        var k    = kSel ? parseInt(kSel.value, 10) : 3;

        var statusEl = document.getElementById('kmeansStatus');
        if (statusEl) statusEl.textContent = 'Calculando…';

        var btn = document.getElementById('btnRunKmeans');
        if (btn) { MaintUtils.loading.show(btn, 'Calculando…'); }

        _destroyScatter();
        var scatterContainer = document.getElementById('scatterContainer');
        if (scatterContainer) scatterContainer.innerHTML =
            '<span class="mn-skeleton d-block" style="height:300px;border-radius:8px;"></span>';

        var cardsRow = document.getElementById('clusterCardsRow');
        if (cardsRow) cardsRow.innerHTML =
            '<div class="col-12"><span class="mn-skeleton d-block" style="height:80px;"></span></div>';

        MaintUtils.api.fetch(API + '/kmeans' + _qs({ k: k }))
            .then(function (data) {
                if (statusEl) statusEl.textContent = '';
                if (btn) MaintUtils.loading.hide(btn);
                renderClusters(data.data || {}, k);
            })
            .catch(function (err) {
                if (statusEl) statusEl.textContent = 'Error: ' + ((err && err.message) || 'desconocido');
                if (btn) MaintUtils.loading.hide(btn);
                if (scatterContainer) scatterContainer.innerHTML =
                    '<div class="alert alert-danger py-2 small">' + _esc((err && err.message) || 'Error') + '</div>';
            });
    }

    function renderClusters(d, k) {
        var clusters = d.clusters || [];

        var cardsRow = document.getElementById('clusterCardsRow');
        if (!cardsRow) return;

        if (!clusters.length) {
            cardsRow.innerHTML = '<div class="col-12 text-center text-muted py-4">' +
                (d.note ? _esc(d.note) : 'Sin datos suficientes para clustering') + '</div>';
            return;
        }

        // Cluster summary cards
        cardsRow.innerHTML = clusters.map(function (c, i) {
            var color   = CLUSTER_COLORS[i % CLUSTER_COLORS.length];
            var samples = (c.sample_tickets || []).map(function (t) {
                return '<a href="/maint/tickets/' + t.id + '" target="_blank" class="badge me-1 mb-1" ' +
                    'style="background:' + color + ';color:#fff;text-decoration:none;">' + _esc(t.ticket_number) + '</a>';
            }).join('');

            return '<div class="col-12 col-md-6 col-lg-4">' +
                '<div class="card shadow-sm p-3 mn-cluster-card" style="border-left-color:' + color + ';">' +
                    '<div class="d-flex align-items-center gap-2 mb-1">' +
                        '<span class="mn-cluster-badge" style="background:' + color + ';"></span>' +
                        '<span class="fw-semibold">Clúster ' + (c.cluster_id + 1) + '</span>' +
                        '<span class="badge bg-secondary ms-auto">' + c.size + ' tickets</span>' +
                    '</div>' +
                    '<div class="small text-muted mb-2">' +
                        'Centroide: [' + (c.centroid || []).map(function (v) { return _fmt(v, 3); }).join(', ') + ']' +
                    '</div>' +
                    '<div class="small">' + (samples || '<span class="text-muted">Sin tickets de muestra</span>') + '</div>' +
                '</div>' +
            '</div>';
        }).join('');

        // Scatter chart (centroid dim 0 = time_invested_norm, dim 1 = rating_attention)
        var scatterContainer = document.getElementById('scatterContainer');
        if (!scatterContainer) return;
        scatterContainer.innerHTML = '';

        var series = clusters.map(function (c, i) {
            var color = CLUSTER_COLORS[i % CLUSTER_COLORS.length];
            // We only have centroids, not individual points — render centroid as a single prominent point
            return {
                name: 'Clúster ' + (c.cluster_id + 1) + ' (' + c.size + ')',
                data: [{ x: c.centroid[0], y: c.centroid[1] }],
                color: color,
            };
        });

        _scatter = new ApexCharts(scatterContainer, {
            series: series,
            chart: {
                type: 'scatter',
                height: 320,
                toolbar: { show: false },
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif",
            },
            markers: {
                size: clusters.map(function (c) {
                    // Scale marker by cluster size (min 10, max 40)
                    var total = clusters.reduce(function (s, cl) { return s + cl.size; }, 0);
                    return total ? Math.max(10, Math.min(40, Math.round(c.size / total * 60))) : 15;
                }),
                strokeWidth: 2,
            },
            xaxis: {
                title: { text: 'Tiempo invertido (norm.)' },
                labels: { formatter: function (v) { return _fmt(v, 3); } },
            },
            yaxis: {
                title: { text: 'Calificación atención' },
                min: 0,
                max: 5,
            },
            tooltip: {
                custom: function (opts) {
                    var s = clusters[opts.seriesIndex];
                    return '<div class="px-3 py-2 small">' +
                        '<strong>Clúster ' + (s.cluster_id + 1) + '</strong><br>' +
                        'Tickets: ' + s.size + '<br>' +
                        'Tiempo norm.: ' + _fmt(s.centroid[0], 4) + '<br>' +
                        'Atención: ' + _fmt(s.centroid[1], 4) + '<br>' +
                        'Velocidad: ' + _fmt(s.centroid[2], 4) +
                    '</div>';
                },
            },
            legend: { show: true, position: 'top' },
        });
        _scatter.render();
    }

    // ── TAB: DISTRIBUCIÓN ─────────────────────────────────────────────────────

    function loadDist() {
        var titleEl = document.getElementById('distChartTitle');
        if (titleEl) titleEl.textContent = 'Histograma — ' + (METRIC_LABELS[_distMetric] || _distMetric);

        _destroyChart('dist');
        var canvas = document.getElementById('chartDist');
        if (canvas) {
            // show loading
            var ctx = canvas.getContext('2d');
            if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        }

        MaintUtils.api.fetch(API + '/distribution' + _qs({ metric: _distMetric, bins: _distBins }))
            .then(function (data) {
                renderDist(data.data || {});
                _loaded.dist = true;
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al cargar distribución', 'error');
            });
    }

    function renderDist(d) {
        var bins   = d.bins || [];
        var canvas = document.getElementById('chartDist');
        if (!canvas) return;

        _destroyChart('dist');

        if (!bins.length) {
            canvas.style.display = 'none';
            return;
        }
        canvas.style.display = '';

        var labels = bins.map(function (b) {
            return _fmt(b.lower, 1) + '–' + _fmt(b.upper, 1);
        });

        _charts.dist = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: METRIC_LABELS[_distMetric] || _distMetric,
                    data: bins.map(function (b) { return b.count; }),
                    backgroundColor: '#546E7A',
                    borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { maxRotation: 45, minRotation: 30 } },
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                },
            },
        });
    }

    // ── TAB: TENDENCIAS ───────────────────────────────────────────────────────

    function loadTrends() {
        _destroyChart('trends');
        _destroyChart('trendsTime');

        MaintUtils.api.fetch(API + '/trends' + _qs({ granularity: _trendsGranularity }))
            .then(function (data) {
                renderTrends(data.data || {});
                _loaded.trends = true;
            })
            .catch(function (err) {
                MaintUtils.toast((err && err.message) || 'Error al cargar tendencias', 'error');
            });
    }

    function renderTrends(d) {
        var labels   = d.labels || [];
        var created  = d.created || [];
        var resolved = d.resolved || [];
        var canceled = d.canceled || [];
        var avgMin   = d.avg_resolution_minutes || [];

        // Multi-line chart
        var canvas = document.getElementById('chartTrends');
        if (canvas) {
            _destroyChart('trends');
            _charts.trends = new Chart(canvas, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Creados',
                            data: created,
                            borderColor: '#546E7A',
                            backgroundColor: 'rgba(84,110,122,0.10)',
                            tension: 0.3,
                            fill: false,
                            pointRadius: labels.length > 90 ? 0 : 3,
                        },
                        {
                            label: 'Resueltos',
                            data: resolved,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16,185,129,0.10)',
                            tension: 0.3,
                            fill: false,
                            pointRadius: labels.length > 90 ? 0 : 3,
                        },
                        {
                            label: 'Cancelados',
                            data: canceled,
                            borderColor: '#9ca3af',
                            borderDash: [4, 3],
                            tension: 0.3,
                            fill: false,
                            pointRadius: labels.length > 90 ? 0 : 3,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: { ticks: { maxTicksLimit: 14 } },
                        y: { beginAtZero: true },
                    },
                },
            });
        }

        // Avg resolution line
        var timeCanvas = document.getElementById('chartTrendsTime');
        if (timeCanvas) {
            _destroyChart('trendsTime');
            _charts.trendsTime = new Chart(timeCanvas, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Prom. minutos resolución',
                        data: avgMin,
                        borderColor: '#f59e0b',
                        backgroundColor: 'rgba(245,158,11,0.10)',
                        tension: 0.3,
                        fill: true,
                        spanGaps: true,
                        pointRadius: labels.length > 90 ? 0 : 3,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: { ticks: { maxTicksLimit: 14 } },
                        y: { beginAtZero: true },
                    },
                },
            });
        }
    }

    // ── Arranque ──────────────────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
