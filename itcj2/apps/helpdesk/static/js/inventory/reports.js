/**
 * Reportes de Inventario
 * Maneja 5 pestañas: Equipos, Movimientos, Garantías, Mantenimiento, Ciclo de Vida
 */
(function () {
    'use strict';

    const API_BASE = '/api/help-desk/v2/inventory';
    const AUTH_HEADERS = () => ({
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        'Content-Type': 'application/json'
    });

    // Estado
    let allDepartments = [];
    let allCategories = [];
    let eqCurrentPage = 1;
    let mvCurrentPage = 1;
    let currentActiveTab = typeof ACTIVE_TAB !== 'undefined' ? ACTIVE_TAB : 'equipos';

    // Labels para event types y statuses
    const EVENT_LABELS = {
        'REGISTERED': 'Registrado',
        'ASSIGNED_TO_DEPT': 'Asignado a Depto.',
        'ASSIGNED_TO_USER': 'Asignado a Usuario',
        'UNASSIGNED': 'Desasignado',
        'REASSIGNED': 'Reasignado',
        'LOCATION_CHANGED': 'Cambio Ubicación',
        'STATUS_CHANGED': 'Cambio de Estado',
        'MAINTENANCE_SCHEDULED': 'Mant. Programado',
        'MAINTENANCE_COMPLETED': 'Mant. Completado',
        'SPECS_UPDATED': 'Specs Actualizadas',
        'TRANSFERRED': 'Transferido',
        'DEACTIVATED': 'Dado de Baja',
        'REACTIVATED': 'Reactivado',
        'VERIFIED':    'Verificación Física'
    };

    const STATUS_LABELS = {
        'PENDING_ASSIGNMENT': 'Pendiente',
        'ACTIVE': 'Activo',
        'MAINTENANCE': 'En Mantenimiento',
        'DAMAGED': 'Dañado',
        'RETIRED': 'Retirado',
        'LOST': 'Extraviado'
    };

    // ==================== INIT ====================

    document.addEventListener('DOMContentLoaded', function () {
        loadFilterData();
        setupTabListeners();
        setDatePreset('month');

        // Cargar datos del tab activo
        loadActiveTabData();
    });

    function setupTabListeners() {
        const tabEls = document.querySelectorAll('#reportTabs button[data-bs-toggle="tab"]');
        tabEls.forEach(function (tabEl) {
            tabEl.addEventListener('shown.bs.tab', function (event) {
                const target = event.target.getAttribute('data-bs-target');
                if (target === '#panel-equipos') currentActiveTab = 'equipos';
                else if (target === '#panel-movimientos') currentActiveTab = 'movimientos';
                else if (target === '#panel-garantias') currentActiveTab = 'garantias';
                else if (target === '#panel-mantenimiento') currentActiveTab = 'mantenimiento';
                else if (target === '#panel-ciclo-vida') currentActiveTab = 'ciclo-vida';
                else if (target === '#panel-verificacion') currentActiveTab = 'verificacion';

                // Actualizar URL sin recargar
                const url = new URL(window.location);
                url.searchParams.set('tab', currentActiveTab);
                history.replaceState(null, '', url);

                loadActiveTabData();
                updateExportButtons();
            });
        });
    }

    function loadActiveTabData() {
        switch (currentActiveTab) {
            case 'equipos':
                // Solo cargar si la tabla está vacía (placeholder)
                break;
            case 'movimientos':
                break;
            case 'garantias':
                loadWarrantyReport();
                break;
            case 'mantenimiento':
                loadMaintenanceReport();
                break;
            case 'ciclo-vida':
                loadLifecycleReport();
                break;
            case 'verificacion':
                loadVerificationReport();
                break;
        }
        updateExportButtons();
    }

    async function loadFilterData() {
        try {
            const [deptRes, catRes] = await Promise.all([
                fetch('/api/core/v2/departments?active=true', { headers: AUTH_HEADERS() }),
                fetch(`${API_BASE}/categories`, { headers: AUTH_HEADERS() })
            ]);

            if (deptRes.ok) {
                const deptData = await deptRes.json();
                allDepartments = deptData.data || [];
                populateDepartmentSelects();
            }

            if (catRes.ok) {
                const catData = await catRes.json();
                allCategories = catData.data || [];
                populateCategorySelect();
            }
        } catch (error) {
            console.error('Error cargando datos de filtros:', error);
        }
    }

    function populateDepartmentSelects() {
        const multiSelects = ['eq-departments', 'mv-departments'];
        multiSelects.forEach(function (id) {
            const select = document.getElementById(id);
            if (!select) return;
            select.innerHTML = '';
            allDepartments.forEach(function (dept) {
                const option = document.createElement('option');
                option.value = dept.id;
                option.textContent = dept.name;
                select.appendChild(option);
            });
        });

        // Single-select con opción "Todos" para el tab de verificación
        const vrSelect = document.getElementById('vr-department');
        if (vrSelect) {
            vrSelect.innerHTML = '<option value="">Todos</option>';
            allDepartments.forEach(function (dept) {
                const option = document.createElement('option');
                option.value = dept.id;
                option.textContent = dept.name;
                vrSelect.appendChild(option);
            });
        }
    }

    function populateCategorySelect() {
        const select = document.getElementById('eq-categories');
        if (!select) return;
        select.innerHTML = '';
        allCategories.forEach(function (cat) {
            const option = document.createElement('option');
            option.value = cat.id;
            option.textContent = cat.name;
            select.appendChild(option);
        });
    }

    // ==================== REPORTE DE EQUIPOS ====================

    window.loadEquipmentReport = async function (page) {
        eqCurrentPage = page || 1;
        const tbody = document.getElementById('eq-tbody');
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-3"><i class="fas fa-spinner fa-spin"></i> Cargando...</td></tr>';

        const filters = {
            department_ids: getMultiSelectValues('eq-departments'),
            category_ids: getMultiSelectValues('eq-categories'),
            statuses: getMultiSelectValues('eq-statuses'),
            search: document.getElementById('eq-search').value.trim(),
            page: eqCurrentPage,
            per_page: parseInt(document.getElementById('eq-per-page').value)
        };

        try {
            const response = await fetch(`${API_BASE}/reports/equipment`, {
                method: 'POST',
                headers: AUTH_HEADERS(),
                body: JSON.stringify(filters)
            });

            if (!response.ok) throw new Error('Error al cargar reporte');
            const result = await response.json();

            document.getElementById('eq-total').textContent = result.total;
            renderEquipmentTable(result.items);
            renderPagination('eq-pagination', 'eq-pagination-container', result.page, result.total_pages, 'loadEquipmentReport');
            updateExportButtons();

        } catch (error) {
            console.error('Error:', error);
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3"><i class="fas fa-exclamation-triangle"></i> Error al cargar datos</td></tr>';
        }
    };

    function renderEquipmentTable(items) {
        const tbody = document.getElementById('eq-tbody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4"><i class="fas fa-inbox fa-2x mb-2 d-block"></i><small>No se encontraron equipos con los filtros seleccionados</small></td></tr>';
            return;
        }

        tbody.innerHTML = items.map(function (item) {
            const dept = item.department || {};
            const user = item.assigned_to_user || {};
            const cat = item.category || {};

            return `<tr class="clickable-row" onclick="window.open('/help-desk/inventory/items/${item.id}', '_blank')">
                <td><strong>${escapeHtml(item.inventory_number || '')}</strong></td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml(cat.name || '')}</small></td>
                <td>${escapeHtml(item.brand || '')} ${escapeHtml(item.model || '')}</td>
                <td class="d-none d-lg-table-cell"><small class="text-muted">${escapeHtml(item.serial_number || '-')}</small></td>
                <td><small>${escapeHtml(dept.name || 'Sin asignar')}</small></td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml(user.full_name || 'Global')}</small></td>
                <td><span class="badge badge-status badge-status-${item.status}">${STATUS_LABELS[item.status] || item.status}</span></td>
            </tr>`;
        }).join('');
    }

    window.clearEquipmentFilters = function () {
        document.getElementById('eq-departments').selectedIndex = -1;
        document.getElementById('eq-categories').selectedIndex = -1;
        document.getElementById('eq-statuses').selectedIndex = -1;
        document.getElementById('eq-search').value = '';
        // Deseleccionar todos
        ['eq-departments', 'eq-categories', 'eq-statuses'].forEach(function (id) {
            const select = document.getElementById(id);
            Array.from(select.options).forEach(function (opt) { opt.selected = false; });
        });
    };

    // ==================== REPORTE DE MOVIMIENTOS ====================

    window.loadMovementsReport = async function (page) {
        mvCurrentPage = page || 1;
        const tbody = document.getElementById('mv-tbody');
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-3"><i class="fas fa-spinner fa-spin"></i> Cargando...</td></tr>';

        const filters = {
            date_from: document.getElementById('mv-date-from').value || null,
            date_to: document.getElementById('mv-date-to').value || null,
            event_types: getMultiSelectValues('mv-event-types'),
            department_ids: getMultiSelectValues('mv-departments'),
            search: document.getElementById('mv-search').value.trim(),
            page: mvCurrentPage,
            per_page: parseInt(document.getElementById('mv-per-page').value)
        };

        try {
            const response = await fetch(`${API_BASE}/reports/movements`, {
                method: 'POST',
                headers: AUTH_HEADERS(),
                body: JSON.stringify(filters)
            });

            if (!response.ok) throw new Error('Error al cargar movimientos');
            const result = await response.json();

            document.getElementById('mv-total').textContent = result.total;
            renderMovementsTable(result.events);
            renderPagination('mv-pagination', 'mv-pagination-container', result.page, result.total_pages, 'loadMovementsReport');
            updateExportButtons();

        } catch (error) {
            console.error('Error:', error);
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-3"><i class="fas fa-exclamation-triangle"></i> Error al cargar datos</td></tr>';
        }
    };

    function renderMovementsTable(events) {
        const tbody = document.getElementById('mv-tbody');

        if (!events || events.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4"><i class="fas fa-inbox fa-2x mb-2 d-block"></i><small>No se encontraron movimientos con los filtros seleccionados</small></td></tr>';
            return;
        }

        tbody.innerHTML = events.map(function (event) {
            const performedBy = event.performed_by || {};
            const timestamp = event.timestamp ? formatDateTime(event.timestamp) : '';
            const eventType = event.event_type || '';

            return `<tr>
                <td><small>${timestamp}</small></td>
                <td><span class="badge badge-event badge-event-${eventType}">${EVENT_LABELS[eventType] || eventType}</span></td>
                <td><a href="/help-desk/inventory/items/${event.item_id}" target="_blank" class="text-decoration-none"><small>${escapeHtml(String(event.item_id))}</small></a></td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml(performedBy.full_name || '')}</small></td>
                <td class="d-none d-lg-table-cell"><small class="text-muted">${escapeHtml(event.notes || '-')}</small></td>
            </tr>`;
        }).join('');
    }

    window.clearMovementsFilters = function () {
        setDatePreset('month');
        ['mv-event-types', 'mv-departments'].forEach(function (id) {
            const select = document.getElementById(id);
            Array.from(select.options).forEach(function (opt) { opt.selected = false; });
        });
        document.getElementById('mv-search').value = '';
    };

    // ==================== DATE PRESETS ====================

    window.setDatePreset = function (preset) {
        const today = new Date();
        let from = new Date();
        const to = today;

        // Highlight active preset button
        document.querySelectorAll('.date-presets .btn').forEach(function (btn) {
            btn.classList.remove('active');
        });

        switch (preset) {
            case 'today':
                from = today;
                break;
            case 'week':
                from.setDate(today.getDate() - 7);
                break;
            case 'month':
                from.setMonth(today.getMonth() - 1);
                break;
            case 'semester':
                from.setMonth(today.getMonth() - 6);
                break;
            case 'custom':
                // No cambiar fechas, solo habilitar edición
                break;
        }

        // Find and activate the clicked button
        const buttons = document.querySelectorAll('.date-presets .btn');
        buttons.forEach(function (btn) {
            if (btn.textContent.trim().toLowerCase().includes(preset === 'today' ? 'hoy' :
                preset === 'week' ? 'semana' : preset === 'month' ? 'mes' :
                    preset === 'semester' ? 'semestre' : 'personalizado')) {
                btn.classList.add('active');
            }
        });

        if (preset !== 'custom') {
            document.getElementById('mv-date-from').value = formatDate(from);
            document.getElementById('mv-date-to').value = formatDate(to);
        }
    };

    // ==================== GARANTÍAS ====================

    async function loadWarrantyReport() {
        try {
            const response = await fetch(`${API_BASE}/stats/warranty`, {
                headers: AUTH_HEADERS()
            });

            if (!response.ok) throw new Error('Error al cargar garantías');
            const result = await response.json();
            const data = result.data;

            document.getElementById('w-under-warranty').textContent = data.under_warranty;
            document.getElementById('w-expiring-30').textContent = data.expiring_30_days.count;
            document.getElementById('w-expired').textContent = data.expired;
            document.getElementById('w-no-info').textContent = data.no_warranty_info;

            // Combinar items que vencen pronto
            const allExpiring = [
                ...data.expiring_30_days.items.map(function (i) { return { ...i, _urgency: '30 días' }; }),
                ...data.expiring_60_days.items.map(function (i) { return { ...i, _urgency: '60 días' }; })
            ];

            renderWarrantyTable(allExpiring);
            updateExportButtons();

        } catch (error) {
            console.error('Error:', error);
        }
    }

    function renderWarrantyTable(items) {
        const tbody = document.getElementById('warranty-tbody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3"><small>No hay equipos con garantía por vencer</small></td></tr>';
            return;
        }

        const today = new Date();
        tbody.innerHTML = items.map(function (item) {
            let daysLeft = '';
            let daysClass = '';
            if (item.warranty_expiration) {
                const exp = new Date(item.warranty_expiration);
                const diff = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
                daysLeft = diff;
                daysClass = diff <= 15 ? 'days-danger' : diff <= 30 ? 'days-warning' : 'days-success';
            }

            return `<tr class="clickable-row" onclick="window.open('/help-desk/inventory/items/${item.id}', '_blank')">
                <td><strong>${escapeHtml(item.inventory_number || '')}</strong></td>
                <td>${escapeHtml(item.brand || '')} ${escapeHtml(item.model || '')}</td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml((item.department || {}).name || '')}</small></td>
                <td><small>${item.warranty_expiration || '-'}</small></td>
                <td><span class="${daysClass}">${daysLeft} días</span></td>
            </tr>`;
        }).join('');
    }

    // ==================== MANTENIMIENTO ====================

    async function loadMaintenanceReport() {
        try {
            const response = await fetch(`${API_BASE}/stats/maintenance`, {
                headers: AUTH_HEADERS()
            });

            if (!response.ok) throw new Error('Error al cargar mantenimiento');
            const result = await response.json();
            const data = result.data;

            document.getElementById('m-overdue').textContent = data.overdue.count;
            document.getElementById('m-upcoming').textContent = data.upcoming_30_days.count;
            document.getElementById('m-no-recent').textContent = data.no_recent_maintenance;

            const allItems = [
                ...data.overdue.items.map(function (i) { return { ...i, _maint_status: 'overdue' }; }),
                ...data.upcoming_30_days.items.map(function (i) { return { ...i, _maint_status: 'upcoming' }; })
            ];

            renderMaintenanceTable(allItems);
            updateExportButtons();

        } catch (error) {
            console.error('Error:', error);
        }
    }

    function renderMaintenanceTable(items) {
        const tbody = document.getElementById('maintenance-tbody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-3"><small>No hay equipos con mantenimiento pendiente</small></td></tr>';
            return;
        }

        tbody.innerHTML = items.map(function (item) {
            const statusBadge = item._maint_status === 'overdue'
                ? '<span class="badge bg-danger">Vencido</span>'
                : '<span class="badge bg-warning text-dark">Próximo</span>';

            return `<tr class="clickable-row" onclick="window.open('/help-desk/inventory/items/${item.id}', '_blank')">
                <td><strong>${escapeHtml(item.inventory_number || '')}</strong></td>
                <td>${escapeHtml(item.brand || '')} ${escapeHtml(item.model || '')}</td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml((item.department || {}).name || '')}</small></td>
                <td><small>${item.last_maintenance_date || '-'}</small></td>
                <td><small>${item.next_maintenance_date || '-'}</small></td>
                <td>${statusBadge}</td>
            </tr>`;
        }).join('');
    }

    // ==================== CICLO DE VIDA ====================

    async function loadLifecycleReport() {
        try {
            const response = await fetch(`${API_BASE}/stats/lifecycle`, {
                headers: AUTH_HEADERS()
            });

            if (!response.ok) throw new Error('Error al cargar ciclo de vida');
            const result = await response.json();
            const data = result.data;

            document.getElementById('lc-old').textContent = data.older_than_5_years.count;
            document.getElementById('lc-mid').textContent = data.between_3_and_5_years;
            document.getElementById('lc-new').textContent = data.less_than_1_year;

            renderLifecycleTable(data.older_than_5_years.items);
            updateExportButtons();

        } catch (error) {
            console.error('Error:', error);
        }
    }

    function renderLifecycleTable(items) {
        const tbody = document.getElementById('lifecycle-tbody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3"><small>No hay equipos con más de 5 años</small></td></tr>';
            return;
        }

        const today = new Date();
        tbody.innerHTML = items.map(function (item) {
            let years = '';
            if (item.acquisition_date) {
                const acq = new Date(item.acquisition_date);
                years = ((today - acq) / (1000 * 60 * 60 * 24 * 365.25)).toFixed(1);
            }

            return `<tr class="clickable-row" onclick="window.open('/help-desk/inventory/items/${item.id}', '_blank')">
                <td><strong>${escapeHtml(item.inventory_number || '')}</strong></td>
                <td>${escapeHtml(item.brand || '')} ${escapeHtml(item.model || '')}</td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml((item.department || {}).name || '')}</small></td>
                <td><small>${item.acquisition_date || '-'}</small></td>
                <td><span class="days-danger">${years} años</span></td>
            </tr>`;
        }).join('');
    }

    // ==================== VERIFICACIÓN ====================

    const VERIF_LABELS = {
        recent:   { text: 'Reciente',      cls: 'badge-verif-recent'   },
        outdated: { text: 'Vencido',       cls: 'badge-verif-outdated' },
        critical: { text: 'Crítico',       cls: 'badge-verif-critical' },
        never:    { text: 'Sin verificar', cls: 'badge-verif-never'    }
    };

    window.loadVerificationReport = async function () {
        const tbody = document.getElementById('vr-tbody');
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-3"><i class="fas fa-spinner fa-spin"></i> Cargando...</td></tr>';

        const deptId      = document.getElementById('vr-department') ? document.getElementById('vr-department').value : '';
        const verifStatus = document.getElementById('vr-verif-status') ? document.getElementById('vr-verif-status').value : 'all';

        const params = new URLSearchParams({ per_page: '500' });
        if (deptId)      params.set('department_id', deptId);
        if (verifStatus !== 'all') params.set('status_filter', verifStatus);

        try {
            const response = await fetch(
                `/api/help-desk/v2/inventory/verification/status?${params.toString()}`,
                { headers: AUTH_HEADERS() }
            );

            if (!response.ok) throw new Error('Error al cargar verificaciones');
            const result = await response.json();

            const stats = result.stats || {};
            document.getElementById('vr-stat-total').textContent    = stats.total    ?? 0;
            document.getElementById('vr-stat-recent').textContent   = stats.recent   ?? 0;
            document.getElementById('vr-stat-outdated').textContent = stats.outdated ?? 0;
            document.getElementById('vr-stat-critical').textContent =
                (stats.critical ?? 0) + (stats.never ?? 0);

            document.getElementById('vr-total').textContent = result.pagination
                ? result.pagination.total : (result.data || []).length;

            renderVerificationTable(result.data || []);
            updateExportButtons();

        } catch (error) {
            console.error('Error:', error);
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3"><i class="fas fa-exclamation-triangle"></i> Error al cargar datos</td></tr>';
        }
    };

    function renderVerificationTable(items) {
        const tbody = document.getElementById('vr-tbody');

        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4"><i class="fas fa-inbox fa-2x mb-2 d-block"></i><small>No hay equipos con los filtros seleccionados</small></td></tr>';
            return;
        }

        tbody.innerHTML = items.map(function (item) {
            const vs      = item.verification_status || 'never';
            const info    = VERIF_LABELS[vs] || VERIF_LABELS.never;
            const dept    = (item.department || {}).name || '—';
            const equip   = [item.brand, item.model].filter(Boolean).join(' ') || '—';
            const loc     = item.location_detail || '—';
            const lastDt  = item.last_verified_at ? formatDateTime(item.last_verified_at) : '—';
            const verifier = item.last_verified_by ? item.last_verified_by.full_name : '—';

            return `<tr class="clickable-row" onclick="window.open('/help-desk/inventory/items/${item.id}', '_blank')">
                <td><strong>${escapeHtml(item.inventory_number || '')}</strong></td>
                <td class="d-none d-md-table-cell"><small>${escapeHtml(equip)}</small></td>
                <td class="d-none d-lg-table-cell"><small>${escapeHtml(dept)}</small></td>
                <td class="d-none d-md-table-cell"><small class="text-muted">${escapeHtml(loc)}</small></td>
                <td><small>${escapeHtml(lastDt)}</small></td>
                <td class="d-none d-sm-table-cell"><small>${escapeHtml(verifier)}</small></td>
                <td><span class="badge ${info.cls}">${info.text}</span></td>
            </tr>`;
        }).join('');
    }

    // ==================== EXPORTACIÓN ====================

    window.exportReport = async function (format) {
        if (format === 'pdf') {
            // Usar impresión del navegador
            window.print();
            return;
        }

        // CSV export
        let reportType = '';
        let filters = {};

        switch (currentActiveTab) {
            case 'equipos':
                reportType = 'equipment';
                filters = {
                    department_ids: getMultiSelectValues('eq-departments'),
                    category_ids: getMultiSelectValues('eq-categories'),
                    statuses: getMultiSelectValues('eq-statuses'),
                    search: document.getElementById('eq-search').value.trim()
                };
                break;
            case 'movimientos':
                reportType = 'movements';
                filters = {
                    date_from: document.getElementById('mv-date-from').value || null,
                    date_to: document.getElementById('mv-date-to').value || null,
                    event_types: getMultiSelectValues('mv-event-types'),
                    department_ids: getMultiSelectValues('mv-departments'),
                    search: document.getElementById('mv-search').value.trim()
                };
                break;
            case 'garantias':
                reportType = 'warranty';
                break;
            case 'mantenimiento':
                reportType = 'maintenance';
                break;
            case 'ciclo-vida':
                reportType = 'lifecycle';
                break;
            case 'verificacion':
                reportType = 'verification';
                filters = {
                    department_id: document.getElementById('vr-department') ? document.getElementById('vr-department').value || null : null,
                    status_filter: document.getElementById('vr-verif-status') ? document.getElementById('vr-verif-status').value : 'all'
                };
                break;
        }

        try {
            const btn = document.getElementById('btn-export-csv');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

            const response = await fetch(`${API_BASE}/reports/export/csv`, {
                method: 'POST',
                headers: AUTH_HEADERS(),
                body: JSON.stringify({ report_type: reportType, filters: filters })
            });

            if (!response.ok) throw new Error('Error al exportar');

            // Descargar archivo
            const blob = await response.blob();
            const disposition = response.headers.get('Content-Disposition') || '';
            const filenameMatch = disposition.match(/filename=(.+)/);
            const filename = filenameMatch ? filenameMatch[1] : `reporte_${reportType}.csv`;

            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-file-csv"></i><span class="d-none d-sm-inline"> CSV</span>';

        } catch (error) {
            console.error('Error exportando:', error);
            showToast('Error al exportar el reporte', 'error');
            const btn = document.getElementById('btn-export-csv');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-file-csv"></i><span class="d-none d-sm-inline"> CSV</span>';
        }
    };

    function updateExportButtons() {
        const csvBtn = document.getElementById('btn-export-csv');
        const pdfBtn = document.getElementById('btn-export-pdf');
        // Habilitar export siempre que haya un tab activo
        csvBtn.disabled = false;
        pdfBtn.disabled = false;
    }

    // ==================== PAGINACIÓN ====================

    function renderPagination(paginationId, containerId, currentPage, totalPages, callbackName) {
        const container = document.getElementById(containerId);
        const pagination = document.getElementById(paginationId);

        if (totalPages <= 1) {
            container.style.display = 'none';
            return;
        }

        container.style.display = 'block';
        let html = '';

        // Prev
        html += `<li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault(); ${callbackName}(${currentPage - 1})">«</a>
        </li>`;

        // Page numbers (max 7 visible)
        const maxVisible = 7;
        let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
        let endPage = Math.min(totalPages, startPage + maxVisible - 1);
        if (endPage - startPage + 1 < maxVisible) {
            startPage = Math.max(1, endPage - maxVisible + 1);
        }

        if (startPage > 1) {
            html += `<li class="page-item"><a class="page-link" href="#" onclick="event.preventDefault(); ${callbackName}(1)">1</a></li>`;
            if (startPage > 2) html += '<li class="page-item disabled"><span class="page-link">...</span></li>';
        }

        for (let i = startPage; i <= endPage; i++) {
            html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="event.preventDefault(); ${callbackName}(${i})">${i}</a>
            </li>`;
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) html += '<li class="page-item disabled"><span class="page-link">...</span></li>';
            html += `<li class="page-item"><a class="page-link" href="#" onclick="event.preventDefault(); ${callbackName}(${totalPages})">${totalPages}</a></li>`;
        }

        // Next
        html += `<li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault(); ${callbackName}(${currentPage + 1})">»</a>
        </li>`;

        pagination.innerHTML = html;
    }

    // ==================== HELPERS ====================

    function getMultiSelectValues(selectId) {
        const select = document.getElementById(selectId);
        if (!select) return [];
        return Array.from(select.selectedOptions).map(function (opt) {
            // Intentar parsear como int, sino devolver string
            const val = opt.value;
            const num = parseInt(val);
            return isNaN(num) ? val : num;
        });
    }

    function formatDate(d) {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    function formatDateTime(isoStr) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        const date = formatDate(d);
        const hours = String(d.getHours()).padStart(2, '0');
        const mins = String(d.getMinutes()).padStart(2, '0');
        return `${date} ${hours}:${mins}`;
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

})();
