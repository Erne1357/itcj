/* =============================================================================
   Roles globales — módulo del registry ConfigPage (C2).
   init() re-vincula TODO en cada visita (A→B→A recrea los nodos del content);
   destroy() quita el listener de document y dispone los modales.
   Toasts/escape via ConfigUtils (helpers compartidos del shell).
   ============================================================================= */
(function () {
    'use strict';

    var API = '/api/core/v2';
    var createModal = null;
    var onDocClick = null;

    function toast(msg, type) {
        if (window.ConfigUtils) window.ConfigUtils.showToast(msg, type || 'success');
    }

    function esc(v) {
        return window.ConfigUtils ? window.ConfigUtils.escapeHtml(v) : String(v);
    }

    function validateRoleName(e) {
        var value = e.target.value;
        if (!/^[a-z0-9_]*$/.test(value)) {
            e.target.classList.add('is-invalid');
            e.target.setCustomValidity('Solo se permiten letras minúsculas, números y guiones bajos');
        } else {
            e.target.classList.remove('is-invalid');
            e.target.setCustomValidity('');
        }
    }

    async function handleCreateRole(e) {
        e.preventDefault();
        var form = e.target;
        var data = { name: new FormData(form).get('name') };
        try {
            const response = await fetch(API + '/authz/roles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await response.json();
            if (response.ok) {
                toast('Rol creado correctamente');
                if (createModal) createModal.hide();
                addRoleToContainer(result.data);
                form.reset();
            } else {
                toast(result.error || 'Error al crear el rol', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error creating role:', err);
        }
    }

    async function onDeleteRole(roleName) {
        const ok = await AppModal.confirm({
            title: 'Eliminar rol',
            message: `Se eliminara el rol "${roleName}" y sus asignaciones`,
            confirmText: 'Eliminar',
            confirmVariant: 'danger',
        });
        if (!ok) return;

        try {
            const response = await fetch(API + '/authz/roles/' + encodeURIComponent(roleName), {
                method: 'DELETE'
            });
            if (response.ok) {
                toast('Rol eliminado correctamente');
                removeRoleFromContainer(roleName);
            } else {
                const result = await response.json();
                toast(result.error || 'Error al eliminar el rol', 'error');
            }
        } catch (err) {
            toast('Error de conexión', 'error');
            console.error('Error deleting role:', err);
        }
    }

    function addRoleToContainer(roleData) {
        var container = document.getElementById('rolesContainer');
        if (!container || !roleData) return;
        container.appendChild(createRoleCard(roleData));
        var emptyState = document.getElementById('emptyState');
        if (emptyState) emptyState.remove();
    }

    function removeRoleFromContainer(roleName) {
        var card = document.querySelector('[data-role-name="' + roleName + '"]');
        if (card) card.remove();
        var container = document.getElementById('rolesContainer');
        if (container && container.children.length === 0) showEmptyState();
    }

    function createRoleCard(roleData) {
        var name = esc(roleData.name);
        var colDiv = document.createElement('div');
        colDiv.className = 'col-12 col-sm-6 col-lg-4';
        colDiv.setAttribute('data-role-name', roleData.name);
        colDiv.innerHTML = `
            <div class="card h-100 shadow-sm">
                <div class="card-body py-3">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <div class="d-flex align-items-center">
                            <div class="bg-success bg-opacity-10 rounded p-2 me-2 me-sm-3">
                                <i class="bi bi-person-badge text-success"></i>
                            </div>
                            <div>
                                <h5 class="card-title mb-1">${name}</h5>
                                <small class="text-muted">Rol global</small>
                            </div>
                        </div>
                        <div class="dropdown">
                            <button class="btn btn-sm btn-outline-secondary"
                                    data-bs-toggle="dropdown" aria-expanded="false">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu">
                                <li>
                                    <button class="dropdown-item text-danger delete-role-btn"
                                            data-role-name="${name}">
                                        <i class="bi bi-trash me-2"></i>Eliminar Rol
                                    </button>
                                </li>
                            </ul>
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">
                            <i class="bi bi-people me-1"></i>
                            0 usuarios asignados
                        </small>
                    </div>
                </div>
            </div>`;
        return colDiv;
    }

    function showEmptyState() {
        var container = document.getElementById('rolesContainer');
        if (!container) return;
        var emptyDiv = document.createElement('div');
        emptyDiv.id = 'emptyState';
        emptyDiv.className = 'text-center py-5';
        emptyDiv.innerHTML = `
            <i class="bi bi-people display-1 text-muted"></i>
            <h5 class="text-muted mt-3">No hay roles registrados</h5>
            <p class="text-muted">Crea tu primer rol para comenzar</p>`;
        container.parentNode.appendChild(emptyDiv);
    }

    function init() {
        var createForm = document.getElementById('createRoleForm');
        if (!createForm) return;   // no estamos en la página de roles

        // Nodos recreados en cada visita → bind directo seguro (sin flags de módulo)
        createForm.addEventListener('submit', handleCreateRole);

        var nameInput = document.getElementById('roleName');
        if (nameInput) nameInput.addEventListener('input', validateRoleName);

        createModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('createRoleModal'));

        // Delegación en document (cards creadas en runtime) → se limpia en destroy
        onDocClick = function (e) {
            var btn = e.target.closest('.delete-role-btn');
            if (btn) onDeleteRole(btn.dataset.roleName);
        };
        document.addEventListener('click', onDocClick);
    }

    function destroy() {
        if (onDocClick) {
            document.removeEventListener('click', onDocClick);
            onDocClick = null;
        }
        [createModal].forEach(function (m) {
            if (m) { try { m.hide(); m.dispose(); } catch (e) { /* noop */ } }
        });
        createModal = null;
    }

    if (window.ConfigPage) {
        window.ConfigPage.register('roles', { init: init, destroy: destroy });
    }
})();
