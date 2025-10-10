// itcj/core/static/js/profile-menu.js

class ProfileMenu {
    constructor(desktopInstance) {
        this.desktop = desktopInstance;
        this.isOpen = false;
        this.userData = null;
        this.useLogoutModal = false; // ⭐ Cambia a true si quieres modal de confirmación
        this.init();
    }

    async init() {
        await this.loadUserData();
        this.render();
        this.setupEventListeners();
    }

    async loadUserData() {
        try {
            const response = await fetch('/api/core/v1/user/me');
            const result = await response.json();
            
            if (response.ok && result.data) {
                this.userData = result.data;
            } else {
                console.error('Error loading user data:', result);
                this.userData = {
                    full_name: 'Usuario',
                    role: 'Usuario',
                    positions: []
                };
            }
        } catch (error) {
            console.error('Error fetching user data:', error);
            this.userData = {
                full_name: 'Usuario',
                role: 'Usuario',
                positions: []
            };
        }
    }

    getInitials(name) {
        if (!name) return 'U';
        const parts = name.trim().split(' ');
        if (parts.length === 1) return parts[0][0].toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    render() {
        const existingMenu = document.querySelector('.profile-menu');
        if (existingMenu) {
            existingMenu.remove();
        }

        const existingOverlay = document.querySelector('.profile-menu-overlay');
        if (existingOverlay) {
            existingOverlay.remove();
        }

        // ⭐ NUEVO: Remover modal de logout existente
        const existingLogoutModal = document.querySelector('.logout-modal');
        if (existingLogoutModal) {
            existingLogoutModal.remove();
        }

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'profile-menu-overlay';
        overlay.id = 'profileMenuOverlay';
        document.body.appendChild(overlay);

        // Create menu
        const menu = document.createElement('div');
        menu.className = 'profile-menu';
        menu.id = 'profileMenu';
        
        const initials = this.getInitials(this.userData?.full_name);
        const positions = this.userData?.positions || [];
        
        menu.innerHTML = `
            <!-- ⭐ User Info - Doble clic para abrir perfil -->
            <div class="profile-menu-user" id="profileMenuUser" title="Doble clic para ver mi perfil">
                <div class="profile-menu-avatar">${initials}</div>
                <div class="profile-menu-info">
                    <div class="profile-menu-name">${this.userData?.full_name || 'Usuario'}</div>
                    <div class="profile-menu-role">${this.userData?.role || 'Usuario'}</div>
                </div>
            </div>

            <!-- Positions (si existen) -->
            ${positions.length > 0 ? `
                <div class="profile-menu-positions">
                    ${positions.map(pos => `
                        <div class="profile-menu-position-item">
                            <div class="profile-menu-position-title">
                                <i data-lucide="briefcase" style="width:12px;height:12px;display:inline;margin-right:4px;"></i>
                                ${pos.title}
                            </div>
                            ${pos.department ? `
                                <div class="profile-menu-position-dept">${pos.department}</div>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>
            ` : ''}

            <!-- Actions -->
            <div class="profile-menu-actions">
                <button class="profile-menu-action" id="profileMenuSettings" title="Doble clic para abrir configuración">
                    <i data-lucide="settings"></i>
                    <span>Configuración</span>
                </button>
                <button class="profile-menu-action danger" id="profileMenuLogout">
                    <i data-lucide="log-out"></i>
                    <span>Cerrar sesión</span>
                </button>
            </div>
        `;

        document.body.appendChild(menu);

        // ⭐ NUEVO: Crear modal de logout si está habilitado
        if (this.useLogoutModal) {
            this.createLogoutModal();
        }

        // Initialize lucide icons
        if (window.lucide) {
            lucide.createIcons();
        }

        this.setupMenuActions();
    }

    // ⭐ NUEVO: Crear modal de confirmación de logout
    createLogoutModal() {
        const modal = document.createElement('div');
        modal.className = 'logout-modal';
        modal.id = 'logoutModal';
        
        modal.innerHTML = `
            <div class="logout-modal-header">
                <div class="logout-modal-icon">
                    <i data-lucide="log-out"></i>
                </div>
                <div class="logout-modal-title">Cerrar sesión</div>
            </div>
            <div class="logout-modal-body">
                ¿Estás seguro de que deseas cerrar sesión?
            </div>
            <div class="logout-modal-actions">
                <button class="logout-modal-button secondary" id="logoutModalCancel">
                    Cancelar
                </button>
                <button class="logout-modal-button danger" id="logoutModalConfirm">
                    Cerrar sesión
                </button>
            </div>
        `;

        document.body.appendChild(modal);

        // Setup modal actions
        document.getElementById('logoutModalCancel')?.addEventListener('click', () => {
            this.hideLogoutModal();
        });

        document.getElementById('logoutModalConfirm')?.addEventListener('click', () => {
            this.hideLogoutModal();
            this.performLogout();
        });

        // Initialize lucide icons
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    showLogoutModal() {
        const modal = document.getElementById('logoutModal');
        const overlay = document.getElementById('profileMenuOverlay');
        
        if (modal) {
            modal.classList.add('show');
        }
        
        // Keep overlay visible
        if (overlay) {
            overlay.classList.add('show');
        }
    }

    hideLogoutModal() {
        const modal = document.getElementById('logoutModal');
        const overlay = document.getElementById('profileMenuOverlay');
        
        if (modal) {
            modal.classList.remove('show');
        }
        
        // Hide overlay too
        if (overlay) {
            overlay.classList.remove('show');
        }
    }

    setupEventListeners() {
        const startButton = document.querySelector('.start-button');
        const overlay = document.getElementById('profileMenuOverlay');
        
        if (startButton) {
            startButton.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggle();
            });
        }

        if (overlay) {
            overlay.addEventListener('click', () => {
                this.close();
                this.hideLogoutModal();
            });
        }

        // Cerrar con ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (this.isOpen) {
                    this.close();
                }
                this.hideLogoutModal();
            }
        });
    }

    setupMenuActions() {
        const userSection = document.getElementById('profileMenuUser');
        const settingsBtn = document.getElementById('profileMenuSettings');
        const logoutBtn = document.getElementById('profileMenuLogout');

        // ⭐ NUEVO: Doble clic en usuario para abrir perfil
        if (userSection) {
            let clickCount = 0;
            let clickTimer = null;

            userSection.addEventListener('click', () => {
                clickCount++;
                
                if (clickCount === 1) {
                    clickTimer = setTimeout(() => {
                        clickCount = 0;
                    }, 300);
                } else if (clickCount === 2) {
                    clearTimeout(clickTimer);
                    clickCount = 0;
                    this.openProfile();
                    this.close();
                }
            });
        }

        // ⭐ NUEVO: Doble clic en configuración
        if (settingsBtn) {
            let clickCount = 0;
            let clickTimer = null;

            settingsBtn.addEventListener('click', () => {
                clickCount++;
                
                if (clickCount === 1) {
                    clickTimer = setTimeout(() => {
                        clickCount = 0;
                    }, 300);
                } else if (clickCount === 2) {
                    clearTimeout(clickTimer);
                    clickCount = 0;
                    this.openSettings();
                    this.close();
                }
            });
        }

        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => {
                if (this.useLogoutModal) {
                    this.close();
                    this.showLogoutModal();
                } else {
                    // ⭐ Logout directo sin confirmación
                    this.performLogout();
                }
            });
        }
    }

    // ⭐ NUEVO: Abrir perfil del usuario
    openProfile() {
        // Usar la función del desktop para abrir perfil
        if (this.desktop && typeof this.desktop.openApplication === 'function') {
            // Primero verificar si existe la config de profile
            const profileConfig = this.desktop.getAppConfig('profile');
            if (profileConfig) {
                this.desktop.openApplication('profile');
            } else {
                // Si no existe, abrir directamente
                window.location.href = '/itcj/profile';
            }
        } else {
            // Fallback: abrir directamente
            window.location.href = '/itcj/profile';
        }
    }

    openSettings() {
        // Usar la función del desktop para abrir configuración
        if (this.desktop && typeof this.desktop.openApplication === 'function') {
            this.desktop.openApplication('settings');
        } else {
            // Fallback: abrir en ventana nueva
            window.location.href = '/itcj/config';
        }
    }

    async performLogout() {
        try {
            await fetch('/api/core/v1/auth/logout', { 
                method: 'POST', 
                credentials: 'include' 
            });
        } catch (e) {
            console.error('Error during logout:', e);
        }
        
        // Cerrar todas las ventanas
        if (this.desktop && typeof this.desktop.closeAllWindows === 'function') {
            this.desktop.closeAllWindows();
        }
        
        window.location.href = '/itcj/login';
    }

    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    open() {
        const menu = document.getElementById('profileMenu');
        const overlay = document.getElementById('profileMenuOverlay');
        
        if (menu) {
            menu.classList.add('show');
        }
        
        if (overlay) {
            overlay.classList.add('show');
        }
        
        this.isOpen = true;
    }

    close() {
        const menu = document.getElementById('profileMenu');
        const overlay = document.getElementById('profileMenuOverlay');
        
        if (menu) {
            menu.classList.remove('show');
        }
        
        if (overlay) {
            overlay.classList.remove('show');
        }
        
        this.isOpen = false;
    }
}

// Export para usar en dashboard.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ProfileMenu;
}