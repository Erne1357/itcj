/**
 * Widget FAB (Floating Action Button) Reutilizable para Notificaciones por App
 *
 * Este widget puede ser usado en cualquier aplicación (helpdesk, agendatec, inventory, etc.)
 * para mostrar notificaciones específicas de esa app con un FAB flotante.
 *
 * Uso:
 *   const helpdeskNotifications = new AppNotificationFAB('helpdesk');
 *
 * Requiere:
 *   - socket-base.js cargado previamente (o Socket.IO CDN)
 *   - notifications.css cargado previamente
 */

class AppNotificationFAB {
    constructor(appName, apiBase = '/api/core/v1') {
        this.appName = appName;
        this.apiBase = apiBase;
        this.socket = null;
        this.notifications = [];
        this.unreadCount = 0;
        this.panelOpen = false;
        this.currentTab = 'recent'; // 'recent' o 'history'
        this.historyOffset = 0;
        this.hasMore = false;

        this.init();
    }

    init() {
        this.injectHTML();
        this.attachEventListeners();
        this.loadUnreadCount();
        this.connectWebSocket();
    }

    /**
     * Inyecta el HTML del FAB y panel
     */
    injectHTML() {
        const fabHTML = `
            <div id="notifFab-${this.appName}" class="d-flex align-items-center justify-content-center" style="position:fixed;bottom:24px;right:24px;width:56px;height:56px;background:linear-gradient(135deg,#198754 0%,#146c43 100%);border-radius:50%;box-shadow:0 4px 12px rgba(25,135,84,0.4);cursor:pointer;z-index:1000;">
                <i class="bi bi-bell-fill fs-4" style="color:white;"></i>
                <span id="notifBadge-${this.appName}" class="badge rounded-pill text-bg-danger" style="position:absolute;top:-4px;right:-4px;min-width:22px;height:22px;font-size:11px;font-weight:700;" hidden>0</span>
            </div>
        `;

        const panelHTML = `
            <div id="notifPanel-${this.appName}" class="shadow-sm" style="position:fixed;bottom:90px;right:24px;width:360px;max-height:500px;background:white;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.15);z-index:999;display:none;flex-direction:column;">
                <div class="head" style="display:flex;align-items:center;padding:16px;border-bottom:1px solid #e9ecef;">
                    <div class="fw-semibold" style="flex:1;font-size:16px;">Notificaciones</div>
                    <div class="tabs" style="display:flex;gap:8px;margin-left:16px;">
                        <div class="tab active" data-tab="recent" style="padding:6px 12px;font-size:13px;cursor:pointer;border-radius:6px;background:#198754;color:white;">Recientes</div>
                        <div class="tab" data-tab="history" style="padding:6px 12px;font-size:13px;cursor:pointer;border-radius:6px;color:#6c757d;">Historial</div>
                    </div>
                    <button id="notifMarkAll-${this.appName}" class="btn bg-primary btn-outline-white btn-icon ms-2" type="button" style="background:#0d6efd;color:white;border:none;padding:6px 10px;border-radius:6px;">
                        <i class="bi bi-check2-all"></i>
                    </button>
                </div>
                <div id="notifList-${this.appName}" class="list small" style="flex:1;overflow-y:auto;max-height:400px;"></div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', fabHTML);
        document.body.insertAdjacentHTML('beforeend', panelHTML);
    }

    /**
     * Adjunta event listeners
     */
    attachEventListeners() {
        // Toggle panel
        const fab = document.getElementById(`notifFab-${this.appName}`);
        if (fab) {
            fab.addEventListener('click', (e) => {
                e.stopPropagation();
                this.togglePanel();
            });
        }

        // Cambio de tabs
        const panel = document.getElementById(`notifPanel-${this.appName}`);
        if (panel) {
            panel.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    const tabType = tab.dataset.tab;
                    this.switchTab(tabType);
                });
            });
        }

        // Marcar todas como leídas
        const markAllBtn = document.getElementById(`notifMarkAll-${this.appName}`);
        if (markAllBtn) {
            markAllBtn.addEventListener('click', () => {
                this.markAllAsRead();
            });
        }

        // Cerrar panel al hacer click fuera
        document.addEventListener('click', (e) => {
            const panelEl = document.getElementById(`notifPanel-${this.appName}`);
            const fabEl = document.getElementById(`notifFab-${this.appName}`);

            if (panelEl && !panelEl.contains(e.target) && !fabEl.contains(e.target)) {
                this.closePanel();
            }
        });

        // Scroll infinito en historial
        const list = document.getElementById(`notifList-${this.appName}`);
        if (list) {
            list.addEventListener('scroll', () => {
                if (this.currentTab === 'history' && this.hasMore) {
                    const scrollPercentage = (list.scrollTop + list.clientHeight) / list.scrollHeight;
                    if (scrollPercentage > 0.9) {
                        this.loadMoreHistory();
                    }
                }
            });
        }
    }

    /**
     * Carga el conteo de no leídas
     */
    async loadUnreadCount() {
        try {
            const response = await fetch(`${this.apiBase}/notifications/unread-counts`, {
                credentials: 'include'
            });

            if (response.ok) {
                const result = await response.json();
                const count = result.data.counts[this.appName] || 0;
                this.updateBadge(count);
            }
        } catch (error) {
            console.error(`[FAB-${this.appName}] Error loading unread count:`, error);
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
                script.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
                script.crossOrigin = 'anonymous';
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
                console.log(`[FAB-${this.appName}] WebSocket connected`, data);
            });

            // Evento: nueva notificación
            this.socket.on('notify', (notification) => {
                // Solo procesar si es de esta app
                if (notification.app_name === this.appName) {
                    this.handleNewNotification(notification);
                }
            });

            this.socket.on('connect_error', (error) => {
                console.error(`[FAB-${this.appName}] WebSocket error:`, error);
            });
        }).catch(err => {
            console.error(`[FAB-${this.appName}] Failed to load Socket.IO:`, err);
        });
    }

    /**
     * Actualiza el badge
     */
    updateBadge(count) {
        this.unreadCount = count;

        const badge = document.getElementById(`notifBadge-${this.appName}`);
        if (badge) {
            if (count > 0) {
                badge.textContent = count > 99 ? '99+' : count;
                badge.hidden = false;
            } else {
                badge.hidden = true;
            }
        }
    }

    /**
     * Maneja una nueva notificación
     */
    handleNewNotification(notification) {
        // Incrementar conteo
        this.unreadCount++;
        this.updateBadge(this.unreadCount);

        // Agregar a la lista si el panel está abierto y en tab recientes
        if (this.panelOpen && this.currentTab === 'recent') {
            this.notifications.unshift(notification);
            if (this.notifications.length > 8) {
                this.notifications = this.notifications.slice(0, 8);
            }
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

        const panel = document.getElementById(`notifPanel-${this.appName}`);
        if (panel) {
            panel.style.display = this.panelOpen ? 'flex' : 'none';

            if (this.panelOpen) {
                await this.loadRecent();
            }
        }
    }

    /**
     * Cierra el panel
     */
    closePanel() {
        this.panelOpen = false;
        const panel = document.getElementById(`notifPanel-${this.appName}`);
        if (panel) {
            panel.style.display = 'none';
        }
    }

    /**
     * Cambia de tab
     */
    switchTab(tabType) {
        this.currentTab = tabType;

        // Actualizar estilos de tabs
        const panel = document.getElementById(`notifPanel-${this.appName}`);
        if (panel) {
            panel.querySelectorAll('.tab').forEach(tab => {
                if (tab.dataset.tab === tabType) {
                    tab.style.background = '#198754';
                    tab.style.color = 'white';
                    tab.classList.add('active');
                } else {
                    tab.style.background = 'transparent';
                    tab.style.color = '#6c757d';
                    tab.classList.remove('active');
                }
            });
        }

        // Cargar datos
        if (tabType === 'recent') {
            this.loadRecent();
        } else {
            this.historyOffset = 0;
            this.loadHistory(true);
        }
    }

    /**
     * Carga notificaciones recientes
     */
    async loadRecent() {
        try {
            const response = await fetch(`${this.apiBase}/notifications?app=${this.appName}&limit=8`, {
                credentials: 'include'
            });

            if (response.ok) {
                const result = await response.json();
                this.notifications = result.data.items;
                this.renderNotifications();
            }
        } catch (error) {
            console.error(`[FAB-${this.appName}] Error loading recent:`, error);
        }
    }

    /**
     * Carga historial de notificaciones
     */
    async loadHistory(reset = false) {
        if (reset) {
            this.historyOffset = 0;
            this.notifications = [];
        }

        try {
            const response = await fetch(
                `${this.apiBase}/notifications?app=${this.appName}&limit=20&offset=${this.historyOffset}`,
                { credentials: 'include' }
            );

            if (response.ok) {
                const result = await response.json();

                if (reset) {
                    this.notifications = result.data.items;
                } else {
                    this.notifications.push(...result.data.items);
                }

                this.hasMore = result.data.has_more;
                this.historyOffset += result.data.items.length;

                this.renderNotifications();
            }
        } catch (error) {
            console.error(`[FAB-${this.appName}] Error loading history:`, error);
        }
    }

    /**
     * Carga más historial (scroll infinito)
     */
    loadMoreHistory() {
        if (!this.hasMore) return;
        this.loadHistory(false);
    }

    /**
     * Renderiza la lista de notificaciones
     */
    renderNotifications() {
        const list = document.getElementById(`notifList-${this.appName}`);
        if (!list) return;

        if (this.notifications.length === 0) {
            list.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="bi bi-inbox fs-1"></i>
                    <p class="small mb-0 mt-2">No hay notificaciones</p>
                </div>
            `;
            return;
        }

        const html = this.notifications.map(n => this.renderNotificationItem(n)).join('');
        list.innerHTML = html;

        // Attach click listeners
        list.querySelectorAll('.notification-item').forEach(item => {
            item.addEventListener('click', () => {
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
                 data-url="${url}"
                 style="display:flex;padding:12px 16px;border-bottom:1px solid #e9ecef;cursor:pointer;background:${isUnread ? '#f0f9ff' : 'white'};">
                <div class="notification-icon bg-${color}" style="width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin-right:12px;color:white;">
                    <i class="${icon}"></i>
                </div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:13px;font-weight:600;color:#212529;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${notification.title}</div>
                    ${notification.body ? `<div style="font-size:12px;color:#6c757d;margin-top:2px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">${notification.body}</div>` : ''}
                    <div style="font-size:11px;color:#adb5bd;margin-top:4px;">${timeAgo}</div>
                </div>
                ${isUnread ? '<div style="width:8px;height:8px;background:#0d6efd;border-radius:50%;margin-left:8px;"></div>' : ''}
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
                const notif = this.notifications.find(n => n.id === notificationId);
                if (notif && !notif.is_read) {
                    notif.is_read = true;
                    this.unreadCount = Math.max(0, this.unreadCount - 1);
                    this.updateBadge(this.unreadCount);
                    this.renderNotifications();
                }
            }
        } catch (error) {
            console.error(`[FAB-${this.appName}] Error marking as read:`, error);
        }
    }

    /**
     * Marca todas las notificaciones de esta app como leídas
     */
    async markAllAsRead() {
        try {
            const response = await fetch(`${this.apiBase}/notifications/mark-all-read?app=${this.appName}`, {
                method: 'PATCH',
                credentials: 'include'
            });

            if (response.ok) {
                this.notifications.forEach(n => n.is_read = true);
                this.unreadCount = 0;
                this.updateBadge(0);
                this.renderNotifications();
            }
        } catch (error) {
            console.error(`[FAB-${this.appName}] Error marking all as read:`, error);
        }
    }

    /**
     * Muestra un toast de notificación
     */
    showToast(notification) {
        // Usar la función global showToast si existe (de agendatec)
        if (typeof showToast === 'function') {
            showToast(notification.title, 'info');
            return;
        }

        // Fallback: implementación simple
        console.log(`[${this.appName}] Nueva notificación:`, notification.title);
    }

    /**
     * Calcula tiempo relativo
     */
    getTimeAgo(dateString) {
        const date = new Date(dateString);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return 'Ahora';
        if (seconds < 3600) return `Hace ${Math.floor(seconds / 60)}m`;
        if (seconds < 86400) return `Hace ${Math.floor(seconds / 3600)}h`;
        if (seconds < 604800) return `Hace ${Math.floor(seconds / 86400)}d`;

        return date.toLocaleDateString('es-MX', { month: 'short', day: 'numeric' });
    }
}

// Exportar para uso global
if (typeof window !== 'undefined') {
    window.AppNotificationFAB = AppNotificationFAB;
}
