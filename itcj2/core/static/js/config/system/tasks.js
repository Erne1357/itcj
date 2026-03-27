'use strict';

const Tasks = (() => {
    // ── Estado interno ────────────────────────────────────────────────
    let _definitions = [];
    let _currentExecDef = null;
    let _currentPeriodicId = null;
    let _currentRunId = null;
    let _runsPage = 1;
    let _autoRefreshTimer = null;

    // ── Helpers de fetch ──────────────────────────────────────────────
    const api = async (method, path, body = null) => {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body !== null) opts.body = JSON.stringify(body);
        const res = await fetch(`/api/core/v2/tasks${path}`, opts);
        if (res.status === 204) return null;
        return res.json();
    };

    // ── Utilitarias de presentación ───────────────────────────────────
    const statusBadge = (s) => {
        const labels = { PENDING: 'Pendiente', RUNNING: 'Ejecutando', SUCCESS: 'Exitoso', FAILURE: 'Fallido', REVOKED: 'Cancelado' };
        return `<span class="badge status-badge status-${s}">${labels[s] || s}</span>`;
    };

    const timeAgo = (iso) => {
        if (!iso) return '-';
        // Si viene sin Z y parece ser local del servidor, asumiremos que es hora local
        // y el navegador intentará parsearlo como tal.
        let date = new Date(iso);
        
        // Si la fecha es válida pero está en el futuro (diferencia negativa)
        // puede ser que el servidor esté en UTC y nosotros en local pero sin la 'Z'.
        // Intentamos corregirlo asumiendo que era UTC.
        let now = Date.now();
        if (date.getTime() > now + 5000) { // Si está más de 5s en el futuro
             // Intentar parsear como UTC agregando 'Z' si no la tiene
             if (!iso.endsWith('Z')) {
                 const utcDate = new Date(iso + 'Z');
                 if (utcDate.getTime() <= now + 5000) {
                     date = utcDate;
                 }
             }
        }

        const diff = Math.floor((now - date.getTime()) / 1000);
        
        if (diff < 0) return 'hace 0s'; // Evitar mostrar negativos
        if (diff < 60) return `${diff}s`;
        if (diff < 3600) return `${Math.floor(diff / 60)}m`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
        return `${Math.floor(diff / 86400)}d`;
    };

    const duration = (secs) => {
        if (secs == null) return '-';
        return secs < 1 ? `${(secs * 1000).toFixed(0)}ms` : `${secs.toFixed(1)}s`;
    };

    const cronDesc = (expr) => {
        try { return cronstrue.toString(expr); } catch { return 'Expresión inválida'; }
    };

    // ── TAB 1: Catálogo ──────────────────────────────────────────────

    const loadDefinitions = async () => {
        const res = await api('GET', '/definitions');
        _definitions = res.data || [];
        const tbody = document.getElementById('definitionsTableBody');

        if (!_definitions.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No hay tareas registradas. Usa "Sincronizar tareas".</td></tr>';
            return;
        }

        const catIcons = { maintenance: 'bi-tools', notification: 'bi-bell', report: 'bi-file-earmark-bar-graph', document: 'bi-file-earmark-pdf', import: 'bi-upload' };

        tbody.innerHTML = _definitions.map(d => `
            <tr>
                <td>
                    <div class="fw-semibold">${d.display_name}</div>
                    <div class="text-muted small font-monospace">${d.task_name}</div>
                </td>
                <td><span class="badge bg-secondary">${d.app_name}</span></td>
                <td><i class="bi ${catIcons[d.category] || 'bi-gear'} me-1"></i>${d.category}</td>
                <td>
                    <span class="badge ${d.is_active ? 'bg-success' : 'bg-secondary'}">
                        ${d.is_active ? 'Activa' : 'Inactiva'}
                    </span>
                </td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-success me-1" onclick="Tasks.openExecuteModal('${d.task_name}')" title="Ejecutar ahora" ${!d.is_active ? 'disabled' : ''}>
                        <i class="bi bi-play-fill"></i> Ejecutar
                    </button>
                    <button class="btn btn-sm btn-outline-primary" onclick="Tasks.openPeriodicModalFromDef('${d.task_name}')" title="Agendar">
                        <i class="bi bi-calendar-plus"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    };

    const syncDefinitions = () => {
        new bootstrap.Modal(document.getElementById('confirmSyncModal')).show();
    };

    const _doSyncDefinitions = async () => {
        bootstrap.Modal.getInstance(document.getElementById('confirmSyncModal')).hide();
        try {
            const res = await api('POST', '/definitions/sync');
            showSuccess(`Sincronización completa: ${res.data.created} creadas, ${res.data.updated} actualizadas`);
            await loadDefinitions();
        } catch (e) {
            showError('Error al sincronizar tareas');
        }
    };

    // ── Modal: Ejecutar tarea ─────────────────────────────────────────

    const _TASK_SIZES = {
        'itcj2.tasks.helpdesk_tasks.export_inventory_report': 'modal-lg',
        'itcj2.tasks.notification_tasks.send_mass_notification': 'modal-lg',
    };

    const _renderCleanupForm = () => `
        <div class="form-check form-switch p-3 border rounded bg-light">
            <input class="form-check-input" type="checkbox" id="f_dry_run" style="font-size:1.1rem">
            <label class="form-check-label ms-2" for="f_dry_run">
                <strong>Modo simulación (dry run)</strong>
                <div class="text-muted small mt-1">
                    Solo calcula cuántos adjuntos se marcarían y eliminarían, sin realizar
                    cambios en la base de datos ni en el disco.
                </div>
            </label>
        </div>`;

    const _renderConvertDocForm = () => `
        <div class="mb-3">
            <label class="form-label fw-semibold">ID del Ticket <span class="text-danger">*</span></label>
            <input type="number" class="form-control" id="f_ticket_id" min="1" placeholder="ID interno del ticket">
            <div class="form-text">El ID numérico del ticket en la base de datos.</div>
        </div>
        <div class="mb-3">
            <label class="form-label fw-semibold">Tipo de documento</label>
            <select class="form-select" id="f_doc_type">
                <option value="solicitud">Solicitud de Mantenimiento</option>
                <option value="orden_trabajo">Orden de Trabajo</option>
            </select>
        </div>
        <div class="mb-0">
            <label class="form-label fw-semibold">ID de usuario a notificar</label>
            <input type="number" class="form-control" id="f_notify_user_id" min="0" value="0" placeholder="0 = sin notificación">
            <div class="form-text">El usuario recibirá una notificación con el enlace de descarga del PDF.</div>
        </div>`;

    const _renderExportReportForm = async () => {
        const container = document.getElementById('execParamsContainer');
        container.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-primary"></div> Cargando opciones...</div>';

        let depts = [], cats = [];
        try {
            const [dRes, cRes] = await Promise.all([
                fetch('/api/core/v2/departments').then(r => r.json()),
                fetch('/api/help-desk/v2/inventory/categories?active=true').then(r => r.json()),
            ]);
            depts = dRes.data || [];
            cats = cRes.data || [];
        } catch (e) {
            console.warn('[executeModal] Error cargando filtros:', e);
        }

        const deptCheckboxes = depts.length
            ? depts.map(d => `<div class="form-check">
                <input class="form-check-input f-dept-id" type="checkbox" value="${d.id}" id="fd_${d.id}">
                <label class="form-check-label small" for="fd_${d.id}">${d.name}</label>
              </div>`).join('')
            : '<span class="text-muted small">Sin departamentos</span>';

        const catCheckboxes = cats.length
            ? cats.map(c => `<div class="form-check">
                <input class="form-check-input f-cat-id" type="checkbox" value="${c.id}" id="fc_${c.id}">
                <label class="form-check-label small" for="fc_${c.id}">${c.name}</label>
              </div>`).join('')
            : '<span class="text-muted small">Sin categorías</span>';

        const STATUSES = [
            { val: 'ACTIVE',             label: 'Activo' },
            { val: 'MAINTENANCE',        label: 'En mantenimiento' },
            { val: 'DAMAGED',            label: 'Dañado' },
            { val: 'RETIRED',            label: 'Dado de baja' },
            { val: 'LOST',               label: 'Perdido' },
            { val: 'PENDING_ASSIGNMENT', label: 'Pend. asignación' },
        ];
        const statusCheckboxes = STATUSES.map(s => `
            <div class="form-check form-check-inline">
                <input class="form-check-input f-status" type="checkbox" value="${s.val}" id="fs_${s.val}" checked>
                <label class="form-check-label small" for="fs_${s.val}">${s.label}</label>
            </div>`).join('');

        container.innerHTML = `
            <div class="row g-3">
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Departamentos <span class="text-muted fw-normal">(vacío = todos)</span></label>
                    <div class="border rounded p-2" style="max-height:130px;overflow-y:auto">
                        <div class="form-check mb-1">
                            <input class="form-check-input" type="checkbox" id="fd_all"
                                onchange="document.querySelectorAll('.f-dept-id').forEach(c=>c.checked=this.checked)">
                            <label class="form-check-label text-muted small fst-italic" for="fd_all">Seleccionar todos</label>
                        </div>
                        ${deptCheckboxes}
                    </div>
                </div>
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Categorías <span class="text-muted fw-normal">(vacío = todas)</span></label>
                    <div class="border rounded p-2" style="max-height:130px;overflow-y:auto">
                        <div class="form-check mb-1">
                            <input class="form-check-input" type="checkbox" id="fc_all"
                                onchange="document.querySelectorAll('.f-cat-id').forEach(c=>c.checked=this.checked)">
                            <label class="form-check-label text-muted small fst-italic" for="fc_all">Seleccionar todas</label>
                        </div>
                        ${catCheckboxes}
                    </div>
                </div>
                <div class="col-12">
                    <label class="form-label fw-semibold small">Estados</label>
                    <div class="border rounded p-2">${statusCheckboxes}</div>
                </div>
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Marca</label>
                    <input type="text" class="form-control form-control-sm" id="f_brand" placeholder="Ej: Dell, HP, Lenovo...">
                </div>
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Búsqueda libre</label>
                    <input type="text" class="form-control form-control-sm" id="f_search" placeholder="No. inventario, serie, modelo...">
                </div>
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Formato de exportación</label>
                    <div class="mt-1">
                        <div class="form-check form-check-inline">
                            <input class="form-check-input" type="radio" name="f_format" id="fmt_xlsx" value="xlsx" checked>
                            <label class="form-check-label" for="fmt_xlsx">XLSX (Excel)</label>
                        </div>
                        <div class="form-check form-check-inline">
                            <input class="form-check-input" type="radio" name="f_format" id="fmt_csv" value="csv">
                            <label class="form-check-label" for="fmt_csv">CSV</label>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="form-check mt-3 pt-1">
                        <input class="form-check-input" type="checkbox" id="f_include_inactive">
                        <label class="form-check-label small" for="f_include_inactive">Incluir equipos inactivos</label>
                    </div>
                </div>
                <div class="col-12">
                    <label class="form-label fw-semibold small">Notificar a usuario (ID)</label>
                    <input type="number" class="form-control form-control-sm" id="f_requested_by" min="0" value="0">
                    <div class="form-text">ID del usuario que recibirá notificación con el enlace de descarga.</div>
                </div>
            </div>`;
    };

    const _renderMassNotifForm = () => `
        <div class="mb-3">
            <label class="form-label fw-semibold">Título <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="f_notif_title" placeholder="Título de la notificación">
        </div>
        <div class="mb-3">
            <label class="form-label fw-semibold">Mensaje <span class="text-danger">*</span></label>
            <textarea class="form-control" id="f_notif_message" rows="3" placeholder="Texto del cuerpo de la notificación"></textarea>
        </div>
        <div class="mb-3">
            <label class="form-label fw-semibold">Destinatarios</label>
            <select class="form-select" id="f_target_type" onchange="Tasks._onTargetTypeChange()">
                <option value="all">Todos los usuarios activos</option>
                <option value="role_global">Rol global</option>
                <option value="role_app">Rol en app específica</option>
                <option value="app">Todos en una app</option>
                <option value="users">IDs de usuarios específicos</option>
            </select>
        </div>
        <div id="f_target_extra" class="mb-3 d-none"></div>
        <div class="row g-2">
            <div class="col-md-6">
                <label class="form-label fw-semibold small">App de origen</label>
                <select class="form-select form-select-sm" id="f_notif_app">
                    <option value="core">core</option>
                    <option value="helpdesk">helpdesk</option>
                    <option value="agendatec">agendatec</option>
                    <option value="vistetec">vistetec</option>
                </select>
            </div>
            <div class="col-md-6">
                <label class="form-label fw-semibold small">Enlace (opcional)</label>
                <input type="text" class="form-control form-control-sm" id="f_notif_link" placeholder="/ruta/opcional">
            </div>
        </div>`;

    const _onTargetTypeChange = () => {
        const type = document.getElementById('f_target_type')?.value;
        const extra = document.getElementById('f_target_extra');
        if (!type || !extra) return;

        const templates = {
            role_global: `<label class="form-label small fw-semibold">Nombre del rol</label>
                <input type="text" class="form-control form-control-sm" id="f_role_name" placeholder="Ej: admin, super_admin">`,
            role_app: `<div class="row g-2">
                <div class="col">
                    <label class="form-label small fw-semibold">App</label>
                    <input type="text" class="form-control form-control-sm" id="f_role_app" placeholder="Ej: helpdesk">
                </div>
                <div class="col">
                    <label class="form-label small fw-semibold">Rol</label>
                    <input type="text" class="form-control form-control-sm" id="f_role_name" placeholder="Ej: tecnico">
                </div>
            </div>`,
            app: `<label class="form-label small fw-semibold">Clave de la app</label>
                <input type="text" class="form-control form-control-sm" id="f_app_key" placeholder="Ej: helpdesk, vistetec">`,
            users: `<label class="form-label small fw-semibold">IDs de usuarios (separados por coma)</label>
                <input type="text" class="form-control form-control-sm" id="f_user_ids" placeholder="Ej: 1, 5, 23">`,
        };

        if (templates[type]) {
            extra.innerHTML = templates[type];
            extra.classList.remove('d-none');
        } else {
            extra.innerHTML = '';
            extra.classList.add('d-none');
        }
    };

    const openExecuteModal = async (taskName) => {
        _currentExecDef = _definitions.find(d => d.task_name === taskName);
        if (!_currentExecDef) return;

        document.getElementById('execTaskName').textContent = _currentExecDef.display_name;
        document.getElementById('execTaskDesc').textContent = _currentExecDef.description || '';

        // Ajustar tamaño del modal según la tarea
        document.getElementById('executeModalDialog').className =
            'modal-dialog ' + (_TASK_SIZES[taskName] || '');

        // Mostrar spinner en el contenedor mientras carga
        const container = document.getElementById('execParamsContainer');
        container.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

        new bootstrap.Modal(document.getElementById('executeModal')).show();

        // Renderizar formulario específico de la tarea
        if (taskName === 'itcj2.tasks.helpdesk_tasks.cleanup_attachments') {
            container.innerHTML = _renderCleanupForm();
        } else if (taskName === 'itcj2.tasks.helpdesk_tasks.convert_document') {
            container.innerHTML = _renderConvertDocForm();
        } else if (taskName === 'itcj2.tasks.helpdesk_tasks.export_inventory_report') {
            await _renderExportReportForm();
        } else if (taskName === 'itcj2.tasks.notification_tasks.send_mass_notification') {
            container.innerHTML = _renderMassNotifForm();
        } else {
            // Fallback genérico para tareas sin formulario definido
            const defaults = _currentExecDef.default_args || {};
            const entries = Object.entries(defaults).filter(([k]) => k !== 'task_run_id');
            container.innerHTML = entries.length
                ? entries.map(([k, v]) => {
                    if (typeof v === 'boolean') {
                        return `<div class="form-check mb-2">
                            <input class="form-check-input" type="checkbox" id="ep_${k}" ${v ? 'checked' : ''} data-key="${k}" data-type="bool">
                            <label class="form-check-label" for="ep_${k}">${k.replace(/_/g, ' ')}</label>
                        </div>`;
                    }
                    return `<div class="mb-2">
                        <label class="form-label small fw-semibold">${k.replace(/_/g, ' ')}</label>
                        <input type="text" class="form-control form-control-sm" id="ep_${k}" value="${v ?? ''}" data-key="${k}" data-type="str">
                    </div>`;
                }).join('')
                : '<p class="text-muted small mb-0">Esta tarea no requiere parámetros adicionales.</p>';
        }
    };

    const _collectTaskKwargs = () => {
        if (!_currentExecDef) return {};
        const taskName = _currentExecDef.task_name;

        if (taskName === 'itcj2.tasks.helpdesk_tasks.cleanup_attachments') {
            return {
                dry_run: document.getElementById('f_dry_run')?.checked ?? false,
            };
        }

        if (taskName === 'itcj2.tasks.helpdesk_tasks.convert_document') {
            return {
                ticket_id: parseInt(document.getElementById('f_ticket_id')?.value || '0') || 0,
                doc_type: document.getElementById('f_doc_type')?.value || 'solicitud',
                notify_user_id: parseInt(document.getElementById('f_notify_user_id')?.value || '0') || 0,
            };
        }

        if (taskName === 'itcj2.tasks.helpdesk_tasks.export_inventory_report') {
            const deptIds = [...document.querySelectorAll('.f-dept-id:checked')].map(c => parseInt(c.value));
            const catIds  = [...document.querySelectorAll('.f-cat-id:checked')].map(c => parseInt(c.value));
            const statuses = [...document.querySelectorAll('.f-status:checked')].map(c => c.value);
            const brand   = document.getElementById('f_brand')?.value.trim() || '';
            const search  = document.getElementById('f_search')?.value.trim() || '';
            const includeInactive = document.getElementById('f_include_inactive')?.checked ?? false;
            const format  = document.querySelector('input[name="f_format"]:checked')?.value || 'xlsx';
            const requestedBy = parseInt(document.getElementById('f_requested_by')?.value || '0') || 0;

            return {
                filters: {
                    department_ids: deptIds,
                    category_ids: catIds,
                    statuses,
                    brand,
                    search,
                    include_inactive: includeInactive,
                },
                format,
                requested_by_user_id: requestedBy,
            };
        }

        if (taskName === 'itcj2.tasks.notification_tasks.send_mass_notification') {
            const targetType = document.getElementById('f_target_type')?.value || 'all';
            let target = 'all';
            if (targetType === 'role_global') {
                target = 'role:' + (document.getElementById('f_role_name')?.value.trim() || '');
            } else if (targetType === 'role_app') {
                const app  = document.getElementById('f_role_app')?.value.trim() || '';
                const role = document.getElementById('f_role_name')?.value.trim() || '';
                target = `role:${app}.${role}`;
            } else if (targetType === 'app') {
                target = 'app:' + (document.getElementById('f_app_key')?.value.trim() || '');
            } else if (targetType === 'users') {
                const raw = document.getElementById('f_user_ids')?.value || '';
                const ids = raw.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
                target = 'users:' + JSON.stringify(ids);
            }
            return {
                title:    document.getElementById('f_notif_title')?.value.trim() || '',
                message:  document.getElementById('f_notif_message')?.value.trim() || '',
                target,
                app_name: document.getElementById('f_notif_app')?.value || 'core',
                link:     document.getElementById('f_notif_link')?.value.trim() || null,
            };
        }

        // Fallback genérico: recoger campos data-key
        const kwargs = {};
        document.querySelectorAll('#execParamsContainer [data-key]').forEach(el => {
            const key = el.dataset.key;
            if (el.dataset.type === 'bool') {
                kwargs[key] = el.checked;
            } else {
                const val = el.value.trim();
                const num = Number(val);
                kwargs[key] = val === '' ? null : (!isNaN(num) ? num : val);
            }
        });
        return kwargs;
    };

    const dispatchTask = async () => {
        if (!_currentExecDef) return;

        const kwargs = _collectTaskKwargs();

        try {
            document.getElementById('execConfirmBtn').disabled = true;
            const res = await api('POST', '/runs', { task_name: _currentExecDef.task_name, kwargs });
            if (res.status === 'ok') {
                bootstrap.Modal.getInstance(document.getElementById('executeModal')).hide();
                showSuccess(`Tarea "${_currentExecDef.display_name}" enviada (run #${res.data.id})`);
                document.querySelector('[data-bs-target="#tab-history"]').click();
                await loadRuns();
            } else {
                showError(res.error || 'Error al despachar la tarea');
            }
        } finally {
            document.getElementById('execConfirmBtn').disabled = false;
        }
    };

    // ── TAB 2: Tareas Programadas ────────────────────────────────────

    const loadPeriodic = async () => {
        const res = await api('GET', '/periodic');
        const rows = res.data || [];
        const tbody = document.getElementById('periodicTableBody');

        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No hay tareas programadas.</td></tr>';
            return;
        }

        tbody.innerHTML = rows.map(pt => `
            <tr>
                <td>
                    <div class="fw-semibold">${pt.name}</div>
                    <div class="text-muted small">${pt.display_name || pt.task_name}</div>
                </td>
                <td>
                    <code>${pt.cron_expression}</code>
                    <div class="text-muted small">${cronDesc(pt.cron_expression)}</div>
                </td>
                <td>${pt.last_run_at ? timeAgo(pt.last_run_at) : '<span class="text-muted">Nunca</span>'}</td>
                <td>${pt.next_run_at ? new Date(pt.next_run_at).toLocaleString('es-MX') : '-'}</td>
                <td>
                    <div class="form-check form-switch mb-0">
                        <input class="form-check-input" type="checkbox" ${pt.is_active ? 'checked' : ''}
                            onchange="Tasks.togglePeriodic(${pt.id}, this)">
                        <label class="form-check-label small ${pt.is_active ? 'text-success' : 'text-muted'}">
                            ${pt.is_active ? 'Activa' : 'Pausada'}
                        </label>
                    </div>
                </td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-secondary me-1" onclick="Tasks.openPeriodicModal(${pt.id})" title="Editar">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="Tasks.confirmDeletePeriodic(${pt.id}, '${pt.name.replace(/'/g, "\\'")}')" title="Eliminar">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    };

    const openPeriodicModal = async (id = null) => {
        _currentPeriodicId = id;
        const title = document.getElementById('periodicModalTitle');
        title.innerHTML = id
            ? '<i class="bi bi-pencil me-2"></i>Editar tarea programada'
            : '<i class="bi bi-calendar-plus me-2"></i>Nueva tarea programada';

        // Llenar select de tareas
        const select = document.getElementById('periodicTaskName');
        select.innerHTML = '<option value="">-- Seleccionar tarea --</option>' +
            _definitions.map(d => `<option value="${d.task_name}">${d.display_name} (${d.app_name})</option>`).join('');

        if (id) {
            const res = await api('GET', '/periodic');
            const pt = (res.data || []).find(p => p.id === id);
            if (pt) {
                document.getElementById('periodicName').value = pt.name;
                document.getElementById('periodicTaskName').value = pt.task_name;
                const parts = (pt.cron_expression || '0 3 * * *').split(' ');
                document.getElementById('cronMin').value = parts[0] || '*';
                document.getElementById('cronHour').value = parts[1] || '*';
                document.getElementById('cronDay').value = parts[2] || '*';
                document.getElementById('cronMonth').value = parts[3] || '*';
                document.getElementById('cronWeekday').value = parts[4] || '*';
                document.getElementById('periodicDesc').value = pt.description || '';
                document.getElementById('periodicActive').checked = pt.is_active;
                updateCronDesc();
            }
        } else {
            document.getElementById('periodicForm').reset();
            document.getElementById('cronMin').value = '0';
            document.getElementById('cronHour').value = '3';
            document.getElementById('cronDay').value = '*';
            document.getElementById('cronMonth').value = '*';
            document.getElementById('cronWeekday').value = '*';
            updateCronDesc();
        }

        new bootstrap.Modal(document.getElementById('periodicModal')).show();
    };

    const openPeriodicModalFromDef = (taskName) => {
        openPeriodicModal().then(() => {
            document.getElementById('periodicTaskName').value = taskName;
        });
    };

    const updateCronDesc = () => {
        const expr = [
            document.getElementById('cronMin').value,
            document.getElementById('cronHour').value,
            document.getElementById('cronDay').value,
            document.getElementById('cronMonth').value,
            document.getElementById('cronWeekday').value,
        ].join(' ');
        document.getElementById('cronDescription').textContent = cronDesc(expr);
    };

    const savePeriodic = async () => {
        const cronExpr = [
            document.getElementById('cronMin').value,
            document.getElementById('cronHour').value,
            document.getElementById('cronDay').value,
            document.getElementById('cronMonth').value,
            document.getElementById('cronWeekday').value,
        ].join(' ');

        const payload = {
            name: document.getElementById('periodicName').value.trim(),
            task_name: document.getElementById('periodicTaskName').value,
            cron_expression: cronExpr,
            description: document.getElementById('periodicDesc').value.trim() || null,
            is_active: document.getElementById('periodicActive').checked,
        };

        try {
            let res;
            if (_currentPeriodicId) {
                res = await api('PATCH', `/periodic/${_currentPeriodicId}`, payload);
            } else {
                res = await api('POST', '/periodic', payload);
            }

            if (res && res.status === 'ok') {
                bootstrap.Modal.getInstance(document.getElementById('periodicModal')).hide();
                showSuccess(_currentPeriodicId ? 'Tarea programada actualizada' : 'Tarea programada creada');
                await loadPeriodic();
            } else {
                showError(res?.error || 'Error al guardar');
            }
        } catch (e) {
            showError('Error de comunicación con el servidor');
        }
    };

    const togglePeriodic = async (id, checkbox) => {
        try {
            const res = await api('PATCH', `/periodic/${id}/toggle`);
            if (res.status === 'ok') {
                const label = checkbox.nextElementSibling;
                label.textContent = res.data.is_active ? 'Activa' : 'Pausada';
                label.className = `form-check-label small ${res.data.is_active ? 'text-success' : 'text-muted'}`;
            } else {
                checkbox.checked = !checkbox.checked; // revertir
                showError('Error al cambiar estado');
            }
        } catch {
            checkbox.checked = !checkbox.checked;
            showError('Error de comunicación');
        }
    };

    const confirmDeletePeriodic = (id, name) => {
        _currentPeriodicId = id;
        document.getElementById('deletePeriodicName').textContent = name;
        new bootstrap.Modal(document.getElementById('deletePeriodicModal')).show();
    };

    const deletePeriodic = async () => {
        if (!_currentPeriodicId) return;
        try {
            await api('DELETE', `/periodic/${_currentPeriodicId}`);
            bootstrap.Modal.getInstance(document.getElementById('deletePeriodicModal')).hide();
            showSuccess('Tarea programada eliminada');
            await loadPeriodic();
        } catch {
            showError('Error al eliminar');
        }
    };

    // ── TAB 3: Historial ─────────────────────────────────────────────

    const loadRuns = async (page = 1) => {
        _runsPage = page;
        const status = document.getElementById('filterStatus').value;
        const days = document.getElementById('filterDays').value;

        const params = new URLSearchParams({ days, page, per_page: 50 });
        if (status) params.set('status', status);

        const res = await fetch(`/api/core/v2/tasks/runs?${params}`).then(r => r.json());
        const runs = res.data || [];
        const meta = res.meta || {};
        const tbody = document.getElementById('runsTableBody');

        if (!runs.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No hay ejecuciones en el período seleccionado.</td></tr>';
            stopAutoRefresh();
            return;
        }

        const hasActive = runs.some(r => r.status === 'PENDING' || r.status === 'RUNNING');

        tbody.innerHTML = runs.map(r => {
            const progressBar = r.status === 'RUNNING'
                ? `<div class="progress mt-1" style="height:4px">
                       <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary"
                            style="width:${r.progress || 10}%"></div>
                   </div>
                   <div class="small text-muted">${r.progress_message || 'Ejecutando...'}</div>`
                : '';

            const trigger = r.trigger === 'MANUAL'
                ? `<span class="small">Manual${r.triggered_by_user ? ': ' + r.triggered_by_user : ''}</span>`
                : '<span class="small text-muted">Programada</span>';

            return `<tr>
                <td>
                    <div class="fw-semibold">${r.display_name}</div>
                    ${progressBar}
                </td>
                <td>${trigger}</td>
                <td>${statusBadge(r.status)}</td>
                <td>${duration(r.duration_seconds)}</td>
                <td title="${r.created_at || ''}">${timeAgo(r.created_at)}</td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-secondary me-1" onclick="Tasks.viewRun(${r.id})">
                        Ver
                    </button>
                    ${(r.status === 'PENDING' || r.status === 'RUNNING')
                        ? `<button class="btn btn-sm btn-outline-danger" onclick="Tasks.confirmRevokeRun(${r.id})">
                               <i class="bi bi-x-circle"></i>
                           </button>`
                        : ''}
                </td>
            </tr>`;
        }).join('');

        // Paginación
        const footer = document.getElementById('runsPagination');
        if (meta.total_pages > 1) {
            footer.style.removeProperty('display');
            footer.innerHTML = `
                <small class="text-muted">${meta.total} ejecuciones</small>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-secondary" ${page <= 1 ? 'disabled' : ''} onclick="Tasks.loadRuns(${page - 1})">‹</button>
                    <button class="btn btn-outline-secondary" disabled>${page} / ${meta.total_pages}</button>
                    <button class="btn btn-outline-secondary" ${page >= meta.total_pages ? 'disabled' : ''} onclick="Tasks.loadRuns(${page + 1})">›</button>
                </div>`;
        } else {
            footer.style.display = 'none';
        }

        // Badge en pestaña
        const runningCount = runs.filter(r => r.status === 'RUNNING').length;
        const badge = document.getElementById('runningBadge');
        if (runningCount > 0) {
            badge.textContent = runningCount;
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }

        // Auto-refresh
        if (hasActive) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    };

    const startAutoRefresh = () => {
        if (_autoRefreshTimer) return;
        document.getElementById('runsAutoRefreshStatus').textContent = '↻ Actualizando cada 5s...';
        _autoRefreshTimer = setInterval(() => loadRuns(_runsPage), 5000);
    };

    const stopAutoRefresh = () => {
        if (_autoRefreshTimer) {
            clearInterval(_autoRefreshTimer);
            _autoRefreshTimer = null;
        }
        document.getElementById('runsAutoRefreshStatus').textContent = '';
    };

    const viewRun = async (id) => {
        _currentRunId = id;
        const body = document.getElementById('runDetailBody');
        const revokeBtn = document.getElementById('revokeRunBtn');
        body.innerHTML = '<div class="text-center py-3"><div class="spinner-border text-primary"></div></div>';
        revokeBtn.classList.add('d-none');
        new bootstrap.Modal(document.getElementById('runDetailModal')).show();

        const res = await api('GET', `/runs/${id}`);
        const r = res.data;

        if (r.status === 'PENDING' || r.status === 'RUNNING') {
            revokeBtn.classList.remove('d-none');
        }

        const resultJson = r.result_json
            ? JSON.stringify(r.result_json, null, 2)
            : null;

        body.innerHTML = `
            <div class="row g-3 mb-3">
                <div class="col-sm-6"><strong>Tarea:</strong><br>${r.display_name}</div>
                <div class="col-sm-6"><strong>Estado:</strong><br>${statusBadge(r.status)}</div>
                <div class="col-sm-6"><strong>Disparador:</strong><br>${r.trigger} ${r.triggered_by_user ? '— ' + r.triggered_by_user : ''}</div>
                <div class="col-sm-6"><strong>Duración:</strong><br>${duration(r.duration_seconds)}</div>
                <div class="col-sm-6"><strong>Inicio:</strong><br>${r.started_at ? new Date(r.started_at).toLocaleString('es-MX') : '-'}</div>
                <div class="col-sm-6"><strong>Fin:</strong><br>${r.finished_at ? new Date(r.finished_at).toLocaleString('es-MX') : '-'}</div>
            </div>
            ${r.status === 'RUNNING' ? `
                <div class="mb-3">
                    <div class="d-flex justify-content-between mb-1">
                        <small class="text-muted">Progreso</small>
                        <small>${r.progress}%</small>
                    </div>
                    <div class="progress">
                        <div class="progress-bar progress-bar-striped progress-bar-animated" style="width:${r.progress}%"></div>
                    </div>
                    ${r.progress_message ? `<small class="text-muted">${r.progress_message}</small>` : ''}
                </div>` : ''}
            ${r.args_json && Object.keys(r.args_json).length ? `
                <div class="mb-3">
                    <strong>Argumentos:</strong>
                    <pre class="result-json mt-1">${JSON.stringify(r.args_json, null, 2)}</pre>
                </div>` : ''}
            ${resultJson ? `
                <div class="mb-0">
                    <strong>Resultado:</strong>
                    <pre class="result-json mt-1">${resultJson}</pre>
                </div>` : ''}
        `;
    };

    const confirmRevokeRun = (id) => {
        _currentRunId = id;
        new bootstrap.Modal(document.getElementById('confirmRevokeModal')).show();
    };

    const _doRevokeRun = async () => {
        if (!_currentRunId) return;
        bootstrap.Modal.getInstance(document.getElementById('confirmRevokeModal'))?.hide();
        try {
            const res = await api('DELETE', `/runs/${_currentRunId}/revoke`);
            if (res.status === 'ok') {
                showSuccess('Tarea cancelada');
                bootstrap.Modal.getInstance(document.getElementById('runDetailModal'))?.hide();
                await loadRuns(_runsPage);
            } else {
                showError(res.error || 'No se pudo cancelar');
            }
        } catch {
            showError('Error de comunicación');
        }
    };

    // ── Init ──────────────────────────────────────────────────────────

    const init = () => {
        // Cargar catálogo al inicio
        loadDefinitions();

        // Cargar programadas al cambiar de tab
        document.querySelector('[data-bs-target="#tab-scheduled"]').addEventListener('shown.bs.tab', loadPeriodic);
        document.querySelector('[data-bs-target="#tab-history"]').addEventListener('shown.bs.tab', () => loadRuns());

        // Cron fields → descripción en tiempo real
        ['cronMin','cronHour','cronDay','cronMonth','cronWeekday'].forEach(id => {
            document.getElementById(id).addEventListener('input', updateCronDesc);
        });

        // Botones de modales
        document.getElementById('confirmSyncBtn').addEventListener('click', _doSyncDefinitions);
        document.getElementById('confirmDeletePeriodic').addEventListener('click', deletePeriodic);
        document.getElementById('revokeRunBtn').addEventListener('click', () => confirmRevokeRun(_currentRunId));
        document.getElementById('confirmRevokeBtn').addEventListener('click', _doRevokeRun);

        // Filtros de historial
        document.getElementById('filterStatus').addEventListener('change', () => loadRuns());
        document.getElementById('filterDays').addEventListener('change', () => loadRuns());

        // Detener auto-refresh al salir del tab de historial
        document.querySelector('[data-bs-target="#tab-catalog"]').addEventListener('shown.bs.tab', stopAutoRefresh);
        document.querySelector('[data-bs-target="#tab-scheduled"]').addEventListener('shown.bs.tab', stopAutoRefresh);
    };

    // API pública del módulo
    return {
        init,
        syncDefinitions,
        openExecuteModal,
        openPeriodicModal,
        openPeriodicModalFromDef,
        savePeriodic,
        togglePeriodic,
        confirmDeletePeriodic,
        dispatchTask,
        loadRuns,
        viewRun,
        confirmRevokeRun,
        _onTargetTypeChange,
    };
})();

document.addEventListener('DOMContentLoaded', Tasks.init);
