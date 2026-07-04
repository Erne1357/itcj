/* =============================================================================
   Permisos por app — módulo del registry ConfigPage (C2).
   IIFE + register: appKey desde #cfgMain[data-app-key] (F3-D2); init() re-vincula
   en cada visita; destroy() dispone modales + quita listener de document.
   Badges de scope C8 por sufijo del código (F3-D5). Nombre/ícono de módulo
   DERIVADOS del código (F3-D6) — sin mapas hardcoded. escapeHtml en todo
   innerHTML de servidor. Toasts via ConfigUtils; sin showSuccess/showError
   privados.
   ============================================================================= */
(function () {
    'use strict';

    var API = '/api/core/v2';
    var appKey = null;
    var roles = [];
    var permissions = [];
    var selectedRole = null;
    var createModal = null;
    var onDocClick = null;

    function esc(v) { return window.ConfigUtils ? ConfigUtils.escapeHtml(v) : String(v == null ? '' : v); }
    function toast(msg, type) { if (window.ConfigUtils) ConfigUtils.showToast(msg, type || 'success'); }
    function sel(v) { return (window.CSS && CSS.escape) ? CSS.escape(v) : v; }

    // ---- Derivaciones desde el código de permiso -------------------------
    // Badge de scope (C8): sufijo -> clase. own_dept ANTES de own.
    function scopeBadge(code) {
        var m = /\.(subtree|own_dept|own|all)$/.exec(code || '');
        if (!m) return '';
        var cls = { subtree: 'scope-subtree', own_dept: 'scope-dept', own: 'scope-own', all: 'scope-all' }[m[1]];
        var label = { subtree: 'subtree', own_dept: 'own dept', own: 'own', all: 'all' }[m[1]];
        return ' <span class="scope-badge ' + cls + '">' + label + '</span>';
    }

    function moduleFriendlyName(m) {
        if (!m) return 'General';
        return m.split('_').map(function (w) {
            return w ? w.charAt(0).toUpperCase() + w.slice(1) : w;
        }).join(' ');
    }

    function validatePermCode(e) {
        if (!/^[a-z0-9._]*$/.test(e.target.value)) {
            e.target.classList.add('is-invalid');
            e.target.setCustomValidity('Solo se permiten letras minúsculas, números, puntos y guiones bajos');
        } else {
            e.target.classList.remove('is-invalid');
            e.target.setCustomValidity('');
        }
    }

    // ---- Roles (dropdown de asignación) ----------------------------------
    async function loadRoles() {
        try {
            var response = await fetch(API + '/authz/roles');
            var result = await response.json();
            if (response.ok && result.data) {
                roles = result.data;
                populateRoleSelect();
            }
        } catch (err) {
            console.error('Error loading roles:', err);
        }
    }

    function populateRoleSelect() {
        var select = document.getElementById('roleSelect');
        if (!select) return;
        while (select.children.length > 1) select.removeChild(select.lastChild);
        roles.forEach(function (role) {
            var opt = document.createElement('option');
            opt.value = role.name;
            opt.textContent = role.name;
            select.appendChild(opt);
        });
    }

    // ---- Crear permiso ---------------------------------------------------
    async function handleCreatePermission(e) {
        e.preventDefault();
        var fd = new FormData(e.target);
        var data = { code: fd.get('code'), name: fd.get('name'), description: fd.get('description') || undefined };
        try {
            var response = await fetch(API + '/authz/apps/' + encodeURIComponent(appKey) + '/perms', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            var result = await response.json();
            if (response.ok) {
                toast('Permiso creado correctamente');
                if (createModal) createModal.hide();
                addPermissionRow(result.data);
                e.target.reset();
                refreshRolePermissions();
            } else {
                toast(result.error || 'Error al crear el permiso', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error creating permission:', err);
        }
    }

    // ---- Eliminar permiso ------------------------------------------------
    async function onDeletePermission(permCode) {
        const ok = await AppModal.confirm({
            title: 'Eliminar permiso',
            message: `Se eliminara el permiso "${permCode}"`,
            confirmText: 'Eliminar',
            confirmVariant: 'danger',
        });
        if (!ok) return;

        try {
            var response = await fetch(
                API + '/authz/apps/' + encodeURIComponent(appKey) + '/perms/' + encodeURIComponent(permCode),
                { method: 'DELETE' });
            if (response.ok) {
                toast('Permiso eliminado correctamente');
                removePermissionRow(permCode);
                refreshRolePermissions();
            } else {
                var result = await response.json();
                toast(result.error || 'Error al eliminar el permiso', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error deleting permission:', err);
        }
    }

    // ---- Asignación por rol ----------------------------------------------
    async function handleRoleSelection(roleName) {
        if (!roleName) { hideRolePermissions(); return; }
        selectedRole = roleName;
        document.getElementById('selectedRoleName').textContent = roleName;
        try {
            var permsResponse = await fetch(API + '/authz/apps/' + encodeURIComponent(appKey) + '/perms');
            var permsResult = await permsResponse.json();
            var rolePermsResponse = await fetch(
                API + '/authz/apps/' + encodeURIComponent(appKey) + '/roles/' + encodeURIComponent(roleName) + '/perms');
            var rolePermsResult = await rolePermsResponse.json();
            if (permsResponse.ok && rolePermsResponse.ok) {
                permissions = permsResult.data || [];
                showRolePermissions(rolePermsResult.data || []);
            }
        } catch (err) {
            toast('Error al cargar los permisos', 'error');
            console.error('Error loading permissions:', err);
        }
    }

    function groupPermissions(perms) {
        var groups = { pages: [], dashboards: [], modules: {} };
        perms.forEach(function (perm) {
            var parts = perm.code.split('.');
            if (perm.code.indexOf('.page.') !== -1) {
                groups.pages.push(perm);
            } else if (perm.code.indexOf('.dashboard') !== -1) {
                groups.dashboards.push(perm);
            } else {
                var moduleName = parts[1] || 'general';
                (groups.modules[moduleName] = groups.modules[moduleName] || []).push(perm);
            }
        });
        return groups;
    }

    function showRolePermissions(rolePermissions) {
        var groups = groupPermissions(permissions);
        document.getElementById('permissionsModuleTabs').innerHTML = buildPermissionsTabs(groups, rolePermissions);
        document.getElementById('rolePermissionsContent').classList.remove('d-none');
        document.getElementById('noRoleSelected').classList.add('d-none');
    }

    function buildPermissionsTabs(groups, rolePermissions) {
        var nav = '<ul class="nav nav-tabs mb-3" role="tablist">';
        var content = '<div class="tab-content">';
        var first = true;

        function addTab(id, icon, label, perms) {
            nav += '<li class="nav-item" role="presentation">'
                + '<button class="nav-link ' + (first ? 'active' : '') + '" id="' + id + '-tab"'
                + ' data-bs-toggle="tab" data-bs-target="#' + id + '-pane" type="button" role="tab">'
                + '<i class="' + icon + ' me-1"></i>' + esc(label) + ' (' + perms.length + ')</button></li>';
            content += '<div class="tab-pane fade ' + (first ? 'show active' : '') + '" id="' + id + '-pane" role="tabpanel">'
                + '<div class="row g-2">' + buildCheckboxes(perms, rolePermissions) + '</div></div>';
            first = false;
        }

        if (groups.pages.length) addTab('perm-pages', 'bi bi-window', 'Páginas', groups.pages);
        if (groups.dashboards.length) addTab('perm-dashboards', 'bi bi-speedometer2', 'Dashboards', groups.dashboards);
        Object.keys(groups.modules).sort().forEach(function (m) {
            // F3-D6: ícono genérico para módulos API (sin mapa hardcoded)
            addTab('perm-module-' + m.replace(/[^a-z0-9_]/gi, '_'), 'bi bi-collection',
                moduleFriendlyName(m), groups.modules[m]);
        });

        return nav + '</ul>' + content + '</div>';
    }

    function buildCheckboxes(perms, rolePermissions) {
        return perms.map(function (perm) {
            var checked = rolePermissions.indexOf(perm.code) !== -1;
            var idSafe = 'perm_' + perm.code.replace(/\./g, '_');
            return '<div class="col-12 col-md-6 col-lg-4"><div class="form-check">'
                + '<input class="form-check-input" type="checkbox" id="' + esc(idSafe) + '" value="' + esc(perm.code) + '" ' + (checked ? 'checked' : '') + '>'
                + '<label class="form-check-label" for="' + esc(idSafe) + '">'
                + '<strong>' + esc(perm.name) + '</strong>' + scopeBadge(perm.code) + '<br>'
                + '<small class="text-muted">' + esc(perm.code) + '</small>'
                + (perm.description ? '<br><small class="text-muted">' + esc(perm.description) + '</small>' : '')
                + '</label></div></div>';
        }).join('');
    }

    function hideRolePermissions() {
        document.getElementById('rolePermissionsContent').classList.add('d-none');
        document.getElementById('noRoleSelected').classList.remove('d-none');
        selectedRole = null;
    }

    async function saveRolePermissions() {
        if (!selectedRole) return;
        var checkboxes = document.querySelectorAll('#permissionsModuleTabs input[type="checkbox"]');
        var codes = Array.prototype.filter.call(checkboxes, function (cb) { return cb.checked; })
            .map(function (cb) { return cb.value; });
        try {
            var response = await fetch(
                API + '/authz/apps/' + encodeURIComponent(appKey) + '/roles/' + encodeURIComponent(selectedRole) + '/perms', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ codes: codes }),
                });
            if (response.ok) {
                toast('Permisos del rol actualizados correctamente');
            } else {
                var result = await response.json();
                toast(result.error || 'Error al actualizar los permisos', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error saving role permissions:', err);
        }
    }

    async function refreshRolePermissions() {
        if (selectedRole) await handleRoleSelection(selectedRole);
    }

    // ---- Tabla de permisos (crear/eliminar sin reload) -------------------
    function permRowHtml(perm) {
        return '<td class="px-4"><code class="bg-light px-2 py-1 rounded">' + esc(perm.code) + '</code>' + scopeBadge(perm.code) + '</td>'
            + '<td><strong>' + esc(perm.name) + '</strong></td>'
            + '<td><small class="text-muted">' + esc(perm.description || 'Sin descripcion') + '</small></td>'
            + '<td class="text-end pe-4"><button class="btn btn-sm btn-outline-danger delete-perm-btn"'
            + ' data-perm-code="' + esc(perm.code) + '" data-perm-name="' + esc(perm.name) + '" title="Eliminar"><i class="bi bi-trash"></i></button></td>';
    }

    function addPermissionRow(perm) {
        if (!perm) return;
        var tbody = document.querySelector('#permissionsTable tbody');
        if (!tbody) return;
        var tr = document.createElement('tr');
        tr.setAttribute('data-perm-code', perm.code);
        tr.innerHTML = permRowHtml(perm);
        tbody.appendChild(tr);
        var empty = document.getElementById('emptyPermsState');
        if (empty) empty.remove();
        bumpTabCount(1);
    }

    function removePermissionRow(code) {
        var row = document.querySelector('#permissionsTable tbody tr[data-perm-code="' + sel(code) + '"]');
        if (row) row.remove();
        bumpTabCount(-1);
    }

    function bumpTabCount(delta) {
        var tab = document.getElementById('permissions-tab');
        if (!tab) return;
        var m = tab.textContent.match(/\((\d+)\)/);
        if (m) tab.innerHTML = tab.innerHTML.replace(/\(\d+\)/, '(' + Math.max(0, parseInt(m[1], 10) + delta) + ')');
    }

    function init() {
        var main = document.getElementById('cfgMain');
        appKey = main ? main.dataset.appKey : null;
        var createForm = document.getElementById('createPermForm');
        if (!createForm || !appKey) return;   // no estamos en la página de permisos

        createForm.addEventListener('submit', handleCreatePermission);
        var permCode = document.getElementById('permCode');
        if (permCode) permCode.addEventListener('input', validatePermCode);
        var roleSelect = document.getElementById('roleSelect');
        if (roleSelect) roleSelect.addEventListener('change', function (e) { handleRoleSelection(e.target.value); });
        var saveBtn = document.getElementById('saveRolePermissions');
        if (saveBtn) saveBtn.addEventListener('click', saveRolePermissions);

        createModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('createPermModal'));

        onDocClick = function (e) {
            var btn = e.target.closest('.delete-perm-btn');
            if (btn) onDeletePermission(btn.dataset.permCode);
        };
        document.addEventListener('click', onDocClick);

        selectedRole = null;
        roles = [];
        permissions = [];
        loadRoles();
    }

    function destroy() {
        if (onDocClick) { document.removeEventListener('click', onDocClick); onDocClick = null; }
        [createModal].forEach(function (m) {
            if (m) { try { m.hide(); m.dispose(); } catch (e) { /* noop */ } }
        });
        createModal = null;
        selectedRole = null;
    }

    if (window.ConfigPage) {
        window.ConfigPage.register('permissions', { init: init, destroy: destroy });
    }
})();
