import { Bell, X } from 'lucide-react';

export interface NotificationsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * NotificationsPanel - Panel de notificaciones estilo Windows
 *
 * Características:
 * - Lista de notificaciones
 * - Placeholder para futuro desarrollo
 * - Animación de apertura/cierre
 */
export function NotificationsPanel({ isOpen, onClose }: NotificationsPanelProps) {
  if (!isOpen) return null;

  return (
    <>
      {/* Overlay para cerrar al hacer click fuera */}
      <div className="notifications-overlay" onClick={onClose} />

      {/* Panel */}
      <div className="notifications-panel">
        {/* Header */}
        <div className="notifications-header">
          <div className="notifications-title">
            <Bell size={20} />
            <span>Notificaciones</span>
          </div>
          <button className="notifications-close" onClick={onClose} aria-label="Cerrar">
            <X size={18} />
          </button>
        </div>

        {/* Content - Placeholder */}
        <div className="notifications-content">
          <div className="notifications-empty">
            <Bell size={48} className="text-muted" />
            <p className="text-muted mt-3">No hay notificaciones</p>
            <small className="text-muted">Las notificaciones aparecerán aquí</small>
          </div>
        </div>
      </div>
    </>
  );
}
