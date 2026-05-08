/**
 * reports.js — Página de Reportes de Mantenimiento
 * Tabs: Tickets (línea) | Técnicos (tabla + barra) | Categorías (doughnut + tabla) | SLA (gauge + cards)
 */
'use strict';

(function () {

    var API = '/api/maint/v2/reports';

    // ── Estado ────────────────────────────────────────────────────────────────

    var _dateRange = null;
    var _activeTab = 'tickets';
    var _loaded    = {};   // { 'tickets': true, ... }

    var _charts = {
        tickets: null,
        tech:    null,
        cat:     null,
    };

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

    function _range() {
        if (_dateRange) return _dateRange.getRange();
        return { from: '', to: '' };
    }

    function _qs(extra) {
        var r = _range();
        var q = [];
        if (r.from) q.push('from=' + r.from);
        if (r.to)   q.push('to='   + r.to);
        if (extra)  Object.keys(extra).forEach(function (k) { q.push(k + '=' + extra[k]); });
        return q.length ? '?' + q.join('&') : '';
    }

    function _skeleton(id, height) {
        var el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = '<span class="mn-skeleton d-block" style="height:' + (height || 180) + 'px;border-radius:8px;"></span>';
    }

    function _errorBox(id, msg) {
        var el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = '<div class="alert alert-danger py-2 small"><i class="fas fa-exclamation-triangle me-1"></i>' + _esc(msg) + '</div>';
    }

    function _showCanvas(canvasId, wrapId) {
        var canvas = document.getElementById(canvasId);
        var wrap   = document.getElementById(wrapId);
        if (canvas) canvas.style.display = '';
        if (wrap) { wrap.innerHTML = ''; wrap.style.display = 'none'; }
    }

    function _destroyChart(key) {
        if (_charts[key]) {
            _charts[key].destroy();
            _charts[key] = null;
        }
    }

    var MAINT_COLORS = [
        '#546E7A', '#78909C', '#37474F', '#90A4AE', '#263238',
        '#B0BEC5', '#455A64', '#607D8B', '#CFD8DC', '#ECEFF1',
    ];

    // ── Init ──────────────────────────────────────────────────────────────────

    function init() {
        _dateRange = window.MaintDateRange.init('#reportDateRange', {
            onChange: function () {
                _loaded = {};
                _loadActiveTab();
            },
        });

        // Tab switching
        document.querySelectorAll('#reportTabs .nav-link').forEach(function (link) {
            link.addEventListener('shown.bs.tab', function (e) {
                _activeTab = e.target.getAttribute('href').replace('#tab-', '');
                _loadActiveTab();
            });
        });

        _loadActiveTab();
    }

    function _loadActiveTab() {
        if (_loaded[_activeTab]) return;
        switch (_activeTab) {
            case 'tickets':     loadTickets();     break;
            case 'technicians': loadTechnicians(); break;
            case 'categories':  loadCategories();  break;
            case 'sla':         loadSLA();         break;
        }
    }

    // ── TAB: TICKETS ─────────────────────────────────────────────────────────

    function loadTickets() {
        var wrap = document.getElementById('ticketsChartWrap');
        if (wrap) {
            wrap.style.display = '';
            wrap.innerHTML = '<span class="mn-skeleton d-block" style="height:260px;border-radius:8px;"></span>';
        }
        var canvas = document.getElementById('chartTickets');
        if (canvas) canvas.style.display = 'none';

        MaintUtils.api.fetch(API + '/tickets' + _qs())
            .then(function (data) {
                renderTicketsChart(data.data || []);
                _loaded.tickets = true;
            })
            .catch(function (err) {
                if (wrap) _errorBox('ticketsChartWrap', (err && err.message) || 'Error al cargar tickets');
            });
    }

    function renderTicketsChart(rows) {
        var wrap   = document.getElementById('ticketsChartWrap');
        var canvas = document.getElementById('chartTickets');
        if (!canvas) return;

        _destroyChart('tickets');

        if (!rows.length) {
            if (wrap) {
                wrap.innerHTML = '<div class="text-center text-muted py-5"><i class="fas fa-chart-line fa-2x mb-2 d-block opacity-25"></i>Sin datos en el período seleccionado</div>';
            }
            return;
        }

        if (wrap) { wrap.style.display = 'none'; wrap.innerHTML = ''; }
        canvas.style.display = '';
        // Restore canvas into chart-wrap dimensions
        canvas.parentElement.style.height = '300px';

        var labels   = rows.map(function (r) { return r.date; });
        var created  = rows.map(function (r) { return r.created; });
        var resolved = rows.map(function (r) { return r.resolved; });

        _charts.tickets = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Creados',
                        data: created,
                        borderColor: '#546E7A',
                        backgroundColor: 'rgba(84,110,122,0.12)',
                        tension: 0.3,
                        fill: true,
                        pointRadius: rows.length > 60 ? 0 : 3,
                    },
                    {
                        label: 'Resueltos',
                        data: resolved,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16,185,129,0.10)',
                        tension: 0.3,
                        fill: true,
                        pointRadius: rows.length > 60 ? 0 : 3,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x: { ticks: { maxTicksLimit: 12 } },
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                },
            },
        });
    }

    // ── TAB: TÉCNICOS ─────────────────────────────────────────────────────────

    function loadTechnicians() {
        document.getElementById('techTableBody').innerHTML =
            '<tr><td colspan="9" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Cargando...</td></tr>';

        var techWrap = document.getElementById('techChartWrap');
        if (techWrap) techWrap.innerHTML = '<span class="mn-skeleton d-block" style="height:180px;border-radius:8px;"></span>';
        var techCanvas = document.getElementById('chartTech');
        if (techCanvas) techCanvas.style.display = 'none';

        MaintUtils.api.fetch(API + '/technicians' + _qs())
            .then(function (data) {
                renderTechTable(data.data || []);
                renderTechChart(data.data || []);
                _loaded.technicians = true;
            })
            .catch(function (err) {
                document.getElementById('techTableBody').innerHTML =
                    '<tr><td colspan="9" class="text-center py-3 text-danger">' +
                    '<i class="fas fa-exclamation-triangle me-1"></i>' + _esc((err && err.message) || 'Error') + '</td></tr>';
            });
    }

    function renderTechTable(rows) {
        var tbody = document.getElementById('techTableBody');
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Sin datos en el período</td></tr>';
            return;
        }

        var maxResolved = Math.max.apply(null, rows.map(function (r) { return r.resolved_count || 0; }));

        tbody.innerHTML = rows.map(function (r, i) {
            var barPct = maxResolved ? Math.round((r.resolved_count || 0) / maxResolved * 100) : 0;
            var slaCls = r.pct_sla_cumplido === null ? '' :
                         r.pct_sla_cumplido >= 90 ? 'sla-badge good' :
                         r.pct_sla_cumplido >= 70 ? 'sla-badge warn' : 'sla-badge bad';
            var slaVal = r.pct_sla_cumplido === null ? '<span class="text-muted">N/A</span>' :
                         '<span class="' + slaCls + '">' + _pct(r.pct_sla_cumplido) + '</span>';

            return '<tr>' +
                '<td class="text-muted">' + (i + 1) + '</td>' +
                '<td class="fw-semibold">' + _esc(r.name) + '</td>' +
                '<td class="text-center">' +
                    '<div class="mn-bar-cell">' +
                        '<div class="mn-bar-track"><div class="mn-bar-fill" style="width:' + barPct + '%;"></div></div>' +
                        '<small class="text-muted">' + _fmt(r.resolved_count) + '</small>' +
                    '</div>' +
                '</td>' +
                '<td class="text-center d-none d-md-table-cell">' + _fmt(r.avg_time_invested_minutes) + '</td>' +
                '<td class="text-center d-none d-md-table-cell">' + _fmt(r.avg_rating_attention) + '</td>' +
                '<td class="text-center d-none d-md-table-cell">' + _fmt(r.avg_rating_speed) + '</td>' +
                '<td class="text-center d-none d-sm-table-cell">' + _pct(r.pct_efficient) + '</td>' +
                '<td class="d-none d-sm-table-cell">' + slaVal + '</td>' +
                '<td class="text-center d-none d-lg-table-cell">' + _fmt(r.resolved_count) + '</td>' +
            '</tr>';
        }).join('');
    }

    function renderTechChart(rows) {
        var wrap   = document.getElementById('techChartWrap');
        var canvas = document.getElementById('chartTech');
        if (!canvas) return;
        _destroyChart('tech');

        if (!rows.length) {
            if (wrap) wrap.innerHTML = '<div class="text-center text-muted py-4">Sin datos</div>';
            return;
        }

        var top = rows.slice(0, 10);
        if (wrap) { wrap.style.display = 'none'; wrap.innerHTML = ''; }
        canvas.style.display = '';

        _charts.tech = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: top.map(function (r) { return r.name; }),
                datasets: [{
                    label: 'Resueltos',
                    data: top.map(function (r) { return r.resolved_count || 0; }),
                    backgroundColor: MAINT_COLORS[0],
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

    // ── TAB: CATEGORÍAS ───────────────────────────────────────────────────────

    function loadCategories() {
        document.getElementById('catTableBody').innerHTML =
            '<tr><td colspan="5" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Cargando...</td></tr>';

        var catWrap = document.getElementById('catChartWrap');
        if (catWrap) catWrap.innerHTML = '<span class="mn-skeleton d-block" style="height:260px;border-radius:8px;"></span>';
        var catCanvas = document.getElementById('chartCat');
        if (catCanvas) catCanvas.style.display = 'none';

        MaintUtils.api.fetch(API + '/categories' + _qs())
            .then(function (data) {
                renderCatTable(data.data || []);
                renderCatChart(data.data || []);
                _loaded.categories = true;
            })
            .catch(function (err) {
                document.getElementById('catTableBody').innerHTML =
                    '<tr><td colspan="5" class="text-center py-3 text-danger">' +
                    _esc((err && err.message) || 'Error') + '</td></tr>';
            });
    }

    function renderCatTable(rows) {
        var tbody = document.getElementById('catTableBody');
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Sin datos en el período</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map(function (r) {
            return '<tr>' +
                '<td class="fw-semibold">' + _esc(r.category_name) + '</td>' +
                '<td class="text-center">' + _fmt(r.total) + '</td>' +
                '<td class="text-center d-none d-sm-table-cell">' + _fmt(r.open) + '</td>' +
                '<td class="text-center d-none d-sm-table-cell">' + _fmt(r.resolved) + '</td>' +
                '<td class="text-center">' + _fmt(r.avg_resolution_minutes) + '</td>' +
            '</tr>';
        }).join('');
    }

    function renderCatChart(rows) {
        var wrap   = document.getElementById('catChartWrap');
        var canvas = document.getElementById('chartCat');
        if (!canvas) return;
        _destroyChart('cat');

        if (!rows.length) {
            if (wrap) wrap.innerHTML = '<div class="text-center text-muted py-4">Sin datos</div>';
            return;
        }

        if (wrap) { wrap.style.display = 'none'; wrap.innerHTML = ''; }
        canvas.style.display = '';

        _charts.cat = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: rows.map(function (r) { return r.category_name; }),
                datasets: [{
                    data: rows.map(function (r) { return r.total; }),
                    backgroundColor: rows.map(function (_, i) { return MAINT_COLORS[i % MAINT_COLORS.length]; }),
                    borderWidth: 2,
                    borderColor: '#fff',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right' },
                },
            },
        });
    }

    // ── TAB: SLA ──────────────────────────────────────────────────────────────

    function loadSLA() {
        var gaugeCard  = document.getElementById('slaGaugeCard');
        var detailWrap = document.getElementById('slaDetailWrap');
        if (gaugeCard)  gaugeCard.innerHTML  = '<span class="mn-skeleton d-block" style="height:100px;border-radius:8px;"></span>';
        if (detailWrap) detailWrap.innerHTML = '<div class="col-12"><span class="mn-skeleton d-block" style="height:120px;border-radius:8px;"></span></div>';

        MaintUtils.api.fetch(API + '/sla' + _qs())
            .then(function (data) {
                renderSLA(data.data || {});
                _loaded.sla = true;
            })
            .catch(function (err) {
                if (gaugeCard) gaugeCard.innerHTML =
                    '<div class="alert alert-danger py-2 small">' + _esc((err && err.message) || 'Error') + '</div>';
            });
    }

    function renderSLA(d) {
        var gaugeCard  = document.getElementById('slaGaugeCard');
        var detailWrap = document.getElementById('slaDetailWrap');
        if (!gaugeCard) return;

        var pct = d.pct_on_time;
        var cls = pct === null ? '' : pct >= 90 ? 'good' : pct >= 70 ? 'warn' : 'bad';

        gaugeCard.innerHTML =
            '<div class="sla-gauge-value ' + cls + '">' +
                (pct !== null ? _pct(pct) : 'N/D') +
            '</div>' +
            '<div class="sla-gauge-label mt-2">Cumplimiento SLA</div>' +
            '<div class="text-muted small mt-1">' +
                _fmt(d.on_time) + ' de ' + _fmt(d.with_due_at) + ' tickets a tiempo' +
            '</div>';

        if (!detailWrap) return;
        detailWrap.innerHTML =
            '<div class="col-6 col-sm-3">' +
                '<div class="card p-3 text-center shadow-sm">' +
                    '<div class="fs-5 fw-bold text-secondary">' + _fmt(d.total_resolved) + '</div>' +
                    '<div class="small text-muted">Total resueltos</div>' +
                '</div>' +
            '</div>' +
            '<div class="col-6 col-sm-3">' +
                '<div class="card p-3 text-center shadow-sm">' +
                    '<div class="fs-5 fw-bold" style="color:var(--maint-primary);">' + _fmt(d.with_due_at) + '</div>' +
                    '<div class="small text-muted">Con fecha límite</div>' +
                '</div>' +
            '</div>' +
            '<div class="col-6 col-sm-3">' +
                '<div class="card p-3 text-center shadow-sm">' +
                    '<div class="fs-5 fw-bold text-success">' + _fmt(d.on_time) + '</div>' +
                    '<div class="small text-muted">A tiempo</div>' +
                '</div>' +
            '</div>' +
            '<div class="col-6 col-sm-3">' +
                '<div class="card p-3 text-center shadow-sm">' +
                    '<div class="fs-5 fw-bold text-danger">' + _fmt(d.overdue) + '</div>' +
                    '<div class="small text-muted">Fuera de plazo</div>' +
                    (d.avg_overrun_hours ? '<div class="small text-muted">Prom. exceso: ' + _fmt(d.avg_overrun_hours) + ' h</div>' : '') +
                '</div>' +
            '</div>';
    }

    // ── Arranque ──────────────────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
