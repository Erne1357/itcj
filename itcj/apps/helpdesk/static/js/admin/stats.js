/* itcj/apps/helpdesk/static/helpdesk/js/admin/stats.js */
(function () {
    'use strict';

    const API = '/api/help-desk/v1/stats';

    // ── Chart instances ──────────────────────────────────────────
    let chartMonthly   = null;
    let chartStatus    = null;
    let chartArea      = null;
    let chartPriority  = null;
    let chartDeptBar   = null;
    let chartDeptRating= null;
    let chartTechBar   = null;
    let chartTechRating= null;
    let chartTimeHist  = null;
    let chartAreaTime  = null;
    let chartDistAtt   = null;
    let chartDistSpd   = null;

    // ── Estado ───────────────────────────────────────────────────
    let activeTab = 'resumen';
    let loadedTabs = new Set();

    // ── Colores temáticos ─────────────────────────────────────────
    const COLORS = {
        primary:  '#059669',
        warning:  '#f59e0b',
        danger:   '#ef4444',
        info:     '#3b82f6',
        secondary:'#6b7280',
        purple:   '#8b5cf6',
        pink:     '#ec4899',
        status: {
            PENDING:          '#f59e0b',
            ASSIGNED:         '#3b82f6',
            IN_PROGRESS:      '#8b5cf6',
            RESOLVED_SUCCESS: '#059669',
            RESOLVED_FAILED:  '#ef4444',
            CLOSED:           '#6b7280',
            CANCELED:         '#d1d5db',
        },
        priority: {
            URGENTE: '#ef4444',
            ALTA:    '#f59e0b',
            MEDIA:   '#3b82f6',
            BAJA:    '#059669',
        },
    };

    const STATUS_LABELS = {
        PENDING: 'Pendiente', ASSIGNED: 'Asignado', IN_PROGRESS: 'En Proceso',
        RESOLVED_SUCCESS: 'Resuelto OK', RESOLVED_FAILED: 'Resuelto Fail',
        CLOSED: 'Cerrado', CANCELED: 'Cancelado',
    };

    const PRIORITY_COLORS_ALPHA = {
        URGENTE: 'rgba(239,68,68,.7)', ALTA: 'rgba(245,158,11,.7)',
        MEDIA: 'rgba(59,130,246,.7)',  BAJA: 'rgba(5,150,105,.7)',
    };

    // ── Helpers ───────────────────────────────────────────────────
    function fmtHours(h) {
        if (h === null || h === undefined || h === 0) return '—';
        if (h < 1) return `${Math.round(h * 60)}min`;
        if (h < 24) return `${h.toFixed(1)}h`;
        return `${(h / 24).toFixed(1)}d`;
    }

    function fmtRating(r) {
        return r ? r.toFixed(2) : '—';
    }

    function starsHtml(val, max = 5) {
        if (!val) return '';
        let html = '';
        for (let i = 1; i <= max; i++) {
            html += `<i class="fas fa-star${i <= Math.round(val) ? '' : '-o'} ${i <= Math.round(val) ? '' : 'empty'}"></i>`;
        }
        return html;
    }

    function buildFilters() {
        const params  = new URLSearchParams();
        const period  = document.getElementById('filterPeriod')?.value;
        const preset  = document.querySelector('.btn-preset.active')?.dataset?.preset || '';
        const start   = document.getElementById('filterStart')?.value;
        const end     = document.getElementById('filterEnd')?.value;
        const area    = document.getElementById('filterArea')?.value;
        const isClean = document.getElementById('statsModeClean')?.classList.contains('active');

        if (period)  params.set('period_id', period);
        if (preset)  params.set('preset', preset);
        if (start && !preset && !period) params.set('start_date', start);
        if (end   && !preset && !period) params.set('end_date', end);
        if (area)    params.set('area', area);
        if (isClean) params.set('exclude_outliers', '1');
        return params.toString() ? '?' + params.toString() : '';
    }

    function showExclusionBanner(exclusionInfo) {
        const banner = document.getElementById('statsExclusionBanner');
        const text   = document.getElementById('statsExclusionBannerText');
        if (!banner) return;

        const isClean = document.getElementById('statsModeClean')?.classList.contains('active');
        if (!isClean || !exclusionInfo) {
            banner.style.setProperty('display', 'none', 'important');
            return;
        }

        banner.style.removeProperty('display');
        if (text) {
            const exc  = exclusionInfo.excluded_count;
            const orig = exclusionInfo.original_count;
            const filt = exclusionInfo.filtered_count;
            const pct  = exclusionInfo.pct_excluded;
            text.innerHTML =
                `<strong><i class="fas fa-filter me-1"></i>Modo sin outliers activo</strong>` +
                ` &mdash; Se excluyeron <strong>${exc}</strong> de ${orig} tickets (${pct}%)` +
                ` por tiempos atípicos. Estadísticas calculadas sobre <strong>${filt} tickets</strong>.`;
        }
    }

    async function fetchJSON(url) {
        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    function destroyChart(chartRef) {
        if (chartRef) { try { chartRef.destroy(); } catch (_) {} }
        return null;
    }

    function makeChart(id, type, data, options = {}) {
        const ctx = document.getElementById(id);
        if (!ctx) return null;
        return new Chart(ctx, {
            type,
            data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } },
                ...options,
            },
        });
    }

    // ── Cargar períodos académicos ────────────────────────────────
    async function loadPeriods() {
        try {
            const json = await fetchJSON(API + '/global');
            const sel = document.getElementById('filterPeriod');
            if (!sel) return;
            (json.data?.periods || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.name} ${p.status === 'ACTIVE' ? '(activo)' : ''}`;
                sel.appendChild(opt);
            });
        } catch (_) {}
    }

    // ── TAB: RESUMEN ─────────────────────────────────────────────
    async function loadResumen() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/global' + qs);
            const d    = json.data;
            if (!d) return;

            // KPIs
            const active = (d.by_status.PENDING || 0) + (d.by_status.ASSIGNED || 0) + (d.by_status.IN_PROGRESS || 0);
            const res    = (d.by_status.RESOLVED_SUCCESS || 0) + (d.by_status.RESOLVED_FAILED || 0) + (d.by_status.CLOSED || 0);
            setText('kpiTotal',      d.total);
            setText('kpiActive',     active);
            setText('kpiResolved',   res);
            setText('kpiRating',     fmtRating(d.avg_rating_attention));
            setText('kpiRatingCount', `${d.rated_count} calificados`);
            setText('kpiResRate',    `${d.resolution_rate}%`);
            setText('kpiSLA',        `${d.sla_compliance_rate}%`);
            setText('kpiAvgTime',    fmtHours(d.avg_resolution_hours));
            setText('kpiAssignTime', fmtHours(d.avg_time_to_assign_hours));

            // Tendencia mensual
            chartMonthly = destroyChart(chartMonthly);
            chartMonthly = makeChart('chartMonthly', 'line', {
                labels: d.monthly_trend.map(m => m.month),
                datasets: [{
                    label: 'Tickets creados',
                    data: d.monthly_trend.map(m => m.count),
                    borderColor: COLORS.primary,
                    backgroundColor: 'rgba(5,150,105,.1)',
                    fill: true,
                    tension: 0.35,
                    pointRadius: 4,
                }],
            }, { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } });

            // Pie de status
            const statuses = Object.keys(STATUS_LABELS);
            chartStatus = destroyChart(chartStatus);
            chartStatus = makeChart('chartStatus', 'doughnut', {
                labels: statuses.map(s => STATUS_LABELS[s]),
                datasets: [{ data: statuses.map(s => d.by_status[s] || 0), backgroundColor: statuses.map(s => COLORS.status[s]) }],
            }, { cutout: '55%' });

            // Pie de área
            chartArea = destroyChart(chartArea);
            chartArea = makeChart('chartArea', 'doughnut', {
                labels: ['Desarrollo', 'Soporte'],
                datasets: [{ data: [d.by_area.DESARROLLO || 0, d.by_area.SOPORTE || 0], backgroundColor: [COLORS.info, COLORS.primary] }],
            }, { cutout: '55%' });

            // Bar de prioridad
            const prios = ['URGENTE', 'ALTA', 'MEDIA', 'BAJA'];
            chartPriority = destroyChart(chartPriority);
            chartPriority = makeChart('chartPriority', 'bar', {
                labels: prios,
                datasets: [{ label: 'Tickets', data: prios.map(p => d.by_priority[p] || 0), backgroundColor: prios.map(p => PRIORITY_COLORS_ALPHA[p]) }],
            }, { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } });

            // Indicadores generales
            renderGeneralIndicators(d);
            showExclusionBanner(d.exclusion_info || null);

        } catch (err) {
            console.error('[Stats] Error cargando resumen:', err);
            HelpdeskUtils.showToast('Error al cargar estadísticas generales', 'error');
        }
    }

    function renderGeneralIndicators(d) {
        const el = document.getElementById('generalIndicators');
        if (!el) return;
        const items = [
            { label: 'Calificación de atención', value: `${fmtRating(d.avg_rating_attention)} / 5`, pct: (d.avg_rating_attention / 5) * 100, color: 'success' },
            { label: 'Calificación de velocidad', value: `${fmtRating(d.avg_rating_speed)} / 5`, pct: (d.avg_rating_speed / 5) * 100, color: 'info' },
            { label: 'Eficiencia percibida', value: `${d.efficiency_rate}%`, pct: d.efficiency_rate, color: 'primary' },
            { label: 'Cumplimiento SLA', value: `${d.sla_compliance_rate}%`, pct: d.sla_compliance_rate, color: d.sla_compliance_rate >= 80 ? 'success' : d.sla_compliance_rate >= 60 ? 'warning' : 'danger' },
            { label: 'Tasa de resolución', value: `${d.resolution_rate}%`, pct: d.resolution_rate, color: 'primary' },
        ];
        el.innerHTML = items.map(i => `
            <div class="mb-3">
                <div class="d-flex justify-content-between small mb-1">
                    <span>${i.label}</span><strong>${i.value}</strong>
                </div>
                <div class="progress" style="height:8px;border-radius:4px">
                    <div class="progress-bar bg-${i.color}" style="width:${Math.min(i.pct||0,100)}%"></div>
                </div>
            </div>`).join('');
    }

    // ── TAB: POR DEPARTAMENTO ────────────────────────────────────
    async function loadDept() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/by-department' + qs);
            const data = json.data || [];

            // Bar chart
            chartDeptBar = destroyChart(chartDeptBar);
            chartDeptBar = makeChart('chartDeptBar', 'bar', {
                labels: data.slice(0, 12).map(d => truncate(d.department_name, 15)),
                datasets: [
                    { label: 'Total', data: data.slice(0, 12).map(d => d.total), backgroundColor: 'rgba(59,130,246,.6)' },
                    { label: 'Resueltos', data: data.slice(0, 12).map(d => d.resolved), backgroundColor: 'rgba(5,150,105,.7)' },
                ],
            }, { plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true } } });

            // Rating chart
            chartDeptRating = destroyChart(chartDeptRating);
            chartDeptRating = makeChart('chartDeptRating', 'bar', {
                labels: data.slice(0, 12).map(d => truncate(d.department_name, 15)),
                datasets: [{ label: 'Calif. Atención', data: data.slice(0, 12).map(d => d.avg_rating || 0), backgroundColor: 'rgba(245,158,11,.7)', borderRadius: 4 }],
            }, { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, max: 5 } } });

            // Tabla
            renderDeptTable(data);
            setupTableSearch('deptSearch', 'deptTableBody', 'tr');
            showExclusionBanner(json.exclusion_info || null);
        } catch (err) {
            console.error('[Stats] Error dept:', err);
        }
    }

    function renderDeptTable(data) {
        const tbody = document.getElementById('deptTableBody');
        if (!tbody) return;
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Sin datos</td></tr>';
            return;
        }
        tbody.innerHTML = data.map((d, i) => `
            <tr>
                <td><span class="stats-rank-badge ${i < 3 ? 'bg-warning text-dark' : 'bg-light text-muted'}">${i + 1}</span></td>
                <td class="fw-semibold">${esc(d.department_name)}</td>
                <td class="text-center"><strong>${d.total}</strong></td>
                <td class="text-center"><span class="badge bg-warning-subtle text-warning">${d.active}</span></td>
                <td class="text-center"><span class="badge bg-success-subtle text-success">${d.resolved}</span></td>
                <td class="text-center d-none d-md-table-cell">${fmtHours(d.avg_resolution_hours)}</td>
                <td class="text-center d-none d-md-table-cell">${slaBadge(d.sla_rate)}</td>
                <td class="text-center">${ratingBadge(d.avg_rating)}</td>
                <td class="text-muted small d-none d-lg-table-cell">${esc(d.top_category || '—')}</td>
            </tr>`).join('');
    }

    // ── TAB: POR TÉCNICO ─────────────────────────────────────────
    async function loadTech() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/by-technician' + qs);
            const data = json.data || [];

            chartTechBar = destroyChart(chartTechBar);
            chartTechBar = makeChart('chartTechBar', 'bar', {
                labels: data.slice(0, 10).map(d => d.name.split(' ')[0]),
                datasets: [
                    { label: 'Resueltos', data: data.slice(0, 10).map(d => d.resolved), backgroundColor: 'rgba(5,150,105,.7)', borderRadius: 4 },
                    { label: 'En Proceso', data: data.slice(0, 10).map(d => d.in_progress), backgroundColor: 'rgba(139,92,246,.6)', borderRadius: 4 },
                ],
            }, { plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true } } });

            chartTechRating = destroyChart(chartTechRating);
            chartTechRating = makeChart('chartTechRating', 'bar', {
                labels: data.slice(0, 10).map(d => d.name.split(' ')[0]),
                datasets: [
                    { label: 'Atención', data: data.slice(0, 10).map(d => d.avg_rating_attention || 0), backgroundColor: 'rgba(245,158,11,.7)', borderRadius: 4 },
                    { label: 'Velocidad', data: data.slice(0, 10).map(d => d.avg_rating_speed || 0), backgroundColor: 'rgba(59,130,246,.6)', borderRadius: 4 },
                ],
            }, { plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true, max: 5 } } });

            renderTechTable(data);
            setupTableSearch('techSearch', 'techTableBody', 'tr');
            showExclusionBanner(json.exclusion_info || null);
        } catch (err) {
            console.error('[Stats] Error tech:', err);
        }
    }

    function renderTechTable(data) {
        const tbody = document.getElementById('techTableBody');
        if (!tbody) return;
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">Sin datos</td></tr>';
            return;
        }
        tbody.innerHTML = data.map((d, i) => `
            <tr>
                <td><span class="stats-rank-badge ${i < 3 ? 'bg-warning text-dark' : 'bg-light text-muted'}">${i + 1}</span></td>
                <td class="fw-semibold">${esc(d.name)}</td>
                <td class="text-center"><strong>${d.resolved}</strong></td>
                <td class="text-center d-none d-sm-table-cell"><span class="badge bg-purple-subtle text-purple">${d.in_progress}</span></td>
                <td class="text-center d-none d-md-table-cell">${fmtHours(d.avg_resolution_hours)}</td>
                <td class="text-center d-none d-md-table-cell">${fmtHours(d.avg_time_invested_hours)}</td>
                <td class="text-center d-none d-md-table-cell">${slaBadge(d.sla_rate)}</td>
                <td class="text-center">${ratingBadge(d.avg_rating_attention)}</td>
                <td class="text-center d-none d-lg-table-cell">${d.efficiency_rate ? d.efficiency_rate + '%' : '—'}</td>
                <td class="text-muted small d-none d-lg-table-cell">${d.tickets_as_lead}L / ${d.tickets_as_collaborator}C</td>
            </tr>`).join('');
    }

    // ── TAB: TIEMPOS ─────────────────────────────────────────────
    async function loadTime() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/time-breakdown' + qs);
            const d    = json.data;
            if (!d) return;

            setText('timeAssign',   fmtHours(d.avg_time_to_assign_hours));
            setText('timeResolve',  fmtHours(d.avg_resolution_hours));
            setText('timeInvested', fmtHours(d.avg_time_invested_hours));

            // Histograma
            chartTimeHist = destroyChart(chartTimeHist);
            chartTimeHist = makeChart('chartTimeHist', 'bar', {
                labels: d.resolution_histogram.map(b => b.range),
                datasets: [{ label: 'Tickets', data: d.resolution_histogram.map(b => b.count), backgroundColor: 'rgba(59,130,246,.65)', borderRadius: 4 }],
            }, { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } });

            // Tabla por prioridad
            renderTimePriority(d.by_priority);

            // Chart por área
            chartAreaTime = destroyChart(chartAreaTime);
            chartAreaTime = makeChart('chartAreaTime', 'bar', {
                labels: d.by_area.map(a => a.area),
                datasets: [
                    { label: 'Prom. Resolución (h)', data: d.by_area.map(a => a.avg_resolution_hours), backgroundColor: 'rgba(59,130,246,.7)', borderRadius: 4 },
                    { label: 'Prom. Invertido (h)', data: d.by_area.map(a => a.avg_time_invested_hours), backgroundColor: 'rgba(5,150,105,.7)', borderRadius: 4 },
                ],
            }, { plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true } } });
            showExclusionBanner(d.exclusion_info || null);
        } catch (err) {
            console.error('[Stats] Error time:', err);
        }
    }

    function renderTimePriority(rows) {
        const tbody = document.getElementById('timePriorityBody');
        if (!tbody) return;
        const maxH = Math.max(...rows.map(r => r.avg_resolution_hours || 0), 1);
        const PRIO_BADGE = { URGENTE: 'danger', ALTA: 'warning', MEDIA: 'primary', BAJA: 'success' };
        tbody.innerHTML = rows.map(r => `
            <tr>
                <td><span class="badge bg-${PRIO_BADGE[r.priority] || 'secondary'}">${r.priority}</span></td>
                <td class="text-center">${r.count}</td>
                <td class="text-center">${fmtHours(r.avg_resolution_hours)}</td>
                <td class="text-center">${slaBadge(r.sla_rate)}</td>
                <td style="min-width:80px">
                    <div class="stats-mini-bar"><div class="fill" style="width:${Math.round((r.avg_resolution_hours / maxH) * 100)}%"></div></div>
                </td>
            </tr>`).join('');
    }

    // ── TAB: CALIFICACIONES ──────────────────────────────────────
    async function loadRatings() {
        try {
            const qs   = buildFilters();
            const json = await fetchJSON(API + '/ratings-detail' + qs);
            const d    = json.data;
            if (!d) return;

            setText('ratingAvgAtt',    fmtRating(d.avg_attention));
            setText('ratingAvgSpd',    fmtRating(d.avg_speed));
            setText('ratingEfficiency', `${d.efficiency_rate}%`);
            setText('ratingCount',     d.rated_count);
            setText('ratingUnrated',   `${d.unrated_count} sin calificar`);

            const attEl = document.getElementById('ratingStarsAtt');
            const spdEl = document.getElementById('ratingStarsSpd');
            if (attEl) attEl.innerHTML = starsHtml(d.avg_attention);
            if (spdEl) spdEl.innerHTML = starsHtml(d.avg_speed);

            // Distribución atención
            const labels5 = ['1 ⭐', '2 ⭐', '3 ⭐', '4 ⭐', '5 ⭐'];
            const barColors = ['rgba(239,68,68,.7)', 'rgba(245,158,11,.7)', 'rgba(234,179,8,.7)', 'rgba(59,130,246,.7)', 'rgba(5,150,105,.7)'];
            chartDistAtt = destroyChart(chartDistAtt);
            chartDistAtt = makeChart('chartDistAtt', 'bar', {
                labels: labels5,
                datasets: [{ label: 'Tickets', data: d.dist_attention, backgroundColor: barColors, borderRadius: 4 }],
            }, { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } });

            chartDistSpd = destroyChart(chartDistSpd);
            chartDistSpd = makeChart('chartDistSpd', 'bar', {
                labels: labels5,
                datasets: [{ label: 'Tickets', data: d.dist_speed, backgroundColor: barColors, borderRadius: 4 }],
            }, { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } });

            // Tablas
            renderRatingTable('ratingByTechBody', d.by_technician);
            renderRatingTable('ratingByDeptBody', d.by_department);

            // Comentarios
            renderComments(d.recent_comments || []);
            showExclusionBanner(d.exclusion_info || null);
        } catch (err) {
            console.error('[Stats] Error ratings:', err);
        }
    }

    function renderRatingTable(id, rows) {
        const tbody = document.getElementById(id);
        if (!tbody) return;
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">Sin datos</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map((r, i) => `
            <tr>
                <td><span class="stats-rank-badge ${i < 3 ? 'bg-warning text-dark' : 'bg-light text-muted'}">${i + 1}</span></td>
                <td class="fw-semibold">${esc(r.name)}</td>
                <td class="text-center">${ratingBadge(r.avg_attention)}</td>
                <td class="text-center">${ratingBadge(r.avg_speed)}</td>
                <td class="text-center text-muted small">${r.count}</td>
            </tr>`).join('');
    }

    function renderComments(comments) {
        const el = document.getElementById('recentComments');
        if (!el) return;
        if (!comments.length) {
            el.innerHTML = '<p class="text-muted small text-center py-3">No hay comentarios en el período seleccionado.</p>';
            return;
        }
        el.innerHTML = comments.map(c => `
            <div class="rating-comment-card">
                <div class="d-flex justify-content-between align-items-start mb-1">
                    <span class="stats-stars">${starsHtml(c.rating)}</span>
                    <span class="ticket-ref">${esc(c.ticket_number)} · ${c.date ? new Date(c.date).toLocaleDateString('es-MX') : ''}</span>
                </div>
                <div class="text-dark">${esc(c.comment)}</div>
            </div>`).join('');
    }

    // ── Helpers de badge ─────────────────────────────────────────
    function slaBadge(pct) {
        if (pct === null || pct === undefined) return '—';
        const cls = pct >= 80 ? 'success' : pct >= 60 ? 'warning' : 'danger';
        return `<span class="badge bg-${cls}-subtle text-${cls}">${pct}%</span>`;
    }

    function ratingBadge(r) {
        if (!r) return '—';
        const cls = r >= 4 ? 'success' : r >= 3 ? 'warning' : 'danger';
        return `<span class="badge bg-${cls}-subtle text-${cls}">${fmtRating(r)}</span>`;
    }

    function truncate(str, n) {
        return str && str.length > n ? str.slice(0, n) + '…' : str;
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

    function setupTableSearch(inputId, tbodyId) {
        const input = document.getElementById(inputId);
        const tbody = document.getElementById(tbodyId);
        if (!input || !tbody) return;
        input.addEventListener('input', () => {
            const term = input.value.toLowerCase();
            tbody.querySelectorAll('tr').forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(term) ? '' : 'none';
            });
        });
    }

    // ── Carga por tab ────────────────────────────────────────────
    function loadCurrentTab(force = false) {
        if (!force && loadedTabs.has(activeTab)) return;
        loadedTabs.add(activeTab);

        if (activeTab === 'resumen') loadResumen();
        else if (activeTab === 'dept')   loadDept();
        else if (activeTab === 'tech')   loadTech();
        else if (activeTab === 'time')   loadTime();
        else if (activeTab === 'rating') loadRatings();
    }

    function reloadAll() {
        loadedTabs.clear();
        loadCurrentTab(true);
    }

    // ── Setup ────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        loadPeriods();

        // Tab listener
        document.querySelectorAll('#statsTabs .nav-link').forEach(link => {
            link.addEventListener('shown.bs.tab', e => {
                const href = e.target.getAttribute('href');
                activeTab  = href ? href.replace('#tab-', '') : 'resumen';
                loadCurrentTab();
            });
        });

        // Preset buttons
        document.querySelectorAll('.btn-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                // Limpiar fechas personalizadas si se selecciona preset
                if (btn.dataset.preset) {
                    document.getElementById('filterStart').value = '';
                    document.getElementById('filterEnd').value   = '';
                    document.getElementById('filterPeriod').value = '';
                }
                reloadAll();
            });
        });

        // Period select
        document.getElementById('filterPeriod')?.addEventListener('change', () => {
            document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
            document.querySelector('.btn-preset[data-preset=""]')?.classList.add('active');
            reloadAll();
        });

        // Custom date range
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

        // Área
        document.getElementById('filterArea')?.addEventListener('change', reloadAll);

        // Toggle modo análisis
        document.querySelectorAll('#statsModeBtns .btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.classList.contains('active')) return;
                document.querySelectorAll('#statsModeBtns .btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                if (btn.id === 'statsModeAll') {
                    const banner = document.getElementById('statsExclusionBanner');
                    if (banner) banner.style.setProperty('display', 'none', 'important');
                }
                reloadAll();
            });
        });

        // Carga inicial
        loadCurrentTab();
    });
})();
