import { Menu, Search, Calendar, Ticket } from 'lucide-react';
import { SystemTray } from './SystemTray';

export interface OpenApp {
  id: string;
  title: string;
  icon?: string;
  isMinimized: boolean;
  isActive: boolean;
}

export interface TaskbarProps {
  onMenuClick?: () => void;
  onAgendaTecClick?: () => void;
  onHelpDeskClick?: () => void;
  notificationCount?: number;
  onNotificationClick?: () => void;
  openApps?: OpenApp[];
  onTaskbarAppClick?: (appId: string) => void;
}

/**
 * Taskbar - Barra de tareas estilo Windows
 *
 * Características:
 * - Botón de menú (Start button)
 * - Barra de búsqueda con copyright
 * - Apps ancladas (AgendaTec, Help Desk)
 * - Apps abiertas con indicador de estado
 * - System tray con reloj
 */
export function Taskbar({
  onMenuClick,
  onAgendaTecClick,
  onHelpDeskClick,
  notificationCount = 0,
  onNotificationClick,
  openApps = [],
  onTaskbarAppClick,
}: TaskbarProps) {
  return (
    <div className="taskbar">
      {/* Start Button */}
      <button
        className="start-button"
        title="Menú"
        onClick={onMenuClick}
        aria-label="Abrir menú"
      >
        <Menu size={20} />
      </button>

      {/* Search Bar / Copyright */}
      <div className="search-container">
        <Search className="search-icon" size={16} />
        <input
          type="text"
          placeholder="© 2025 ITCJ. Todos los derechos reservados."
          className="search-input disabled"
          readOnly
          aria-label="Copyright"
        />
      </div>

      {/* Pinned Apps */}
      <div className="pinned-apps">
        <button
          className="pinned-app"
          title="AgendaTec"
          onClick={onAgendaTecClick}
          aria-label="Abrir AgendaTec"
        >
          <Calendar size={20} />
        </button>
        <button
          className="pinned-app"
          title="Help Desk"
          onClick={onHelpDeskClick}
          aria-label="Abrir Help Desk"
        >
          <Ticket size={20} />
        </button>
      </div>

      {/* Open Apps */}
      <div className="taskbar-open-apps">
        {openApps.map((app) => (
          <button
            key={app.id}
            className={`taskbar-app ${app.isActive ? 'active' : ''} ${
              app.isMinimized ? 'minimized' : ''
            }`}
            onClick={() => onTaskbarAppClick?.(app.id)}
            title={app.title}
          >
            {app.icon && <img src={app.icon} alt="" className="taskbar-app-icon" />}
            <span className="taskbar-app-title">{app.title}</span>
          </button>
        ))}
      </div>

      {/* System Tray */}
      <SystemTray
        notificationCount={notificationCount}
        onNotificationClick={onNotificationClick}
      />
    </div>
  );
}
