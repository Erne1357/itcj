/**
 * Gestión de Asignaciones de Equipos
 * Interfaz para Jefes de Departamento.
 * Isla de-jQuery-zada: modales via bootstrap.Modal (BS5), tabs nativos BS5,
 * fetch nativo. Sin $()/window.jQuery. Registrada en el controller HelpdeskPage.
 */
(function () {
    'use strict';

    // ==================== ESTADO DEL MÓDULO ====================
    let currentDepartment = null;
    let departmentUsers = [];
    let departmentEquipment = [];
    let departmentGroups = [];
    let selectedUser = null;
    let allCategories = [];
    let userScope = { can_assign_cross_dept: false, user_dept: null };
    let allDepartments = [];
    let _showInactiveUsers = true;
    let currentGroupEquipment = [];

    // Handlers almacenados por referencia para poder removerlos
    let _handlers = {};
    let _deptSelectorHandler = null;
    let _active = false;
    let _resizeHandler = null;
    let _tabShownHandler = null;

    // ==================== HELPERS ====================
    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        return String(text).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
    }

    function getModal(id) {
        const el = document.getElementById(id);
        return el ? bootstrap.Modal.getOrCreateInstance(el) : null;
    }

    function showModal(id) {
        const m = getModal(id);
        if (m) m.show();
    }

    function hideModal(id) {
        const el = document.getElementById(id);
        if (el) bootstrap.Modal.getInstance(el)?.hide();
    }

    function show(id) { document.getElementById(id)?.classList.remove('d-none'); }
    function hide(id) { document.getElementById(id)?.classList.add('d-none'); }

    function debounce(fn, delay) {
        let timer;
        return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
    }

    // ==================== LAYOUT: sin doble scroll ====================
    // Los paneles (#users-panel, #equip-panel) son position:sticky, pero el
    // tope de altura NO puede asumir que el panel ya está "pegado" (stuck):
    // en la carga inicial (scrollY=0) el panel vive en su posición NATURAL,
    // más abajo que el top de sticky (top: var(--hd-sticky-top)), porque el
    // header + encabezado + franja de KPIs todavía no se scrollearon fuera
    // de vista. Un max-height calculado sobre el top "stuck" (más chico) es
    // demasiado generoso para esa posición natural (más abajo) y el panel se
    // sale del viewport de todos modos — doble scroll otra vez.
    // Por eso el tope se mide siempre contra la posición REAL de cada
    // elemento (getBoundingClientRect().top en vivo): el panel nunca rebasa
    // el fondo del viewport, esté o no pegado.
    const HD_STICKY_GAP = 12;        // separación entre el header fijo y el panel (usa el "top" del sticky)
    const HD_BOTTOM_GAP = 16;        // aire entre el panel y el borde inferior del viewport
    const HD_MIN_PANEL_H = 240;
    // Las listas de adentro ya no se miden aquí: su alto lo reparte flexbox
    // dentro del panel (assign_equipment.css). Medirlas contra el viewport era
    // justo lo que las hacía rebasar el panel y quedar recortadas.

    function getStickyTopPx() {
        const header = document.querySelector('.sitec-header-nav');
        const headerH = header ? header.getBoundingClientRect().height : 64;
        return headerH + HD_STICKY_GAP;
    }

    // Espacio real que queda DEBAJO del panel antes del fondo del documento:
    // el margin-bottom de su columna (.mb-4 = 24px) + el padding-bottom del
    // <main class="container-fluid"> (helpdesk.css, safe-area-inset). Medido
    // en vivo (no hardcodeado) porque son reglas de otras hojas de estilo que
    // pueden cambiar; sin esto el panel se ajustaba al viewport pero ese
    // margen/padding de todos modos empujaba el documento más allá — el
    // mismo doble scroll por otra vía.
    function getTrailingChromePx() {
        const col = document.querySelector('.col-lg-7.mb-4');
        const colMarginBottom = col ? parseFloat(getComputedStyle(col).marginBottom) || 0 : 0;
        const container = document.querySelector('main.container-fluid');
        const containerPaddingBottom = container ? parseFloat(getComputedStyle(container).paddingBottom) || 0 : 0;
        return colMarginBottom + containerPaddingBottom;
    }

    // Capea `el` para que su borde inferior no rebase el fondo del viewport,
    // usando su posición ACTUAL en pantalla (no una posición "stuck"
    // hipotética) — por eso funciona igual esté o no pegado el ancestro sticky.
    function fitToViewportBottom(el, bottomGap, minHeight) {
        if (!el) return;
        const top = el.getBoundingClientRect().top;
        const maxH = Math.max(minHeight, window.innerHeight - top - bottomGap);
        el.style.maxHeight = maxH + 'px';
    }

    // Recalcula los topes de ambos paneles y de las 3 listas con scroll
    // interno (usuarios, equipos individuales, grupos). Se llama tras
    // cualquier cambio que afecte la altura del "chrome" arriba de las
    // listas: carga inicial, selección de usuario, cambio de pestaña,
    // toggle de filtros, refresh, cambio de departamento y resize de ventana.
    function applyAssignLayout() {
        if (!_active) return;
        document.documentElement.style.setProperty('--hd-sticky-top', getStickyTopPx() + 'px');

        // El tope del PANEL (con overflow:hidden) es la garantía dura de que
        // la página nunca necesita scroll propio; el de la LISTA es solo para
        // que su scrollbar interna quede bien ubicada dentro de ese tope.
        // Solo se capea el PANEL. El reparto de adentro lo hace flexbox
        // (assign_equipment.css): capear también las listas contra el fondo del
        // viewport era el bug — viven dentro de un panel ya recortado a una caja
        // menor, así que sus topes lo rebasaban y overflow:hidden se comía la
        // última fila. Un hijo flex no puede rebasar a su padre.
        const panelBottomGap = HD_BOTTOM_GAP + getTrailingChromePx();
        fitToViewportBottom(document.getElementById('users-panel'), panelBottomGap, HD_MIN_PANEL_H);
        fitToViewportBottom(document.getElementById('equip-panel'), panelBottomGap, HD_MIN_PANEL_H);
    }

    // ==================== INIT / DESTROY ====================
    function init() {
        _active = true;
        loadInitialData();
        setupEventListeners();

        window.refreshData = refreshData;
        window.toggleInactiveUsers = toggleInactiveUsers;
        window.toggleFilters = toggleFilters;
        window.selectUser = selectUser;
        window.openAssignModal = openAssignModal;
        window.openUnassignModal = openUnassignModal;
        window.openGroupModal = openGroupModal;
        window.quickAssignFromGroup = quickAssignFromGroup;
        window.filterGroupEquipmentModal = filterGroupEquipmentModal;
    }

    function destroy() {
        _active = false;
        // Remover listener del dept-selector (cross-dept)
        var deptSel = document.getElementById('dept-selector');
        if (deptSel && _deptSelectorHandler) {
            deptSel.removeEventListener('change', _deptSelectorHandler);
        }
        _deptSelectorHandler = null;

        // Remover listeners de layout (resize + cambio de tab)
        if (_resizeHandler) {
            window.removeEventListener('resize', _resizeHandler);
            _resizeHandler = null;
        }
        const equipmentTabs = document.getElementById('equipmentTabs');
        if (equipmentTabs && _tabShownHandler) {
            equipmentTabs.removeEventListener('shown.bs.tab', _tabShownHandler);
        }
        _tabShownHandler = null;
        document.documentElement.style.removeProperty('--hd-sticky-top');

        // Remover listeners de formularios/inputs
        const searchUsers = document.getElementById('search-users');
        if (searchUsers && _handlers.filterUsers) {
            searchUsers.removeEventListener('input', _handlers.filterUsers);
        }
        const filterCategory = document.getElementById('filter-category');
        if (filterCategory && _handlers.filterEquipment) {
            filterCategory.removeEventListener('change', _handlers.filterEquipment);
        }
        const filterEquipEl = document.getElementById('filter-equipment');
        if (filterEquipEl && _handlers.filterEquipment) {
            filterEquipEl.removeEventListener('input', _handlers.filterEquipment);
        }
        const searchGroupEq = document.getElementById('search-group-equipment');
        if (searchGroupEq && _handlers.filterGroupModal) {
            searchGroupEq.removeEventListener('input', _handlers.filterGroupModal);
        }
        const assignForm = document.getElementById('assign-form');
        if (assignForm && _handlers.handleAssign) {
            assignForm.removeEventListener('submit', _handlers.handleAssign);
        }
        const unassignForm = document.getElementById('unassign-form');
        if (unassignForm && _handlers.handleUnassign) {
            unassignForm.removeEventListener('submit', _handlers.handleUnassign);
        }

        // Dispose modales BS5
        ['assignModal', 'unassignModal', 'selectGroupEquipmentModal'].forEach(function (id) {
            const el = document.getElementById(id);
            if (el) {
                try {
                    bootstrap.Modal.getInstance(el)?.hide();
                    bootstrap.Modal.getInstance(el)?.dispose();
                } catch (e) { /* ignore */ }
            }
        });

        // Limpiar estado
        currentDepartment = null;
        departmentUsers = [];
        departmentEquipment = [];
        departmentGroups = [];
        selectedUser = null;
        allCategories = [];
        userScope = { can_assign_cross_dept: false, user_dept: null };
        allDepartments = [];
        _handlers = {};

        // Limpiar window fns
        delete window.refreshData;
        delete window.toggleInactiveUsers;
        delete window.toggleFilters;
        delete window.selectUser;
        delete window.openAssignModal;
        delete window.openUnassignModal;
        delete window.openGroupModal;
        delete window.quickAssignFromGroup;
        delete window.filterGroupEquipmentModal;
    }

    // ==================== SETUP ====================
    function setupEventListeners() {
        _handlers.filterUsers = filterUsers;
        _handlers.filterEquipment = filterEquipment;
        _handlers.filterGroupModal = filterGroupEquipmentModal;
        _handlers.handleAssign = handleAssign;
        _handlers.handleUnassign = handleUnassign;

        document.getElementById('search-users').addEventListener('input', _handlers.filterUsers);
        document.getElementById('filter-category').addEventListener('change', _handlers.filterEquipment);
        document.getElementById('filter-equipment').addEventListener('input', _handlers.filterEquipment);
        document.getElementById('search-group-equipment').addEventListener('input', _handlers.filterGroupModal);
        document.getElementById('assign-form').addEventListener('submit', _handlers.handleAssign);
        document.getElementById('unassign-form').addEventListener('submit', _handlers.handleUnassign);
        // Tabs de equipos/grupos: BS5 los maneja nativamente vía data-bs-toggle="tab".

        // Layout sin doble scroll: recalcular topes al cambiar el tamaño de
        // ventana o al cambiar de pestaña (individual/grupos comparten el
        // mismo hueco, pero recalculamos igual por si el navegador difiere
        // en el alto de línea entre badges).
        _resizeHandler = debounce(applyAssignLayout, 150);
        window.addEventListener('resize', _resizeHandler);

        _tabShownHandler = applyAssignLayout;
        document.getElementById('equipmentTabs')?.addEventListener('shown.bs.tab', _tabShownHandler);
    }

    // ==================== CARGAR DATOS ====================
    async function loadInitialData() {
        try {
            await loadUserScope();
            await initDepartmentContext();
            await reloadDepartmentData();
            await loadCategories();
            hideLoading();
            applyAssignLayout();
        } catch (error) {
            console.error('Error cargando datos:', error);
            const errorMessage = error.message || 'Error desconocido';
            showError(`No se pudieron cargar los datos del departamento: ${errorMessage}`);
        }
    }

    async function loadUserScope() {
        try {
            const res = await fetch('/api/help-desk/v2/inventory/assignments/me-scope', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });
            if (!res.ok) throw new Error('No se pudo determinar el alcance');
            const json = await res.json();
            userScope = json.data;
        } catch (err) {
            console.warn('Scope no disponible, asumiendo dept-only:', err);
            userScope = { can_assign_cross_dept: false, user_dept: null };
        }
    }

    async function initDepartmentContext() {
        if (userScope.can_assign_cross_dept) {
            try {
                const res = await fetch('/api/core/v2/departments?active=true', {
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
                });
                const json = await res.json();
                allDepartments = (json.data || []).slice().sort((a, b) => a.name.localeCompare(b.name));
            } catch (err) {
                console.error('Error cargando departamentos:', err);
                allDepartments = [];
            }

            const wrapper = document.getElementById('dept-selector-wrapper');
            const selector = document.getElementById('dept-selector');
            if (wrapper) wrapper.classList.remove('d-none');
            if (selector) {
                selector.innerHTML = allDepartments
                    .map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('');

                const initialId = userScope.user_dept ? userScope.user_dept.id : (allDepartments[0]?.id || '');
                selector.value = String(initialId);
                currentDepartment = allDepartments.find(d => d.id === parseInt(selector.value, 10)) || null;

                if (!_active) return;
                _deptSelectorHandler = async function () {
                    currentDepartment = allDepartments.find(d => d.id === parseInt(selector.value, 10)) || null;
                    if (currentDepartment) {
                        showLoading();
                        selectedUser = null;
                        await reloadDepartmentData();
                        hideLoading();
                        applyAssignLayout();
                    }
                };
                selector.addEventListener('change', _deptSelectorHandler);
            }
            return;
        }

        try {
            const response = await fetch('/api/core/v2/user/me/department', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || errorData.message || 'No tienes un departamento asignado y no tienes permiso para asignar entre departamentos.');
            }

            const result = await response.json();
            currentDepartment = result.data;

            document.getElementById('department-info').textContent =
                `Gestionando equipos del ${currentDepartment.name}`;

        } catch (error) {
            console.error('Error:', error);
            throw error;
        }
    }

    async function reloadDepartmentData() {
        if (!currentDepartment) {
            showError('Sin departamento activo.');
            return;
        }
        document.getElementById('department-info').textContent =
            `Gestionando equipos del ${currentDepartment.name}`;

        await Promise.all([
            loadDepartmentUsers(),
            loadDepartmentEquipment(),
            loadDepartmentGroups(),
        ]);

        renderStats();
        renderUsersList(document.getElementById('search-users')?.value || '');
    }

    function toggleInactiveUsers(checked) {
        _showInactiveUsers = checked;
        loadDepartmentUsers().then(function () {
            renderUsersList(document.getElementById('search-users').value);
        });
    }

    async function loadDepartmentUsers() {
        try {
            const url = `/api/core/v2/departments/${currentDepartment.id}/users` +
                (_showInactiveUsers ? '?include_inactive=true' : '');
            const response = await fetch(url, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Error al cargar usuarios');
            }

            const result = await response.json();
            departmentUsers = result.data.users.sort((a, b) =>
                a.full_name.localeCompare(b.full_name)
            );

        } catch (error) {
            console.error('Error:', error);
            throw error;
        }
    }

    async function loadDepartmentEquipment() {
        try {
            const response = await fetch(
                `/api/help-desk/v2/inventory/items/department/${currentDepartment.id}?include_assigned=true`,
                { headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` } }
            );

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Error al cargar equipos');
            }

            const result = await response.json();
            departmentEquipment = result.data;

        } catch (error) {
            console.error('Error:', error);
            throw error;
        }
    }

    async function loadDepartmentGroups() {
        try {
            const response = await fetch(
                `/api/help-desk/v2/inventory/groups/department/${currentDepartment.id}`,
                { headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` } }
            );

            if (!response.ok) {
                console.warn('No se pudieron cargar grupos');
                departmentGroups = [];
                return;
            }

            const result = await response.json();
            departmentGroups = result.data || [];

        } catch (error) {
            console.error('Error cargando grupos:', error);
            departmentGroups = [];
        }
    }

    async function loadCategories() {
        try {
            const response = await fetch('/api/help-desk/v2/inventory/categories?active=true', {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Error al cargar categorías');
            }

            const result = await response.json();
            allCategories = result.data;

            const select = document.getElementById('filter-category');
            select.innerHTML = '<option value="">Todas las categorías</option>';
            allCategories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat.id;
                option.textContent = cat.name;
                select.appendChild(option);
            });

        } catch (error) {
            console.error('Error:', error);
        }
    }

    // ==================== RENDERIZADO ====================
    function renderStats() {
        const totalUsers = departmentUsers.length;
        const totalEquipment = departmentEquipment.length;
        const assigned = departmentEquipment.filter(e => e.is_assigned_to_user).length;
        const available = totalEquipment - assigned;

        document.getElementById('stat-total-users').textContent = totalUsers;
        document.getElementById('stat-total-equipment').textContent = totalEquipment;
        document.getElementById('stat-assigned').textContent = assigned;
        document.getElementById('stat-available').textContent = available;
    }

    function renderUsersList(filter) {
        filter = filter || '';
        const container = document.getElementById('users-list');
        const filterLower = filter.toLowerCase();

        const filteredUsers = filter
            ? departmentUsers.filter(u =>
                u.full_name.toLowerCase().includes(filterLower) ||
                (u.email || '').toLowerCase().includes(filterLower)
            )
            : departmentUsers;

        document.getElementById('users-count').textContent = filteredUsers.length;

        if (filteredUsers.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-users-slash fa-2x mb-2"></i>
                    <p>No se encontraron usuarios</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredUsers.map(user => {
            const userEquipment = departmentEquipment.filter(e => e.assigned_to_user_id === user.id);
            const isSelected = selectedUser && selectedUser.id === user.id;
            const fullName = escapeHtml(user.full_name);
            const initial = escapeHtml((user.full_name || '?').charAt(0).toUpperCase());

            return `
                <div class="user-card ${isSelected ? 'selected' : ''} p-3 mb-2"
                     onclick="selectUser(${user.id})">
                    <div class="d-flex align-items-center">
                        <div class="me-3">
                            <div class="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center hd-user-avatar">
                                ${initial}
                            </div>
                        </div>
                        <div class="flex-grow-1">
                            <div class="fw-bold">
                                ${fullName}
                                ${!user.is_active ? '<span class="badge bg-secondary ms-1 hd-badge-xs">Inactivo</span>' : ''}
                            </div>
                            <small class="text-muted">
                                ${user.email ? escapeHtml(user.email) : '<span class="fst-italic">Sin correo registrado</span>'}
                            </small>
                        </div>
                        <div class="text-end">
                            <span class="badge bg-${userEquipment.length > 0 ? 'info' : 'secondary'}">
                                ${userEquipment.length} equipos
                            </span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function selectUser(userId) {
        selectedUser = departmentUsers.find(u => u.id === userId);

        if (!selectedUser) return;

        document.querySelectorAll('.user-card').forEach(card => {
            card.classList.remove('selected');
        });
        if (typeof event !== 'undefined' && event.currentTarget) {
            event.currentTarget.classList.add('selected');
        }

        hide('no-user-selected');
        show('user-equipment-section');

        document.getElementById('equipment-panel-title').innerHTML = `
            <i class="fas fa-laptop"></i> Equipos de ${escapeHtml(selectedUser.full_name)}
        `;

        renderUserEquipment();
        applyAssignLayout();
    }

    function renderUserEquipment() {
        if (!selectedUser) return;

        const assignedEquipment = departmentEquipment.filter(e =>
            e.assigned_to_user_id === selectedUser.id
        );

        const individualAvailable = departmentEquipment.filter(e =>
            !e.is_assigned_to_user && e.status === 'ACTIVE' && !e.is_in_group
        );

        const assignedContainer = document.getElementById('assigned-equipment-list');
        document.getElementById('assigned-count').textContent = assignedEquipment.length;

        if (assignedEquipment.length === 0) {
            assignedContainer.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-inbox fa-2x mb-2"></i>
                    <p class="mb-0">Este usuario no tiene equipos asignados</p>
                </div>
            `;
        } else {
            assignedContainer.innerHTML = assignedEquipment.map(item =>
                renderEquipmentItem(item, 'assigned')
            ).join('');
        }

        const individualContainer = document.getElementById('individual-equipment-list');
        document.getElementById('individual-count').textContent = individualAvailable.length;

        if (individualAvailable.length === 0) {
            individualContainer.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-info-circle fa-2x mb-2"></i>
                    <p class="mb-0">No hay equipos individuales disponibles</p>
                </div>
            `;
        } else {
            individualContainer.innerHTML = individualAvailable.map(item =>
                renderEquipmentItem(item, 'available')
            ).join('');
        }

        renderGroupsList();
    }

    function renderGroupsList() {
        const container = document.getElementById('groups-list');
        document.getElementById('groups-count').textContent = departmentGroups.length;

        if (departmentGroups.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-layer-group fa-2x mb-2"></i>
                    <p class="mb-0">No hay grupos disponibles en este departamento</p>
                </div>
            `;
            return;
        }

        container.innerHTML = departmentGroups.map(group => {
            const groupEquipment = departmentEquipment.filter(e =>
                e.group_id === group.id && !e.is_assigned_to_user && e.status === 'ACTIVE'
            );

            const groupTypeIcons = {
                'CLASSROOM': 'fa-chalkboard-teacher',
                'LABORATORY': 'fa-flask',
                'OFFICE': 'fa-briefcase',
                'MEETING_ROOM': 'fa-users',
                'WORKSHOP': 'fa-tools',
                'OTHER': 'fa-door-open'
            };

            const icon = groupTypeIcons[group.group_type] || 'fa-door-open';
            const groupName = escapeHtml(group.name);
            const location = [group.building, group.floor ? `Piso ${group.floor}` : ''].filter(Boolean).join(' - ');

            return `
                <div class="equipment-item group-item" onclick="openGroupModal(${group.id})">
                    <div class="d-flex align-items-center">
                        <div class="me-3">
                            <i class="fas ${icon} fa-2x text-info"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="fw-bold">
                                <i class="fas fa-layer-group me-1"></i>
                                ${groupName}
                            </div>
                            <small class="text-muted">
                                ${group.description ? escapeHtml(group.description) : 'Sin descripción'}
                            </small>
                            <br>
                            <span class="badge bg-success text-white mt-1">
                                <i class="fas fa-laptop me-1"></i>
                                ${groupEquipment.length} equipos disponibles
                            </span>
                            ${location ? `
                                <span class="badge bg-light text-dark mt-1">
                                    <i class="fas fa-map-marker-alt me-1"></i>
                                    ${escapeHtml(location)}
                                </span>
                            ` : ''}
                        </div>
                        <div>
                            <button class="btn btn-sm btn-info" onclick="event.stopPropagation(); openGroupModal(${group.id});">
                                <i class="fas fa-hand-pointer"></i> Ver Equipos
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderEquipmentItem(item, type) {
        const isAssigned = type === 'assigned';
        const icon = escapeHtml(item.category?.icon || 'fas fa-box');

        let groupBadge = '';
        if (item.is_in_group && item.group) {
            groupBadge = `
                <br><small class="badge bg-info text-white mt-1 hd-group-inline-badge">
                    <i class="fas fa-layer-group me-1"></i>${escapeHtml(item.group.name)}
                </small>
            `;
        }

        return `
            <div class="equipment-item ${isAssigned ? 'assigned' : 'global'}">
                <div class="d-flex align-items-center">
                    <div class="me-3">
                        <i class="${icon} fa-2x text-${isAssigned ? 'info' : 'secondary'}"></i>
                    </div>
                    <div class="flex-grow-1">
                        <div class="fw-bold">
                            ${escapeHtml(item.inventory_number)}
                        </div>
                        <small class="text-muted">
                            ${escapeHtml(item.brand || 'N/A')} ${escapeHtml(item.model || '')}
                        </small>
                        ${item.location_detail ? `
                            <br><small class="text-muted">
                                <i class="fas fa-map-marker-alt"></i> ${escapeHtml(item.location_detail)}
                            </small>
                        ` : ''}
                        ${groupBadge}
                    </div>
                    <div>
                        ${isAssigned ? `
                            <button class="btn btn-sm btn-warning quick-assign-btn"
                                    onclick="openUnassignModal(${item.id}); event.stopPropagation();">
                                <i class="fas fa-times"></i> Liberar
                            </button>
                        ` : `
                            <button class="btn btn-sm btn-success quick-assign-btn"
                                    onclick="openAssignModal(${item.id}); event.stopPropagation();">
                                <i class="fas fa-plus"></i> Asignar
                            </button>
                        `}
                        <a href="/help-desk/inventory/items/${item.id}"
                           class="btn btn-sm btn-outline-secondary quick-assign-btn ms-1"
                           target="_blank"
                           onclick="event.stopPropagation();">
                            <i class="fas fa-external-link-alt"></i>
                        </a>
                    </div>
                </div>
            </div>
        `;
    }

    // ==================== MODAL DE GRUPO ====================
    async function openGroupModal(groupId) {
        if (!selectedUser) {
            showError('Seleccione un usuario primero');
            return;
        }

        const group = departmentGroups.find(g => g.id === groupId);
        if (!group) return;

        document.getElementById('selected-group-id').value = groupId;
        document.getElementById('group-modal-name').textContent = group.name;
        document.getElementById('group-modal-description').textContent = group.description || 'Sin descripción';

        document.getElementById('search-group-equipment').value = '';

        showModal('selectGroupEquipmentModal');

        await loadGroupEquipment(groupId);
    }

    async function loadGroupEquipment(groupId) {
        const container = document.getElementById('group-equipment-list');

        container.innerHTML = `
            <div class="text-center py-4">
                <i class="fas fa-spinner fa-spin fa-2x text-info"></i>
                <p class="text-muted mt-2">Cargando equipos...</p>
            </div>
        `;

        try {
            const response = await fetch(
                `/api/help-desk/v2/inventory/groups/${groupId}/items`,
                { headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` } }
            );

            if (!response.ok) throw new Error('Error al cargar equipos del grupo');

            const result = await response.json();

            currentGroupEquipment = result.data.filter(item =>
                !item.is_assigned_to_user && item.status === 'ACTIVE'
            );

            renderGroupEquipmentList();

        } catch (error) {
            console.error('Error:', error);
            container.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle"></i>
                    Error al cargar equipos del grupo
                </div>
            `;
        }
    }

    function renderGroupEquipmentList(filter) {
        filter = filter || '';
        const container = document.getElementById('group-equipment-list');

        const filterLower = filter.toLowerCase();
        const filteredEquipment = filter
            ? currentGroupEquipment.filter(item =>
                item.inventory_number.toLowerCase().includes(filterLower) ||
                (item.brand && item.brand.toLowerCase().includes(filterLower)) ||
                (item.model && item.model.toLowerCase().includes(filterLower))
            )
            : currentGroupEquipment;

        if (filteredEquipment.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="fas fa-inbox fa-2x mb-2"></i>
                    <p class="mb-0">${filter ? 'No se encontraron equipos' : 'No hay equipos disponibles en este grupo'}</p>
                </div>
            `;
            return;
        }

        container.innerHTML = filteredEquipment.map(item => {
            const icon = escapeHtml(item.category?.icon || 'fas fa-laptop');

            return `
                <div class="equipment-item selectable-item" onclick="quickAssignFromGroup(${item.id})">
                    <div class="d-flex align-items-center">
                        <div class="me-3">
                            <i class="${icon} fa-2x text-primary"></i>
                        </div>
                        <div class="flex-grow-1">
                            <div class="fw-bold">
                                ${escapeHtml(item.inventory_number)}
                            </div>
                            <small class="text-muted">
                                ${escapeHtml(item.brand || 'N/A')} ${escapeHtml(item.model || '')}
                            </small>
                            ${item.location_detail ? `
                                <br><small class="text-muted">
                                    <i class="fas fa-map-marker-alt"></i> ${escapeHtml(item.location_detail)}
                                </small>
                            ` : ''}
                        </div>
                        <div>
                            <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); quickAssignFromGroup(${item.id});">
                                <i class="fas fa-plus"></i> Asignar
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function filterGroupEquipmentModal() {
        const searchTerm = document.getElementById('search-group-equipment').value;
        renderGroupEquipmentList(searchTerm);
    }

    async function quickAssignFromGroup(itemId) {
        if (!selectedUser) return;
        hideModal('selectGroupEquipmentModal');
        openAssignModal(itemId);
    }

    // ==================== FILTROS ====================
    function filterUsers() {
        const searchTerm = document.getElementById('search-users').value;
        renderUsersList(searchTerm);
    }

    function filterEquipment() {
        if (selectedUser) {
            renderUserEquipment();
        }
    }

    function toggleFilters() {
        document.getElementById('equipment-filters')?.classList.toggle('d-none');
        // Mostrar/ocultar el bloque de filtros cambia el "chrome" arriba de
        // la lista de equipos disponibles → recalcular su tope.
        applyAssignLayout();
    }

    // ==================== ASIGNACIÓN ====================
    function openAssignModal(itemId) {
        if (!selectedUser) {
            showError('Seleccione un usuario primero');
            return;
        }

        const item = departmentEquipment.find(e => e.id === itemId);
        if (!item) return;

        document.getElementById('assign-item-id').value = itemId;
        document.getElementById('assign-user-id').value = selectedUser.id;
        document.getElementById('assign-item-name').textContent = item.display_name;
        document.getElementById('assign-user-name').textContent = selectedUser.full_name;
        document.getElementById('assign-location').value = '';
        document.getElementById('assign-notes').value = '';

        showModal('assignModal');
    }

    async function handleAssign(e) {
        e.preventDefault();

        const itemId = parseInt(document.getElementById('assign-item-id').value);
        const userId = parseInt(document.getElementById('assign-user-id').value);
        const location = document.getElementById('assign-location').value.trim();
        const notes = document.getElementById('assign-notes').value.trim();

        try {
            const response = await fetch('/api/help-desk/v2/inventory/assignments/assign', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_id: itemId,
                    user_id: userId,
                    location: location || null,
                    notes: notes || null
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || error.message || 'Error al asignar equipo');
            }

            hideModal('assignModal');
            showSuccess('Equipo asignado correctamente');

            await refreshData();

        } catch (error) {
            console.error('Error:', error);
            const errorMessage = error.message || 'Error desconocido';
            showError(`Error al asignar equipo: ${errorMessage}`);
        }
    }

    // ==================== LIBERACIÓN ====================
    function openUnassignModal(itemId) {
        const item = departmentEquipment.find(e => e.id === itemId);
        if (!item) return;

        document.getElementById('unassign-item-id').value = itemId;
        document.getElementById('unassign-item-name').textContent = item.display_name;
        document.getElementById('unassign-user-name').textContent =
            item.assigned_to_user?.full_name || 'N/A';
        document.getElementById('unassign-notes').value = '';

        showModal('unassignModal');
    }

    async function handleUnassign(e) {
        e.preventDefault();

        const itemId = parseInt(document.getElementById('unassign-item-id').value);
        const notes = document.getElementById('unassign-notes').value.trim();

        try {
            const response = await fetch('/api/help-desk/v2/inventory/assignments/unassign', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    item_id: itemId,
                    notes: notes || 'Equipo liberado desde vista de asignaciones'
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Error al liberar equipo');
            }

            hideModal('unassignModal');
            showSuccess('Equipo liberado correctamente');

            await refreshData();

        } catch (error) {
            console.error('Error:', error);
            showError(error.message);
        }
    }

    // ==================== REFRESH ====================
    // Antes llamaba showLoading()/hideLoading(), que desmonta #main-content
    // completo (la página entera parpadeaba en blanco al pulsar "Actualizar").
    // Ahora el feedback es un spinner local en el botón; el contenido nunca
    // se desmonta.
    async function refreshData() {
        const btn = document.getElementById('btn-refresh-assign');
        setButtonBusy(btn, true);

        try {
            await loadDepartmentUsers();
            await loadDepartmentEquipment();
            await loadDepartmentGroups();

            renderStats();
            renderUsersList(document.getElementById('search-users')?.value || '');

            if (selectedUser) {
                const updatedUser = departmentUsers.find(u => u.id === selectedUser.id);
                if (updatedUser) {
                    selectedUser = updatedUser;
                    renderUserEquipment();
                }
            }

            applyAssignLayout();

        } catch (error) {
            console.error('Error:', error);
            showError('Error al actualizar datos');
        } finally {
            setButtonBusy(btn, false);
        }
    }

    // Alterna el spinner inline de un botón sin tocar su contenido/ancho
    // (el ícono y el texto se ocultan, el spinner los reemplaza).
    function setButtonBusy(btn, isBusy) {
        if (!btn) return;
        btn.disabled = isBusy;
        const spinner = btn.querySelector('.hd-btn-spinner');
        const icon = btn.querySelector('.fa-sync-alt');
        if (spinner) spinner.classList.toggle('d-none', !isBusy);
        if (icon) icon.classList.toggle('d-none', isBusy);
    }

    // ==================== HELPERS UI ====================
    function showLoading() {
        show('loading-state');
        hide('main-content');
    }

    function hideLoading() {
        hide('loading-state');
        show('main-content');
    }

    function showSuccess(message) {
        showToast(message, 'success');
    }

    function showError(message) {
        showToast(message, 'error');
    }

    // ==================== REGISTRO ====================
    window.HelpdeskPage.page('inventory_assignment_assign_equipment', { init: init, destroy: destroy });

})();
