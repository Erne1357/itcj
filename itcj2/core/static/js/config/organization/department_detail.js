// itcj2/core/static/js/config/organization/department_detail.js
// Detalle de departamento (puestos). Módulo ConfigPage (C2). Envelope-agnóstico.
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
        const deptId = main ? parseInt(main.dataset.departmentId, 10) : NaN;
        if (!deptId) return;

        S = {
            deptId: deptId,
            department: null,
            positions: [],
            assignPositionId: null,
            createModal: null,
            assignModal: null,
            searchTimer: null,
        };
        const createEl = document.getElementById('createPositionModal');
        if (createEl) S.createModal = new bootstrap.Modal(createEl);
        const assignEl = document.getElementById('assignUserModal');
        if (assignEl) {
            S.assignModal = new bootstrap.Modal(assignEl);
            assignEl.addEventListener('hidden.bs.modal', resetAssignModal);
        }

        document.getElementById('createPositionForm')?.addEventListener('submit', onCreatePosition);
        document.getElementById('assignUserForm')?.addEventListener('submit', onAssignUser);
        document.getElementById('positionsContainer')?.addEventListener('click', onPositionsClick);
        document.getElementById('userSearch')?.addEventListener('input', onUserSearchInput);

        load();
    }

    function destroy() {
        if (S && S.searchTimer) clearTimeout(S.searchTimer);
        if (S) {
            [S.createModal, S.assignModal].forEach(function (m) {
                if (m) { try { m.hide(); m.dispose(); } catch (e) { /* noop */ } }
            });
        }
        S = null;
    }

    // === CARGA (1 solo GET: info + puestos) ================================
    async function load() {
        try {
            const res = await fetch(`${API}/departments/${S.deptId}`);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al cargar el departamento');
            S.department = result.data;
            S.positions = result.data.positions || [];
            renderInfo();
            renderPositions();
        } catch (err) {
            console.error('Error loading department:', err);
            toast('Error al cargar el departamento', 'danger');
        }
    }

    function renderInfo() {
        const d = S.department;
        const bc = document.getElementById('deptNameBreadcrumb');
        if (bc) bc.textContent = d.name;
        const title = document.getElementById('deptNameTitle');
        if (title) title.textContent = d.name;
        const desc = document.getElementById('deptDescription');
        if (desc) desc.textContent = d.description || 'Sin descripción';
        const badge = document.getElementById('deptOfficialBadge');
        if (badge) badge.classList.toggle('d-none', !d.is_official);
        if (d.head) {
            const headInfo = document.getElementById('deptHeadInfo');
            if (headInfo) headInfo.style.display = 'block';
            const headName = document.getElementById('headName');
            if (headName) headName.textContent = d.head.full_name || d.head.name || '';
        }
    }

    function renderPositions() {
        const cont = document.getElementById('positionsContainer');
        if (!cont) return;
        if (S.positions.length === 0) {
            cont.innerHTML = `
                <div class="col-12"><div class="text-center py-5">
                    <i class="bi bi-buildings display-1 text-muted"></i>
                    <h5 class="text-muted mt-3">No hay puestos en este departamento</h5>
                    <p class="text-muted">Crea el primer puesto</p>
                </div></div>`;
            return;
        }
        cont.innerHTML = S.positions.map(positionCard).join('');
    }

    function positionCard(p) {
        const statusBadge = p.is_active
            ? '<span class="badge bg-success">Activo</span>'
            : '<span class="badge bg-secondary">Inactivo</span>';
        const icon = p.allows_multiple ? 'bi-people-fill' : 'bi-person-fill';
        const iconColor = p.allows_multiple ? 'text-info' : 'text-primary';
        const cu = p.current_user;
        return `
        <div class="col-12 col-md-6 col-lg-4" data-position-id="${p.id}">
            <div class="card h-100 shadow-sm">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-3">
                        <div class="d-flex align-items-center">
                            <div class="fs-2 ${iconColor} me-3"><i class="${icon}"></i></div>
                            <div>
                                <h5 class="card-title mb-1">${esc(p.title)}</h5>
                                <small class="text-muted">${esc(p.code)}</small>
                            </div>
                        </div>
                        ${statusBadge}
                    </div>
                    ${p.description ? `<p class="card-text text-muted small">${esc(p.description)}</p>` : ''}
                    <div class="border-top pt-3 mt-3">
                        <h6 class="small text-muted mb-2">${p.allows_multiple ? 'Usuarios Asignados:' : 'Usuario Asignado:'}</h6>
                        ${cu ? `
                            <div class="d-flex align-items-center">
                                <div class="bg-primary bg-opacity-10 rounded-circle p-2 me-2"><i class="bi bi-person text-primary"></i></div>
                                <div>
                                    <div class="fw-bold small">${esc(cu.full_name)}</div>
                                    <small class="text-muted">Desde: ${new Date(cu.start_date).toLocaleDateString('es-ES')}</small>
                                </div>
                            </div>` : `
                            <p class="text-muted small mb-0"><i class="bi bi-x-circle me-1"></i>Sin asignar</p>`}
                    </div>
                </div>
                <div class="card-footer bg-transparent d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-outline-primary flex-fill" data-pos-action="detail" data-position-id="${p.id}">
                        <i class="bi bi-pencil me-1"></i>Editar Puesto
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-success" title="Asignar usuario" data-pos-action="assign" data-position-id="${p.id}">
                        <i class="bi bi-person-plus"></i>
                    </button>
                </div>
            </div>
        </div>`;
    }

    function onPositionsClick(e) {
        const btn = e.target.closest('[data-pos-action]');
        if (!btn) return;
        const positionId = parseInt(btn.dataset.positionId, 10);
        if (btn.dataset.posAction === 'detail') {
            window.ConfigPage.navigate(`/itcj/config/positions/${positionId}`);
        } else if (btn.dataset.posAction === 'assign') {
            openAssignModal(positionId);
        }
    }

    // === CREAR PUESTO ======================================================
    async function onCreatePosition(e) {
        e.preventDefault();
        const formData = new FormData(e.target);
        const payload = {
            code: (formData.get('code') || '').trim(),
            title: (formData.get('title') || '').trim(),
            department_id: S.deptId,
            description: (formData.get('description') || '').trim() || null,
            email: (formData.get('email') || '').trim() || null,
            allows_multiple: formData.get('allows_multiple') === 'on',
            is_active: formData.get('is_active') === 'on',
        };
        const submitBtn = e.target.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        try {
            const res = await fetch(`${API}/positions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al crear el puesto', 'danger');
                return;
            }
            toast('Puesto creado correctamente');
            if (S.createModal) S.createModal.hide();
            e.target.reset();
            await load();
        } catch (err) {
            console.error('Error creating position:', err);
            toast('Error de conexión', 'danger');
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    // === ASIGNAR USUARIO ===================================================
    async function openAssignModal(positionId) {
        S.assignPositionId = positionId;
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
            const url = `${API}/users?per_page=100&only_staff=true` + (q ? `&q=${encodeURIComponent(q)}` : '');
            const res = await fetch(url);
            const result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Error al obtener usuarios');
            // Tolerante al shape de F4: data lista top-level, o data.users legacy.
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
        if (!S.assignPositionId) return;
        const formData = new FormData(e.target);
        const userId = formData.get('user_id');
        if (!userId) { toast('Debe seleccionar un usuario', 'danger'); return; }
        const payload = {
            user_id: parseInt(String(userId), 10),
            start_date: formData.get('start_date') || null,
            notes: (formData.get('notes') || '').trim() || null,
        };
        const submitBtn = e.target.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        try {
            const res = await fetch(`${API}/positions/${S.assignPositionId}/assign-user`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) {
                toast(result.error || 'Error al asignar usuario', 'danger');
                return;
            }
            toast('Usuario asignado correctamente');
            if (S.assignModal) S.assignModal.hide();
            e.target.reset();
            await load();
        } catch (err) {
            console.error('Error assigning user:', err);
            toast('Error de conexión', 'danger');
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    function resetAssignModal() {
        const search = document.getElementById('userSearch');
        if (search) search.value = '';
        const select = document.getElementById('userSelect');
        if (select) select.innerHTML = '<option value="">Seleccionar usuario…</option>';
        document.getElementById('assignUserForm')?.reset();
        if (S) S.assignPositionId = null;
    }

    window.ConfigPage.register('department_detail', { init: init, destroy: destroy });
})();
