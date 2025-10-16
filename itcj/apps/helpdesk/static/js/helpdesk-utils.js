// itcj/apps/helpdesk/static/js/helpdesk-utils.js

/**
 * HelpDesk Utilities - Funciones compartidas para toda la app
 */

// ==================== API CLIENT ====================
class HelpdeskAPI {
    constructor() {
        this.baseURL = '/api/help-desk/v1';
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };

        try {
            const response = await fetch(url, config);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    // Tickets
    async getTickets(filters = {}) {
        const params = new URLSearchParams(filters);
        return this.request(`/tickets?${params}`);
    }

    async getTicket(ticketId) {
        return this.request(`/tickets/${ticketId}`);
    }

    async createTicket(data) {
        return this.request('/tickets', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async startTicket(ticketId) {
        return this.request(`/tickets/${ticketId}/start`, { method: 'POST' });
    }

    async resolveTicket(ticketId, data) {
        return this.request(`/tickets/${ticketId}/resolve`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async rateTicket(ticketId, data) {
        return this.request(`/tickets/${ticketId}/rate`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async cancelTicket(ticketId, reason) {
        return this.request(`/tickets/${ticketId}/cancel`, {
            method: 'POST',
            body: JSON.stringify({ reason })
        });
    }

    // Comments
    async getComments(ticketId) {
        return this.request(`/tickets/${ticketId}/comments`);
    }

    async addComment(ticketId, content, isInternal = false) {
        return this.request(`/tickets/${ticketId}/comments`, {
            method: 'POST',
            body: JSON.stringify({ content, is_internal: isInternal })
        });
    }

    // Categories
    async getCategories(area = null) {
        const params = area ? `?area=${area}` : '';
        return this.request(`/categories${params}`);
    }

    // Assignments
    async assignTicket(ticketId, assignedToUserId, assignedToTeam, reason) {
        return this.request('/assignments', {
            method: 'POST',
            body: JSON.stringify({
                ticket_id: ticketId,
                assigned_to_user_id: assignedToUserId,
                assigned_to_team: assignedToTeam,
                reason
            })
        });
    }

    async selfAssignTicket(ticketId) {
        return this.request(`/assignments/${ticketId}/self-assign`, { method: 'POST' });
    }

    async getTeamTickets(teamName) {
        return this.request(`/assignments/team/${teamName}`);
    }
}

// Instancia global
const api = new HelpdeskAPI();


// ==================== TOAST NOTIFICATIONS ====================
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toastId = `toast-${Date.now()}`;
    const bgClass = {
        success: 'bg-success',
        error: 'bg-danger',
        warning: 'bg-warning',
        info: 'bg-info'
    }[type] || 'bg-primary';

    const icon = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    }[type] || 'fa-bell';

    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = 'toast align-items-center text-white border-0';
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body ${bgClass} rounded d-flex align-items-center gap-2">
                <i class="fas ${icon}"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;

    container.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
    bsToast.show();

    toast.addEventListener('hidden.bs.toast', () => toast.remove());
}


// ==================== FORMATTING HELPERS ====================
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('es-MX', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatTimeAgo(dateString) {
    if (!dateString) return 'N/A';
    
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Hace un momento';
    if (diffMins < 60) return `Hace ${diffMins} min`;
    if (diffHours < 24) return `Hace ${diffHours}h`;
    if (diffDays < 7) return `Hace ${diffDays} día${diffDays > 1 ? 's' : ''}`;
    
    return formatDate(dateString);
}


// ==================== STATUS & PRIORITY BADGES ====================
function getStatusBadge(status) {
    const statusMap = {
        'PENDING': { class: 'bg-secondary', icon: 'fa-clock', text: 'Pendiente' },
        'ASSIGNED': { class: 'bg-info', icon: 'fa-user-check', text: 'Asignado' },
        'IN_PROGRESS': { class: 'bg-warning', icon: 'fa-cog', text: 'En Progreso' },
        'RESOLVED_SUCCESS': { class: 'bg-success', icon: 'fa-check-circle', text: 'Resuelto' },
        'RESOLVED_FAILED': { class: 'bg-danger', icon: 'fa-times-circle', text: 'No Resuelto' },
        'CLOSED': { class: 'bg-dark', icon: 'fa-lock', text: 'Cerrado' },
        'CANCELED': { class: 'bg-secondary', icon: 'fa-ban', text: 'Cancelado' }
    };

    const config = statusMap[status] || statusMap['PENDING'];
    return `<span class="badge ${config.class}">
        <i class="fas ${config.icon} me-1"></i>${config.text}
    </span>`;
}

function getPriorityBadge(priority) {
    const priorityMap = {
        'BAJA': { class: 'bg-success', icon: 'fa-arrow-down' },
        'MEDIA': { class: 'bg-warning', icon: 'fa-minus' },
        'ALTA': { class: 'bg-danger', icon: 'fa-arrow-up' },
        'URGENTE': { class: 'bg-dark', icon: 'fa-fire', pulse: true }
    };

    const config = priorityMap[priority] || priorityMap['MEDIA'];
    return `<span class="badge ${config.class} ${config.pulse ? 'priority-pulse' : ''}">
        <i class="fas ${config.icon} me-1"></i>${priority}
    </span>`;
}

function getAreaBadge(area) {
    const areaMap = {
        'DESARROLLO': { class: 'bg-primary', icon: 'fa-code', text: 'Desarrollo' },
        'SOPORTE': { class: 'bg-info', icon: 'fa-wrench', text: 'Soporte' }
    };

    const config = areaMap[area] || areaMap['SOPORTE'];
    return `<span class="badge ${config.class}">
        <i class="fas ${config.icon} me-1"></i>${config.text}
    </span>`;
}


// ==================== STAR RATING ====================
function renderStarRating(rating, size = '1x') {
    let html = '';
    for (let i = 1; i <= 5; i++) {
        const icon = i <= rating ? 'fas fa-star' : 'far fa-star';
        const color = i <= rating ? 'text-warning' : 'text-muted';
        html += `<i class="${icon} ${color} fa-${size}"></i>`;
    }
    return html;
}


// ==================== LOADING STATE ====================
function showLoading(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;

    element.innerHTML = `
        <div class="text-center py-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Cargando...</span>
            </div>
            <p class="text-muted mt-3">Cargando información...</p>
        </div>
    `;
}

function showEmpty(elementId, message = 'No hay tickets disponibles') {
    const element = document.getElementById(elementId);
    if (!element) return;

    element.innerHTML = `
        <div class="text-center py-5">
            <i class="fas fa-inbox fa-3x text-muted mb-3"></i>
            <p class="text-muted">${message}</p>
        </div>
    `;
}


// ==================== CONFIRMATION DIALOG ====================
async function confirmDialog(title, message, confirmText = 'Confirmar', cancelText = 'Cancelar') {
    return new Promise((resolve) => {
        const modalId = `modal-${Date.now()}`;
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = modalId;
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${title}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        ${message}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">${cancelText}</button>
                        <button type="button" class="btn btn-primary" id="confirm-btn">${confirmText}</button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        modal.querySelector('#confirm-btn').addEventListener('click', () => {
            bsModal.hide();
            resolve(true);
        });

        modal.addEventListener('hidden.bs.modal', () => {
            modal.remove();
            resolve(false);
        });
    });
}


// ==================== SMART NAVIGATION ====================
function goToTicketDetail(ticketId, fromPage = null) {
    // Determinar fromPage automáticamente si no se proporciona
    if (!fromPage) {
        const currentPath = window.location.pathname;
        if (currentPath.includes('/user/tickets')) {
            fromPage = 'my_tickets';
        } else if (currentPath.includes('/department')) {
            fromPage = 'department';
        } else if (currentPath.includes('/admin') || currentPath.includes('/technician')) {
            fromPage = 'admin';
        } else if (currentPath.includes('/user')) {
            fromPage = 'dashboard';
        }
    }
    
    const url = fromPage ? 
        `/help-desk/user/tickets/${ticketId}?from=${fromPage}` :
        `/help-desk/user/tickets/${ticketId}`;
    
    window.location.href = url;
}

function goToTicketDetailNewTab(ticketId, fromPage = null) {
    const currentPath = window.location.pathname;
    if (!fromPage) {
        if (currentPath.includes('/department')) {
            fromPage = 'department';
        } else if (currentPath.includes('/admin') || currentPath.includes('/technician')) {
            fromPage = 'admin';
        }
    }
    
    const url = fromPage ? 
        `/help-desk/user/tickets/${ticketId}?from=${fromPage}` :
        `/help-desk/user/tickets/${ticketId}`;
    
    window.open(url, '_blank');
}

// ==================== EXPORT ====================
window.HelpdeskUtils = {
    api,
    showToast,
    formatDate,
    formatTimeAgo,
    getStatusBadge,
    getPriorityBadge,
    getAreaBadge,
    renderStarRating,
    showLoading,
    showEmpty,
    confirmDialog,
    goToTicketDetail,
    goToTicketDetailNewTab
};