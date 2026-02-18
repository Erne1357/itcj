// apps.js - Gestión de aplicaciones
class AppsManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.init();
    }

    init() {
        this.bindEvents();
        this.initModals();
    }

    bindEvents() {
        // Form submissions
        const createForm = document.getElementById('createAppForm');
        const editForm = document.getElementById('editAppForm');
        
        if (createForm) {
            createForm.addEventListener('submit', (e) => this.handleCreateApp(e));
        }
        
        if (editForm) {
            editForm.addEventListener('submit', (e) => this.handleEditApp(e));
        }

        // Edit buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.edit-app-btn')) {
                const btn = e.target.closest('.edit-app-btn');
                this.showEditModal(btn);
            }
        });

        // Delete buttons
        document.addEventListener('click', (e) => {
            if (e.target.closest('.delete-app-btn')) {
                const btn = e.target.closest('.delete-app-btn');
                this.showDeleteModal(btn);
            }
        });

        // Confirm delete
        const confirmDeleteBtn = document.getElementById('confirmDeleteApp');
        if (confirmDeleteBtn) {
            confirmDeleteBtn.addEventListener('click', () => this.handleDeleteApp());
        }

        // Input validation for app key
        const appKeyInput = document.getElementById('appKey');
        if (appKeyInput) {
            appKeyInput.addEventListener('input', this.validateAppKey);
        }
    }

    initModals() {
        this.createModal = new bootstrap.Modal(document.getElementById('createAppModal'));
        this.editModal = new bootstrap.Modal(document.getElementById('editAppModal'));
        this.deleteModal = new bootstrap.Modal(document.getElementById('deleteAppModal'));
    }

    validateAppKey(e) {
        const value = e.target.value;
        const pattern = /^[a-z0-9_]*$/;
        
        if (!pattern.test(value)) {
            e.target.classList.add('is-invalid');
            e.target.setCustomValidity('Solo se permiten letras minúsculas, números y guiones bajos');
        } else {
            e.target.classList.remove('is-invalid');
            e.target.setCustomValidity('');
        }
    }

    async handleCreateApp(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const data = {
            key: formData.get('key'),
            name: formData.get('name'),
            is_active: formData.has('is_active'),
            mobile_enabled: formData.has('mobile_enabled'),
            visible_to_students: formData.has('visible_to_students'),
            mobile_url: formData.get('mobile_url') || null,
            mobile_icon: formData.get('mobile_icon') || null
        };

        try {
            const response = await fetch(`${this.apiBase}/authz/apps`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Aplicación creada correctamente');
                this.createModal.hide();
                // Reload page to show new app with all data
                location.reload();
            } else {
                this.showError(result.error || 'Error al crear la aplicación');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error creating app:', error);
        }
    }

    showEditModal(btn) {
        const appKey = btn.dataset.appKey;
        const appName = btn.dataset.appName;
        const appActive = btn.dataset.appActive === 'true';
        const appMobileEnabled = btn.dataset.appMobileEnabled === 'true';
        const appVisibleStudents = btn.dataset.appVisibleStudents === 'true';
        const appMobileUrl = btn.dataset.appMobileUrl || '';
        const appMobileIcon = btn.dataset.appMobileIcon || '';

        document.getElementById('editAppKey').value = appKey;
        document.getElementById('editAppName').value = appName;
        document.getElementById('editAppActive').checked = appActive;
        document.getElementById('editAppMobileEnabled').checked = appMobileEnabled;
        document.getElementById('editAppVisibleStudents').checked = appVisibleStudents;
        document.getElementById('editAppMobileUrl').value = appMobileUrl;
        document.getElementById('editAppMobileIcon').value = appMobileIcon;

        this.editModal.show();
    }

    async handleEditApp(e) {
        e.preventDefault();
        
        const formData = new FormData(e.target);
        const appKey = formData.get('key');
        const data = {
            name: formData.get('name'),
            is_active: formData.has('is_active'),
            mobile_enabled: formData.has('mobile_enabled'),
            visible_to_students: formData.has('visible_to_students'),
            mobile_url: formData.get('mobile_url') || null,
            mobile_icon: formData.get('mobile_icon') || null
        };

        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${appKey}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Aplicación actualizada correctamente');
                this.editModal.hide();
                // Reload page to show updated data
                location.reload();
            } else {
                this.showError(result.error || 'Error al actualizar la aplicación');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error updating app:', error);
        }
    }

    showDeleteModal(btn) {
        const appKey = btn.dataset.appKey;
        const appName = btn.dataset.appName;

        this.deleteAppKey = appKey;
        document.getElementById('deleteAppName').textContent = appName;
        this.deleteModal.show();
    }

    async handleDeleteApp() {
        try {
            const response = await fetch(`${this.apiBase}/authz/apps/${this.deleteAppKey}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.showSuccess('Aplicación eliminada correctamente');
                this.deleteModal.hide();
                this.removeAppFromTable(this.deleteAppKey);
            } else {
                const result = await response.json();
                this.showError(result.error || 'Error al eliminar la aplicación');
            }
        } catch (error) {
            this.showError('Error de conexión');
            console.error('Error deleting app:', error);
        }
    }

    addAppToTable(appData) {
        const tbody = document.querySelector('#appsTable tbody');
        const row = this.createAppRow(appData);
        tbody.appendChild(row);
        
        // Remove empty state if present
        const emptyState = document.querySelector('.text-center.py-5');
        if (emptyState) {
            emptyState.remove();
        }
    }

    updateAppInTable(appKey, appData) {
        const row = document.querySelector(`tr[data-app-key="${appKey}"]`);
        if (row) {
            const nameCell = row.querySelector('td:nth-child(2) strong');
            const statusCell = row.querySelector('td:nth-child(3)');
            
            nameCell.textContent = appData.name;
            statusCell.innerHTML = appData.is_active ? 
                '<span class="badge bg-success">Activa</span>' : 
                '<span class="badge bg-secondary">Inactiva</span>';
            
            // Update button data
            const editBtn = row.querySelector('.edit-app-btn');
            editBtn.dataset.appName = appData.name;
            editBtn.dataset.appActive = appData.is_active;
        }
    }

    removeAppFromTable(appKey) {
        const row = document.querySelector(`tr[data-app-key="${appKey}"]`);
        if (row) {
            row.remove();
        }
        
        // Check if table is empty
        const tbody = document.querySelector('#appsTable tbody');
        if (tbody.children.length === 0) {
            location.reload(); // Reload to show empty state
        }
    }

    createAppRow(appData) {
        const row = document.createElement('tr');
        row.setAttribute('data-app-key', appData.key);
        
        const currentDate = new Date().toLocaleDateString('es-ES');
        
        row.innerHTML = `
            <td class="px-4 py-3">
                <code class="bg-light px-2 py-1 rounded">${appData.key}</code>
            </td>
            <td class="py-3">
                <strong>${appData.name}</strong>
            </td>
            <td class="py-3">
                ${appData.is_active ? 
                    '<span class="badge bg-success">Activa</span>' : 
                    '<span class="badge bg-secondary">Inactiva</span>'}
            </td>
            <td class="py-3">
                <small class="text-muted">${currentDate}</small>
            </td>
            <td class="py-3 text-end">
                <div class="btn-group btn-group-sm">
                    <a href="/itcj/config/apps/${appData.key}/permissions" 
                       class="btn btn-outline-primary" title="Gestionar Permisos">
                        <i class="bi bi-key"></i>
                    </a>
                    <button class="btn btn-outline-secondary edit-app-btn" 
                            data-app-key="${appData.key}"
                            data-app-name="${appData.name}"
                            data-app-active="${appData.is_active}"
                            title="Editar">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-outline-danger delete-app-btn" 
                            data-app-key="${appData.key}"
                            data-app-name="${appData.name}"
                            title="Eliminar">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </td>
        `;
        
        return row;
    }

    showSuccess(message) {
        const toast = document.getElementById('successToast');
        const messageEl = document.getElementById('successMessage');
        messageEl.textContent = message;
        
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
    }

    showError(message) {
        const toast = document.getElementById('errorToast');
        const messageEl = document.getElementById('errorMessage');
        messageEl.textContent = message;
        
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new AppsManager();
});