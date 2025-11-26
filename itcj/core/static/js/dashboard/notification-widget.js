/**
 * Widget de Notificaciones para el Dashboard
 *
 * Muestra un icono de campana en la taskbar con badge de notificaciones no leídas,
 * panel desplegable con notificaciones recientes, y actualización en tiempo real vía SSE.
 *
 * Uso:
 *   // El widget se inicializa automáticamente al cargar
 *   // Requiere: NotificationSSEClient.js cargado previamente
 */

class DashboardNotificationWidget {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.sseClient = null;
        this.notifications = [];
        this.counts = {};
        this.totalUnread = 0;
        this.panelOpen = false;

        this.init();
    }

    init() {
        this.injectHTML();
        this.attachEventListeners();
        this.loadInitialCounts();
        this.connectSSE();
    }

    /**
     * Inyecta el HTML del widget en el dashboard
     */
    injectHTML() {
        const systemTray = document.querySelector('.system-tray');
        if (!systemTray) {
            console.error('[NotificationWidget] System tray not found');
            return;
        }

        // Insertar icono de campana antes del datetime
        const bellHTML = `
            <button class="system-icon" id="notification-bell" title="Notificaciones">
                <i data-lucide="bell"></i>
                <span class="notification-badge" id="notification-badge" hidden>0</span>
            </button>
        `;

        const datetime = systemTray.querySelector('.datetime');
        if (datetime) {
            datetime.insertAdjacentHTML('beforebegin', bellHTML);
        } else {
            systemTray.insertAdjacentHTML('beforeend', bellHTML);
        }

        // Panel desplegable
        const panelHTML = `
            <div class="notification-panel" id="notification-panel" hidden>
                <div class="notification-panel-header">
                    <h6 class="mb-0">Notificaciones</h6>
                    <button class="btn btn-sm btn-link" id="mark-all-read-btn">
                        <i data-lucide="check-check"></i> Marcar todas
                    </button>
                </div>
                <div class="notification-panel-body" id="notification-list">
                    <div class="text-center py-4 text-muted">
                        <i data-lucide="inbox"></i>
                        <p class="small mb-0 mt-2">Cargando...</p>
                    </div>
                </div>
                <div class="notification-panel-footer">
                    <a href="/profile?tab=notifications" class="btn btn-sm btn-primary w-100">
                        Ver todas las notificaciones
                    </a>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', panelHTML);

        // Inicializar iconos lucide si está disponible
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }

    /**
     * Adjunta event listeners
     */
    attachEventListeners() {
        // Toggle panel
        const bellBtn = document.getElementById('notification-bell');
        if (bellBtn) {
            bellBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.togglePanel();
            });
        }

        // Marcar todas como leídas
        const markAllBtn = document.getElementById('mark-all-read-btn');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', () => {
                this.markAllAsRead();
            });
        }

        // Cerrar panel al hacer click fuera
        document.addEventListener('click', (e) => {
            const panel = document.getElementById('notification-panel');
            const bell = document.getElementById('notification-bell');

            if (panel && !panel.contains(e.target) && !bell.contains(e.target)) {
                this.closePanel();
            }
        });
    }

    /**
     * Carga conteos iniciales desde la API
     */
    async loadInitialCounts() {
        try {
            const response = await fetch(`${this.apiBase}/notifications/unread-counts`, {
                credentials: 'include'
            });

            if (response.ok) {
                const result = await response.json();
                this.updateCounts(result.data.counts, result.data.total);
            }
        } catch (error) {
            console.error('[NotificationWidget] Error loading counts:', error);
        }
    }

    /**
     * Conecta al stream SSE
     */
    connectSSE() {
        if (!window.NotificationSSEClient) {
            console.error('[NotificationWidget] NotificationSSEClient not loaded');
            return;
        }

        this.sseClient = new NotificationSSEClient(this.apiBase);

        // Evento: conectado
        this.sseClient.on('connected', (data) => {
            console.log('[NotificationWidget] SSE connected', data);
            if (data.counts) {
                this.updateCounts(data.counts, data.total_unread);
            }
        });

        // Evento: nueva notificación
        this.sseClient.on('notification', (notification) => {
            this.handleNewNotification(notification);
        });

        // Evento: conteos actualizados
        this.sseClient.on('counts', (counts) => {
            const total = Object.values(counts).reduce((a, b) => a + b, 0);
            this.updateCounts(counts, total);
        });

        // Evento: error
        this.sseClient.on('error', (error) => {
            console.error('[NotificationWidget] SSE error:', error);
        });

        // Conectar
        this.sseClient.connect();
    }

    /**
     * Actualiza los conteos de notificaciones
     */
    updateCounts(counts, total) {
        this.counts = counts;
        this.totalUnread = total;

        // Actualizar badge
        const badge = document.getElementById('notification-badge');
        if (badge) {
            if (total > 0) {
                badge.textContent = total > 99 ? '99+' : total;
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }
        }

        // Actualizar badges en iconos de apps del escritorio
        this.updateAppBadges();
    }

    /**
     * Actualiza badges en iconos de aplicaciones
     */
    updateAppBadges() {
        // Iterar sobre cada app con notificaciones
        for (const [appName, count] of Object.entries(this.counts)) {
            const appIcon = document.querySelector(`.desktop-icon[data-app="${appName}"]`);
            if (!appIcon) continue;

            // Buscar o crear badge
            let badge = appIcon.querySelector('.app-notification-badge');

            if (count > 0) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'app-notification-badge';
                    appIcon.appendChild(badge);
                }
                badge.textContent = count > 99 ? '99+' : count;
                badge.hidden = false;
            } else if (badge) {
                badge.hidden = true;
            }
        }
    }

    /**
     * Maneja una nueva notificación en tiempo real
     */
    handleNewNotification(notification) {
        // Agregar al inicio de la lista
        this.notifications.unshift(notification);

        // Mantener solo las 10 más recientes
        if (this.notifications.length > 10) {
            this.notifications = this.notifications.slice(0, 10);
        }

        // Incrementar conteo
        const appName = notification.app_name;
        this.counts[appName] = (this.counts[appName] || 0) + 1;
        this.totalUnread++;

        this.updateCounts(this.counts, this.totalUnread);

        // Si el panel está abierto, actualizar lista
        if (this.panelOpen) {
            this.renderNotifications();
        }

        // Mostrar toast
        this.showToast(notification);
    }

    /**
     * Toggle del panel
     */
    async togglePanel() {
        this.panelOpen = !this.panelOpen;

        const panel = document.getElementById('notification-panel');
        if (panel) {
            panel.hidden = !this.panelOpen;

            if (this.panelOpen) {
                await this.loadRecentNotifications();
                this.renderNotifications();
            }
        }
    }

    /**
     * Cierra el panel
     */
    closePanel() {
        this.panelOpen = false;
        const panel = document.getElementById('notification-panel');
        if (panel) {
            panel.hidden = true;
        }
    }

    /**
     * Carga notificaciones recientes
     */
    async loadRecentNotifications() {
        try {
            const response = await fetch(`${this.apiBase}/notifications?limit=10`, {
                credentials: 'include'
            });

            if (response.ok) {
                const result = await response.json();
                this.notifications = result.data.items;
            }
        } catch (error) {
            console.error('[NotificationWidget] Error loading notifications:', error);
        }
    }

    /**
     * Renderiza la lista de notificaciones
     */
    renderNotifications() {
        const list = document.getElementById('notification-list');
        if (!list) return;

        if (this.notifications.length === 0) {
            list.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i data-lucide="inbox"></i>
                    <p class="small mb-0 mt-2">No hay notificaciones</p>
                </div>
            `;

            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
            return;
        }

        const html = this.notifications.map(n => this.renderNotificationItem(n)).join('');
        list.innerHTML = html;

        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }

        // Attach click listeners
        list.querySelectorAll('.notification-item').forEach(item => {
            item.addEventListener('click', (e) => {
                const id = parseInt(item.dataset.id);
                const url = item.dataset.url;

                if (!item.classList.contains('read')) {
                    this.markAsRead(id);
                }

                if (url) {
                    window.location.href = url;
                }
            });
        });
    }

    /**
     * Renderiza un item de notificación
     */
    renderNotificationItem(notification) {
        const isUnread = !notification.is_read;
        const icon = notification.app_icon || 'bi-bell';
        const color = notification.app_color || 'secondary';
        const url = notification.action_url || '';
        const timeAgo = this.getTimeAgo(notification.created_at);

        return `
            <div class="notification-item ${isUnread ? 'unread' : 'read'}"
                 data-id="${notification.id}"
                 data-url="${url}">
                <div class="notification-icon bg-${color}">
                    <i class="${icon}"></i>
                </div>
                <div class="notification-content">
                    <div class="notification-title">${notification.title}</div>
                    ${notification.body ? `<div class="notification-body">${notification.body}</div>` : ''}
                    <div class="notification-meta">
                        <span class="app-tag badge bg-${color}">${notification.app_name}</span>
                        <span class="time">${timeAgo}</span>
                    </div>
                </div>
                ${isUnread ? '<div class="unread-indicator"></div>' : ''}
            </div>
        `;
    }

    /**
     * Marca una notificación como leída
     */
    async markAsRead(notificationId) {
        try {
            const response = await fetch(`${this.apiBase}/notifications/${notificationId}/read`, {
                method: 'PATCH',
                credentials: 'include'
            });

            if (response.ok) {
                // Actualizar localmente
                const notif = this.notifications.find(n => n.id === notificationId);
                if (notif && !notif.is_read) {
                    notif.is_read = true;

                    // Decrementar conteo
                    const appName = notif.app_name;
                    this.counts[appName] = Math.max(0, (this.counts[appName] || 1) - 1);
                    this.totalUnread = Math.max(0, this.totalUnread - 1);

                    this.updateCounts(this.counts, this.totalUnread);
                    this.renderNotifications();
                }
            }
        } catch (error) {
            console.error('[NotificationWidget] Error marking as read:', error);
        }
    }

    /**
     * Marca todas las notificaciones como leídas
     */
    async markAllAsRead() {
        try {
            const response = await fetch(`${this.apiBase}/notifications/mark-all-read`, {
                method: 'PATCH',
                credentials: 'include'
            });

            if (response.ok) {
                // Actualizar localmente
                this.notifications.forEach(n => n.is_read = true);
                this.counts = {};
                this.totalUnread = 0;

                this.updateCounts(this.counts, this.totalUnread);
                this.renderNotifications();

                this.showToast({ title: 'Todas las notificaciones marcadas como leídas', app_name: 'core' });
            }
        } catch (error) {
            console.error('[NotificationWidget] Error marking all as read:', error);
        }
    }

    /**
     * Muestra un toast de notificación
     */
    showToast(notification) {
        // Implementación simple de toast
        const toast = document.createElement('div');
        toast.className = 'notification-toast';
        toast.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="${notification.app_icon || 'bi-bell'} me-2"></i>
                <div>
                    <div class="fw-bold">${notification.title}</div>
                    ${notification.body ? `<div class="small">${notification.body}</div>` : ''}
                </div>
            </div>
        `;

        document.body.appendChild(toast);

        setTimeout(() => toast.classList.add('show'), 10);

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    }

    /**
     * Calcula tiempo relativo (time ago)
     */
    getTimeAgo(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return 'Ahora';
        if (seconds < 3600) return `Hace ${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `Hace ${Math.floor(seconds / 3600)}h`;
        if (seconds < 604800) return `Hace ${Math.floor(seconds / 86400)}d`;

        return date.toLocaleDateString('es-MX');
    }
}

// Auto-inicializar cuando el DOM esté listo
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.dashboardNotificationWidget = new DashboardNotificationWidget();
    });
} else {
    window.dashboardNotificationWidget = new DashboardNotificationWidget();
}
