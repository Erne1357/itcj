/* itcj/apps/helpdesk/static/helpdesk/js/admin/analysis.js */
(function () {
    'use strict';

    const API = '/api/help-desk/v1/stats';

    // ── Chart instances ──────────────────────────────────────────
    let scatterChart    = null;
    let trend24Chart    = null;
    let heatmapChart    = null;
    let distResChart    = null;
    let distInvChart    = null;
    let chartYoY        = null;
    let chartSLATrend   = null;
    let chartByWeekday  = null;
    let chartByHour     = null;
    let chartByCategory = null;

    // ── Estado global de outliers ─────────────────────────────────
    let outlierData  = null;
    let activeOutlier= 'resolution';

    // ── Estado global de clustering ───────────────────────────────
    let kmeansData   = null;

    // ── Estado de tabs ───────────────────────────────────────────
    let activeTab  = 'outliers';
    let loadedTabs = new Set();

    // ── Colores ApexCharts ────────────────────────────────────────
    const CLUSTER_COLORS = ['#3b82f6','#059669','#f59e0b','#ec4899','#8b5cf6','#ef4444'];

    // ── Helpers ───────────────────────────────────────────────────
    function buildFilters() {
        const params = new URLSearchParams();
        const period  = document.getElementById('filterPeriod')?.value;
        const preset  = document.querySelector('.btn-preset.active')?.dataset?.preset || '';
        const start   = document.getElementById('filterStart')?.value;
        const end     = document.getElementById('filterEnd')?.value;
        const area    = document.getElementById('filterArea')?.value;

        if (period) params.set('period_id', period);
        if (preset) params.set('preset', preset);
        if (start && !preset && !period) params.set('start_date', start);
        if (end   && !preset && !period) params.set('end_date', end);
        if (area)   params.set('area', area);
        return params.toString() ? '?' + params.toString() : '?';
    }

    async function fetchJSON(url) {
        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function fmtHours(h) {
        if (!h && h !== 0) return '—';
        if (h < 1)  return `${Math.round(h * 60)}min`;
        if (h < 24) return `${h.toFixed(1)}h`;
        return `${(h / 24).toFixed(1)}d`;
    }

    function destroyApex(chart) {
        if (chart) { try { chart.destroy(); } catch (_) {} }
        return null;
    }

    function destroyCjs(chart) {
        if (chart) { try { chart.destroy(); } catch (_) {} }
        return null;
    }

    // ── Cargar períodos ────────────────────────────────────────────
    async function loadPeriods() {
        try {
            const json = await fetchJSON(API + '/global');
            const sel  = document.getElementById('filterPeriod');
            if (!sel) return;
            (json.data?.periods || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.name} ${p.status === 'ACTIVE' ? '(activo)' : ''}`;
                sel.appendChild(opt);
            });
        } catch (_) {}
    }

    // ================================================================
    // TAB 1: OUTLIERS
    // ================================================================
    async function loadOutliers() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/analysis/outliers' + qs);
            outlierData = json.data;
            if (!outlierData) return;

            // KPI cards
            setText('outResCount', outlierData.resolution.outlier_count);
            setText('outRatCount', outlierData.rating.outlier_count);
            setText('outInvCount', outlierData.time_invested.outlier_count);

            if (outlierData.resolution.bounds) {
                setText('outResThreshold', `Umbral: > ${outlierData.resolution.bounds.upper_fence.toFixed(1)}h`);
            }
            if (outlierData.rating.bounds) {
                setText('outRatThreshold', `Umbral: < ${outlierData.rating.bounds.lower_fence.toFixed(2)} estrellas`);
            }
            if (outlierData.time_invested.bounds) {
                setText('outInvThreshold', `Umbral: > ${outlierData.time_invested.bounds.upper_fence.toFixed(1)}h`);
            }

            showOutlierType(activeOutlier);
        } catch (err) {
            console.error('[Analysis] Error outliers:', err);
        }
    }

    window.showOutlierType = function (type) {
        activeOutlier = type;
        if (!outlierData) return;

        // Resaltar botón activo
        ['resolution', 'rating', 'time_invested'].forEach(t => {
            const ids = { resolution: 'outlierBtnRes', rating: 'outlierBtnRat', time_invested: 'outlierBtnInv' };
            const btn  = document.getElementById(ids[t]);
            if (!btn) return;
            const colors = { resolution: 'danger', rating: 'warning', time_invested: 'info' };
            btn.className = `btn btn-sm btn-${type === t ? '' : 'outline-'}${colors[t]}`;
        });

        const titlesMap = {
            resolution:    'Tickets con tiempo de resolución atípico (muy lento)',
            rating:        'Tickets con calificación atípicamente baja',
            time_invested: 'Tickets con tiempo invertido atípicamente alto',
        };
        const metricMap = {
            resolution:    'Tiempo Res.',
            rating:        'Calificación',
            time_invested: 'Tiempo Inv.',
        };

        setText('outlierTableTitle',  titlesMap[type]);
        setText('outlierMetricHeader', metricMap[type]);

        const section = outlierData[type];
        const badge   = document.getElementById('outlierCountBadge');
        if (badge) badge.textContent = section?.outlier_count || 0;

        renderOutlierTable(section?.tickets || [], type);
    };

    function renderOutlierTable(tickets, type) {
        const tbody = document.getElementById('outlierTableBody');
        if (!tbody) return;

        if (!tickets.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4"><i class="fas fa-check-circle text-success me-2"></i>Sin outliers detectados</td></tr>';
            return;
        }

        tbody.innerHTML = tickets.map(t => {
            let metricVal = '—';
            let rowClass  = 'outlier-row-high';
            if (type === 'resolution' && t.resolution_hours) {
                metricVal = fmtHours(t.resolution_hours);
            } else if (type === 'rating') {
                metricVal  = t.rating_attention ? `${t.rating_attention} ⭐` : '—';
                rowClass   = 'outlier-row-medium';
            } else if (type === 'time_invested' && t.time_invested_hours) {
                metricVal = fmtHours(t.time_invested_hours);
            }

            const PRIO = { URGENTE: 'danger', ALTA: 'warning', MEDIA: 'primary', BAJA: 'success' };
            const AREA = { DESARROLLO: 'info', SOPORTE: 'success' };

            return `<tr class="${rowClass}">
                <td><a href="/help-desk/user/tickets/${t.id}" target="_blank" class="fw-semibold text-decoration-none">${esc(t.ticket_number)}</a></td>
                <td class="text-muted small d-none d-sm-table-cell" style="max-width:200px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${esc(t.title)}</td>
                <td class="text-center"><span class="badge bg-${PRIO[t.priority] || 'secondary'}-subtle text-${PRIO[t.priority] || 'secondary'}">${t.priority}</span></td>
                <td class="text-center"><span class="badge bg-${AREA[t.area] || 'secondary'}-subtle text-${AREA[t.area] || 'secondary'}">${t.area}</span></td>
                <td class="text-center fw-bold">${esc(metricVal)}</td>
                <td class="text-center d-none d-md-table-cell">${t.rating_attention ? t.rating_attention + ' ⭐' : '—'}</td>
                <td class="text-center text-muted small d-none d-lg-table-cell">${t.created_at ? new Date(t.created_at).toLocaleDateString('es-MX') : '—'}</td>
            </tr>`;
        }).join('');
    }

    // ================================================================
    // TAB 2: CLUSTERING K-MEANS
    // ================================================================
    async function runKmeans() {
        const k       = parseInt(document.getElementById('kSelect')?.value || '3');
        const status  = document.getElementById('kmeansStatus');
        const btn     = document.getElementById('runKmeans');

        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Calculando...'; }
        if (status) status.textContent = '';

        try {
            const qs   = buildFilters();
            const json = await fetchJSON(`${API}/analysis/kmeans${qs}&k=${k}`.replace('?', '?').replace('&&', '&'));
            kmeansData = json.data;

            if (!kmeansData || !kmeansData.clusters.length) {
                if (status) status.textContent = kmeansData?.message || 'Sin datos suficientes';
                return;
            }

            if (status) status.textContent = `${kmeansData.total_tickets} tickets agrupados en ${k} clústeres`;
            renderClusterCards(kmeansData.clusters);
            renderScatterChart(kmeansData);
        } catch (err) {
            console.error('[Analysis] Error kmeans:', err);
            if (status) status.textContent = 'Error al calcular clustering';
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play me-1"></i>Ejecutar clustering'; }
        }
    }

    function renderClusterCards(clusters) {
        const container = document.getElementById('clusterCards');
        if (!container) return;

        container.innerHTML = clusters.map((c, i) => `
            <div class="col-12 col-sm-6 col-md-4">
                <div class="card shadow-sm p-3 h-100 border-2" style="border-color:${CLUSTER_COLORS[i % CLUSTER_COLORS.length]}!important;border-style:solid">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <span class="cluster-badge cluster-${i}">${i + 1}</span>
                        <strong class="small">${esc(c.label)}</strong>
                    </div>
                    <div class="row row-cols-2 g-2 small">
                        <div class="col"><span class="text-muted">Tickets:</span> <strong>${c.size}</strong></div>
                        <div class="col"><span class="text-muted">Prom. tiempo:</span> <strong>${fmtHours(c.centroid_hours)}</strong></div>
                        <div class="col"><span class="text-muted">Prom. calif.:</span> <strong>${c.centroid_rating.toFixed(2)} ⭐</strong></div>
                    </div>
                    <button class="btn btn-xs btn-outline-secondary btn-sm mt-2" onclick="window.showClusterDetail(${i})">
                        <i class="fas fa-list me-1"></i>Ver tickets
                    </button>
                </div>
            </div>`).join('');
    }

    window.showClusterDetail = function (clusterIdx) {
        if (!kmeansData?.clusters) return;
        const cluster = kmeansData.clusters[clusterIdx];
        if (!cluster) return;

        const card  = document.getElementById('clusterDetailCard');
        const title = document.getElementById('clusterDetailTitle');
        const tbody = document.getElementById('clusterDetailBody');
        if (!card || !tbody) return;

        if (title) title.textContent = `Clúster ${clusterIdx + 1}: ${cluster.label} — ${cluster.size} tickets`;
        card.style.display = '';

        if (!cluster.tickets.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Sin tickets</td></tr>';
            return;
        }

        const PRIO = { URGENTE: 'danger', ALTA: 'warning', MEDIA: 'primary', BAJA: 'success' };
        tbody.innerHTML = cluster.tickets.map(t => `
            <tr>
                <td><a href="/help-desk/user/tickets/${t.id}" target="_blank" class="text-decoration-none fw-semibold small">${esc(t.ticket_number)}</a></td>
                <td class="text-muted small d-none d-sm-table-cell">${esc(t.title)}</td>
                <td><span class="badge bg-${PRIO[t.priority] || 'secondary'}-subtle text-${PRIO[t.priority] || 'secondary'} small">${t.priority}</span></td>
                <td class="text-center">${t.resolution_hours}h</td>
                <td class="text-center">${t.rating} ⭐</td>
            </tr>`).join('');

        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    function renderScatterChart(data) {
        scatterChart = destroyApex(scatterChart);
        const container = document.getElementById('scatterChart');
        if (!container) return;

        const series = data.clusters.map((c, i) => ({
            name: `C${i + 1}: ${c.label}`,
            data: c.tickets.map(t => ({ x: t.resolution_hours, y: t.rating, id: t.id, num: t.ticket_number })),
        }));

        scatterChart = new ApexCharts(container, {
            chart: { type: 'scatter', height: 380, zoom: { enabled: true, type: 'xy' }, toolbar: { show: true } },
            series,
            colors: CLUSTER_COLORS,
            xaxis: {
                title: { text: 'Tiempo de resolución (horas)' },
                tickAmount: 8,
            },
            yaxis: {
                title: { text: 'Calificación de atención (1-5)' },
                min: 0, max: 5.5, tickAmount: 5,
            },
            tooltip: {
                custom: ({ series, seriesIndex, dataPointIndex, w }) => {
                    const pt = w.config.series[seriesIndex].data[dataPointIndex];
                    return `<div class="px-2 py-1 small"><strong>${esc(pt.num)}</strong><br>Tiempo: ${pt.x}h<br>Calif.: ${pt.y} ⭐</div>`;
                },
            },
            markers: { size: 6, hover: { sizeOffset: 3 } },
            legend: { position: 'bottom' },
        });
        scatterChart.render();
    }

    // ================================================================
    // TAB 3: DISTRIBUCIONES
    // ================================================================
    async function loadDistributions() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/analysis/distribution' + qs);
            const d    = json.data;
            if (!d) return;

            renderApexBar('chartDistResolution', d.resolution_histogram, 'Rango', 'Tickets', '#3b82f6', 'range', 'count');
            renderApexBar('chartDistInvested',   d.time_invested_histogram, 'Rango', 'Tickets', '#059669', 'range', 'count');

            // Weekday Chart.js
            chartByWeekday = destroyCjs(chartByWeekday);
            const wdCtx = document.getElementById('chartByWeekday');
            if (wdCtx) {
                chartByWeekday = new Chart(wdCtx, {
                    type: 'bar',
                    data: {
                        labels: d.by_weekday.map(w => w.day),
                        datasets: [{ label: 'Tickets', data: d.by_weekday.map(w => w.count), backgroundColor: d.by_weekday.map((_, i) => i < 5 ? 'rgba(59,130,246,.7)' : 'rgba(239,68,68,.5)'), borderRadius: 4 }],
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
                });
            }

            // Hour chart
            chartByHour = destroyCjs(chartByHour);
            const hrCtx = document.getElementById('chartByHour');
            if (hrCtx) {
                chartByHour = new Chart(hrCtx, {
                    type: 'line',
                    data: {
                        labels: d.by_hour.map(h => h.label),
                        datasets: [{ label: 'Tickets', data: d.by_hour.map(h => h.count), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,.1)', fill: true, tension: 0.4, pointRadius: 2 }],
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
                });
            }

            // Category chart
            chartByCategory = destroyCjs(chartByCategory);
            const catCtx = document.getElementById('chartByCategory');
            if (catCtx) {
                chartByCategory = new Chart(catCtx, {
                    type: 'bar',
                    data: {
                        labels: d.by_category.map(c => c.category),
                        datasets: [{ label: 'Tickets', data: d.by_category.map(c => c.count), backgroundColor: 'rgba(139,92,246,.7)', borderRadius: 4 }],
                    },
                    options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } } },
                });
            }
        } catch (err) {
            console.error('[Analysis] Error distributions:', err);
        }
    }

    function renderApexBar(containerId, data, xKey, yTitle, color, labelKey, valueKey) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        const chart = new ApexCharts(container, {
            chart: { type: 'bar', height: 300, toolbar: { show: false } },
            series: [{ name: yTitle, data: data.map(d => d[valueKey]) }],
            xaxis: { categories: data.map(d => d[labelKey]) },
            colors: [color],
            plotOptions: { bar: { borderRadius: 4, columnWidth: '60%' } },
            dataLabels: { enabled: false },
            grid: { borderColor: '#f1f1f1' },
            legend: { show: false },
        });
        chart.render();
    }

    // ================================================================
    // TAB 4: TENDENCIAS
    // ================================================================
    async function loadTrends() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/analysis/trends' + qs);
            const d    = json.data;
            if (!d) return;

            // Trend 24 meses (ApexCharts line)
            trend24Chart = destroyApex(trend24Chart);
            const t24El = document.getElementById('chartTrend24');
            if (t24El) {
                t24El.innerHTML = '';
                trend24Chart = new ApexCharts(t24El, {
                    chart: { type: 'line', height: 380, toolbar: { show: true }, zoom: { enabled: false } },
                    series: [
                        { name: 'Creados', data: d.monthly.map(m => ({ x: m.month, y: m.created })) },
                        { name: 'Resueltos', data: d.monthly.map(m => ({ x: m.month, y: m.resolved })) },
                    ],
                    colors: ['#3b82f6', '#059669'],
                    stroke: { curve: 'smooth', width: 2 },
                    xaxis: { type: 'category', tickAmount: 12, labels: { rotate: -30, style: { fontSize: '10px' } } },
                    yaxis: { title: { text: 'Tickets' }, min: 0 },
                    legend: { position: 'top' },
                    tooltip: { shared: true, intersect: false },
                    markers: { size: 4 },
                });
                trend24Chart.render();
            }

            // YoY — Chart.js
            chartYoY = destroyCjs(chartYoY);
            const yoyCtx = document.getElementById('chartYoY');
            const now = new Date();
            if (yoyCtx) {
                chartYoY = new Chart(yoyCtx, {
                    type: 'bar',
                    data: {
                        labels: d.yoy.map(m => m.month_label),
                        datasets: [
                            { label: String(now.getFullYear()), data: d.yoy.map(m => m.this_year), backgroundColor: 'rgba(59,130,246,.7)', borderRadius: 4 },
                            { label: String(now.getFullYear() - 1), data: d.yoy.map(m => m.prev_year), backgroundColor: 'rgba(107,114,128,.4)', borderRadius: 4 },
                        ],
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true } } },
                });
            }

            // SLA trend — Chart.js
            chartSLATrend = destroyCjs(chartSLATrend);
            const slaCtx = document.getElementById('chartSLATrend');
            if (slaCtx) {
                chartSLATrend = new Chart(slaCtx, {
                    type: 'line',
                    data: {
                        labels: d.monthly.slice(-12).map(m => m.month),
                        datasets: [{ label: 'Cumplimiento SLA (%)', data: d.monthly.slice(-12).map(m => m.sla_rate), borderColor: '#059669', backgroundColor: 'rgba(5,150,105,.1)', fill: true, tension: 0.3, pointRadius: 4 }],
                    },
                    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, max: 100 } } },
                });
            }

            // Heatmap — ApexCharts
            renderHeatmap(d.heatmap);
        } catch (err) {
            console.error('[Analysis] Error trends:', err);
        }
    }

    function renderHeatmap(heatmap) {
        heatmapChart = destroyApex(heatmapChart);
        const el = document.getElementById('chartHeatmap');
        if (!el || !heatmap?.length) return;
        el.innerHTML = '';

        const DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
        const series = DAYS.map((day, dow) => ({
            name: day,
            data: heatmap.filter(h => h.dow === dow).map(h => ({ x: `${h.hour}:00`, y: h.count })),
        }));

        heatmapChart = new ApexCharts(el, {
            chart: { type: 'heatmap', height: 260, toolbar: { show: false } },
            series,
            dataLabels: { enabled: false },
            colors: ['#059669'],
            xaxis: { title: { text: 'Hora del día' }, labels: { style: { fontSize: '9px' } } },
            legend: { show: false },
            tooltip: { y: { formatter: v => `${v} tickets` } },
        });
        heatmapChart.render();
    }

    // ================================================================
    // Control de tabs
    // ================================================================
    function loadCurrentTab(force = false) {
        if (!force && loadedTabs.has(activeTab)) return;
        loadedTabs.add(activeTab);

        if (activeTab === 'outliers')   loadOutliers();
        else if (activeTab === 'clustering') { /* se activa con botón */ }
        else if (activeTab === 'dist')   loadDistributions();
        else if (activeTab === 'trends') loadTrends();
    }

    function reloadAll() {
        loadedTabs.clear();
        outlierData = null;
        kmeansData  = null;
        loadCurrentTab(true);
    }

    // ================================================================
    // Setup
    // ================================================================
    document.addEventListener('DOMContentLoaded', () => {
        loadPeriods();

        // Tab listener
        document.querySelectorAll('#analysisTabs .nav-link').forEach(link => {
            link.addEventListener('shown.bs.tab', e => {
                const href = e.target.getAttribute('href');
                activeTab = href ? href.replace('#tab-', '') : 'outliers';
                loadCurrentTab();
            });
        });

        // K-means button
        document.getElementById('runKmeans')?.addEventListener('click', runKmeans);

        // Preset buttons
        document.querySelectorAll('.btn-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                if (btn.dataset.preset) {
                    document.getElementById('filterStart').value = '';
                    document.getElementById('filterEnd').value   = '';
                    document.getElementById('filterPeriod').value = '';
                }
                reloadAll();
            });
        });

        document.getElementById('filterPeriod')?.addEventListener('change', () => {
            document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
            document.querySelector('.btn-preset[data-preset=""]')?.classList.add('active');
            reloadAll();
        });

        let dateDebounce = null;
        ['filterStart', 'filterEnd'].forEach(id => {
            document.getElementById(id)?.addEventListener('change', () => {
                clearTimeout(dateDebounce);
                dateDebounce = setTimeout(() => {
                    document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
                    reloadAll();
                }, 400);
            });
        });

        document.getElementById('filterArea')?.addEventListener('change', reloadAll);

        // Carga inicial
        loadCurrentTab();
    });
})();
