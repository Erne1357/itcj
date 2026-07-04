// itcj2/core/static/js/config/users/user_detail.js
// Detalle de usuario. Módulo ConfigPage (C2): IIFE + register + destroy.
// BUG A resuelto: carga inicial = 1 GET (positions); pestaña apps = 1 GET batch
// (app-assignments) cacheado con refresh manual; permisos por puesto bajo demanda.
// Envelope-agnóstico: branch por response.ok; lee result.data / result.error / result.warning.
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
        const userId = main ? parseInt(main.dataset.userId, 10) : NaN;
        if (!userId) return;

        S = {
            userId: userId,
            batch: null,               // cache de app-assignments (BUG A)
            batchLoading: null,
            posPermsCache: new Map(),  // positionId -> apps dict
            permsCache: new Map(),     // appKey -> catálogo de permisos (picker)
            currentAppKey: null,
            manageModal: null, editModal: null,
        };

        const manageEl = document.getElementById('manageAssignmentsModal');
        if (manageEl) {
            S.manageModal = new bootstrap.Modal(manageEl);
            manageEl.addEventListener('click', onManageModalClick);
        }
        const editEl = document.getElementById('editUserModal');
        if (editEl) S.editModal = new bootstrap.Modal(editEl);

        document.getElementById('btnEditUser')?.addEventListener('click', () => S.editModal && S.editModal.show());
        document.getElementById('btnToggleStatus')?.addEventListener('click', onToggleStatus);
        document.getElementById('btnResetPassword')?.addEventListener('click', onResetPassword);
        document.getElementById('editUserForm')?.addEventListener('submit', (e) => { e.preventDefault(); saveUserInfo(); });
        document.getElementById('modalAssignRole')?.addEventListener('click', assignRole);
        document.getElementById('modalPermSearchInput')?.addEventListener('input', onPermSearch);
        document.getElementById('refreshAssignmentsBtn')?.addEventListener('click', () => loadAssignments(true));

        // Lazy tabs: la pestaña de apps carga en su PRIMER show (BUG A)
        document.querySelectorAll('#userDetailTabs button[data-bs-toggle="tab"]').forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                if (e.target.getAttribute('data-bs-target') === '#apps-pane') loadAssignments(false);
            });
        });

        document.getElementById('userAppsContainer')?.addEventListener('click', onAppsClick);
        document.getElementById('userPositionsContainer')?.addEventListener('click', onPositionsClick);

        loadPositions(); // única carga inicial: 1 GET
    }

    function destroy() {
        S = null;
    }

    // === PUESTOS (1 GET; permisos por puesto bajo demanda) ===================
    async function loadPositions() {
        const container = document.getElementById('userPositionsContainer');
        if (!container) return;
        try {
            const res = await fetch(`${API}/positions/users/${S.userId}/positions`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar puestos');
            renderPositions(result.data || []);
        } catch (err) {
            console.error('Error loading user positions:', err);
            container.innerHTML = `
                <div class="col-12"><div class="text-center py-5">
                    <i class="bi bi-exclamation-triangle display-1 text-danger"></i>
                    <h5 class="text-danger mt-3">Error al cargar puestos</h5>
                    <p class="text-muted">No se pudieron cargar los puestos organizacionales</p>
                </div></div>`;
        }
    }

    function renderPositions(positions) {
        const container = document.getElementById('userPositionsContainer');
        if (!container) return;
        if (!positions.length) {
            container.innerHTML = `
                <div class="col-12"><div class="text-center py-5">
                    <i class="bi bi-briefcase display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">Sin puestos asignados</h5>
                    <p class="text-muted">Este usuario no tiene puestos organizacionales activos</p>
                </div></div>`;
            return;
        }
        container.innerHTML = positions.map(p => `
            <div class="col-12 col-md-6 col-lg-4">
                <div class="card h-100 shadow-sm position-card">
                    <div class="card-header bg-primary text-white">
                        <div class="d-flex align-items-center">
                            <i class="bi bi-briefcase me-2"></i>
                            <div>
                                <h6 class="mb-0">${esc(p.title)}</h6>
                                <small class="opacity-75">${esc(p.code)}</small>
                            </div>
                        </div>
                    </div>
                    <div class="card-body">
                        ${p.department ? `
                        <div class="mb-3">
                            <h6 class="text-muted mb-2"><i class="bi bi-building me-1"></i>Departamento</h6>
                            <div class="d-flex align-items-center">
                                <i class="bi ${esc(p.department.icon_class || 'bi-building')} me-2 text-primary"></i>
                                <div>
                                    <div class="fw-bold">${esc(p.department.name)}</div>
                                    <small class="text-muted">${esc(p.department.code)}</small>
                                </div>
                            </div>
                        </div>` : ''}
                        <div class="mb-3">
                            <h6 class="text-success mb-2"><i class="bi bi-calendar-check me-1"></i>Información</h6>
                            <div class="small text-muted">
                                <div><strong>Inicio:</strong> ${esc(p.start_date ? new Date(p.start_date).toLocaleDateString('es-ES') : '—')}</div>
                                ${p.notes ? `<div><strong>Notas:</strong> ${esc(p.notes)}</div>` : ''}
                            </div>
                        </div>
                        <div>
                            <h6 class="text-info mb-2"><i class="bi bi-shield-check me-1"></i>Permisos por Puesto</h6>
                            <div id="positionPerms_${p.position_id}" class="d-flex flex-wrap gap-1">
                                <button type="button" class="btn btn-sm btn-outline-info"
                                        data-pos-action="load-perms" data-position-id="${p.position_id}">
                                    <i class="bi bi-eye me-1"></i>Ver permisos
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>`).join('');
    }

    function onPositionsClick(e) {
        const btn = e.target.closest('[data-pos-action="load-perms"]');
        if (!btn) return;
        loadPositionPerms(parseInt(btn.dataset.positionId, 10));
    }

    async function loadPositionPerms(positionId) {
        const container = document.getElementById(`positionPerms_${positionId}`);
        if (!container || !positionId) return;
        if (S.posPermsCache.has(positionId)) {
            renderPositionPerms(positionId, S.posPermsCache.get(positionId));
            return;
        }
        container.innerHTML = '<span class="badge bg-light text-muted">Cargando...</span>';
        try {
            const res = await fetch(`${API}/positions/${positionId}/assignments`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar permisos del puesto');
            const apps = (result.data && result.data.apps) || {};
            S.posPermsCache.set(positionId, apps);
            renderPositionPerms(positionId, apps);
        } catch (err) {
            console.error(`Error loading permissions for position ${positionId}:`, err);
            container.innerHTML = '<span class="badge text-bg-danger">Error al cargar</span>';
        }
    }

    function renderPositionPerms(positionId, apps) {
        const container = document.getElementById(`positionPerms_${positionId}`);
        if (!container) return;
        const badges = [];
        Object.entries(apps || {}).forEach(([appKey, appData]) => {
            (appData.roles || []).forEach(role => {
                badges.push(`<span class="badge bg-primary" title="${esc(appData.app_name || appKey)} - Rol">${esc(appKey)}: ${esc(role)}</span>`);
            });
            (appData.direct_permissions || []).forEach(perm => {
                badges.push(`<span class="badge bg-success" title="${esc(appData.app_name || appKey)} - Permiso directo">${esc(appKey)}: ${esc(perm)}</span>`);
            });
        });
        container.innerHTML = badges.length ? badges.join(' ') : '<small class="text-muted">Sin permisos asignados</small>';
    }

    // === ASIGNACIONES POR APP (1 GET batch, cache + refresh — BUG A) =========
    function appCards() {
        // Scoped: SOLO los cards (el botón "Gestionar" también trae data-app-key)
        return document.querySelectorAll('#userAppsContainer .app-card[data-app-key]');
    }

    function loadAssignments(force) {
        if (!S) return Promise.resolve();
        if (S.batch && !force) return Promise.resolve(S.batch); // cache: re-show NO refetchea
        if (S.batchLoading) return S.batchLoading;

        appCards().forEach(card => {
            const key = card.dataset.appKey;
            ['roles', 'perms', 'effective'].forEach(kind => {
                const el = document.getElementById(`${kind}_${key}`);
                if (el) el.innerHTML = '<span class="badge bg-light text-muted">Cargando...</span>';
            });
        });

        S.batchLoading = (async () => {
            try {
                const res = await fetch(`${API}/users/${S.userId}/app-assignments`);
                const result = await res.json();
                if (!res.ok) throw new Error(result.error || 'Error al cargar asignaciones');
                S.batch = result.data || {};
                appCards().forEach(card => renderCard(card.dataset.appKey));
            } catch (err) {
                console.error('Error loading app assignments:', err);
                appCards().forEach(card => {
                    const key = card.dataset.appKey;
                    ['roles', 'perms', 'effective'].forEach(kind => {
                        const el = document.getElementById(`${kind}_${key}`);
                        if (el) el.innerHTML = '<span class="badge text-bg-danger">Error</span>';
                    });
                });
            } finally {
                if (S) S.batchLoading = null;
            }
        })();
        return S.batchLoading;
    }

    function appData(appKey) {
        const d = (S.batch && S.batch[appKey]) || {};
        return { roles: d.roles || [], perms: d.perms || [], effective: d.effective || [] };
    }

    function renderCard(appKey) {
        const { roles, perms, effective } = appData(appKey);
        const rolesEl = document.getElementById(`roles_${appKey}`);
        if (rolesEl) {
            rolesEl.innerHTML = roles.length
                ? roles.map(r => `<span class="badge bg-primary">${esc(r)}</span>`).join(' ')
                : '<small class="text-muted">Sin roles asignados</small>';
        }
        const permsEl = document.getElementById(`perms_${appKey}`);
        if (permsEl) {
            permsEl.innerHTML = perms.length
                ? perms.map(p => `<span class="badge bg-success permission-badge">${esc(p)}</span>`).join(' ')
                : '<small class="text-muted">Sin permisos directos</small>';
        }
        const effEl = document.getElementById(`effective_${appKey}`);
        if (effEl) {
            effEl.innerHTML = effective.length
                ? effective.map(p => `<span class="badge bg-info permission-badge">${esc(p)}</span>`).join(' ')
                : '<small class="text-muted">Sin permisos efectivos</small>';
        }
    }

    function onAppsClick(e) {
        const btn = e.target.closest('.manage-app-btn');
        if (!btn) return;
        openManageModal(btn.dataset.appKey, btn.dataset.appName);
    }

    // === MODAL GESTIONAR (alimentado por el batch) ===========================
    async function openManageModal(appKey, appName) {
        S.currentAppKey = appKey;
        const nameEl = document.getElementById('modalAppName');
        if (nameEl) nameEl.textContent = appName || appKey;
        if (S.manageModal) S.manageModal.show();
        try {
            await loadAssignments(false);
            renderModalLists();
            await loadPickerPerms();
        } catch (err) {
            console.error('Error loading manage modal:', err);
            toast('Error al cargar las asignaciones', 'danger');
        }
    }

    function renderModalLists() {
        const { roles, perms, effective } = appData(S.currentAppKey);
        const rolesEl = document.getElementById('modalUserRoles');
        if (rolesEl) {
            rolesEl.innerHTML = roles.length
                ? roles.map(r => `
                    <span class="badge bg-primary d-flex align-items-center gap-1">
                        ${esc(r)}
                        <button class="btn-close btn-close-white btn-sm remove-role-btn" data-role-name="${esc(r)}"></button>
                    </span>`).join('')
                : '<small class="text-muted">Sin roles asignados</small>';
        }
        const permsEl = document.getElementById('modalUserPerms');
        if (permsEl) {
            permsEl.innerHTML = perms.length
                ? perms.map(p => `
                    <span class="badge bg-success d-flex align-items-center gap-1">
                        ${esc(p)}
                        <button class="btn-close btn-close-white btn-sm remove-perm-btn" data-perm-code="${esc(p)}"></button>
                    </span>`).join('')
                : '<small class="text-muted">Sin permisos directos</small>';
        }
        const effEl = document.getElementById('modalEffectivePerms');
        if (effEl) {
            effEl.innerHTML = effective.length
                ? effective.map(p => `<span class="badge bg-info permission-badge">${esc(p)}</span>`).join(' ')
                : '<small class="text-muted">Sin permisos efectivos</small>';
        }
    }

    async function loadPickerPerms() {
        const appKey = S.currentAppKey;
        if (!appKey) return;
        if (!S.permsCache.has(appKey)) {
            const res = await fetch(`${API}/authz/apps/${appKey}/perms`);
            const result = await res.json();
            S.permsCache.set(appKey, (res.ok && result.data) || []);
        }
        renderPermPicker(S.permsCache.get(appKey) || [], appData(appKey).perms);
    }

    function renderPermPicker(allPerms, assignedPerms) {
        const listContainer = document.getElementById('modalPermPickerList');
        const footer = document.getElementById('modalPermPickerFooter');
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
        const container = document.getElementById('modalPermPickerList');
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

    function onManageModalClick(e) {
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

    async function afterMutation() {
        try {
            await loadAssignments(true); // 1 GET: refresca batch + cards
            renderModalLists();
            await loadPickerPerms();
        } catch (err) {
            console.error('Error refreshing assignments:', err);
        }
    }

    async function assignRole() {
        const select = document.getElementById('modalRoleToAssign');
        const roleName = select ? select.value : '';
        if (!roleName) { toast('Selecciona un rol', 'danger'); return; }
        try {
            const res = await fetch(`${API}/authz/apps/${S.currentAppKey}/users/${S.userId}/roles`, {
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
            const res = await fetch(`${API}/authz/apps/${S.currentAppKey}/users/${S.userId}/perms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: permCode, allow: true }),
            });
            const result = await res.json();
            if (!res.ok) { toast(result.error || 'Error al asignar el permiso', 'danger'); return; }
            // spec §3.3: guardrail scope departamental sin puesto que lo ancle (authz.py).
            if (result.warning === 'scope_departamental_sin_puesto') {
                toast('Aviso: el usuario no tiene un puesto que ancle este permiso departamental; no surtirá efecto.', 'warning');
            }
            toast('Permiso asignado correctamente');
            await afterMutation();
        } catch (err) {
            console.error('Error assigning permission:', err);
            toast('Error de conexión', 'danger');
        }
    }

    async function removeRoleFn(roleName) {
        try {
            const res = await fetch(`${API}/authz/apps/${S.currentAppKey}/users/${S.userId}/roles/${roleName}`, {
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
            const res = await fetch(`${API}/authz/apps/${S.currentAppKey}/users/${S.userId}/perms/${permCode}`, {
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

    // === ACCIONES DE USUARIO (reset / toggle / editar) =======================
    // D6: sin gates sobre códigos de error — result.error ya es string humano (F1a).
    async function onResetPassword() {
        const ok = await AppModal.confirm({
            title: 'Confirmar Reset de Contrasena',
            message: 'Esta seguro de resetear la contrasena de este usuario? '
                + 'La contrasena se cambiara a "tecno#2K" y el usuario sera obligado '
                + 'a cambiarla en su proximo inicio de sesion.',
            confirmText: 'Si, Resetear',
            confirmVariant: 'warning',
        });
        if (!ok) return;

        const btn = document.getElementById('btnResetPassword');
        try {
            if (btn) btn.disabled = true;
            const res = await fetch(`${API}/users/${S.userId}/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al resetear la contraseña', 'danger');
                return;
            }
            toast('Contraseña reseteada exitosamente. Nueva contraseña: "tecno#2K"');
        } catch (err) {
            console.error('Error resetting password:', err);
            toast('Error de conexión', 'danger');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function onToggleStatus(e) {
        const isActive = e.currentTarget.dataset.active === 'true';
        const userName = e.currentTarget.dataset.userName || '';
        const ok = await AppModal.confirm({
            title: isActive ? 'Confirmar Desactivacion' : 'Confirmar Activacion',
            message: isActive
                ? `Esta seguro de desactivar la cuenta de este usuario? El usuario no podra iniciar sesion `
                  + `mientras su cuenta este desactivada. Esta accion se puede revertir en cualquier momento. Usuario: ${userName}`
                : `Esta seguro de activar la cuenta de este usuario? El usuario podra iniciar sesion nuevamente `
                  + `con sus credenciales existentes. Usuario: ${userName}`,
            confirmText: isActive ? 'Si, Desactivar' : 'Si, Activar',
            confirmVariant: isActive ? 'danger' : 'success',
        });
        if (!ok) return;

        const btn = document.getElementById('btnToggleStatus');
        try {
            if (btn) btn.disabled = true;
            const res = await fetch(`${API}/users/${S.userId}/toggle-status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al cambiar el estado de la cuenta', 'danger');
                return;
            }
            const nowActive = result.data && result.data.is_active;
            toast(`Cuenta ${nowActive ? 'activada' : 'desactivada'} exitosamente`);
            setTimeout(() => window.location.reload(), 800);
        } catch (err) {
            console.error('Error toggling user status:', err);
            toast('Error de conexión', 'danger');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function saveUserInfo() {
        const btn = document.getElementById('saveEditUserBtn');
        const original = btn ? btn.innerHTML : '';
        const data = {};
        const map = [['editFirstName', 'first_name'], ['editLastName', 'last_name'],
                     ['editMiddleName', 'middle_name'], ['editEmail', 'email'],
                     ['editUsername', 'username'], ['editControlNumber', 'control_number']];
        map.forEach(([id, key]) => {
            const el = document.getElementById(id);
            if (el) data[key] = el.value.trim();
        });
        try {
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Guardando...';
            }
            const res = await fetch(`${API}/users/${S.userId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(data),
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al guardar los cambios', 'danger');
                return;
            }
            if (S.editModal) S.editModal.hide();
            toast('Información actualizada exitosamente');
            setTimeout(() => window.location.reload(), 800);
        } catch (err) {
            console.error('Error saving user info:', err);
            toast('Error de conexión', 'danger');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = original; }
        }
    }

    window.ConfigPage.register('user_detail', { init: init, destroy: destroy });
})();
