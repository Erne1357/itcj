import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { DesktopIcon } from './DesktopIcon';
import { Taskbar } from './Taskbar';
import { Window } from './Window';
import { StartMenu } from './StartMenu';
import { NotificationsPanel } from './NotificationsPanel';
import './desktop.css';

export interface DesktopApp {
  id: string;
  icon: string;
  label: string;
  url?: string; // URL para abrir en iframe
  badge?: number;
  onOpen?: () => void;
}

export interface DesktopProps {
  apps?: DesktopApp[];
  notificationCount?: number;
}

interface OpenWindow {
  id: string;
  title: string;
  url: string;
  icon?: string;
  isMinimized: boolean;
  zIndex: number;
}

/**
 * Desktop - Escritorio estilo Windows/MacOS
 *
 * Características:
 * - Grid de iconos de aplicaciones
 * - Doble click para abrir apps en ventanas
 * - Gestión de ventanas (minimizar, maximizar, cerrar)
 * - Menú de inicio con perfil y configuración
 * - Panel de notificaciones
 * - Papelera (estético)
 * - Taskbar con apps ancladas
 * - Fondo institucional con glassmorphism
 * - Responsivo para desktop y mobile
 */
export function Desktop({ apps = [], notificationCount = 0 }: DesktopProps) {
  const [selectedIcon, setSelectedIcon] = useState<string | null>(null);
  const [openWindows, setOpenWindows] = useState<OpenWindow[]>([]);
  const [nextZIndex, setNextZIndex] = useState(1000);
  const [isStartMenuOpen, setIsStartMenuOpen] = useState(false);
  const [isNotificationsPanelOpen, setIsNotificationsPanelOpen] = useState(false);

  const handleIconClick = (appId: string) => {
    setSelectedIcon(appId);
  };

  const handleIconDoubleClick = (app: DesktopApp) => {
    // Si la app tiene URL, abrirla en ventana
    if (app.url) {
      openWindow(app.id, app.label, app.url, app.icon);
    } else if (app.onOpen) {
      // Si tiene onOpen callback, ejecutarlo
      app.onOpen();
    }
    setSelectedIcon(null);
  };

  const openWindow = (id: string, title: string, url: string, icon?: string) => {
    // Verificar si la ventana ya está abierta
    const existingWindow = openWindows.find((w) => w.id === id);
    if (existingWindow) {
      // Si está minimizada, restaurarla
      if (existingWindow.isMinimized) {
        setOpenWindows((windows) =>
          windows.map((w) =>
            w.id === id ? { ...w, isMinimized: false, zIndex: nextZIndex } : w
          )
        );
        setNextZIndex((z) => z + 1);
      } else {
        // Si ya está abierta, traerla al frente
        focusWindow(id);
      }
      return;
    }

    // Abrir nueva ventana
    const newWindow: OpenWindow = {
      id,
      title,
      url,
      icon,
      isMinimized: false,
      zIndex: nextZIndex,
    };

    setOpenWindows((windows) => [...windows, newWindow]);
    setNextZIndex((z) => z + 1);
  };

  const closeWindow = (id: string) => {
    setOpenWindows((windows) => windows.filter((w) => w.id !== id));
  };

  const minimizeWindow = (id: string) => {
    setOpenWindows((windows) => windows.map((w) => (w.id === id ? { ...w, isMinimized: true } : w)));
  };

  const focusWindow = (id: string) => {
    setOpenWindows((windows) =>
      windows.map((w) => (w.id === id ? { ...w, zIndex: nextZIndex } : w))
    );
    setNextZIndex((z) => z + 1);
  };

  const handleDesktopClick = () => {
    setSelectedIcon(null);
  };

  const handleMenuClick = () => {
    setIsStartMenuOpen(!isStartMenuOpen);
  };

  const handleNotificationClick = () => {
    setIsNotificationsPanelOpen(!isNotificationsPanelOpen);
  };

  const handleOpenProfile = () => {
    // TODO: Abrir ventana de perfil (placeholder)
    console.log('Abrir perfil');
  };

  const handleOpenSettings = () => {
    // TODO: Abrir ventana de configuración (placeholder)
    console.log('Abrir configuración');
  };

  // Apps por defecto para el taskbar
  const agendaTecApp = apps.find((app) => app.id === 'agendatec');
  const helpDeskApp = apps.find((app) => app.id === 'helpdesk');

  return (
    <div className="desktop-container">
      {/* Desktop Area */}
      <div className="desktop-area" onClick={handleDesktopClick}>
        {/* Recycle Bin - Esquina superior derecha */}
        <div className="recycle-bin" onDoubleClick={() => console.log('Papelera')}>
          <div className="recycle-bin-icon">
            <Trash2 size={48} color="white" strokeWidth={1.5} />
          </div>
          <span className="icon-label">Papelera</span>
        </div>

        {/* Apps Grid */}
        <div className="desktop-icons-grid">
          {apps.map((app) => (
            <DesktopIcon
              key={app.id}
              icon={app.icon}
              label={app.label}
              badge={app.badge}
              selected={selectedIcon === app.id}
              onClick={() => handleIconClick(app.id)}
              onDoubleClick={() => handleIconDoubleClick(app)}
            />
          ))}
        </div>
      </div>

      {/* Windows */}
      {openWindows.map((window) => (
        <Window
          key={window.id}
          id={window.id}
          title={window.title}
          url={window.url}
          icon={window.icon}
          isMinimized={window.isMinimized}
          zIndex={window.zIndex}
          onClose={() => closeWindow(window.id)}
          onMinimize={() => minimizeWindow(window.id)}
          onFocus={() => focusWindow(window.id)}
        />
      ))}

      {/* Start Menu */}
      <StartMenu
        isOpen={isStartMenuOpen}
        onClose={() => setIsStartMenuOpen(false)}
        onOpenProfile={handleOpenProfile}
        onOpenSettings={handleOpenSettings}
      />

      {/* Notifications Panel */}
      <NotificationsPanel
        isOpen={isNotificationsPanelOpen}
        onClose={() => setIsNotificationsPanelOpen(false)}
      />

      {/* Taskbar */}
      <Taskbar
        onMenuClick={handleMenuClick}
        onAgendaTecClick={() =>
          agendaTecApp?.url
            ? openWindow(agendaTecApp.id, agendaTecApp.label, agendaTecApp.url, agendaTecApp.icon)
            : agendaTecApp?.onOpen?.()
        }
        onHelpDeskClick={() =>
          helpDeskApp?.url
            ? openWindow(helpDeskApp.id, helpDeskApp.label, helpDeskApp.url, helpDeskApp.icon)
            : helpDeskApp?.onOpen?.()
        }
        notificationCount={notificationCount}
        onNotificationClick={handleNotificationClick}
        openApps={openWindows.map((w) => ({
          id: w.id,
          title: w.title,
          icon: w.icon,
          isMinimized: w.isMinimized,
          isActive: w.zIndex === nextZIndex - 1,
        }))}
        onTaskbarAppClick={(appId) => {
          const window = openWindows.find((w) => w.id === appId);
          if (window) {
            if (window.isMinimized) {
              // Restaurar si está minimizada
              setOpenWindows((windows) =>
                windows.map((w) => (w.id === appId ? { ...w, isMinimized: false, zIndex: nextZIndex } : w))
              );
              setNextZIndex((z) => z + 1);
            } else if (window.zIndex === nextZIndex - 1) {
              // Si ya está activa, minimizarla
              minimizeWindow(appId);
            } else {
              // Traer al frente
              focusWindow(appId);
            }
          }
        }}
      />
    </div>
  );
}
