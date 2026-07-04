// itcj2/core/static/js/config/organization/position_detail.js
// Detalle de puesto. Módulo ConfigPage (C2). Envelope-agnóstico.
(function () {
    'use strict';

    const API = '/api/core/v2';

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

    let S = null;

    function init() {
        const main = document.getElementById('cfgMain');
        const positionId = main ? parseInt(main.dataset.positionId, 10) : NaN;
        if (!positionId) return;

        S = {
            positionId: positionId,
            position: null,
            currentAppKey: null,
            permissions: [],
            assignModal: null,
            appsModal: null,
            searchTimer: null,
        };
        const assignEl = document.getElementById('assignUserModal');
        if (assignEl) S.assignModal = new bootstrap.Modal(assignEl);
        const appsEl = document.getElementById('manageAppsModal');
        if (appsEl) S.appsModal = new bootstrap.Modal(appsEl);

        document.getElementById('savePositionBtn')?.addEventListener('click', savePosition);
        document.getElementById('deletePositionBtn')?.addEventListener('click', deletePosition);
        document.getElementById('assignUserBtn')?.addEventListener('click', showAssignUserModal);
        document.getElementById('manageAppsBtn')?.addEventListener('click', showManageAppsModal);
        document.getElementById('assignUserForm')?.addEventListener('submit', onAssignUser);
        document.getElementById('userSearch')?.addEventListener('input', onUserSearchInput);
        document.getElementById('allowsMultiple')?.addEventListener('change', onAllowsMultipleChange);

        // Delegación scoped al content root (no document: A→B→A recrea nodos)
        main.addEventListener('click', onMainClick);
        // El modal de apps vive en el bloque modals (dentro del morph root también)
        appsEl?.addEventListener('click', onAppsModalClick);

        loadAll();
    }

    function destroy() {
        if (S && S.searchTimer) clearTimeout(S.searchTimer);
        if (S) {
            [S.assignModal, S.appsModal].forEach(function (m) {
                if (m) { try { m.hide(); m.dispose(); } catch (e) { /* noop */ } }
            });
        }
        S = null;
    }

    // Named (no arrow inline): evita acumular listeners con identidad distinta
    // en nodos que persisten entre morphs (B5, paridad con el resto del módulo).
    function onAllowsMultipleChange(e) {
        const emailField = document.getElementById('positionEmail');
        if (e.target.checked) { emailField.value = ''; emailField.disabled = true; }
        else { emailField.disabled = false; }
    }

    function onMainClick(e) {
        if (e.target.closest('.remove-user-btn')) {
            removeUser(parseInt(e.target.closest('.remove-user-btn').dataset.userId, 10));
        }
    }

    function onAppsModalClick(e) {
        const appBtn = e.target.closest('.app-item');
        if (appBtn) { selectApp(appBtn); return; }
        if (e.target.closest('#assignRoleBtn')) { assignRole(); return; }
        const permItem = e.target.closest('.perm-item:not(.assigned)');
        if (permItem) { assignPermission(permItem.dataset.permCode); return; }
        const groupHeader = e.target.closest('.perm-group-header');
        if (groupHeader) {
            groupHeader.classList.toggle('collapsed');
            groupHeader.nextElementSibling?.classList.toggle('collapsed');
            return;
        }
        if (e.target.closest('.remove-role-btn')) {
            removeRole(e.target.closest('.remove-role-btn').dataset.roleName); return;
        }
        if (e.target.closest('.remove-perm-btn')) {
            removePermission(e.target.closest('.remove-perm-btn').dataset.permCode);
        }
    }

    // === CARGA =============================================================
    async function loadAll() {
        await loadPosition();
        renderUsers();
        renderAppsAssignments();
        renderAnchorPanel(); // [Task 6] — en Task 5 es un stub
    }

    async function loadPosition() {
        try {
            const res = await fetch(`${API}/positions/${S.positionId}`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar el puesto');
            S.position = result.data;
            renderPositionInfo();
        } catch (err) {
            console.error('Error loading position:', err);
            toast('Error al cargar el puesto', 'danger');
        }
    }

    function renderPositionInfo() {
        const pos = S.position;
        document.getElementById('positionBreadcrumb').textContent = pos.title;
        document.getElementById('positionName').textContent = pos.title;
        document.getElementById('positionCode').textContent = `código: ${pos.code}`;
        if (pos.department_id) {
            const link = document.getElementById('departmentBreadcrumb');
            link.href = `/itcj/config/departments/${pos.department_id}`;
            loadDepartmentName(pos.department_id);
        } else {
            document.getElementById('departmentBreadcrumb').textContent = 'Sin departamento';
        }
        document.getElementById('positionTitleInput').value = pos.title || '';
        document.getElementById('positionDescription').value = pos.description || '';
        document.getElementById('positionEmail').value = pos.email || '';
        document.getElementById('allowsMultiple').checked = pos.allows_multiple;
        document.getElementById('isActive').checked = pos.is_active;
        document.getElementById('displayCode').textContent = pos.code;
        document.getElementById('positionEmail').disabled = pos.allows_multiple;
    }

    async function loadDepartmentName(deptId) {
        try {
            const res = await fetch(`${API}/departments/${deptId}`);
            const result = await res.json();
            if (res.ok && result.data) {
                document.getElementById('departmentBreadcrumb').textContent = result.data.name;
            }
        } catch (err) { console.error('Error loading department name:', err); }
    }

    function renderUsers() {
        const cont = document.getElementById('usersListContainer');
        if (!cont) return;
        const users = (S.position && S.position.current_users) || [];
        if (users.length === 0) {
            cont.innerHTML = '<div class="alert alert-info mb-0"><i class="bi bi-info-circle me-2"></i>No hay usuarios asignados</div>';
            return;
        }
        cont.innerHTML = `<div class="list-group">${users.map(u => `
            <div class="list-group-item d-flex justify-content-between align-items-center">
                <div>
                    <div class="fw-bold">${esc(u.full_name)}</div>
                    <small class="text-muted">${esc(u.email || 'Sin email')}</small><br>
                    <small class="text-muted"><i class="bi bi-calendar me-1"></i>Desde: ${new Date(u.start_date).toLocaleDateString('es-ES')}</small>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger remove-user-btn" data-user-id="${u.user_id}" title="Remover usuario">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>`).join('')}</div>`;
    }

    function renderAppsAssignments() {
        const cont = document.getElementById('appsContainer');
        if (!cont) return;
        const appsData = (S.position && S.position.assignments && S.position.assignments.apps) || {};
        if (Object.keys(appsData).length === 0) {
            cont.innerHTML = '<div class="alert alert-info"><i class="bi bi-info-circle me-2"></i>Este puesto no tiene aplicaciones asignadas</div>';
            return;
        }
        cont.innerHTML = Object.entries(appsData).map(([appKey, appData]) => `
            <div class="card mb-3">
                <div class="card-header"><strong>${esc(appData.app_name)}</strong> <small class="text-muted">(${esc(appKey)})</small></div>
                <div class="card-body"><div class="row">
                    <div class="col-md-6">
                        <h6 class="text-primary small">Roles:</h6>
                        ${appData.roles.length
                            ? appData.roles.map(r => `<span class="badge bg-primary me-1">${esc(r)}</span>`).join('')
                            : '<span class="text-muted small">Sin roles</span>'}
                    </div>
                    <div class="col-md-6">
                        <h6 class="text-success small">Permisos Directos:</h6>
                        ${appData.direct_permissions.length
                            ? appData.direct_permissions.map(p => permBadge(p, 'bg-success')).join(' ')
                            : '<span class="text-muted small">Sin permisos</span>'}
                    </div>
                </div></div>
            </div>`).join('');
    }

    // El badge del permiso directo lleva su badge de scope (C8).
    function permBadge(code, cls) {
        return `<span class="badge ${cls} me-1 mb-1">${esc(code)} ${pickerScopeBadge(code)}</span>`;
    }

    async function renderAnchorPanel() {
        const panel = document.getElementById('anchorPanel');
        if (!panel || !S || !S.position) return;
        const deptId = S.position.department_id;
        if (!deptId) {
            panel.innerHTML = `
                <div class="alert alert-warning mb-0" data-cfg-anchor-warning>
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    <strong>Este puesto no tiene departamento ancla.</strong>
                    Los permisos de alcance departamental (<span class="scope-badge scope-subtree">.subtree</span>)
                    asignados a este puesto <strong>no surtirán efecto</strong>: el alcance se resuelve
                    a partir del departamento del puesto que otorga el permiso.
                </div>`;
            return;
        }
        panel.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div></div>';
        try {
            const res = await fetch(`${API}/departments/${deptId}/subtree`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar el subtree');
            const depts = (result.data && result.data.departments) || [];
            const baseDepth = depts.length ? Math.min(...depts.map(d => d.depth)) : 0;
            panel.innerHTML = `
                <p class="mb-2 small text-muted">
                    Los permisos <span class="scope-badge scope-subtree">.subtree</span> de este puesto
                    aplican sobre el departamento ancla y todo su subárbol
                    (<strong>${depts.length}</strong> departamento${depts.length === 1 ? '' : 's'} visibles):
                </p>
                <ul class="list-unstyled mb-0 anchor-subtree-list">
                    ${depts.map(d => `
                        <li class="anchor-subtree-item" data-subtree-dept-id="${d.id}">
                            <span class="anchor-subtree-indent" aria-hidden="true">${'&nbsp;&nbsp;&nbsp;'.repeat(Math.max(0, d.depth - baseDepth))}</span>
                            <i class="bi ${d.id === deptId ? 'bi-geo-alt-fill text-primary' : 'bi-building text-muted'} me-1"></i>
                            ${esc(d.name)}${d.id === deptId ? ' <span class="badge text-bg-primary">ancla</span>' : ''}
                        </li>`).join('')}
                </ul>`;
        } catch (err) {
            console.error('Error loading subtree preview:', err);
            panel.innerHTML = '<div class="alert alert-danger mb-0">Error al cargar el alcance del puesto</div>';
        }
    }

    // === GUARDAR / BORRAR ==================================================
    async function savePosition() {
        const payload = {
            title: document.getElementById('positionTitleInput').value.trim(),
            description: document.getElementById('positionDescription').value.trim() || null,
            email: document.getElementById('positionEmail').value.trim() || null,
            allows_multiple: document.getElementById('allowsMultiple').checked,
            is_active: document.getElementById('isActive').checked,
        };
        if (!payload.title) { toast('El título es obligatorio', 'danger'); return; }
        try {
            const res = await fetch(`${API}/positions/${S.positionId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al guardar cambios', 'danger'); return; }
            toast('Cambios guardados correctamente');
            await loadAll();
        } catch (err) {
            console.error('Error saving position:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function deletePosition() {
        const users = (S.position && S.position.current_users) || [];
        if (users.length > 0) {
            toast('No se puede eliminar el puesto porque tiene usuarios asignados', 'danger');
            return;
        }
        const ok = await window.AppModal.confirm({
            title: 'Eliminar puesto',
            variant: 'danger', confirmVariant: 'danger', confirmText: 'Eliminar',
            message: `¿Eliminar el puesto "${S.position.title}"? Esta acción no se puede deshacer.`,
        });
        if (!ok) return;
        try {
            const res = await fetch(`${API}/positions/${S.positionId}`, { method: 'DELETE' });
            if (!res.ok) {
                const result = await res.json();
                toast(result.error || 'Error al eliminar el puesto', 'danger');
                return;
            }
            toast('Puesto eliminado correctamente');
            setTimeout(() => {
                const deptId = S.position && S.position.department_id;
                window.ConfigPage.navigate(deptId ? `/itcj/config/departments/${deptId}` : '/itcj/config/departments');
            }, 600);
        } catch (err) {
            console.error('Error deleting position:', err);
            toast('Error de conexión', 'danger');
        }
    }

    // === USUARIOS ==========================================================
    async function showAssignUserModal() {
        await loadUsers('');
        if (S.assignModal) S.assignModal.show();
    }

    function onUserSearchInput(e) {
        if (!S) return;
        clearTimeout(S.searchTimer);
        const q = e.target.value.trim();
        S.searchTimer = setTimeout(() => loadUsers(q), 300);
    }

    async function loadUsers(q) {
        const select = document.getElementById('userSelect');
        if (!select) return;
        select.innerHTML = '<option value="">Cargando usuarios…</option>';
        try {
            const url = `${API}/users?per_page=50&only_staff=true` + (q ? `&q=${encodeURIComponent(q)}` : '');
            const res = await fetch(url);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al obtener usuarios');
            const users = Array.isArray(result.data) ? result.data : ((result.data && result.data.users) || []);
            select.innerHTML = '<option value="">Seleccionar usuario…</option>';
            users.forEach(u => {
                const opt = document.createElement('option');
                opt.value = u.id;
                const label = u.full_name || u.name || u.username || `Usuario ${u.id}`;
                opt.textContent = `${label}${u.email ? ` (${u.email})` : ''}`;
                select.appendChild(opt);
            });
            if (users.length === 0) select.innerHTML = '<option value="">No hay usuarios disponibles</option>';
        } catch (err) {
            console.error('Error loading users:', err);
            select.innerHTML = '<option value="">Error al cargar usuarios</option>';
        }
    }

    async function onAssignUser(e) {
        e.preventDefault();
        const userId = document.getElementById('userSelect').value;
        if (!userId) { toast('Debe seleccionar un usuario', 'danger'); return; }
        const payload = {
            user_id: parseInt(userId, 10),
            start_date: document.getElementById('startDate').value || null,
            notes: document.getElementById('assignmentNotes').value.trim() || null,
        };
        try {
            const res = await fetch(`${API}/positions/${S.positionId}/assign-user`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al asignar usuario', 'danger'); return; }
            toast('Usuario asignado correctamente');
            if (S.assignModal) S.assignModal.hide();
            e.target.reset();
            await loadAll();
        } catch (err) {
            console.error('Error assigning user:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function removeUser(userId) {
        const ok = await window.AppModal.confirm({
            title: 'Remover usuario',
            confirmText: 'Remover', confirmVariant: 'danger', variant: 'warning',
            message: '¿Estás seguro de remover este usuario del puesto?',
        });
        if (!ok) return;
        try {
            const res = await fetch(`${API}/positions/${S.positionId}/remove-user`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId }),
            });
            if (!res.ok) {
                const result = await res.json();
                toast(result.error || 'Error al remover usuario', 'danger');
                return;
            }
            toast('Usuario removido correctamente');
            await loadAll();
        } catch (err) {
            console.error('Error removing user:', err);
            toast('Error de conexión', 'danger');
        }
    }

    // === APPS / ROLES / PERMISOS ==========================================
    async function showManageAppsModal() {
        await Promise.all([loadAppsForModal(), loadGlobalRoles()]);
        if (S.appsModal) S.appsModal.show();
        document.getElementById('appAssignmentPanel').style.display = 'none';
    }

    async function loadGlobalRoles() {
        const select = document.getElementById('roleToAssign');
        if (!select) return;
        select.innerHTML = '<option value="">Seleccionar rol…</option>';
        try {
            const res = await fetch(`${API}/authz/roles`);
            const result = await res.json();
            if (!res.ok) return;
            (result.data || []).forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.name || r;
                opt.textContent = r.name || r;
                select.appendChild(opt);
            });
        } catch (err) { console.error('Error loading roles:', err); }
    }

    async function loadAppsForModal() {
        const cont = document.getElementById('appsListModal');
        try {
            const res = await fetch(`${API}/authz/apps`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar aplicaciones');
            const apps = result.data || [];
            if (apps.length === 0) {
                cont.innerHTML = '<div class="text-muted text-center py-3">No hay aplicaciones</div>';
                return;
            }
            cont.innerHTML = apps.map(app => `
                <button type="button" class="list-group-item list-group-item-action app-item d-flex align-items-center"
                        data-app-key="${esc(app.key)}" data-app-name="${esc(app.name)}">
                    <i class="bi bi-app me-2 text-primary"></i>
                    <div><div class="fw-bold">${esc(app.name)}</div><small class="text-muted">${esc(app.key)}</small></div>
                </button>`).join('');
        } catch (err) {
            console.error('Error loading apps:', err);
            cont.innerHTML = '<div class="alert alert-danger">Error al cargar aplicaciones</div>';
        }
    }

    async function selectApp(btn) {
        document.querySelectorAll('.app-item').forEach(i => i.classList.remove('active'));
        btn.classList.add('active');
        S.currentAppKey = btn.dataset.appKey;
        document.getElementById('selectedAppName').textContent = btn.dataset.appName;
        document.getElementById('appAssignmentPanel').style.display = 'block';
        await loadAppAssignments();
    }

    async function loadAppAssignments() {
        if (!S.currentAppKey) return;
        try {
            const [rolesRes, permsRes, effRes] = await Promise.all([
                fetch(`${API}/positions/${S.positionId}/apps/${S.currentAppKey}/roles`),
                fetch(`${API}/positions/${S.positionId}/apps/${S.currentAppKey}/perms`),
                fetch(`${API}/positions/${S.positionId}/effective-perms/${S.currentAppKey}`),
            ]);
            const [roles, perms, eff] = await Promise.all([
                rolesRes.ok ? rolesRes.json() : { data: [] },
                permsRes.ok ? permsRes.json() : { data: [] },
                effRes.ok ? effRes.json() : { data: [] },
            ]);
            renderRoles(roles.data || []);
            renderPermissions(perms.data || []);
            renderEffectivePermissions(eff.data || []);
            await loadAppPermissions(perms.data || []);
        } catch (err) { console.error('Error loading app assignments:', err); }
    }

    async function loadAppPermissions(assignedPerms) {
        try {
            const res = await fetch(`${API}/authz/apps/${S.currentAppKey}/perms`);
            if (!res.ok) return;
            const result = await res.json();
            S.permissions = result.data || [];
            populatePermissionPicker(assignedPerms);
        } catch (err) { console.error('Error loading app permissions:', err); }
    }

    function populatePermissionPicker(assignedPerms) {
        const listContainer = document.getElementById('permPickerList');
        const footer = document.getElementById('permPickerFooter');
        const searchInput = document.getElementById('permSearchInput');
        if (!listContainer) return;

        const groups = {};
        const assignedSet = new Set(assignedPerms || []);
        S.permissions.forEach(perm => {
            const parts = perm.code.split('.');
            const module = parts.length >= 2 ? parts[1] : 'otros';
            (groups[module] = groups[module] || []).push(perm);
        });
        const sortedModules = Object.keys(groups).sort();
        if (sortedModules.length === 0) {
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
            html += '<div class="perm-group-items">';
            perms.forEach(perm => {
                const isAssigned = assignedSet.has(perm.code);
                html += `<div class="perm-item ${isAssigned ? 'assigned' : ''}" data-perm-code="${esc(perm.code)}" data-perm-name="${esc(perm.name)}">`;
                html += `<div class="perm-item-icon">${isAssigned ? '<i class="bi bi-check-circle-fill"></i>' : '<i class="bi bi-circle"></i>'}</div>`;
                html += `<div class="perm-item-info">`;
                html += `<div class="perm-item-name">${esc(perm.name)} ${pickerScopeBadge(perm.code)}</div>`;
                html += `<div class="perm-item-code">${esc(perm.code)}</div></div>`;
                if (!isAssigned) html += '<div class="perm-item-add"><i class="bi bi-plus-circle"></i></div>';
                html += '</div>';
            });
            html += '</div></div>';
        });
        listContainer.innerHTML = html;
        if (footer) footer.textContent = `${totalAvailable} disponibles de ${S.permissions.length} permisos`;
        if (searchInput) {
            searchInput.value = '';
            searchInput.oninput = () => filterPermPicker(searchInput.value, listContainer);
        }
    }

    // === SCOPE-AWARE (C8) ==================================================
    function scopeOf(code) {
        if (code.endsWith('.subtree')) return 'subtree';
        if (code.endsWith('.own_dept') || code.endsWith('.department')) return 'dept';
        if (code.endsWith('.own')) return 'own';
        if (code.endsWith('.all')) return 'all';
        return null;
    }

    const SCOPE_LABEL = {
        subtree: 'subtree — depto. + sub-departamentos',
        dept: 'departamento propio',
        own: 'solo lo propio',
        all: 'todo (global)',
    };

    function pickerScopeBadge(code) {
        const scope = scopeOf(code);
        if (!scope) return '';
        return `<span class="scope-badge scope-${scope}" title="${esc(SCOPE_LABEL[scope])}">.${esc(scope === 'dept' ? 'dept' : scope)}</span>`;
    }

    function filterPermPicker(query, container) {
        const q = query.toLowerCase().trim();
        container.querySelectorAll('.perm-group').forEach(group => {
            let visibleCount = 0;
            group.querySelectorAll('.perm-item').forEach(item => {
                const name = (item.dataset.permName || '').toLowerCase();
                const code = (item.dataset.permCode || '').toLowerCase();
                const match = !q || name.includes(q) || code.includes(q);
                item.style.display = match ? '' : 'none';
                if (match) visibleCount++;
            });
            group.style.display = visibleCount > 0 ? '' : 'none';
            if (q) {
                group.querySelector('.perm-group-header')?.classList.remove('collapsed');
                group.querySelector('.perm-group-items')?.classList.remove('collapsed');
            }
        });
    }

    function renderRoles(roles) {
        const cont = document.getElementById('rolesList');
        if (!cont) return;
        cont.innerHTML = roles.length
            ? roles.map(role => `
                <span class="badge bg-primary d-flex align-items-center gap-1">${esc(role)}
                    <button type="button" class="btn-close btn-close-white btn-sm remove-role-btn" data-role-name="${esc(role)}"></button>
                </span>`).join('')
            : '<small class="text-muted">Sin roles</small>';
    }

    function renderPermissions(perms) {
        const cont = document.getElementById('permsList');
        if (!cont) return;
        cont.innerHTML = perms.length
            ? perms.map(perm => `
                <span class="badge bg-success d-flex align-items-center gap-1">${esc(perm)} ${pickerScopeBadge(perm)}
                    <button type="button" class="btn-close btn-close-white btn-sm remove-perm-btn" data-perm-code="${esc(perm)}"></button>
                </span>`).join('')
            : '<small class="text-muted">Sin permisos directos</small>';
    }

    function renderEffectivePermissions(perms) {
        const cont = document.getElementById('effectivePermsList');
        if (!cont) return;
        cont.innerHTML = perms.length
            ? perms.map(perm => `<span class="badge bg-info">${esc(perm)} ${pickerScopeBadge(perm)}</span>`).join(' ')
            : '<small class="text-muted">Sin permisos efectivos</small>';
    }

    async function assignRole() {
        const select = document.getElementById('roleToAssign');
        const roleName = select ? select.value : '';
        if (!roleName) { toast('Selecciona un rol', 'danger'); return; }
        try {
            const res = await fetch(`${API}/positions/${S.positionId}/apps/${S.currentAppKey}/roles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role_name: roleName }),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al asignar rol', 'danger'); return; }
            toast('Rol asignado correctamente');
            select.value = '';
            await Promise.all([loadAppAssignments(), refreshPosition()]);
        } catch (err) {
            console.error('Error assigning role:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function assignPermission(permCode) {
        if (!permCode) return;
        try {
            const res = await fetch(`${API}/positions/${S.positionId}/apps/${S.currentAppKey}/perms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: permCode, allow: true }),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al asignar permiso', 'danger'); return; }
            toast('Permiso asignado correctamente');
            notifyScopeWarning(result); // [Task 6]
            await Promise.all([loadAppAssignments(), refreshPosition()]);
        } catch (err) {
            console.error('Error assigning permission:', err);
            toast('Error de conexión', 'danger');
        }
    }

    // Lee el warning del guardrail (fail-closed). El endpoint de puesto
    // devuelve 'scope_departamental_sin_departamento' (positions.py); se acepta
    // también 'scope_departamental_sin_puesto' (espejo del flujo user-direct).
    function notifyScopeWarning(result) {
        const w = result && result.warning;
        if (w === 'scope_departamental_sin_departamento' || w === 'scope_departamental_sin_puesto') {
            toast('Aviso: el puesto no tiene departamento ancla; este permiso departamental no surtirá efecto.', 'warning');
        }
    }

    async function removeRole(roleName) {
        try {
            const res = await fetch(`${API}/positions/${S.positionId}/apps/${S.currentAppKey}/roles/${roleName}`, { method: 'DELETE' });
            if (!res.ok) {
                const result = await res.json();
                toast(result.error || 'Error al remover rol', 'danger');
                return;
            }
            toast('Rol removido correctamente');
            await Promise.all([loadAppAssignments(), refreshPosition()]);
        } catch (err) {
            console.error('Error removing role:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function removePermission(permCode) {
        try {
            const res = await fetch(`${API}/positions/${S.positionId}/apps/${S.currentAppKey}/perms/${permCode}`, { method: 'DELETE' });
            if (!res.ok) {
                const result = await res.json();
                toast(result.error || 'Error al remover permiso', 'danger');
                return;
            }
            toast('Permiso removido correctamente');
            await Promise.all([loadAppAssignments(), refreshPosition()]);
        } catch (err) {
            console.error('Error removing permission:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function refreshPosition() {
        await loadPosition();
        renderAppsAssignments();
        renderAnchorPanel(); // [Task 6]
    }

    window.ConfigPage.register('position_detail', { init: init, destroy: destroy });
})();
