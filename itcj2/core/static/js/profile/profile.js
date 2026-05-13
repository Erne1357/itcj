class ProfileManager {
    constructor() {
        this.apiBase = '/api/core/v2';
        this.currentFilter = 'all';
        this.readStatusFilter = 'all';
        this.dateRangeFilter = 'week';
        this.socket = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadActivity();
        this.loadNotifications();
        this.connectWebSocket();

        // Make instance globally accessible for SSE
        window.profileManager = this;
    }

    /**
     * Conecta al WS /notify para sincronizar:
     *  - notify          → llega notificación nueva: refrescar lista
     *  - notification:read → se marcó leída en otro lugar: refrescar
     */
    connectWebSocket() {
        const ensureIO = () => new Promise((resolve, reject) => {
            if (window.io) return resolve();
            const s = document.createElement('script');
            s.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
            s.crossOrigin = 'anonymous';
            s.onload = () => resolve();
            s.onerror = reject;
            document.head.appendChild(s);
        });

        ensureIO().then(() => {
            if (window.__notifySocket) {
                this.socket = window.__notifySocket;
            } else {
                this.socket = window.io('/notify', {
                    withCredentials: true,
                    reconnection: true,
                    transports: ['websocket', 'polling'],
                });
                window.__notifySocket = this.socket;
            }

            this.socket.on('notify', () => {
                // Refrescar lista para mostrar la nueva
                this.loadNotifications();
            });

            this.socket.on('notification:read', () => {
                // Estado cambió desde otro tab/iframe — re-render
                this.loadNotifications();
            });
        }).catch(err => {
            console.warn('[ProfileManager] socket.io load failed:', err);
        });
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

        // Notification filters - App filter
        const filterButtons = document.querySelectorAll('input[name="notifFilter"]');
        filterButtons.forEach(button => {
            button.addEventListener('change', (e) => {
                this.currentFilter = e.target.id.replace('notif', '').toLowerCase();
                this.filterNotifications();
            });
        });

        // Notification filters - Read/Unread status
        const readStatusFilter = document.getElementById('readStatusFilter');
        if (readStatusFilter) {
            readStatusFilter.addEventListener('change', (e) => {
                this.readStatusFilter = e.target.value;
                this.filterNotifications();
            });
        }

        // Notification filters - Date range
        const dateRangeFilter = document.getElementById('dateRangeFilter');
        if (dateRangeFilter) {
            dateRangeFilter.addEventListener('change', (e) => {
                this.dateRangeFilter = e.target.value;
                this.filterNotifications();
            });
        }

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
                return;
            }

            // Interceptar click en boton "Ver" de notificacion → abrir como ventana
            const notifLink = e.target.closest('.notification-action-link');
            if (notifLink) {
                e.preventDefault();
                const url = notifLink.getAttribute('href') || notifLink.dataset.url;
                const notifId = notifLink.dataset.notifId;
                if (notifId) {
                    this.markNotificationAsRead(notifId);
                }
                this.openNotificationUrl(url);
            }
        });
    }

    /**
     * Mapea una URL a un appId del dashboard.
     */
    detectAppId(url) {
        if (!url) return null;
        if (url.includes('/agendatec')) return 'agendatec';
        if (url.includes('/help-desk')) return 'helpdesk';
        if (url.includes('/maint')) return 'maint';
        if (url.includes('/vistetec')) return 'vistetec';
        if (url.includes('/compras')) return 'compras';
        if (url.includes('/itcj/config')) return 'settings';
        if (url.includes('/itcj/profile')) return 'profile';
        return null;
    }

    /**
     * Abre el URL de la notificacion como ventana del dashboard.
     * Si profile esta dentro de un iframe → usa parent.desktop API.
     * Si esta en top-level → window.location fallback.
     */
    openNotificationUrl(url) {
        if (!url) return;

        const appId = this.detectAppId(url);
        const isIframe = window.self !== window.top;

        // Resolver objeto desktop (vive en el dashboard padre)
        let desktopApi = null;
        try {
            if (isIframe && window.parent && window.parent.desktop) {
                desktopApi = window.parent.desktop;
            } else if (!isIframe && window.desktop) {
                desktopApi = window.desktop;
            }
        } catch (err) {
            // Cross-origin: parent inaccesible. Fallback abajo.
            desktopApi = null;
        }

        if (appId && desktopApi && typeof desktopApi.openApplication === 'function') {
            desktopApi.openApplication(appId);

            // Navegar dentro del iframe de la app a la URL especifica
            // Dar tiempo a createWindow si es la primera vez
            const navigateToUrl = () => {
                try {
                    const parentDoc = isIframe ? window.parent.document : document;
                    const iframe = parentDoc.querySelector(`[data-app-id="${appId}"] .window-iframe`);
                    if (iframe) {
                        try {
                            iframe.contentWindow.location.href = url;
                        } catch (_) {
                            iframe.src = url;
                        }
                    }
                } catch (err) {
                    console.warn('[ProfileManager] navigateToUrl failed:', err);
                }
            };

            // Si root del app, no necesita navegacion adicional
            const isRootUrl = url.endsWith('/agendatec') || url.endsWith('/agendatec/')
                           || url.endsWith('/help-desk') || url.endsWith('/help-desk/')
                           || url.endsWith('/maint') || url.endsWith('/maint/')
                           || url.endsWith('/vistetec') || url.endsWith('/vistetec/');
            if (!isRootUrl) {
                setTimeout(navigateToUrl, 500);
            }
        } else {
            // Sin desktop API: navegar directo (peor caso)
            window.location.href = url;
        }
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
            const response = await fetch(`${this.apiBase}/notifications?limit=50`);
            const result = await response.json();

            if (response.ok && result.data) {
                this.renderNotifications(result.data);
                this.updateNotificationBadge(result.data.unread);
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

        const notifications = data.items || [];

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
            const unreadClass = notif.is_read ? 'read' : 'unread';
            const appKey = this.getAppKeyFromName(notif.app_name);
            const icon = notif.app_icon || 'bi-bell';
            const color = notif.app_color || 'secondary';

            html += `
                <div class="notification-item ${unreadClass}"
                     data-app="${appKey}"
                     data-notif-id="${notif.id}"
                     data-created="${notif.created_at}">
                    ${!notif.is_read ? '<div class="notification-indicator"></div>' : ''}
                    <div class="notification-icon bg-${color}">
                        <i class="${icon}"></i>
                    </div>
                    <div class="notification-content">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <h6 class="mb-0 ${notif.is_read ? 'text-muted' : ''}">${notif.title}</h6>
                            <small class="text-muted">${this.formatTimeAgo(notif.created_at)}</small>
                        </div>
                        ${notif.body ? `<p class="text-muted small mb-2">${notif.body}</p>` : ''}
                        <div class="d-flex justify-content-between align-items-center">
                            <span class="badge bg-${color}">${notif.app_name}</span>
                            <div class="notification-actions">
                                ${notif.action_url ? `<a href="${notif.action_url}"
                                    class="btn btn-sm btn-primary notification-action-link"
                                    data-notif-id="${notif.id}"
                                    data-url="${notif.action_url}">Ver</a>` : ''}
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

        // Apply current filters
        this.filterNotifications();
    }

    updateFilterButtons(appCounts, total) {
        const filterGroup = document.getElementById('notificationFilters');
        if (!filterGroup) return;

        // Update "All" badge
        const allBadge = document.getElementById('badgeAll');
        if (allBadge) {
            allBadge.textContent = total;
        }

        // Limpiar filtros dinámicos previos (mantener solo "All")
        filterGroup.querySelectorAll('[data-dynamic-filter="1"]').forEach(el => el.remove());

        // Generar dinámicamente: una entrada por cada app_name presente
        Object.entries(appCounts)
            .sort((a, b) => b[1] - a[1])  // mayor count primero
            .forEach(([appName, count]) => {
                const appKey = this.getAppKey(appName);
                const displayName = this.getAppDisplayName(appKey);
                const safeKey = appKey.replace(/[^a-z0-9_-]/gi, '');
                const filterId = `notif-${safeKey}`;

                const inputHtml = `
                    <input type="radio" class="btn-check" name="notifFilter"
                           id="${filterId}" data-dynamic-filter="1" data-app-key="${appKey}">
                    <label class="btn btn-outline-secondary btn-sm" for="${filterId}"
                           data-dynamic-filter="1">
                        ${displayName}
                        <span class="badge bg-secondary ms-1">${count}</span>
                    </label>
                `;
                filterGroup.insertAdjacentHTML('beforeend', inputHtml);

                document.getElementById(filterId).addEventListener('change', () => {
                    this.currentFilter = appKey;
                    this.filterNotifications();
                });
            });

        // Si el filtro activo desapareció (app sin notificaciones), reset a "All"
        const activeRadio = document.querySelector('input[name="notifFilter"]:checked');
        if (!activeRadio) {
            const allRadio = document.getElementById('notifAll');
            if (allRadio) {
                allRadio.checked = true;
                this.currentFilter = 'all';
            }
        }
    }

    filterNotifications() {
        const notifications = document.querySelectorAll('.notification-item');
        const now = new Date();

        notifications.forEach(notif => {
            const app = notif.getAttribute('data-app');
            const isRead = notif.classList.contains('read') || !notif.classList.contains('unread');
            const createdAt = new Date(notif.getAttribute('data-created'));

            let showNotif = true;

            // Filter by app
            if (this.currentFilter !== 'all') {
                showNotif = showNotif && (app === this.currentFilter);
            }

            // Filter by read status
            if (this.readStatusFilter === 'unread') {
                showNotif = showNotif && !isRead;
            } else if (this.readStatusFilter === 'read') {
                showNotif = showNotif && isRead;
            }

            // Filter by date range
            if (this.dateRangeFilter !== 'all' && createdAt) {
                const daysDiff = Math.floor((now - createdAt) / (1000 * 60 * 60 * 24));

                switch (this.dateRangeFilter) {
                    case 'today':
                        showNotif = showNotif && (daysDiff === 0);
                        break;
                    case 'week':
                        showNotif = showNotif && (daysDiff <= 7);
                        break;
                    case 'month':
                        showNotif = showNotif && (daysDiff <= 30);
                        break;
                    case '3months':
                        showNotif = showNotif && (daysDiff <= 90);
                        break;
                }
            }

            notif.style.display = showNotif ? 'flex' : 'none';
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
                method: 'PATCH'
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
        // app_name viene ya como key raw ('helpdesk', 'maint', etc).
        // Mapping legacy para casos donde llegue display name.
        if (!appName) return 'other';
        const lower = String(appName).trim().toLowerCase();
        const legacyMap = {
            'itcj core': 'core',
            'agendatec': 'agendatec',
            'help desk': 'helpdesk',
            'vistetec': 'vistetec',
            'mantenimiento': 'maint',
            'tickets': 'tickets',
        };
        return legacyMap[lower] || lower;
    }

    getAppDisplayName(appKey) {
        const names = {
            'agendatec': 'AgendaTec',
            'helpdesk': 'Help Desk',
            'maint': 'Mantenimiento',
            'vistetec': 'VisteTec',
            'warehouse': 'Almacén',
            'inventory': 'Inventario',
            'core': 'Sistema',
        };
        if (names[appKey]) return names[appKey];
        // Fallback: capitalizar primera letra
        return appKey ? appKey.charAt(0).toUpperCase() + appKey.slice(1) : 'Otro';
    }

    getAppKeyFromName(appName) {
        return this.getAppKey(appName);
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