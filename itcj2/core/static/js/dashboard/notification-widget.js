/**
 * Widget de Notificaciones del escritorio (/itcj/dashboard)
 *
 * Campana de la bandeja del sistema con badge de no leídas, panel desplegable con
 * las notificaciones recientes y actualización en vivo vía WebSocket (/notify).
 * Los badges de apps son cualquier `[data-badge-for="<badge_key>"]` del documento.
 *
 * Depende de `window.desktop` (boot.js: openUrl/openProfile) y de
 * `window.ItcjDesktop.icon` (icons.js); ambos se resuelven de forma perezosa
 * porque boot.js arranca en DOMContentLoaded, después de este script.
 * Requiere Socket.IO (se carga dinámicamente si no está disponible).
 */
(function () {
'use strict';

const BELL_ID = 'notificationBell';

/** Icono del sprite del escritorio; vacío si icons.js aún no cargó. */
function ico(name, cls) {
    const D = window.ItcjDesktop;
    return D && typeof D.icon === 'function' ? D.icon(name, cls) : '';
}

/**
 * URL de acción segura: ruta relativa que empieza con `/` (no `//` ni `/\`) o
 * mismo origen http/https. Cualquier otra cosa (`javascript:`, `data:`, otro
 * origen) devuelve '' (sin acción).
 */
function safeUrl(u) {
    if (typeof u !== 'string') return '';
    const raw = u.trim();
    if (!raw) return '';
    if (raw.startsWith('/') && !raw.startsWith('//') && !raw.startsWith('/\\')) return raw;
    try {
        const parsed = new URL(raw, window.location.origin);
        if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
            parsed.origin === window.location.origin) {
            return parsed.pathname + parsed.search + parsed.hash;
        }
    } catch (e) { /* inválida: sin acción */ }
    return '';
}

/** Color de la app: solo #rrggbb; si no, gris. */
function safeColor(c) {
    return typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c) ? c : '#6c757d';
}

class DashboardNotificationWidget {
    constructor() {
        this.apiBase = '/api/core/v2';
        this.socket = null;
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
        this.connectWebSocket();
    }

    /**
     * Inyecta el HTML del widget en el dashboard
     */
    injectHTML() {
        // Verificar si ya existe el icono de campana en el HTML
        const existingBell = document.getElementById(BELL_ID);

        if (!existingBell) {
            console.error('[NotificationWidget] Notification bell not found in HTML');
            return;
        }

        // No inyectar un nuevo icono, usar el existente
        // El badge ya está en el HTML con id 'globalNotificationBadge'

        // Panel desplegable
        const panelHTML = `
            <div class="notification-panel" id="notification-panel" role="dialog" aria-label="Notificaciones" hidden>
                <div class="notification-panel-header">
                    <h6 class="mb-0">Notificaciones</h6>
                    <button class="btn btn-sm btn-link" id="mark-all-read-btn">
                        ${ico('check-check')} Marcar todas
                    </button>
                </div>
                <div class="notification-panel-body" id="notification-list">
                    <div class="text-center py-4 text-muted">
                        ${ico('inbox')}
                        <p class="small mb-0 mt-2">Cargando...</p>
                    </div>
                </div>
                <div class="notification-panel-footer">
                    <button id="view-all-notifications-btn" class="btn btn-sm btn-primary w-100">
                        Ver todas las notificaciones
                    </button>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', panelHTML);
    }

    /**
     * Adjunta event listeners
     */
    attachEventListeners() {
        // Toggle panel - usar el icono existente en el HTML
        const bellBtn = document.getElementById(BELL_ID);
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

        // Ver todas las notificaciones
        const viewAllBtn = document.getElementById('view-all-notifications-btn');
        if (viewAllBtn) {
            viewAllBtn.addEventListener('click', () => {
                this.openProfileNotifications();
            });
        }

        // Cerrar panel al hacer click fuera
        document.addEventListener('click', (e) => {
            const panel = document.getElementById('notification-panel');
            const bell = document.getElementById(BELL_ID);

            if (panel && !panel.contains(e.target) && !(bell && bell.contains(e.target))) {
                this.closePanel();
            }
        });

        // Esc cierra el panel y devuelve el foco a la campana
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.panelOpen) {
                this.closePanel();
                const bell = document.getElementById(BELL_ID);
                if (bell) bell.focus();
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
     * Conecta al WebSocket /notify namespace
     */
    connectWebSocket() {
        // Cargar Socket.IO si no está disponible
        const ensureIO = () => {
            return new Promise((resolve, reject) => {
                if (window.io) return resolve();
                const script = document.createElement('script');
                script.src = '/static/core/js/vendor/socket.io.min.js?v=4.7.5';
                script.onload = () => resolve();
                script.onerror = reject;
                document.head.appendChild(script);
            });
        };

        ensureIO().then(() => {
            // Reusar socket existente si ya hay uno conectado
            if (window.__notifySocket) {
                this.socket = window.__notifySocket;
            } else {
                this.socket = io('/notify', {
                    withCredentials: true,
                    reconnection: true,
                    timeout: 20000,
                    transports: ['websocket', 'polling']
                });
                window.__notifySocket = this.socket;
            }

            // Evento: conectado
            this.socket.on('hello', (data) => {
                console.log('[NotificationWidget] WebSocket connected', data);
            });

            // Evento: nueva notificación
            this.socket.on('notify', (notification) => {
                this.handleNewNotification(notification);
            });

            // Evento: notificación leída (sincronización de badges)
            this.socket.on('notification:read', (data) => {
                if (data.counts !== undefined) {
                    this.updateCounts(data.counts, data.total);
                    // Recargar lista si el panel está abierto
                    if (this.panelOpen) {
                        this.loadRecentNotifications().then(() => this.renderNotifications());
                    }
                }
            });

            // Evento: error
            this.socket.on('connect_error', (error) => {
                console.error('[NotificationWidget] WebSocket error:', error);
            });
        }).catch(err => {
            console.error('[NotificationWidget] Failed to load Socket.IO:', err);
        });
    }

    /**
     * Actualiza los conteos de notificaciones
     */
    updateCounts(counts, total) {
        this.counts = counts;
        this.totalUnread = total;

        // Actualizar badge - usar el badge existente en el HTML
        const badge = document.getElementById('globalNotificationBadge');
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
     * Actualiza badges en iconos de aplicaciones del escritorio
     */
    updateAppBadges() {
        document.querySelectorAll('[data-badge-for]').forEach(badge => {
            const count = this.counts[badge.getAttribute('data-badge-for')] || 0;
            if (count > 0) {
                badge.textContent = count > 99 ? '99+' : count;
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }
        });
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

        const bell = document.getElementById(BELL_ID);
        if (bell) bell.setAttribute('aria-expanded', String(this.panelOpen));
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
        const bell = document.getElementById(BELL_ID);
        if (bell) bell.setAttribute('aria-expanded', 'false');
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
                    ${ico('inbox')}
                    <p class="small mb-0 mt-2">No hay notificaciones</p>
                </div>
            `;
            return;
        }

        const html = this.notifications.map(n => this.renderNotificationItem(n)).join('');
        list.innerHTML = html;

        // Attach click listeners
        list.querySelectorAll('.notification-item').forEach(item => {
            item.addEventListener('click', (e) => {
                const id = parseInt(item.dataset.id, 10);
                const url = safeUrl(item.dataset.url);

                if (!item.classList.contains('read')) {
                    this.markAsRead(id);
                }

                if (url) {
                    this.handleNotificationClick(url);
                }
            });
        });
    }

    /**
     * Renderiza un item de notificación
     */
    renderNotificationItem(notification) {
        const isUnread = !notification.is_read;
        const color = safeColor(notification.app_color_hex);
        const url = safeUrl(notification.action_url);
        const timeAgo = this.getTimeAgo(notification.created_at);

        return `
            <div class="notification-item ${isUnread ? 'unread' : 'read'}"
                 data-id="${this.escapeHtml(notification.id)}"
                 data-url="${this.escapeHtml(url)}">
                <div class="notification-icon" style="background-color: ${color}">
                    ${ico('bell')}
                </div>
                <div class="notification-content">
                    <div class="notification-title">${this.escapeHtml(notification.title)}</div>
                    ${notification.body ? `<div class="notification-body">${this.escapeHtml(notification.body)}</div>` : ''}
                    <div class="notification-meta">
                        <span class="app-tag badge" style="background-color: ${color}">${this.escapeHtml(notification.app_name)}</span>
                        <span class="time">${this.escapeHtml(timeAgo)}</span>
                    </div>
                </div>
                ${isUnread ? '<div class="unread-indicator"></div>' : ''}
            </div>
        `;
    }

    /**
     * Escapa HTML para prevenir XSS al interpolar datos del servidor
     */
    escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
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
     * Click en una notificación (o toast) con `action_url`: abre la URL en el
     * escritorio. Si no pasa safeUrl no se hace nada. Dentro de un iframe (sin
     * escritorio) se navega directamente.
     */
    handleNotificationClick(url) {
        this.closePanel();
        const target = safeUrl(url);
        if (!target) return;

        if (window.self !== window.top) {
            window.location.href = target;
        } else if (window.desktop && typeof window.desktop.openUrl === 'function') {
            window.desktop.openUrl(target);
        } else {
            window.location.href = target;
        }
    }

    /** "Ver todas": pestaña de notificaciones del perfil, como ventana del escritorio. */
    openProfileNotifications() {
        this.closePanel();

        if (window.self === window.top && window.desktop && typeof window.desktop.openProfile === 'function') {
            window.desktop.openProfile('notifications');
        } else {
            window.location.href = '/itcj/profile?tab=notifications';
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
        const url = safeUrl(notification.action_url);
        const toast = document.createElement('div');
        toast.className = 'notification-toast';
        toast.setAttribute('role', 'status');
        toast.innerHTML = `
            <div class="d-flex align-items-center">
                <span class="notification-toast-icon me-2">${ico('bell')}</span>
                <div>
                    <div class="fw-bold">${this.escapeHtml(notification.title)}</div>
                    ${notification.body ? `<div class="small">${this.escapeHtml(notification.body)}</div>` : ''}
                </div>
            </div>
        `;

        if (url) {
            toast.classList.add('is-actionable');
            toast.addEventListener('click', () => {
                if (notification.id != null) this.markAsRead(parseInt(notification.id, 10));
                this.handleNotificationClick(url);
                toast.remove();
            });
        }

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
})();
