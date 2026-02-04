/**
 * ITCJ Mobile Dashboard - Main Application Script
 *
 * Maneja notificaciones en tiempo real via WebSocket,
 * actualizacion de badges, y logica general del mobile dashboard.
 */

class MobileApp {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.socket = null;
        this.totalUnread = 0;
        this.init();
    }

    init() {
        this.loadNotificationCounts();
        this.connectWebSocket();
        this.bindEvents();
    }

    /**
     * Carga conteos iniciales de notificaciones
     */
    async loadNotificationCounts() {
        try {
            const resp = await fetch(`${this.apiBase}/notifications/unread-counts`, {
                credentials: 'include'
            });
            if (resp.ok) {
                const result = await resp.json();
                this.updateBadges(result.data.total);
            }
        } catch (e) {
            console.error('[MobileApp] Error loading notification counts:', e);
        }
    }

    /**
     * Actualiza todos los badges de notificaciones
     */
    updateBadges(total) {
        this.totalUnread = total;
        const badgeIds = ['globalNotificationBadgeMobile', 'navBadgeNotifications'];

        badgeIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = total > 99 ? '99+' : total;
                el.style.display = total > 0 ? 'flex' : 'none';
            }
        });
    }

    /**
     * Conecta al WebSocket /notify para notificaciones en tiempo real
     */
    connectWebSocket() {
        const ensureIO = () => {
            return new Promise((resolve, reject) => {
                if (window.io) return resolve();
                const s = document.createElement('script');
                s.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
                s.crossOrigin = 'anonymous';
                s.onload = () => resolve();
                s.onerror = reject;
                document.head.appendChild(s);
            });
        };

        ensureIO().then(() => {
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

            this.socket.on('hello', (data) => {
                console.log('[MobileApp] WebSocket connected', data);
            });

            this.socket.on('notify', () => {
                this.loadNotificationCounts();
            });

            this.socket.on('connect_error', (err) => {
                console.error('[MobileApp] WebSocket error:', err);
            });
        }).catch(err => {
            console.error('[MobileApp] Failed to load Socket.IO:', err);
        });
    }

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Notification bell en header -> ir a pagina de notificaciones
        const bell = document.getElementById('notificationBellMobile');
        if (bell) {
            bell.addEventListener('click', () => {
                window.location.href = '/itcj/m/notifications';
            });
        }
    }

    /**
     * Muestra un toast temporal
     */
    showToast(message, type = 'success') {
        const toastEl = document.getElementById('mobileToast');
        const msgEl = document.getElementById('mobileToastMessage');
        if (!toastEl || !msgEl) return;

        toastEl.className = `toast align-items-center text-bg-${type} border-0`;
        msgEl.textContent = message;

        const toast = new bootstrap.Toast(toastEl, { delay: 3000 });
        toast.show();
    }
}

// Inicializar al cargar el DOM
document.addEventListener('DOMContentLoaded', () => {
    window.mobileApp = new MobileApp();
});
