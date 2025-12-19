import type { HTMLAttributes } from 'react';
import clsx from 'clsx';

export interface DesktopIconProps extends HTMLAttributes<HTMLDivElement> {
  icon: string;
  label: string;
  badge?: number;
  onDoubleClick?: () => void;
  selected?: boolean;
}

/**
 * DesktopIcon - Icono de aplicación en el escritorio
 *
 * Características:
 * - Estilo Windows/MacOS con glassmorphism
 * - Badge para notificaciones
 * - Hover y selected states
 * - Double click para abrir
 */
export function DesktopIcon({
  icon,
  label,
  badge,
  onDoubleClick,
  selected = false,
  className,
  ...props
}: DesktopIconProps) {
  return (
    <div
      className={clsx('desktop-icon', { selected }, className)}
      onDoubleClick={onDoubleClick}
      {...props}
    >
      <div className="icon-container">
        <img src={icon} alt={label} draggable={false} />
        {badge && badge > 0 && (
          <span
            className="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger"
            style={{ fontSize: '9px', padding: '2px 5px' }}
          >
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </div>
      <span className="icon-label">{label}</span>
    </div>
  );
}
