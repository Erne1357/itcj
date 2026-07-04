/* =============================================================================
   Apps config — módulo del registry ConfigPage (C2).
   IIFE + register: init() re-vincula en cada visita (nodos recreados por morph);
   destroy() dispone modales y quita el listener de document. Color/icono badge
   DB-driven (C4/C8): color-picker + input de icono con preview en vivo; crear y
   editar re-renderizan la fila SIN location.reload. Toasts/escape via ConfigUtils
   (shell) — sin showSuccess/showError privados; sin createAppRow/addAppToTable
   muertos.
   ============================================================================= */
(function () {
    'use strict';

    var API = '/api/core/v2';
    var createModal = null;
    var editModal = null;
    var deleteModal = null;
    var pendingDeleteKey = null;
    var onDocClick = null;
    var editPreviewSync = null;

    function esc(v) { return window.ConfigUtils ? ConfigUtils.escapeHtml(v) : String(v == null ? '' : v); }
    function toast(msg, type) { if (window.ConfigUtils) ConfigUtils.showToast(msg, type || 'success'); }
    function sel(key) { return (window.CSS && CSS.escape) ? CSS.escape(key) : key; }

    function validateAppKey(e) {
        if (!/^[a-z0-9_]*$/.test(e.target.value)) {
            e.target.classList.add('is-invalid');
            e.target.setCustomValidity('Solo se permiten letras minúsculas, números y guiones bajos');
        } else {
            e.target.classList.remove('is-invalid');
            e.target.setCustomValidity('');
        }
    }

    // Preview del badge (prefix = 'app' para crear, 'editApp' para editar)
    function bindPreview(prefix) {
        var color = document.getElementById(prefix + 'Color');
        var icon = document.getElementById(prefix + 'Icon');
        var badge = document.getElementById(prefix + 'BadgePreview');
        var badgeIcon = document.getElementById(prefix + 'BadgePreviewIcon');
        if (!color || !icon || !badge) return null;
        function sync() {
            badge.style.setProperty('--app-badge-color', color.value || '#6c757d');
            if (badgeIcon) badgeIcon.className = 'bi ' + ((icon.value || '').trim() || 'bi-app') + ' me-1';
        }
        color.addEventListener('input', sync);
        icon.addEventListener('input', sync);
        sync();
        return sync;
    }

    function payload(form, withKey) {
        var fd = new FormData(form);
        var data = {
            name: fd.get('name'),
            is_active: fd.has('is_active'),
            mobile_enabled: fd.has('mobile_enabled'),
            visible_to_students: fd.has('visible_to_students'),
            mobile_url: fd.get('mobile_url') || null,
            mobile_icon: fd.get('mobile_icon') || null,
            color: fd.get('color') || null,
            icon_class: fd.get('icon_class') || null,
        };
        if (withKey) data.key = fd.get('key');
        return data;
    }

    async function handleCreateApp(e) {
        e.preventDefault();
        try {
            var response = await fetch(API + '/authz/apps', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload(e.target, true)),
            });
            var result = await response.json();
            if (response.ok) {
                toast('Aplicación creada correctamente');
                if (createModal) createModal.hide();
                upsertRow(result.data, true);
                e.target.reset();
            } else {
                toast(result.error || 'Error al crear la aplicación', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error creating app:', err);
        }
    }

    function showEditModal(btn) {
        document.getElementById('editAppKey').value = btn.dataset.appKey;
        document.getElementById('editAppName').value = btn.dataset.appName || '';
        document.getElementById('editAppActive').checked = btn.dataset.appActive === 'true';
        document.getElementById('editAppMobileEnabled').checked = btn.dataset.appMobileEnabled === 'true';
        document.getElementById('editAppVisibleStudents').checked = btn.dataset.appVisibleStudents === 'true';
        document.getElementById('editAppMobileUrl').value = btn.dataset.appMobileUrl || '';
        document.getElementById('editAppMobileIcon').value = btn.dataset.appMobileIcon || '';
        document.getElementById('editAppColor').value = btn.dataset.appColor || '#6c757d';
        document.getElementById('editAppIcon').value = btn.dataset.appIcon || '';
        if (editPreviewSync) editPreviewSync();   // re-sincroniza el preview con los valores cargados
        if (editModal) editModal.show();
    }

    async function handleEditApp(e) {
        e.preventDefault();
        var appKey = new FormData(e.target).get('key');
        try {
            var response = await fetch(API + '/authz/apps/' + encodeURIComponent(appKey), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload(e.target, false)),
            });
            var result = await response.json();
            if (response.ok) {
                toast('Aplicación actualizada correctamente');
                if (editModal) editModal.hide();
                upsertRow(result.data, false);
            } else {
                toast(result.error || 'Error al actualizar la aplicación', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error updating app:', err);
        }
    }

    function showDeleteModal(btn) {
        pendingDeleteKey = btn.dataset.appKey;
        document.getElementById('deleteAppName').textContent = btn.dataset.appName || '';
        if (deleteModal) deleteModal.show();
    }

    async function handleDeleteApp() {
        if (!pendingDeleteKey) return;
        try {
            var response = await fetch(API + '/authz/apps/' + encodeURIComponent(pendingDeleteKey), { method: 'DELETE' });
            if (response.ok) {
                toast('Aplicación eliminada correctamente');
                if (deleteModal) deleteModal.hide();
                removeRow(pendingDeleteKey);
            } else {
                var result = await response.json();
                toast(result.error || 'Error al eliminar la aplicación', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error deleting app:', err);
        }
    }

    // Re-render de fila (crear=append, editar=replace). Reemplaza los builders
    // muertos createAppRow/addAppToTable/updateAppInTable. Reproduce las 7
    // columnas del template server-side.
    function rowHtml(app) {
        var active = app.is_active
            ? '<span class="badge bg-success">Activa</span>'
            : '<span class="badge bg-secondary">Inactiva</span>';
        var mobile = app.mobile_enabled
            ? '<span class="badge bg-info"><i class="bi bi-phone me-1"></i>Si</span>'
            : '<span class="badge bg-secondary">No</span>';
        var students = app.visible_to_students
            ? '<span class="badge bg-primary"><i class="bi bi-mortarboard me-1"></i>Si</span>'
            : '<span class="badge bg-secondary">No</span>';
        var created = app.created_at
            ? new Date(app.created_at).toLocaleDateString('es-MX')
            : new Date().toLocaleDateString('es-MX');
        var key = esc(app.key);
        var name = esc(app.name);
        var color = esc(app.color || '#6c757d');
        var icon = esc(app.icon_class || 'bi-app');
        return ''
            + '<td class="px-4 px-sm-3">'
            +   '<span class="app-badge me-2" style="--app-badge-color: ' + color + '"><i class="bi ' + icon + '"></i></span>'
            +   '<code class="bg-light px-2 py-1 rounded small">' + key + '</code>'
            + '</td>'
            + '<td><strong class="d-block text-truncate" style="max-width:150px;">' + name + '</strong></td>'
            + '<td>' + active + '</td>'
            + '<td class="d-none d-md-table-cell">' + mobile + '</td>'
            + '<td class="d-none d-md-table-cell">' + students + '</td>'
            + '<td class="d-none d-md-table-cell"><small class="text-muted">' + created + '</small></td>'
            + '<td class="text-end pe-4"><div class="btn-group btn-group-sm">'
            +   '<a href="/itcj/config/apps/' + encodeURIComponent(app.key) + '/permissions" class="btn btn-outline-primary" title="Gestionar Permisos"><i class="bi bi-key"></i></a>'
            +   '<button class="btn btn-outline-secondary edit-app-btn" ' + editAttrs(app) + ' title="Editar"><i class="bi bi-pencil"></i></button>'
            +   '<button class="btn btn-outline-danger delete-app-btn" data-app-key="' + key + '" data-app-name="' + name + '" title="Eliminar"><i class="bi bi-trash"></i></button>'
            + '</div></td>';
    }

    function editAttrs(app) {
        return 'data-app-key="' + esc(app.key) + '"'
            + ' data-app-name="' + esc(app.name) + '"'
            + ' data-app-active="' + (app.is_active ? 'true' : 'false') + '"'
            + ' data-app-mobile-enabled="' + (app.mobile_enabled ? 'true' : 'false') + '"'
            + ' data-app-visible-students="' + (app.visible_to_students ? 'true' : 'false') + '"'
            + ' data-app-mobile-url="' + esc(app.mobile_url || '') + '"'
            + ' data-app-mobile-icon="' + esc(app.mobile_icon || '') + '"'
            + ' data-app-color="' + esc(app.color || '') + '"'
            + ' data-app-icon="' + esc(app.icon_class || '') + '"';
    }

    function upsertRow(app, isNew) {
        if (!app) return;
        var tbody = document.querySelector('#appsTable tbody');
        if (!tbody) return;
        var existing = tbody.querySelector('tr[data-app-key="' + sel(app.key) + '"]');
        if (existing && !isNew) { existing.innerHTML = rowHtml(app); return; }
        var tr = document.createElement('tr');
        tr.setAttribute('data-app-key', app.key);
        tr.innerHTML = rowHtml(app);
        tbody.appendChild(tr);
        var empty = document.querySelector('.empty-state');
        if (empty) empty.remove();
    }

    function removeRow(appKey) {
        var row = document.querySelector('#appsTable tbody tr[data-app-key="' + sel(appKey) + '"]');
        if (row) row.remove();
    }

    function init() {
        var createForm = document.getElementById('createAppForm');
        if (!createForm) return;   // no estamos en la página de apps

        createForm.addEventListener('submit', handleCreateApp);
        var editForm = document.getElementById('editAppForm');
        if (editForm) editForm.addEventListener('submit', handleEditApp);
        var keyInput = document.getElementById('appKey');
        if (keyInput) keyInput.addEventListener('input', validateAppKey);
        var confirmDelete = document.getElementById('confirmDeleteApp');
        if (confirmDelete) confirmDelete.addEventListener('click', handleDeleteApp);

        createModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('createAppModal'));
        editModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('editAppModal'));
        deleteModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('deleteAppModal'));

        bindPreview('app');
        editPreviewSync = bindPreview('editApp');

        onDocClick = function (e) {
            var editBtn = e.target.closest('.edit-app-btn');
            if (editBtn) { showEditModal(editBtn); return; }
            var delBtn = e.target.closest('.delete-app-btn');
            if (delBtn) { showDeleteModal(delBtn); return; }
        };
        document.addEventListener('click', onDocClick);
    }

    function destroy() {
        if (onDocClick) { document.removeEventListener('click', onDocClick); onDocClick = null; }
        [createModal, editModal, deleteModal].forEach(function (m) {
            if (m) { try { m.hide(); m.dispose(); } catch (e) { /* noop */ } }
        });
        createModal = editModal = deleteModal = null;
        pendingDeleteKey = null;
        editPreviewSync = null;
    }

    if (window.ConfigPage) {
        window.ConfigPage.register('apps', { init: init, destroy: destroy });
    }
})();
