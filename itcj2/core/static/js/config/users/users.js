// itcj2/core/static/js/config/users/users.js
// Gestión de usuarios (lista). Módulo ConfigPage (C2): IIFE + register + destroy.
// Envelope-agnóstico: branch por response.ok; lecturas TOLERANTES de result.data
// (funciona con el envelope viejo {"status","data":{users,pagination}} y con el
// nuevo {"success","data":[...],total,page,per_page,total_pages} del flip Task 4).
(function () {
    'use strict';

    const API = '/api/core/v2';
    const FALLBACK_COLOR = '#6c757d'; // D7: fallback si app.color es NULL

    const esc = (window.ConfigUtils && window.ConfigUtils.escapeHtml) || function (s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    };

    function toast(msg, type) {
        if (window.ConfigUtils && window.ConfigUtils.showToast) {
            window.ConfigUtils.showToast(msg, type || 'success');
        } else {
            (type === 'danger' ? console.error : console.log)(msg);
        }
    }

    // Lecturas tolerantes pre/post flip (Task 4)
    function listFrom(result) {
        if (Array.isArray(result.data)) return result.data;
        return (result.data && result.data.users) || [];
    }
    function pageMeta(result) {
        if (result.total_pages != null) {
            return { page: result.page || 1, pages: result.total_pages || 1, total: result.total || 0 };
        }
        const p = (result.data && result.data.pagination) || {};
        return { page: p.page || 1, pages: p.pages || 1, total: p.total || 0 };
    }

    let S = null;

    function init() {
        S = {
            apps: [],
            appsLoaded: null,          // promise-cache de /authz/apps
            assign: { userId: null, userName: '', appKey: null, batch: null, permsCache: new Map() },
            newUserModal: null,
            assignModal: null,
        };

        // Tabla: delegación scoped (fila navegable + botón engrane)
        document.getElementById('usersTable')?.addEventListener('click', onTableClick);

        // Búsqueda y filtros
        document.getElementById('searchButton')?.addEventListener('click', () => applyFilters(true));
        document.getElementById('searchUsers')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); applyFilters(true); }
        });
        ['roleFilter', 'appFilter', 'statusFilter'].forEach(id => {
            document.getElementById(id)?.addEventListener('change', () => applyFilters(true));
        });

        // Paginación JS (delegación en el nav; los links server-rendered siguen
        // siendo <a href> de full-reload y no traen data-page)
        document.querySelector('nav[aria-label="User pagination"]')?.addEventListener('click', onPaginationClick);

        // Modal nuevo usuario (BUG B)
        const newUserEl = document.getElementById('newUserModal');
        if (newUserEl) {
            S.newUserModal = new bootstrap.Modal(newUserEl);
            // BUG B: sincronizar campos visibles/required al ABRIR el modal
            newUserEl.addEventListener('show.bs.modal', toggleUserTypeFields);
            newUserEl.querySelectorAll('input[name="userType"]').forEach(radio => {
                radio.addEventListener('change', toggleUserTypeFields);
            });
        }
        document.getElementById('saveNewUserBtn')?.addEventListener('click', saveNewUser);

        // Modal asignaciones
        const assignEl = document.getElementById('assignUserModal');
        if (assignEl) {
            S.assignModal = new bootstrap.Modal(assignEl);
            assignEl.addEventListener('click', onAssignModalClick);
            assignEl.addEventListener('hidden.bs.modal', () => {
                if (S) S.assign = { userId: null, userName: '', appKey: null, batch: null, permsCache: S.assign.permsCache };
            });
        }
        document.getElementById('assignRoleBtn')?.addEventListener('click', assignRole);
        document.getElementById('permSearchInput')?.addEventListener('input', onPermSearch);

        // Filtros desde URL (role/app/status no los aplica el server; q sí)
        const params = new URLSearchParams(window.location.search);
        const qParam = params.get('q') || params.get('search') || '';
        if (qParam && document.getElementById('searchUsers')) {
            document.getElementById('searchUsers').value = qParam;
        }
        let needsApiFilter = false;
        [['role', 'roleFilter'], ['app', 'appFilter'], ['status', 'statusFilter']].forEach(([p, id]) => {
            const el = document.getElementById(id);
            if (el && params.get(p)) { el.value = params.get(p); needsApiFilter = true; }
        });

        if (needsApiFilter) {
            applyFilters(false);
        } else {
            loadBadges(); // filas server-rendered: 1 solo GET apps-summary
        }
    }

    function destroy() {
        // Listeners viven en nodos del content root: el morph los descarta.
        S = null;
    }

    // === APPS METADATA (1 GET cacheado; trae color/icon_class post-F1b) ======
    function ensureApps() {
        if (!S.appsLoaded) {
            S.appsLoaded = fetch(`${API}/authz/apps`)
                .then(r => r.json().then(j => ({ ok: r.ok, j })))
                .then(({ ok, j }) => { S.apps = (ok && Array.isArray(j.data)) ? j.data : []; })
                .catch(() => { S.apps = []; });
        }
        return S.appsLoaded;
    }

    // === BADGES (BUG A lista: 1 request batch para TODAS las filas) ==========
    async function loadBadges() {
        // Scoped: SOLO las filas (el botón engrane también trae data-user-id)
        const rows = document.querySelectorAll('#usersTable tbody tr[data-user-id]');
        const ids = Array.from(rows).map(r => r.dataset.userId).filter(Boolean);
        if (!ids.length) return;
        try {
            await ensureApps();
            const res = await fetch(`${API}/users/apps-summary?ids=${ids.join(',')}`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'apps-summary failed');
            const summary = result.data || {};
            ids.forEach(id => renderUserBadges(id, summary[id] || summary[String(id)] || []));
        } catch (err) {
            console.error('Error loading app badges:', err);
            ids.forEach(id => {
                const c = document.getElementById(`userApps_${id}`);
                if (c) c.innerHTML = '<span class="badge text-bg-danger">Error</span>';
            });
        }
    }

    function appBadge(appKey) {
        const app = S.apps.find(a => a.key === appKey);
        const color = (app && app.color) || FALLBACK_COLOR;
        const name = app ? app.name : appKey;
        return `<span class="app-badge" style="--app-badge-color: ${esc(color)}" title="${esc(name)}">${esc(appKey)}</span>`;
    }

    function renderUserBadges(userId, appKeys) {
        const container = document.getElementById(`userApps_${userId}`);
        if (!container) return;
        if (!appKeys.length) {
            container.innerHTML = '<span class="badge bg-light text-muted">Sin apps</span>';
            return;
        }
        const sorted = [...appKeys].sort((a, b) => {
            if (a === 'itcj') return 1;
            if (b === 'itcj') return -1;
            return a.localeCompare(b);
        });
        container.innerHTML = sorted.map(appBadge).join(' ');
    }

    // === TABLA ================================================================
    function onTableClick(e) {
        const assignBtn = e.target.closest('.assign-user-btn');
        if (assignBtn) { openAssignModal(assignBtn); return; }
        if (e.target.closest('a, button, .btn-group')) return;
        const row = e.target.closest('tr.clickable-row[data-href]');
        if (row) window.ConfigPage.navigate(row.dataset.href);
    }

    function renderRow(user) {
        const sub = user.username
            ? `<small class="text-muted">@${esc(user.username)}</small>`
            : (user.control_number ? `<small class="text-muted">${esc(user.control_number)}</small>` : '');
        const roles = user.is_active
            ? ((user.roles && user.roles.length)
                ? user.roles.map(r => `<span class="badge bg-secondary badge-role">${esc(r)}</span>`).join(' ')
                : '<span class="text-muted">Sin rol</span>')
            : '<span class="text-muted">Usuario inactivo</span>';
        return `
        <tr class="user-row clickable-row" data-user-id="${user.id}" data-href="/itcj/config/users/${user.id}">
            <td class="px-4">
                <div class="d-flex align-items-center">
                    <div class="user-avatar rounded-circle d-flex align-items-center justify-content-center text-white me-3">
                        ${esc((user.full_name || '?')[0].toUpperCase())}
                    </div>
                    <div>
                        <div class="fw-bold">${esc(user.full_name)}</div>
                        ${sub}
                    </div>
                </div>
            </td>
            <td>${roles}</td>
            <td>${esc(user.email || 'N/A')}</td>
            <td>
                <span class="badge ${user.is_active ? 'bg-success' : 'bg-danger'}">
                    ${user.is_active ? 'Activo' : 'Inactivo'}
                </span>
            </td>
            <td>
                <div class="d-flex gap-1" id="userApps_${user.id}">
                    <span class="badge bg-light text-muted">Cargando...</span>
                </div>
            </td>
            <td class="text-end pe-4">
                <div class="btn-group btn-group-sm">
                    <a href="/itcj/config/users/${user.id}" class="btn btn-outline-primary" title="Ver Detalles">
                        <i class="bi bi-eye"></i>
                    </a>
                    <button class="btn btn-outline-secondary assign-user-btn"
                            data-user-id="${user.id}" data-user-name="${esc(user.full_name)}"
                            title="Asignar Apps/Roles">
                        <i class="bi bi-gear"></i>
                    </button>
                </div>
            </td>
        </tr>`;
    }

    function renderTable(users) {
        const tbody = document.querySelector('#usersTable tbody');
        if (!tbody) return;
        if (!users.length) {
            tbody.innerHTML = `
                <tr><td colspan="6" class="text-center py-5">
                    <i class="bi bi-person-lines-fill display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">No se encontraron usuarios</h5>
                    <p class="text-muted">Intenta con otros filtros de búsqueda</p>
                </td></tr>`;
            return;
        }
        tbody.innerHTML = users.map(renderRow).join('');
    }

    // Fila nueva tras crear usuario (spec §3.7: refreshUsersTable inserta la fila)
    function insertUserRow(user) {
        const tbody = document.querySelector('#usersTable tbody');
        if (!tbody || !user || !user.id) return;
        tbody.insertAdjacentHTML('afterbegin', renderRow(user));
        renderUserBadges(user.id, []); // usuario nuevo: sin apps
    }

    // === FILTROS / PAGINACIÓN =================================================
    function currentParams(pageNumber) {
        const params = new URLSearchParams();
        const qv = (document.getElementById('searchUsers')?.value || '').trim();
        const role = document.getElementById('roleFilter')?.value || '';
        const app = document.getElementById('appFilter')?.value || '';
        const status = document.getElementById('statusFilter')?.value || '';
        if (qv) params.append('q', qv);
        if (role) params.append('role', role);
        if (app) params.append('app', app);
        if (status) params.append('status', status);
        params.append('page', String(pageNumber));
        params.append('per_page', '20');
        return params;
    }

    async function applyFilters(resetToPage1, pageNumber) {
        const page = pageNumber != null
            ? pageNumber
            : (resetToPage1 ? 1 : parseInt(new URLSearchParams(window.location.search).get('page') || '1', 10));
        const params = currentParams(page);
        try {
            const res = await fetch(`${API}/users?${params.toString()}`);
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al aplicar filtros', 'danger');
                return;
            }
            renderTable(listFrom(result));
            renderPagination(pageMeta(result));
            window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`);
            loadBadges();
        } catch (err) {
            console.error('Error applying filters:', err);
            toast('Error de conexión al aplicar filtros', 'danger');
        }
    }

    function onPaginationClick(e) {
        const link = e.target.closest('a[data-page]');
        if (!link) return; // links server-rendered (href) navegan normal
        e.preventDefault();
        applyFilters(false, parseInt(link.dataset.page, 10));
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function renderPagination(meta) {
        const ul = document.querySelector('nav[aria-label="User pagination"] ul.pagination');
        if (!ul) return;
        const item = (label, page, opts) => {
            const o = opts || {};
            if (o.disabled) return `<li class="page-item disabled"><span class="page-link">${label}</span></li>`;
            if (o.active) return `<li class="page-item active"><span class="page-link">${label}</span></li>`;
            return `<li class="page-item"><a class="page-link" href="#" data-page="${page}">${label}</a></li>`;
        };
        let html = item('Anterior', meta.page - 1, { disabled: meta.page <= 1 });
        const start = Math.max(1, meta.page - 2);
        const end = Math.min(meta.pages, meta.page + 2);
        if (start > 1) {
            html += item('1', 1);
            if (start > 2) html += item('...', 0, { disabled: true });
        }
        for (let i = start; i <= end; i++) html += item(String(i), i, { active: i === meta.page });
        if (end < meta.pages) {
            if (end < meta.pages - 1) html += item('...', 0, { disabled: true });
            html += item(String(meta.pages), meta.pages);
        }
        html += item('Siguiente', meta.page + 1, { disabled: meta.page >= meta.pages });
        ul.innerHTML = html;
    }

    // === NUEVO USUARIO (BUG B) ===============================================
    function toggleUserTypeFields() {
        const staffRadio = document.getElementById('typeStaff');
        const isStaff = !!(staffRadio && staffRadio.checked);
        const studentFields = document.getElementById('studentFields');
        const staffFields = document.getElementById('staffFields');
        const controlNumberInput = document.getElementById('controlNumber');
        const usernameInput = document.getElementById('username');
        if (!studentFields || !staffFields || !controlNumberInput || !usernameInput) return;
        studentFields.classList.toggle('d-none', isStaff);
        staffFields.classList.toggle('d-none', !isStaff);
        // required SOLO en el campo visible (nunca en markup — BUG B)
        controlNumberInput.required = !isStaff;
        usernameInput.required = isStaff;
    }

    async function saveNewUser() {
        const form = document.getElementById('newUserForm');
        if (!form) return;
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        const btn = document.getElementById('saveNewUserBtn');
        const isStaff = !!document.getElementById('typeStaff')?.checked;
        const payload = {
            full_name: document.getElementById('fullName').value.trim(),
            email: document.getElementById('email').value.trim() || null,
            user_type: isStaff ? 'staff' : 'student',
            control_number: isStaff ? null : document.getElementById('controlNumber').value.trim(),
            username: isStaff ? document.getElementById('username').value.trim() : null,
            password: document.getElementById('password').value,
        };
        if (btn) btn.disabled = true;
        try {
            const res = await fetch(`${API}/users`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al crear el usuario', 'danger');
                return;
            }
            toast('Usuario creado exitosamente');
            form.reset();
            toggleUserTypeFields(); // BUG B: re-sincronizar tras reset (radio vuelve a student)
            if (S.newUserModal) S.newUserModal.hide();
            insertUserRow(result.data || {});
        } catch (err) {
            console.error('Error creating user:', err);
            toast('Error de conexión al crear el usuario', 'danger');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // === MODAL ASIGNACIONES (batch C3 + picker bajo demanda) =================
    function openAssignModal(btn) {
        S.assign.userId = btn.dataset.userId;
        S.assign.userName = btn.dataset.userName || '';
        S.assign.appKey = null;
        S.assign.batch = null;
        const nameEl = document.getElementById('assignUserName');
        if (nameEl) nameEl.textContent = S.assign.userName;
        document.getElementById('appAssignmentPanel')?.classList.add('d-none');
        document.querySelectorAll('#appsList .app-item').forEach(i => i.classList.remove('active'));
        if (S.assignModal) S.assignModal.show();
    }

    function onAssignModalClick(e) {
        const appItem = e.target.closest('.app-item');
        if (appItem) { selectApp(appItem); return; }
        const removeRole = e.target.closest('.remove-role-btn');
        if (removeRole) { removeRoleFn(removeRole.dataset.roleName); return; }
        const removePerm = e.target.closest('.remove-perm-btn');
        if (removePerm) { removePermission(removePerm.dataset.permCode); return; }
        const permItem = e.target.closest('.perm-item:not(.assigned)');
        if (permItem && permItem.dataset.permCode) { assignPermission(permItem.dataset.permCode); return; }
        const groupHeader = e.target.closest('.perm-group-header');
        if (groupHeader) {
            groupHeader.classList.toggle('collapsed');
            groupHeader.nextElementSibling?.classList.toggle('collapsed');
        }
    }

    // 1 GET batch por usuario (C3), cacheado mientras el modal esté abierto;
    // las mutaciones lo invalidan con force=true.
    async function ensureBatch(force) {
        if (S.assign.batch && !force) return S.assign.batch;
        const res = await fetch(`${API}/users/${S.assign.userId}/app-assignments`);
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || 'Error al cargar asignaciones');
        S.assign.batch = result.data || {};
        return S.assign.batch;
    }

    async function selectApp(btn) {
        document.querySelectorAll('#appsList .app-item').forEach(i => i.classList.remove('active'));
        btn.classList.add('active');
        S.assign.appKey = btn.dataset.appKey;
        const nameEl = document.getElementById('selectedAppName');
        if (nameEl) nameEl.textContent = btn.dataset.appName || S.assign.appKey;
        document.getElementById('appAssignmentPanel')?.classList.remove('d-none');
        try {
            await ensureBatch(false);
            renderAssignPanel();
            await loadPickerPerms();
        } catch (err) {
            console.error('Error loading assignments:', err);
            toast('Error al cargar las asignaciones del usuario', 'danger');
        }
    }

    function currentAppData() {
        const d = (S.assign.batch && S.assign.batch[S.assign.appKey]) || {};
        return { roles: d.roles || [], perms: d.perms || [], effective: d.effective || [] };
    }

    function renderAssignPanel() {
        const { roles, perms, effective } = currentAppData();
        const rolesEl = document.getElementById('userRolesList');
        if (rolesEl) {
            rolesEl.innerHTML = roles.length
                ? roles.map(r => `
                    <span class="badge bg-primary d-flex align-items-center gap-1">
                        ${esc(r)}
                        <button class="btn-close btn-close-white btn-sm remove-role-btn" data-role-name="${esc(r)}"></button>
                    </span>`).join('')
                : '<small class="text-muted">Sin roles asignados</small>';
        }
        const permsEl = document.getElementById('userPermsList');
        if (permsEl) {
            permsEl.innerHTML = perms.length
                ? perms.map(p => `
                    <span class="badge bg-success d-flex align-items-center gap-1">
                        ${esc(p)}
                        <button class="btn-close btn-close-white btn-sm remove-perm-btn" data-perm-code="${esc(p)}"></button>
                    </span>`).join('')
                : '<small class="text-muted">Sin permisos directos</small>';
        }
        const effEl = document.getElementById('effectivePermsList');
        if (effEl) {
            effEl.innerHTML = effective.length
                ? effective.map(p => `<span class="badge bg-info">${esc(p)}</span>`).join(' ')
                : '<small class="text-muted">Sin permisos efectivos</small>';
        }
    }

    // Picker: catálogo de permisos por app (1 GET por app, cacheado en el módulo)
    async function loadPickerPerms() {
        const appKey = S.assign.appKey;
        if (!appKey) return;
        if (!S.assign.permsCache.has(appKey)) {
            const res = await fetch(`${API}/authz/apps/${appKey}/perms`);
            const result = await res.json();
            S.assign.permsCache.set(appKey, (res.ok && result.data) || []);
        }
        renderPermPicker(S.assign.permsCache.get(appKey) || [], currentAppData().perms);
    }

    function renderPermPicker(allPerms, assignedPerms) {
        const listContainer = document.getElementById('permPickerList');
        const footer = document.getElementById('permPickerFooter');
        if (!listContainer) return;

        const assignedSet = new Set(assignedPerms);
        const groups = {};
        allPerms.forEach(perm => {
            const parts = perm.code.split('.');
            const module = parts.length >= 2 ? parts[1] : 'otros';
            (groups[module] = groups[module] || []).push(perm);
        });
        const sortedModules = Object.keys(groups).sort();
        if (!sortedModules.length) {
            listContainer.innerHTML = '<div class="perm-picker-empty"><i class="bi bi-key"></i>No hay permisos disponibles</div>';
            if (footer) footer.textContent = '';
            return;
        }
        let html = '';
        let totalAvailable = 0;
        sortedModules.forEach(module => {
            const perms = groups[module];
            const availableCount = perms.filter(p => !assignedSet.has(p.code)).length;
            totalAvailable += availableCount;
            html += `<div class="perm-group" data-module="${esc(module)}">`;
            html += `<div class="perm-group-header"><span><i class="bi bi-chevron-down chevron me-1"></i>${esc(module)}</span>`;
            html += `<span class="badge bg-secondary">${availableCount}/${perms.length}</span></div>`;
            html += `<div class="perm-group-items">`;
            perms.forEach(perm => {
                const isAssigned = assignedSet.has(perm.code);
                html += `<div class="perm-item ${isAssigned ? 'assigned' : ''}" data-perm-code="${esc(perm.code)}" data-perm-name="${esc(perm.name)}">`;
                html += `<div class="perm-item-icon">${isAssigned ? '<i class="bi bi-check-circle-fill"></i>' : '<i class="bi bi-circle"></i>'}</div>`;
                html += `<div class="perm-item-info"><div class="perm-item-name">${esc(perm.name)}</div><div class="perm-item-code">${esc(perm.code)}</div></div>`;
                if (!isAssigned) html += `<div class="perm-item-add"><i class="bi bi-plus-circle"></i></div>`;
                html += `</div>`;
            });
            html += `</div></div>`;
        });
        listContainer.innerHTML = html;
        if (footer) footer.textContent = `${totalAvailable} disponibles de ${allPerms.length} permisos`;
    }

    function onPermSearch(e) {
        const q = (e.target.value || '').toLowerCase().trim();
        const container = document.getElementById('permPickerList');
        if (!container) return;
        container.querySelectorAll('.perm-group').forEach(group => {
            let visibleCount = 0;
            group.querySelectorAll('.perm-item').forEach(item => {
                const name = (item.dataset.permName || '').toLowerCase();
                const code = (item.dataset.permCode || '').toLowerCase();
                const match = !q || name.includes(q) || code.includes(q);
                item.classList.toggle('d-none', !match);
                if (match) visibleCount++;
            });
            group.classList.toggle('d-none', visibleCount === 0);
            if (q) {
                group.querySelector('.perm-group-header')?.classList.remove('collapsed');
                group.querySelector('.perm-group-items')?.classList.remove('collapsed');
            }
        });
    }

    async function afterMutation() {
        try {
            await ensureBatch(true); // 1 GET: refresca todo el batch del usuario
            renderAssignPanel();
            await loadPickerPerms();
            // badges de la fila: apps con rol o permiso directo
            const keys = Object.keys(S.assign.batch || {}).filter(k => {
                const d = S.assign.batch[k] || {};
                return (d.roles && d.roles.length) || (d.perms && d.perms.length);
            });
            renderUserBadges(S.assign.userId, keys);
        } catch (err) {
            console.error('Error refreshing assignments:', err);
        }
    }

    async function assignRole() {
        const select = document.getElementById('roleToAssign');
        const roleName = select ? select.value : '';
        if (!roleName) { toast('Selecciona un rol', 'danger'); return; }
        try {
            const res = await fetch(`${API}/authz/apps/${S.assign.appKey}/users/${S.assign.userId}/roles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role_name: roleName }),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al asignar el rol', 'danger'); return; }
            toast('Rol asignado correctamente');
            if (select) select.value = '';
            await afterMutation();
        } catch (err) {
            console.error('Error assigning role:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function assignPermission(permCode) {
        try {
            const res = await fetch(`${API}/authz/apps/${S.assign.appKey}/users/${S.assign.userId}/perms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: permCode, allow: true }),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al asignar el permiso', 'danger'); return; }
            // spec §3.3: mostrar el warning del guardrail (scope departamental sin puesto)
            if (result.warning) toast(`Aviso: ${result.warning}`, 'warning');
            toast('Permiso asignado correctamente');
            await afterMutation();
        } catch (err) {
            console.error('Error assigning permission:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function removeRoleFn(roleName) {
        try {
            const res = await fetch(`${API}/authz/apps/${S.assign.appKey}/users/${S.assign.userId}/roles/${roleName}`, {
                method: 'DELETE',
            });
            if (!res.ok) {
                const result = await res.json();
                toast(result.error || 'Error al remover el rol', 'danger');
                return;
            }
            toast('Rol removido correctamente');
            await afterMutation();
        } catch (err) {
            console.error('Error removing role:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function removePermission(permCode) {
        try {
            const res = await fetch(`${API}/authz/apps/${S.assign.appKey}/users/${S.assign.userId}/perms/${permCode}`, {
                method: 'DELETE',
            });
            if (!res.ok) {
                const result = await res.json();
                toast(result.error || 'Error al remover el permiso', 'danger');
                return;
            }
            toast('Permiso removido correctamente');
            await afterMutation();
        } catch (err) {
            console.error('Error removing permission:', err);
            toast('Error de conexión', 'danger');
        }
    }

    window.ConfigPage.register('users', { init: init, destroy: destroy });
})();
