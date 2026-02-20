/**
 * ITCJ Mobile Dashboard - SPA Application Script
 *
 * Simula una SPA donde la barra inferior persiste siempre.
 * El iframe de apps se mantiene "vivo" al cambiar de tab.
 * Al presionar Inicio: si hay app, vuelve a ella; si está en app, cierra y va al dashboard.
 */

class MobileApp {
    constructor() {
        this.apiBase = '/api/core/v1';
        this.socket = null;
        this.totalUnread = 0;
        
        // Estado SPA
        this.currentView = 'home'; // 'home' | 'app' | 'notifications' | 'profile' | 'student-profile'
        this.previousView = null;
        this.appIsLoaded = false;
        this.currentAppUrl = null;
        this.currentAppName = null;
        this.profileLoaded = false;
        
        // Tipo de usuario (se pasa desde el template)
        this.userType = window.mobileUserType || 'student';
        
        // Elementos DOM
        this.body = document.body;
        this.mainContent = document.getElementById('mobileMainContent');
        this.appContainer = document.getElementById('mobileAppContainer');
        this.appFrame = document.getElementById('mobileAppFrame');
        this.notificationsView = document.getElementById('mobileNotificationsView');
        this.profileView = document.getElementById('mobileProfileView');
        this.profileFrame = document.getElementById('mobileProfileFrame');
        this.studentProfileView = document.getElementById('mobileStudentProfileView');
        this.fabLogout = document.getElementById('mobileFabLogout');
        this.bottomNav = document.getElementById('mobileBottomNav');
        
        this.init();
    }

    init() {
        // Establecer vista inicial
        this.setActiveView('home');
        
        this.loadNotificationCounts();
        this.connectWebSocket();
        this.bindEvents();
        this.bindAppCards();
        this.bindQuickActions();
        this.setupIframeMessageListener();
        this.setupIframeLoadMonitor();
    }

    /**
     * Cambia la vista activa usando data-attribute en body
     */
    setActiveView(view) {
        this.previousView = this.currentView;
        this.currentView = view;
        this.body.setAttribute('data-active-view', view);
        
        // Actualizar navegación activa
        this.updateNavActive(view);
        
        // Mostrar/ocultar FAB de logout para staff
        this.updateFabLogout(view);
        
        console.log('[MobileApp] Vista activa:', view);
    }

    /**
     * Actualiza el estado activo de los botones de navegación
     */
    updateNavActive(view) {
        const navItems = this.bottomNav?.querySelectorAll('.mobile-nav-item');
        navItems?.forEach(item => {
            const tab = item.getAttribute('data-tab');
            // Para 'app', mantenemos 'home' como activo visualmente
            // Para 'student-profile', mantenemos 'profile' como activo
            let isActive = false;
            if (view === 'app' && tab === 'home') isActive = true;
            else if (view === 'student-profile' && tab === 'profile') isActive = true;
            else if (tab === view) isActive = true;
            
            item.classList.toggle('active', isActive);
        });
    }

    /**
     * Muestra/oculta el botón FAB de logout para staff
     */
    updateFabLogout(view) {
        if (!this.fabLogout) return;
        
        // Solo mostrar para staff cuando está en vista de perfil (iframe)
        const showFab = this.userType === 'staff' && view === 'profile';
        this.fabLogout.style.display = showFab ? 'flex' : 'none';
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
                this.updateBadges(result.data?.total || 0);
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
        const badge = document.getElementById('navBadgeNotifications');
        if (badge) {
            badge.textContent = total > 99 ? '99+' : total;
            badge.style.display = total > 0 ? 'flex' : 'none';
        }
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
                this.loadNotifications(); // Recargar lista si está visible
            });

            this.socket.on('connect_error', (err) => {
                console.error('[MobileApp] WebSocket error:', err);
            });
        }).catch(err => {
            console.error('[MobileApp] Failed to load Socket.IO:', err);
        });
    }

    /**
     * Abre una aplicación en el iframe (sin destruir estado anterior)
     */
    openAppInIframe(url, appName) {
        if (!this.appFrame || !this.appContainer) return;

        // Si es la misma app, solo mostrar
        if (this.appIsLoaded && this.currentAppUrl === url) {
            this.setActiveView('app');
            return;
        }

        // Nueva app o primera vez
        this.currentAppUrl = url;
        this.currentAppName = appName || 'Aplicación';
        this.appFrame.src = url;
        this.appIsLoaded = true;
        this.appContainer.classList.add('active');
        this.setActiveView('app');

        console.log('[MobileApp] Abriendo app en iframe:', url);
    }

    /**
     * Cierra el iframe y destruye la app
     */
    closeAndDestroyApp() {
        if (!this.appFrame || !this.appContainer) return;

        this.appFrame.src = 'about:blank';
        this.appContainer.classList.remove('active');
        this.appIsLoaded = false;
        this.currentAppUrl = null;
        this.currentAppName = null;
        this.setActiveView('home');

        console.log('[MobileApp] App cerrada y destruida');
    }

    /**
     * Lógica del botón Inicio:
     * - Si está en notifications/profile y hay app cargada: volver a la app
     * - Si está en la app: cerrar app y volver al dashboard
     * - Si está en home: no hacer nada
     */
    handleHomeClick() {
        if (this.currentView === 'home') {
            // Ya en home, no hacer nada
            return;
        }

        if (this.currentView === 'app') {
            // Está en la app -> cerrar y volver al dashboard
            this.closeAndDestroyApp();
        } else if (this.appIsLoaded) {
            // Está en notifications/profile pero hay app cargada -> volver a la app
            this.setActiveView('app');
        } else {
            // No hay app, solo volver al dashboard
            this.setActiveView('home');
        }
    }

    /**
     * Navega a notificaciones (sin cerrar la app)
     */
    goToNotifications() {
        this.setActiveView('notifications');
        this.loadNotifications();
    }

    /**
     * Navega al perfil (diferente según tipo de usuario)
     */
    goToProfile() {
        if (this.userType === 'staff') {
            // Staff: cargar iframe del perfil
            if (!this.profileLoaded && this.profileFrame) {
                this.profileFrame.src = '/itcj/profile';
                this.profileLoaded = true;
            }
            this.setActiveView('profile');
        } else {
            // Estudiante: mostrar vista inline
            this.setActiveView('student-profile');
        }
    }

    /**
     * Carga lista de notificaciones
     */
    async loadNotifications() {
        const list = document.getElementById('mobileNotificationsList');
        if (!list) return;

        list.innerHTML = `
            <div class="mobile-loading">
                <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
                <span class="ms-2">Cargando...</span>
            </div>
        `;

        try {
            const resp = await fetch(`${this.apiBase}/notifications/?limit=50`, {
                credentials: 'include'
            });
            
            if (!resp.ok) throw new Error('Error al cargar notificaciones');
            
            const result = await resp.json();
            const notifications = result.data?.items || [];

            if (notifications.length === 0) {
                list.innerHTML = `
                    <div class="mobile-notification-empty">
                        <i class="bi bi-bell-slash"></i>
                        <p>No tienes notificaciones</p>
                    </div>
                `;
                return;
            }

            list.innerHTML = notifications.map(n => `
                <div class="mobile-notification-item ${n.read_at ? '' : 'unread'}" 
                     data-id="${n.id}" data-url="${n.action_url || ''}">
                    <div class="mobile-notification-title">${this.escapeHtml(n.title)}</div>
                    <div class="mobile-notification-body">${this.escapeHtml(n.body || '')}</div>
                    <div class="mobile-notification-time">${this.formatDate(n.created_at)}</div>
                </div>
            `).join('');

            // Bind click events
            list.querySelectorAll('.mobile-notification-item').forEach(item => {
                item.addEventListener('click', () => this.handleNotificationClick(item));
            });

        } catch (e) {
            console.error('[MobileApp] Error loading notifications:', e);
            list.innerHTML = `
                <div class="mobile-notification-empty">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>Error al cargar notificaciones</p>
                </div>
            `;
        }
    }

    /**
     * Maneja click en notificación
     */
    async handleNotificationClick(item) {
        const id = item.getAttribute('data-id');
        const url = item.getAttribute('data-url');

        // Marcar como leída visualmente
        try {
            await fetch(`${this.apiBase}/notifications/${id}/read`, {
                method: 'POST',
                credentials: 'include'
            });
            item.classList.remove('unread');
            this.loadNotificationCounts();
        } catch (e) {
            console.error('[MobileApp] Error marking notification as read:', e);
        }

        // Navegar si hay URL
        if (url && url !== '') {
            // Verificar si es una URL de app conocida
            const appInfo = this.getAppInfoFromUrl(url);
            
            if (appInfo) {
                // Si hay una app diferente cargada, cerrarla primero
                if (this.appIsLoaded && this.currentAppUrl && !this.currentAppUrl.includes(appInfo.path)) {
                    this.closeAndDestroyApp();
                }
                // Abrir la app en el iframe
                this.openAppInIframe(url, appInfo.name);
            } else if (url.includes('/itcj/config')) {
                // Configuración también se abre en iframe
                if (this.appIsLoaded) {
                    this.closeAndDestroyApp();
                }
                this.openAppInIframe(url, 'Configuración');
            } else {
                // URLs externas o no reconocidas
                window.location.href = url;
            }
        }
    }

    /**
     * Obtiene información de la app desde la URL
     */
    getAppInfoFromUrl(url) {
        // Detectar diferentes formatos de URL
        if (url.includes('/agendatec')) return { name: 'AgendaTec', path: '/agendatec' };
        if (url.includes('/help-desk') || url.includes('/helpdesk')) return { name: 'Help-Desk', path: '/help-desk' };
        if (url.includes('/vistetec')) return { name: 'VisteTec', path: '/vistetec' };
        return null;
    }

    /**
     * Obtiene nombre de app desde URL (compatibilidad)
     */
    getAppNameFromUrl(url) {
        const info = this.getAppInfoFromUrl(url);
        return info ? info.name : 'Aplicación';
    }

    /**
     * Bind app cards para abrir en iframe
     */
    bindAppCards() {
        const appCards = document.querySelectorAll('.mobile-app-card');
        appCards.forEach(card => {
            card.addEventListener('click', (e) => {
                e.preventDefault();
                const url = card.getAttribute('href');
                const appName = card.querySelector('.mobile-app-card-name')?.textContent || 'Aplicación';

                if (url && url !== '#') {
                    this.openAppInIframe(url, appName);
                }
            });
        });
    }

    /**
     * Bind quick action buttons para abrir en iframe
     */
    bindQuickActions() {
        const quickActions = document.querySelectorAll('.mobile-quick-action-btn');
        quickActions.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const url = btn.getAttribute('href');
                const label = btn.querySelector('span')?.textContent || 'Aplicación';

                if (url && url !== '#') {
                    // Determinar el nombre de la app desde la URL
                    const appInfo = this.getAppInfoFromUrl(url);
                    const appName = appInfo ? appInfo.name : (url.includes('/config') ? 'Configuración' : label);
                    this.openAppInIframe(url, appName);
                }
            });
        });
    }

    /**
     * Escucha mensajes del iframe (ej: cerrar app, logout, sesión expirada)
     * Compatible con iframe_bridge.js para detectar logout/session expired
     */
    setupIframeMessageListener() {
        // Escuchar mensajes postMessage del iframe
        window.addEventListener('message', (event) => {
            if (event.origin !== window.location.origin) return;

            const { type, source, url, reason } = event.data || {};

            console.log('[MobileApp] Mensaje recibido del iframe:', event.data);

            if (type === 'CLOSE_APP' || type === 'GO_TO_DASHBOARD') {
                // Si viene del perfil (staff), volver al home
                if (source === 'profile') {
                    this.setActiveView('home');
                } else {
                    this.closeAndDestroyApp();
                }
            } else if (type === 'LOGOUT') {
                // Logout detectado (ya sea por botón o por navegación del iframe_bridge)
                console.log('[MobileApp] Logout detectado, razón:', reason);
                this.handleSessionEnd('logout');
            } else if (type === 'SESSION_EXPIRED') {
                // Sesión expirada detectada por iframe_bridge
                console.log('[MobileApp] Sesión expirada detectada');
                this.handleSessionEnd('session_expired');
            } else if (type === 'NAVIGATION' && source === 'iframe-bridge') {
                // Navegación detectada por iframe_bridge - verificar si es página de login
                if (url && (url.includes('/login') || url.includes('/logout'))) {
                    console.log('[MobileApp] Navegación a login/logout detectada:', url);
                    this.handleSessionEnd('navigation_to_login');
                }
            }
        });
    }

    /**
     * Configura monitoreo del evento load de los iframes para detectar sesión expirada
     * Esto captura casos donde el iframe carga la página de login directamente
     */
    setupIframeLoadMonitor() {
        // Monitor para el iframe de apps
        if (this.appFrame) {
            this.appFrame.addEventListener('load', () => this.checkIframeForLogin(this.appFrame, 'app'));
        }
        // Monitor para el iframe de perfil (staff)
        if (this.profileFrame) {
            this.profileFrame.addEventListener('load', () => this.checkIframeForLogin(this.profileFrame, 'profile'));
        }
    }

    /**
     * Verifica si el iframe ha cargado una página de login (sesión expirada)
     */
    checkIframeForLogin(iframe, source) {
        try {
            // Intentar acceder al contenido del iframe (solo funciona si es mismo origen)
            const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
            if (!iframeDoc) return;

            const iframeUrl = iframe.contentWindow?.location?.pathname || '';
            const iframeTitle = iframeDoc.title || '';
            
            console.log(`[MobileApp] Iframe ${source} cargó:`, iframeUrl, 'Título:', iframeTitle);

            // Detectar si es página de login
            const isLoginPage = iframeUrl.includes('/login') || 
                               iframeUrl.includes('/logout') ||
                               iframeTitle.toLowerCase().includes('inicio de sesión') ||
                               iframeTitle.toLowerCase().includes('login') ||
                               iframeDoc.querySelector('#loginForm') !== null;

            if (isLoginPage) {
                console.log('[MobileApp] Página de login detectada en iframe, sesión expirada');
                this.handleSessionEnd('iframe_login_detected');
            }
        } catch (e) {
            // Error de cross-origin - no podemos acceder al contenido
            // Esto podría pasar si hay una redirección a otro dominio
            console.warn('[MobileApp] No se pudo verificar contenido del iframe:', e.message);
        }
    }

    /**
     * Maneja el fin de sesión (logout o expiración)
     * Redirige toda la página al login
     */
    handleSessionEnd(reason) {
        console.log('[MobileApp] Finalizando sesión, razón:', reason);
        
        // Evitar múltiples redirecciones
        if (this._sessionEnding) return;
        this._sessionEnding = true;
        
        // Limpiar iframes
        if (this.appFrame) {
            this.appFrame.src = 'about:blank';
        }
        if (this.profileFrame) {
            this.profileFrame.src = 'about:blank';
        }
        
        // Desconectar WebSocket si existe
        if (this.socket) {
            try {
                this.socket.disconnect();
            } catch (e) {
                console.warn('Error desconectando socket:', e);
            }
        }
        
        // Hacer POST al endpoint de logout y luego redirigir al login
        this.doLogout();
    }

    /**
     * Marca todas las notificaciones como leídas y limpia el listado
     */
    async markAllAsRead() {
        const btn = document.getElementById('markAllReadBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Marcando...';
        }

        try {
            await fetch(`${this.apiBase}/notifications/mark-all-read`, {
                method: 'PATCH',
                credentials: 'include'
            });

            // Solo quitar la clase 'unread' de todas las cards, sin eliminarlas
            const list = document.getElementById('mobileNotificationsList');
            if (list) {
                list.querySelectorAll('.mobile-notification-item.unread').forEach(item => {
                    item.classList.remove('unread');
                });
            }

            this.updateBadges(0);
        } catch (e) {
            console.error('[MobileApp] Error marking all as read:', e);
            this.showToast('Error al marcar notificaciones', 'danger');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-check-all me-1"></i>Leer todo';
            }
        }
    }

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Bottom navigation
        document.getElementById('mobileNavHome')?.addEventListener('click', () => {
            this.handleHomeClick();
        });

        document.getElementById('mobileNavNotifications')?.addEventListener('click', () => {
            this.goToNotifications();
        });

        document.getElementById('mobileNavProfile')?.addEventListener('click', () => {
            this.goToProfile();
        });

        // Marcar todas las notificaciones como leídas
        document.getElementById('markAllReadBtn')?.addEventListener('click', () => {
            this.markAllAsRead();
        });

        // Logout buttons
        // FAB logout para staff
        document.getElementById('mobileFabLogout')?.addEventListener('click', () => {
            this.doLogout();
        });
        
        // Botón logout para estudiantes
        document.getElementById('studentLogoutBtn')?.addEventListener('click', () => {
            this.doLogout();
        });
    }

    /**
     * Realiza el logout
     */
    async doLogout() {
        try {
            const res = await fetch('/api/core/v1/auth/logout', {
                method: 'POST',
                credentials: 'include'
            });
            if (res.ok) {
                window.location.href = '/itcj/login';
            }
        } catch (e) {
            console.error('[MobileApp] Error logging out:', e);
            // Intentar redirigir de todas formas
            window.location.href = '/itcj/login';
        }
    }

    /**
     * Utilidades
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) return 'Hace un momento';
        if (diff < 3600000) return `Hace ${Math.floor(diff / 60000)} min`;
        if (diff < 86400000) return `Hace ${Math.floor(diff / 3600000)} h`;
        
        return date.toLocaleDateString('es-MX', {
            day: 'numeric',
            month: 'short'
        });
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

