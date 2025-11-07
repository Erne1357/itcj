class ProfileManager {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.currentFilter = 'all';
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadActivity();
        this.loadNotifications();
    }

    bindEvents() {
        // Tab change events
        const tabTriggers = document.querySelectorAll('#profileTabs button[data-bs-toggle="tab"]');
        tabTriggers.forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                const targetId = e.target.getAttribute('data-bs-target');
                
                if (targetId === '#activity') {
                    this.loadActivity();
                } else if (targetId === '#notifications') {
                    this.loadNotifications();
                }
            });
        });

        // Activity filter
        const activityFilter = document.getElementById('activityFilter');
        if (activityFilter) {
            activityFilter.addEventListener('change', () => this.loadActivity());
        }

        // Notification filters
        const filterButtons = document.querySelectorAll('input[name="notifFilter"]');
        filterButtons.forEach(button => {
            button.addEventListener('change', (e) => {
                this.currentFilter = e.target.id.replace('notif', '').toLowerCase();
                this.filterNotifications();
            });
        });

        // Mark all as read
        const markAllBtn = document.getElementById('markAllReadBtn');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', () => this.markAllAsRead());
        }

        // Edit profile
        const saveBtn = document.getElementById('saveProfileBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveProfile());
        }

        // Delegated event for marking individual notifications as read
        document.addEventListener('click', (e) => {
            if (e.target.closest('.mark-read-btn')) {
                const btn = e.target.closest('.mark-read-btn');
                const notifId = btn.dataset.notifId;
                this.markNotificationAsRead(notifId);
            }
        });
    }

    async loadActivity() {
        const container = document.getElementById('activityContainer');
        if (!container) return;

        try {
            const filter = document.getElementById('activityFilter')?.value || 7;
            const response = await fetch(`${this.apiBase}/user/me/activity?limit=20`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.renderActivity(result.data);
            } else {
                this.renderActivityEmpty();
            }
        } catch (error) {
            console.error('Error loading activity:', error);
            this.renderActivityError();
        }
    }

    renderActivity(activities) {
        const container = document.getElementById('activityContainer');
        if (!container) return;

        if (activities.length === 0) {
            this.renderActivityEmpty();
            return;
        }

        let html = '';
        activities.forEach(activity => {
            html += `
                <div class="activity-item">
                    <div class="activity-icon app-icon-${activity.app_key}">
                        <i class="${activity.icon || 'bi-circle'}"></i>
                    </div>
                    <div class="activity-content">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <h6 class="mb-0">${activity.action}</h6>
                            <small class="text-muted">${this.formatTimeAgo(activity.created_at)}</small>
                        </div>
                        <p class="text-muted small mb-1">${activity.description}</p>
                        <span class="badge app-badge-${activity.app_key} small">${activity.app_name}</span>
                    </div>
                </div>
            `;
        });

        container.innerHTML = html;
    }

    renderActivityEmpty() {
        const container = document.getElementById('activityContainer');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-clock-history display-4 text-muted"></i>
                    <p class="text-muted mt-3">No hay actividad reciente</p>
                </div>
            `;
        }
    }

    renderActivityError() {
        const container = document.getElementById('activityContainer');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-exclamation-triangle display-4 text-danger"></i>
                    <p class="text-danger mt-3">Error al cargar la actividad</p>
                </div>
            `;
        }
    }

    async loadNotifications() {
        const container = document.getElementById('notificationsContainer');
        if (!container) return;

        try {
            const response = await fetch(`${this.apiBase}/user/me/notifications?limit=50`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.renderNotifications(result.data);
                this.updateNotificationBadge(result.data.unread_count);
            } else {
                this.renderNotificationsEmpty();
            }
        } catch (error) {
            console.error('Error loading notifications:', error);
            this.renderNotificationsError();
        }
    }

    renderNotifications(data) {
        const container = document.getElementById('notificationsContainer');
        if (!container) return;

        const notifications = data.notifications || [];
        
        if (notifications.length === 0) {
            this.renderNotificationsEmpty();
            return;
        }

        // Group notifications by app for filters
        const appCounts = {};
        notifications.forEach(notif => {
            const app = notif.app_name || 'other';
            appCounts[app] = (appCounts[app] || 0) + 1;
        });

        // Update filter buttons
        this.updateFilterButtons(appCounts, notifications.length);

        // Render notifications
        let html = '';
        notifications.forEach(notif => {
            const unreadClass = notif.is_read ? '' : 'unread';
            const appKey = this.getAppKey(notif.app_name);
            
            html += `
                <div class="notification-item ${unreadClass}" data-app="${appKey}" data-notif-id="${notif.id}">
                    ${!notif.is_read ? '<div class="notification-indicator"></div>' : ''}
                    <div class="notification-icon app-icon-${appKey}">
                        <i class="${this.getNotificationIcon(notif.notification_type)}"></i>
                    </div>
                    <div class="notification-content">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <h6 class="mb-0 ${notif.is_read ? 'text-muted' : ''}">${notif.title}</h6>
                            <small class="text-muted">${this.formatTimeAgo(notif.created_at)}</small>
                        </div>
                        <p class="text-muted small mb-2">${notif.message}</p>
                        <div class="d-flex justify-content-between align-items-center">
                            <span class="badge app-badge-${appKey}">${notif.app_name}</span>
                            <div class="notification-actions">
                                ${notif.action_url ? `<a href="${notif.action_url}" class="btn btn-sm btn-primary">Ver</a>` : ''}
                                ${!notif.is_read ? `
                                    <button class="btn btn-sm btn-outline-secondary ms-2 mark-read-btn" data-notif-id="${notif.id}">
                                        <i class="bi bi-check2"></i>
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        container.innerHTML = html;
    }

    updateFilterButtons(appCounts, total) {
        const filterGroup = document.getElementById('notificationFilters');
        if (!filterGroup) return;

        // Keep the "All" filter
        const allBadge = document.getElementById('badgeAll');
        if (allBadge) {
            allBadge.textContent = total;
        }

        // Add app-specific filters
        let hasAppFilters = false;
        Object.entries(appCounts).forEach(([appName, count]) => {
            const appKey = this.getAppKey(appName);
            const filterId = `notif${appKey.charAt(0).toUpperCase() + appKey.slice(1)}`;
            
            // Check if filter already exists
            if (!document.getElementById(filterId)) {
                hasAppFilters = true;
                const html = `
                    <input type="radio" class="btn-check" name="notifFilter" id="${filterId}">
                    <label class="btn btn-outline-secondary" for="${filterId}">
                        ${appName} <span class="badge app-badge-${appKey} ms-1">${count}</span>
                    </label>
                `;
                filterGroup.insertAdjacentHTML('beforeend', html);
                
                // Bind event
                document.getElementById(filterId).addEventListener('change', (e) => {
                    this.currentFilter = appKey;
                    this.filterNotifications();
                });
            }
        });
    }

    filterNotifications() {
        const notifications = document.querySelectorAll('.notification-item');
        
        notifications.forEach(notif => {
            const app = notif.getAttribute('data-app');
            
            if (this.currentFilter === 'all') {
                notif.style.display = 'flex';
            } else {
                notif.style.display = app === this.currentFilter ? 'flex' : 'none';
            }
        });
    }

    async markNotificationAsRead(notifId) {
        try {
            const response = await fetch(`${this.apiBase}/notifications/${notifId}/read`, {
                method: 'PATCH'
            });

            if (response.ok) {
                // Update UI
                const notifItem = document.querySelector(`[data-notif-id="${notifId}"]`);
                if (notifItem) {
                    notifItem.classList.remove('unread');
                    const indicator = notifItem.querySelector('.notification-indicator');
                    if (indicator) indicator.remove();
                    
                    const title = notifItem.querySelector('h6');
                    if (title) title.classList.add('text-muted');
                    
                    const markReadBtn = notifItem.querySelector('.mark-read-btn');
                    if (markReadBtn) markReadBtn.remove();
                }
                
                // Update badge
                this.updateNotificationBadgeCount(-1);
            }
        } catch (error) {
            console.error('Error marking notification as read:', error);
            this.showError('Error al marcar como leída');
        }
    }

    async markAllAsRead() {
        try {
            const response = await fetch(`${this.apiBase}/notifications/mark-all-read`, {
                method: 'POST'
            });

            if (response.ok) {
                this.showSuccess('Todas las notificaciones marcadas como leídas');
                await this.loadNotifications();
            } else {
                this.showError('Error al marcar notificaciones');
            }
        } catch (error) {
            console.error('Error marking all as read:', error);
            this.showError('Error de conexión');
        }
    }

    async saveProfile() {
        const email = document.getElementById('editEmail')?.value;
        
        if (!email) {
            this.showError('El correo electrónico es requerido');
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/user/me/profile`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ email })
            });

            const result = await response.json();

            if (response.ok) {
                this.showSuccess('Perfil actualizado correctamente');
                
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('editProfileModal'));
                if (modal) modal.hide();
                
                // Reload page to reflect changes
                setTimeout(() => window.location.reload(), 1000);
            } else {
                this.showError(result.error || 'Error al actualizar el perfil');
            }
        } catch (error) {
            console.error('Error saving profile:', error);
            this.showError('Error de conexión');
        }
    }

    updateNotificationBadge(count) {
        const badge = document.getElementById('notificationBadge');
        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline' : 'none';
        }
    }

    updateNotificationBadgeCount(delta) {
        const badge = document.getElementById('notificationBadge');
        if (badge) {
            const current = parseInt(badge.textContent) || 0;
            const newCount = Math.max(0, current + delta);
            badge.textContent = newCount;
            badge.style.display = newCount > 0 ? 'inline' : 'none';
        }
    }

    renderNotificationsEmpty() {
        const container = document.getElementById('notificationsContainer');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-bell-slash display-4 text-muted"></i>
                    <p class="text-muted mt-3">No tienes notificaciones</p>
                </div>
            `;
        }
    }

    renderNotificationsError() {
        const container = document.getElementById('notificationsContainer');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-exclamation-triangle display-4 text-danger"></i>
                    <p class="text-danger mt-3">Error al cargar notificaciones</p>
                </div>
            `;
        }
    }

    getAppKey(appName) {
        const mapping = {
            'ITCJ Core': 'core',
            'AgendaTec': 'agendatec',
            'Help Desk': 'helpdesk',
            'Tickets': 'tickets'
        };
        return mapping[appName] || 'other';
    }

    getNotificationIcon(type) {
        const icons = {
            'info': 'bi-info-circle',
            'success': 'bi-check-circle',
            'warning': 'bi-exclamation-triangle',
            'error': 'bi-x-circle',
            'assignment': 'bi-person-check',
            'comment': 'bi-chat-dots',
            'status_change': 'bi-arrow-repeat',
            'reminder': 'bi-bell'
        };
        return icons[type] || 'bi-bell';
    }

    formatTimeAgo(dateString) {
        if (!dateString) return '';
        
        const date = new Date(dateString);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000); // seconds

        if (diff < 60) return 'Hace unos segundos';
        if (diff < 3600) return `Hace ${Math.floor(diff / 60)} minutos`;
        if (diff < 86400) return `Hace ${Math.floor(diff / 3600)} horas`;
        if (diff < 604800) return `Hace ${Math.floor(diff / 86400)} días`;
        
        return date.toLocaleDateString('es-ES');
    }

    showSuccess(message) {
        const toast = document.getElementById('successToast');
        const messageEl = document.getElementById('successMessage');
        if (toast && messageEl) {
            messageEl.textContent = message;
            const bsToast = new bootstrap.Toast(toast);
            bsToast.show();
        }
    }

    showError(message) {
        const toast = document.getElementById('errorToast');
        const messageEl = document.getElementById('errorMessage');
        if (toast && messageEl) {
            messageEl.textContent = message;
            const bsToast = new bootstrap.Toast(toast);
            bsToast.show();
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new ProfileManager();
});