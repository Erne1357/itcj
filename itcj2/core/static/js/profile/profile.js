(function () {
    'use strict';

    const PAGE_SIZE = 20;
    const TABS = ['info', 'permissions', 'notifications'];
    const APP_NAMES = {
        agendatec: 'AgendaTec',
        helpdesk: 'Help Desk',
        maint: 'Mantenimiento',
        vistetec: 'VisteTec',
        warehouse: 'Almacén',
        inventory: 'Inventario',
        directory: 'Directorio',
        titulatec: 'TitulaTec',
        core: 'Sistema',
    };
    const GROUP_ORDER = ['Hoy', 'Ayer', 'Esta semana', 'Este mes', 'Anteriores'];

    class ProfileManager {
        constructor() {
            this.apiBase = '/api/core/v2';
            this.appFilter = '';          // '' = todas
            this.statusFilter = 'all';    // all | unread
            this.lastId = null;
            this.hasMore = false;
            this.loaded = false;          // ya se pidió la primera página
            this.loading = false;
            this.requestSeq = 0;          // descarta respuestas de filtros anteriores
            this.lastGroup = null;
            this.knownApps = new Map();   // appKey -> unread
            this.selfReadAt = 0;          // última marca hecha desde esta vista
            this.init();
        }

        init() {
            this.bindEvents();
            this.initTabs();
            this.bindPermissionFilter();
            window.profileManager = this;
        }

        // === PESTAÑAS ===
        initTabs() {
            const wanted = new URLSearchParams(location.search).get('tab')
                || location.hash.replace('#', '')
                || document.body.dataset.initialTab
                || 'info';
            const initial = TABS.includes(wanted) ? wanted : 'info';

            document.querySelectorAll('#profileTabs button[data-bs-toggle="tab"]').forEach((btn) => {
                btn.addEventListener('shown.bs.tab', (e) => {
                    const id = e.target.getAttribute('data-bs-target').replace('#', '');
                    const url = new URL(location.href);
                    url.searchParams.set('tab', id);
                    url.hash = '';
                    history.replaceState(null, '', url);
                    if (id === 'notifications') this.ensureNotificationsLoaded();
                });
            });

            const btn = document.getElementById(initial + '-tab');
            if (btn && initial !== 'info' && window.bootstrap) {
                window.bootstrap.Tab.getOrCreateInstance(btn).show();   // dispara shown.bs.tab
            }
            // Contador del badge de la pestaña aunque no esté activa.
            this.refreshBadge();
        }

        // === EVENTOS ===
        bindEvents() {
            const status = document.getElementById('readStatusFilter');
            if (status) {
                status.addEventListener('change', (e) => {
                    this.statusFilter = e.target.value;
                    this.reloadNotifications();
                });
            }

            const chips = document.getElementById('notificationFilters');
            if (chips) {
                chips.addEventListener('click', (e) => {
                    const chip = e.target.closest('.notif-chip');
                    if (!chip) return;
                    this.appFilter = chip.dataset.appKey || '';
                    this.syncChips();
                    this.reloadNotifications();
                });
            }

            const more = document.getElementById('loadMoreBtn');
            if (more) more.addEventListener('click', () => this.loadMore());

            const markAll = document.getElementById('markAllReadBtn');
            if (markAll) markAll.addEventListener('click', () => this.markAllAsRead());

            const save = document.getElementById('saveProfileBtn');
            if (save) save.addEventListener('click', () => this.saveProfile());

            const container = document.getElementById('notificationsContainer');
            if (container) {
                container.addEventListener('click', (e) => {
                    const markBtn = e.target.closest('.mark-read-btn');
                    if (markBtn) {
                        e.stopPropagation();
                        this.markNotificationAsRead(markBtn.dataset.notifId);
                        return;
                    }
                    const item = e.target.closest('.notification-item');
                    if (item) this.activateItem(item);
                });
                container.addEventListener('keydown', (e) => {
                    if (e.key !== 'Enter' && e.key !== ' ') return;
                    if (e.target.closest('.mark-read-btn')) return;
                    const item = e.target.closest('.notification-item');
                    if (item) {
                        e.preventDefault();
                        this.activateItem(item);
                    }
                });
            }
        }

        // === PERMISOS: filtro ===
        bindPermissionFilter() {
            const input = document.getElementById('permissionFilter');
            if (!input) return;
            input.addEventListener('input', () => {
                const q = input.value.trim().toLowerCase();
                let anyVisible = false;
                document.querySelectorAll('#permissions details.app-permission-section').forEach((det) => {
                    let hits = 0;
                    det.querySelectorAll('.perm-badge').forEach((b) => {
                        const ok = !q || b.textContent.toLowerCase().includes(q);
                        b.classList.toggle('d-none', !ok);
                        if (ok) hits++;
                    });
                    // Con filtro activo solo se muestran las apps con coincidencias (y se abren).
                    det.classList.toggle('d-none', !!q && hits === 0);
                    if (q && hits > 0) det.open = true;
                    if (!det.classList.contains('d-none')) anyVisible = true;
                });
                const empty = document.getElementById('permissionFilterEmpty');
                if (empty) empty.classList.toggle('d-none', anyVisible || !q);
            });
        }

        // === NOTIFICACIONES: carga ===
        ensureNotificationsLoaded() {
            if (this.loaded) return;
            this.loaded = true;
            this.reloadNotifications();
        }

        /** Reinicia la lista (primera página) con los filtros vigentes. */
        reloadNotifications() {
            this.lastId = null;
            this.lastGroup = null;
            this.hasMore = false;
            return this.fetchPage(true);
        }

        /** Compatibilidad con profile_inline.js (eventos de socket). */
        loadNotifications() {
            if (!this.loaded) return Promise.resolve();
            if (Date.now() - this.selfReadAt < 2000) return Promise.resolve();   // eco de nuestra propia marca
            return this.reloadNotifications();
        }

        loadMore() {
            if (this.loading || !this.hasMore) return Promise.resolve();
            return this.fetchPage(false);
        }

        async fetchPage(reset) {
            const container = document.getElementById('notificationsContainer');
            if (!container) return;
            const seq = ++this.requestSeq;
            this.loading = true;
            this.setLoadMore(false, true);

            const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
            if (this.appFilter) params.set('app', this.appFilter);
            if (this.statusFilter === 'unread') params.set('unread', 'true');
            if (!reset && this.lastId) params.set('before_id', String(this.lastId));

            try {
                const response = await fetch(`${this.apiBase}/notifications?${params}`, { credentials: 'include' });
                const result = await response.json();
                if (seq !== this.requestSeq) return;   // llegó tarde: ya hay otro filtro

                if (!response.ok || !result.data) throw new Error('bad response');
                const data = result.data;
                const items = data.items || [];

                if (reset) {
                    container.innerHTML = '';
                    this.lastGroup = null;
                }
                if (reset && items.length === 0) {
                    this.renderEmpty();
                } else {
                    this.appendItems(items);
                }
                items.forEach((n) => this.rememberApp(n.app_name));
                if (items.length) this.lastId = items[items.length - 1].id;
                this.hasMore = !!data.has_more;
                if (!this.appFilter && this.statusFilter === 'all') this.updateBadge(data.unread);
                this.renderChips();
                this.refreshUnreadPerApp();
            } catch (error) {
                if (seq !== this.requestSeq) return;
                console.error('Error loading notifications:', error);
                if (reset) this.renderError();
                else this.showError('No se pudieron cargar más notificaciones');
            } finally {
                if (seq === this.requestSeq) {
                    this.loading = false;
                    this.setLoadMore(this.hasMore, false);
                }
            }
        }

        setLoadMore(visible, busy) {
            const wrap = document.getElementById('loadMoreWrap');
            const btn = document.getElementById('loadMoreBtn');
            if (!wrap || !btn) return;
            wrap.classList.toggle('d-none', !visible && !busy);
            btn.disabled = !!busy;
            btn.textContent = busy ? 'Cargando…' : 'Cargar más';
            if (busy && !this.lastId) wrap.classList.add('d-none');
        }

        // === NOTIFICACIONES: render ===
        appendItems(items) {
            const container = document.getElementById('notificationsContainer');
            let html = '';
            items.forEach((n) => {
                const group = this.groupOf(n.created_at);
                if (group !== this.lastGroup) {
                    html += `<h6 class="notif-group-header">${this.escapeHtml(group)}</h6>`;
                    this.lastGroup = group;
                }
                html += this.itemHtml(n);
            });
            container.insertAdjacentHTML('beforeend', html);
        }

        itemHtml(n) {
            const unread = !n.is_read;
            const color = this.safeColor(n.app_color_hex);
            const icon = this.escapeHtml(this.safeIcon(n.app_icon));
            const url = this.safeUrl(n.action_url);
            const attrs = url
                ? ` role="link" tabindex="0" data-url="${this.escapeHtml(url)}"`
                : '';
            return `
                <div class="notification-item ${unread ? 'unread' : 'read'}${url ? ' has-action' : ''}"
                     data-app="${this.escapeHtml(this.getAppKey(n.app_name))}"
                     data-notif-id="${Number(n.id)}"${attrs}>
                    <div class="notification-icon" style="background-color: ${color}">
                        <i class="bi ${icon}"></i>
                    </div>
                    <div class="notification-content">
                        <div class="d-flex justify-content-between align-items-start gap-2 mb-1">
                            <h6 class="mb-0 ${unread ? '' : 'text-muted'}">${this.escapeHtml(n.title)}</h6>
                            <small class="text-muted text-nowrap">${this.escapeHtml(this.formatTimeAgo(n.created_at))}</small>
                        </div>
                        ${n.body ? `<p class="text-muted small mb-2">${this.escapeHtml(n.body)}</p>` : ''}
                        <div class="d-flex justify-content-between align-items-center">
                            <span class="badge" style="background-color: ${color}">${this.escapeHtml(this.getAppDisplayName(this.getAppKey(n.app_name)))}</span>
                            <div class="notification-actions">
                                ${unread ? `
                                    <button type="button" class="btn btn-sm btn-outline-secondary mark-read-btn"
                                            data-notif-id="${Number(n.id)}" title="Marcar como leída" aria-label="Marcar como leída">
                                        <i class="bi bi-check2"></i>
                                    </button>` : ''}
                            </div>
                        </div>
                    </div>
                </div>`;
        }

        renderEmpty() {
            const container = document.getElementById('notificationsContainer');
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-bell-slash display-4 text-muted"></i>
                    <p class="text-muted mt-3">No tienes notificaciones</p>
                </div>`;
        }

        renderError() {
            const container = document.getElementById('notificationsContainer');
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-exclamation-triangle display-4 text-danger"></i>
                    <p class="text-danger mt-3">Error al cargar notificaciones</p>
                </div>`;
        }

        // === NOTIFICACIONES: chips por app ===
        rememberApp(appName) {
            const key = this.getAppKey(appName);
            if (!this.knownApps.has(key)) this.knownApps.set(key, 0);
        }

        async refreshUnreadPerApp() {
            try {
                const r = await fetch(`${this.apiBase}/notifications/unread-counts`, { credentials: 'include' });
                const j = await r.json();
                const counts = (j.data && j.data.counts) || {};
                Object.entries(counts).forEach(([k, v]) => this.knownApps.set(this.getAppKey(k), v));
                this.knownApps.forEach((_, k) => { if (!(k in counts)) this.knownApps.set(k, 0); });
                this.renderChips();
            } catch (_) { /* los chips siguen sin contador */ }
        }

        renderChips() {
            const group = document.getElementById('notificationFilters');
            if (!group) return;
            group.querySelectorAll('[data-dynamic="1"]').forEach((el) => el.remove());
            [...this.knownApps.entries()]
                .sort((a, b) => this.getAppDisplayName(a[0]).localeCompare(this.getAppDisplayName(b[0])))
                .forEach(([key, unread]) => {
                    const b = document.createElement('button');
                    b.type = 'button';
                    b.className = 'notif-chip';
                    b.dataset.dynamic = '1';
                    b.dataset.appKey = key;
                    b.textContent = this.getAppDisplayName(key);
                    if (unread > 0) {
                        const c = document.createElement('span');
                        c.className = 'badge text-bg-primary ms-1';
                        c.textContent = unread > 99 ? '99+' : String(unread);
                        b.appendChild(c);
                    }
                    group.appendChild(b);
                });
            this.syncChips();
        }

        syncChips() {
            document.querySelectorAll('#notificationFilters .notif-chip').forEach((c) => {
                const on = (c.dataset.appKey || '') === this.appFilter;
                c.classList.toggle('active', on);
                c.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
        }

        // === NOTIFICACIONES: acciones ===
        activateItem(item) {
            const id = item.dataset.notifId;
            const url = item.dataset.url;
            if (item.classList.contains('unread')) this.markNotificationAsRead(id);
            if (url) this.openNotificationUrl(url);
        }

        /** Solo rutas del mismo origen (o http/https absolutas); nada de javascript:/data:. */
        safeUrl(raw) {
            if (!raw || typeof raw !== 'string') return null;
            const value = raw.trim();
            if (!value || value.startsWith('//')) return null;
            try {
                const u = new URL(value, location.origin);
                if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
                return u.origin === location.origin ? u.pathname + u.search + u.hash : u.href;
            } catch (_) {
                return null;
            }
        }

        openNotificationUrl(raw) {
            const url = this.safeUrl(raw);
            if (!url) return;

            const embedded = window.self !== window.top;
            const inMobile = document.body.classList.contains('in-mobile-iframe');
            if (embedded && !inMobile) {
                try {
                    if (window.parent.desktop && typeof window.parent.desktop.openUrl === 'function') {
                        window.parent.desktop.openUrl(url);
                        return;
                    }
                } catch (_) { /* parent inaccesible: probar postMessage */ }
                try {
                    window.parent.postMessage({ type: 'OPEN_URL', url }, location.origin);
                } catch (err) {
                    console.warn('[Profile] no se pudo abrir la URL en el escritorio:', err);
                }
                return;
            }
            window.location.href = url;
        }

        async markNotificationAsRead(notifId) {
            try {
                const response = await fetch(`${this.apiBase}/notifications/${encodeURIComponent(notifId)}/read`, {
                    method: 'PATCH', credentials: 'include',
                });
                if (!response.ok) return;
                this.selfReadAt = Date.now();
                const item = document.querySelector(`.notification-item[data-notif-id="${CSS.escape(String(notifId))}"]`);
                if (item) {
                    item.classList.remove('unread');
                    item.classList.add('read');
                    const title = item.querySelector('h6');
                    if (title) title.classList.add('text-muted');
                    const btn = item.querySelector('.mark-read-btn');
                    if (btn) btn.remove();
                }
                this.refreshBadge();
                this.refreshUnreadPerApp();
            } catch (error) {
                console.error('Error marking notification as read:', error);
                this.showError('Error al marcar como leída');
            }
        }

        async markAllAsRead() {
            const btn = document.getElementById('markAllReadBtn');
            if (btn) btn.disabled = true;
            try {
                const qs = this.appFilter ? `?app=${encodeURIComponent(this.appFilter)}` : '';
                const response = await fetch(`${this.apiBase}/notifications/mark-all-read${qs}`, {
                    method: 'PATCH', credentials: 'include',
                });
                if (response.ok) {
                    this.selfReadAt = Date.now();
                    this.showSuccess('Notificaciones marcadas como leídas');
                    await this.reloadNotifications();
                    this.refreshBadge();
                } else {
                    this.showError('Error al marcar notificaciones');
                }
            } catch (error) {
                console.error('Error marking all as read:', error);
                this.showError('Error de conexión');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        // === PERFIL ===
        async saveProfile() {
            const email = document.getElementById('editEmail')?.value;
            if (!email) {
                this.showError('El correo electrónico es requerido');
                return;
            }
            const btn = document.getElementById('saveProfileBtn');
            if (btn) btn.disabled = true;
            try {
                const response = await fetch(`${this.apiBase}/user/me/profile`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email }),
                });
                const result = await response.json().catch(() => ({}));
                if (response.ok) {
                    this.showSuccess('Perfil actualizado correctamente');
                    const modal = window.bootstrap.Modal.getInstance(document.getElementById('editProfileModal'));
                    if (modal) modal.hide();
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    this.showError(this.errorText(result) || 'Error al actualizar el perfil');
                }
            } catch (error) {
                console.error('Error saving profile:', error);
                this.showError('Error de conexión');
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        errorText(result) {
            const d = result && result.detail;
            if (typeof d === 'string') return d;
            if (Array.isArray(d) && d.length) return d.map((x) => (x && x.msg) || '').filter(Boolean).join('. ');
            return '';
        }

        // === BADGE ===
        updateBadge(count) {
            const badge = document.getElementById('notificationBadge');
            if (!badge) return;
            const n = Number(count) || 0;
            badge.textContent = n > 99 ? '99+' : String(n);
            badge.style.display = n > 0 ? 'inline' : 'none';
        }

        async refreshBadge() {
            try {
                const r = await fetch(`${this.apiBase}/notifications/unread-counts`, { credentials: 'include' });
                const j = await r.json();
                if (j.data) this.updateBadge(j.data.total);
            } catch (_) { /* sin badge */ }
        }

        // === UTILIDADES ===
        groupOf(dateString) {
            const d = new Date(dateString);
            if (isNaN(d)) return 'Anteriores';
            const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
            const today = startOf(new Date());
            const days = Math.round((today - startOf(d)) / 86400000);
            if (days <= 0) return 'Hoy';
            if (days === 1) return 'Ayer';
            if (days < 7) return 'Esta semana';
            if (days < 30) return 'Este mes';
            return 'Anteriores';
        }

        safeColor(value) {
            return /^#[0-9a-f]{3,8}$/i.test(String(value || '')) ? value : '#6c757d';
        }

        safeIcon(value) {
            return /^bi-[a-z0-9-]+$/i.test(String(value || '')) ? value : 'bi-bell';
        }

        getAppKey(appName) {
            if (!appName) return 'other';
            const lower = String(appName).trim().toLowerCase();
            const legacy = { 'itcj core': 'core', 'help desk': 'helpdesk', 'mantenimiento': 'maint' };
            return legacy[lower] || lower;
        }

        getAppDisplayName(appKey) {
            if (APP_NAMES[appKey]) return APP_NAMES[appKey];
            return appKey ? appKey.charAt(0).toUpperCase() + appKey.slice(1) : 'Otro';
        }

        escapeHtml(value) {
            return String(value == null ? '' : value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        formatTimeAgo(dateString) {
            if (!dateString) return '';
            const date = new Date(dateString);
            const diff = Math.floor((Date.now() - date) / 1000);
            if (diff < 60) return 'Hace unos segundos';
            if (diff < 3600) return `Hace ${Math.floor(diff / 60)} min`;
            if (diff < 86400) return `Hace ${Math.floor(diff / 3600)} h`;
            if (diff < 604800) return `Hace ${Math.floor(diff / 86400)} días`;
            return date.toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' });
        }

        showSuccess(message) { this.toast('successToast', 'successMessage', message); }
        showError(message) { this.toast('errorToast', 'errorMessage', message); }

        toast(toastId, messageId, message) {
            const toast = document.getElementById(toastId);
            const el = document.getElementById(messageId);
            if (toast && el && window.bootstrap) {
                el.textContent = message;
                window.bootstrap.Toast.getOrCreateInstance(toast).show();
            }
        }
    }

    document.addEventListener('DOMContentLoaded', () => { new ProfileManager(); });
})();
