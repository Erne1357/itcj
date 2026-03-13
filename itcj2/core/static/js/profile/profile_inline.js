'use strict';

// Detectar si estamos en un iframe móvil
const inIframe = window.self !== window.top;
if (inIframe) {
    document.body.classList.add('in-mobile-iframe');
}

// Función para volver al dashboard
function goToDashboard() {
    if (inIframe) {
        try {
            window.parent.postMessage({
                type: 'CLOSE_APP',
                source: 'profile'
            }, window.location.origin);
        } catch (e) {
            console.warn('No se pudo notificar al parent:', e);
            window.location.href = '/itcj/m/';
        }
    } else {
        window.location.href = '/itcj/m/';
    }
}

// Bind del botón de regreso
document.addEventListener('DOMContentLoaded', () => {
    const backBtn = document.getElementById('mobileBackToDashboard');
    if (backBtn) {
        backBtn.addEventListener('click', goToDashboard);
    }
});

// WebSocket for Real-time Notifications
document.addEventListener('DOMContentLoaded', () => {
    // Load Socket.IO and connect to /notify namespace
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
        const socket = window.__notifySocket || io('/notify', {
            withCredentials: true,
            reconnection: true,
            transports: ['websocket', 'polling']
        });
        window.__notifySocket = socket;

        // Listen for new notifications
        socket.on('notify', (notification) => {
            console.log('[Profile] New notification received:', notification);

            // Reload notifications if in notifications tab
            const notificationsTab = document.getElementById('notifications-tab');
            if (notificationsTab && notificationsTab.classList.contains('active')) {
                setTimeout(() => {
                    if (window.profileManager) {
                        window.profileManager.loadNotifications();
                    }
                }, 500);
            }

            // Update badge count
            fetch('/api/core/v2/notifications/unread-counts', { credentials: 'include' })
                .then(res => res.json())
                .then(result => {
                    if (result.data && result.data.total) {
                        const badge = document.getElementById('notificationBadge');
                        if (badge) {
                            badge.textContent = result.data.total > 99 ? '99+' : result.data.total;
                            badge.style.display = result.data.total > 0 ? 'inline' : 'none';
                        }
                    }
                })
                .catch(err => console.error('[Profile] Error updating badge:', err));
        });

        // Listen for notification read events (badge sync from other widgets)
        socket.on('notification:read', (data) => {
            if (data.total !== undefined) {
                const badge = document.getElementById('notificationBadge');
                if (badge) {
                    badge.textContent = data.total > 99 ? '99+' : data.total;
                    badge.style.display = data.total > 0 ? 'inline' : 'none';
                }
            }
            // Reload notifications if tab is active
            const notificationsTab = document.getElementById('notifications-tab');
            if (notificationsTab && notificationsTab.classList.contains('active')) {
                if (window.profileManager) {
                    window.profileManager.loadNotifications();
                }
            }
        });

        socket.on('connect_error', (error) => {
            console.error('[Profile] WebSocket error:', error);
        });

        console.log('[Profile] WebSocket initialized');
    }).catch(err => console.error('[Profile] Failed to load Socket.IO:', err));
});
