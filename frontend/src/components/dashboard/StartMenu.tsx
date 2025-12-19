import { User, Settings, LogOut } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks';
import { useLogout } from '@/features/auth/hooks/useLogout';

export interface StartMenuProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenProfile: () => void;
  onOpenSettings: () => void;
}

/**
 * StartMenu - Menú de inicio estilo Windows
 *
 * Características:
 * - Información del usuario
 * - Acceso a perfil
 * - Acceso a configuración
 * - Cerrar sesión
 * - Animación de apertura/cierre
 */
export function StartMenu({ isOpen, onClose, onOpenProfile, onOpenSettings }: StartMenuProps) {
  const { user } = useAuth();
  const { logout } = useLogout();

  if (!isOpen) return null;

  const handleLogout = () => {
    logout();
    onClose();
  };

  return (
    <>
      {/* Overlay para cerrar al hacer click fuera */}
      <div className="start-menu-overlay" onClick={onClose} />

      {/* Menú */}
      <div className="start-menu">
        {/* User Info */}
        <div className="start-menu-header">
          <div className="user-avatar">
            <User size={32} />
          </div>
          <div className="user-info">
            <div className="user-name">{user?.full_name || 'Usuario'}</div>
            <div className="user-role">{user?.role || 'N/A'}</div>
          </div>
        </div>

        {/* Menu Items */}
        <div className="start-menu-items">
          <button
            className="start-menu-item"
            onClick={() => {
              onOpenProfile();
              onClose();
            }}
          >
            <User size={18} />
            <span>Perfil</span>
          </button>

          <button
            className="start-menu-item"
            onClick={() => {
              onOpenSettings();
              onClose();
            }}
          >
            <Settings size={18} />
            <span>Configuración</span>
          </button>

          <div className="start-menu-divider" />

          <button className="start-menu-item logout" onClick={handleLogout}>
            <LogOut size={18} />
            <span>Cerrar Sesión</span>
          </button>
        </div>
      </div>
    </>
  );
}
