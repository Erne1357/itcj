import { useState, useEffect } from 'react';
import { Wifi, Volume2, Battery, Bell } from 'lucide-react';

export interface SystemTrayProps {
  notificationCount?: number;
  onNotificationClick?: () => void;
}

/**
 * SystemTray - Bandeja del sistema con reloj y controles
 *
 * Características:
 * - Reloj en tiempo real
 * - Íconos de sistema (Wifi, Volume, Battery)
 * - Campana de notificaciones con badge
 * - Actualización automática cada segundo
 */
export function SystemTray({
  notificationCount = 0,
  onNotificationClick,
}: SystemTrayProps) {
  const [time, setTime] = useState('');
  const [date, setDate] = useState('');

  useEffect(() => {
    const updateDateTime = () => {
      const now = new Date();

      // Formato de hora: HH:MM
      const hours = String(now.getHours()).padStart(2, '0');
      const minutes = String(now.getMinutes()).padStart(2, '0');
      setTime(`${hours}:${minutes}`);

      // Formato de fecha: DD/MM/YYYY
      const day = String(now.getDate()).padStart(2, '0');
      const month = String(now.getMonth() + 1).padStart(2, '0');
      const year = now.getFullYear();
      setDate(`${day}/${month}/${year}`);
    };

    // Actualizar inmediatamente
    updateDateTime();

    // Actualizar cada segundo
    const interval = setInterval(updateDateTime, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="system-tray">
      {/* Notification Bell */}
      <button
        className="system-icon"
        title="Notificaciones"
        onClick={onNotificationClick}
        style={{ position: 'relative' }}
      >
        <Bell size={16} />
        {notificationCount > 0 && (
          <span
            className="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger"
            style={{
              fontSize: '9px',
              padding: '2px 4px',
              minWidth: '16px',
            }}
          >
            {notificationCount > 99 ? '99+' : notificationCount}
          </span>
        )}
      </button>

      {/* System Icons */}
      <button className="system-icon" title="Red">
        <Wifi size={16} />
      </button>
      <button className="system-icon" title="Volumen">
        <Volume2 size={16} />
      </button>
      <button className="system-icon" title="Batería">
        <Battery size={16} />
      </button>

      {/* Date & Time */}
      <div className="datetime">
        <div className="time">{time}</div>
        <div className="date">{date}</div>
      </div>
    </div>
  );
}
