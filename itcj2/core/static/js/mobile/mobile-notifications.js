/**
 * ITCJ Mobile - Notifications Page
 *
 * Carga y gestiona notificaciones del usuario.
 */

class MobileNotifications {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.limit = 20;
        this.offset = 0;
        this.hasMore = false;
        this.init();
    }

    init() {
        this.loadNotifications();
        this.bindEvents();
    }

    bindEvents() {
        const markAllBtn = document.getElementById('markAllReadBtn');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', () => this.markAllAsRead());
        }
    }

    /**
     * Carga notificaciones desde la API
     */
    async loadNotifications(append = false) {
        try {
            const resp = await fetch(
                `${this.apiBase}/notifications?limit=${this.limit}&offset=${this.offset}`,
                { credentials: 'include' }
            );

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const result = await resp.json();
            const { items, has_more } = result.data;
            this.hasMore = has_more;

            const listEl = document.getElementById('notification-list');
            const emptyEl = document.getElementById('notification-empty');

            if (!append) {
                listEl.innerHTML = '';
            }

            if (items.length === 0 && !append) {
                listEl.style.display = 'none';
                emptyEl.style.display = 'block';
                return;
            }

            listEl.style.display = 'block';
            emptyEl.style.display = 'none';

            items.forEach(n => {
                listEl.insertAdjacentHTML('beforeend', this.renderNotification(n));
            });

            // Boton "Cargar mas"
            const existingLoadMore = listEl.querySelector('.mobile-load-more');
            if (existingLoadMore) existingLoadMore.remove();

            if (this.hasMore) {
                listEl.insertAdjacentHTML('beforeend', `
                    <div class="mobile-load-more">
                        <button class="mobile-load-more-btn" id="loadMoreBtn">
                            Cargar mas notificaciones
                        </button>
                    </div>
                `);
                document.getElementById('loadMoreBtn').addEventListener('click', () => {
                    this.offset += this.limit;
                    this.loadNotifications(true);
                });
            }

            // Bind click en items para manejar notificaciones
            listEl.querySelectorAll('.mobile-notification-item').forEach(el => {
                el.addEventListener('click', () => {
                    this.handleNotificationClick(el);
                });
            });

        } catch (err) {
            console.error('[MobileNotifications] Error loading:', err);
            const listEl = document.getElementById('notification-list');
            listEl.innerHTML = `
                <div class="mobile-empty-state">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>Error al cargar notificaciones</p>
                </div>
            `;
        }
    }

    /**
     * Renderiza HTML de una notificacion
     */
    renderNotification(n) {
        const isUnread = !n.is_read;
        const icon = this.getAppIcon(n.app_key);
        const time = this.formatTime(n.created_at);
        
        // Extraer URL del data si existe
        let dataUrl = '';
        let dataJson = '';
        if (n.data) {
            try {
                const data = typeof n.data === 'string' ? JSON.parse(n.data) : n.data;
                if (data.url) {
                    dataUrl = data.url;
                }
                dataJson = JSON.stringify(data);
            } catch (e) {
                console.warn('[MobileNotifications] Error parsing data:', e);
            }
        }

        return `
            <div class="mobile-notification-item ${isUnread ? 'unread' : ''} ${dataUrl ? 'clickable' : ''}"
                 data-id="${n.id}" 
                 data-url="${this.escape(dataUrl)}"
                 data-app-key="${n.app_key || ''}"
                 role="button">
                <div class="mobile-notification-icon">
                    <i class="bi ${icon}"></i>
                </div>
                <div class="mobile-notification-content">
                    <div class="mobile-notification-title">${this.escape(n.title || '')}</div>
                    <div class="mobile-notification-body">${this.escape(n.body || '')}</div>
                    <div class="mobile-notification-time">
                        ${time}
                        ${dataUrl ? '<i class="bi bi-box-arrow-up-right ms-1"></i>' : ''}
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Obtiene el nombre de la app basado en la URL
     */
    getAppNameFromUrl(url) {
        if (!url) return 'Aplicación';
        
        const appNames = {
            'help-desk': 'Help Desk',
            'helpdesk': 'Help Desk',
            'agendatec': 'AgendaTec',
            'vistetec': 'VisteTec',
        };

        // Extraer el primer segmento de la URL
        const match = url.match(/^\/([^\/]+)/);
        if (match) {
            const segment = match[1].toLowerCase();
            return appNames[segment] || segment.charAt(0).toUpperCase() + segment.slice(1);
        }
        return 'Aplicación';
    }

    /**
     * Maneja el clic en una notificación
     */
    handleNotificationClick(el) {
        const id = el.dataset.id;
        const url = el.dataset.url;
        
        // Marcar como leída si no lo está
        if (el.classList.contains('unread') && id) {
            this.markAsRead(id, el);
        }
        
        // Si tiene URL, abrir en iframe
        if (url && window.mobileApp) {
            const appName = this.getAppNameFromUrl(url);
            window.mobileApp.openAppInIframe(url, appName);
        }
    }

    /**
     * Icono segun app
     */
    getAppIcon(appKey) {
        const icons = {
            'agendatec': 'bi-calendar-check',
            'helpdesk': 'bi-ticket-detailed',
            'itcj': 'bi-bell',
        };
        return icons[appKey] || 'bi-bell';
    }

    /**
     * Formatea timestamp a texto relativo
     */
    formatTime(isoString) {
        if (!isoString) return '';
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMin = Math.floor(diffMs / 60000);
        const diffHr = Math.floor(diffMs / 3600000);
        const diffDay = Math.floor(diffMs / 86400000);

        if (diffMin < 1) return 'Ahora';
        if (diffMin < 60) return `Hace ${diffMin} min`;
        if (diffHr < 24) return `Hace ${diffHr}h`;
        if (diffDay < 7) return `Hace ${diffDay}d`;
        return date.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' });
    }

    /**
     * Marca una notificacion como leida
     */
    async markAsRead(id, el) {
        try {
            const resp = await fetch(`${this.apiBase}/notifications/${id}/read`, {
                method: 'PATCH',
                credentials: 'include'
            });
            if (resp.ok) {
                el.classList.remove('unread');
                // Actualizar badges globales
                if (window.mobileApp) {
                    window.mobileApp.loadNotificationCounts();
                }
            }
        } catch (err) {
            console.error('[MobileNotifications] Error marking read:', err);
        }
    }

    /**
     * Marca todas como leidas
     */
    async markAllAsRead() {
        try {
            const resp = await fetch(`${this.apiBase}/notifications/mark-all-read`, {
                method: 'PATCH',
                credentials: 'include'
            });
            if (resp.ok) {
                document.querySelectorAll('.mobile-notification-item.unread').forEach(el => {
                    el.classList.remove('unread');
                });
                if (window.mobileApp) {
                    window.mobileApp.loadNotificationCounts();
                }
                if (window.mobileApp) {
                    window.mobileApp.showToast('Todas las notificaciones marcadas como leidas');
                }
            }
        } catch (err) {
            console.error('[MobileNotifications] Error marking all read:', err);
        }
    }

    /**
     * Escapa HTML para prevenir XSS
     */
    escape(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.mobileNotifications = new MobileNotifications();
});
