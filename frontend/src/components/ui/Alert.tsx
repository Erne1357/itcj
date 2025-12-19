import type { HTMLAttributes, ReactNode } from 'react';
import clsx from 'clsx';
import { AlertCircle, CheckCircle, Info, XCircle } from 'lucide-react';

export interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'warning' | 'info';
  title?: string;
  icon?: ReactNode;
  showIcon?: boolean;
  dismissible?: boolean;
  onClose?: () => void;
}

/**
 * Alert component para mostrar mensajes informativos
 *
 * Características:
 * - Variantes de Bootstrap (success, danger, warning, info)
 * - Iconos automáticos según variante
 * - Dismissible (puede cerrarse)
 * - Título opcional
 * - Completamente accesible
 */
export function Alert({
  variant = 'info',
  title,
  icon,
  showIcon = true,
  dismissible = false,
  onClose,
  children,
  className,
  ...props
}: AlertProps) {
  // Iconos por defecto según variante
  const defaultIcons = {
    primary: <Info size={20} />,
    secondary: <Info size={20} />,
    success: <CheckCircle size={20} />,
    danger: <XCircle size={20} />,
    warning: <AlertCircle size={20} />,
    info: <Info size={20} />,
  };

  const alertIcon = icon || (showIcon ? defaultIcons[variant] : null);

  return (
    <div
      className={clsx(
        'alert',
        `alert-${variant}`,
        {
          'alert-dismissible': dismissible,
          'd-flex': showIcon,
          'align-items-start': showIcon,
        },
        className
      )}
      role="alert"
      {...props}
    >
      {/* Icon */}
      {alertIcon && <div className="flex-shrink-0 me-2 mt-1">{alertIcon}</div>}

      {/* Content */}
      <div className="flex-grow-1">
        {/* Title */}
        {title && <h5 className="alert-heading mb-2">{title}</h5>}

        {/* Message */}
        {children && <div>{children}</div>}
      </div>

      {/* Close button */}
      {dismissible && (
        <button type="button" className="btn-close" aria-label="Cerrar" onClick={onClose} />
      )}
    </div>
  );
}

/**
 * Helper components para casos de uso comunes
 */
export function ErrorAlert({ title = 'Error', ...props }: Omit<AlertProps, 'variant'>) {
  return <Alert variant="danger" title={title} {...props} />;
}

export function SuccessAlert({ title = 'Éxito', ...props }: Omit<AlertProps, 'variant'>) {
  return <Alert variant="success" title={title} {...props} />;
}

export function WarningAlert({ title = 'Advertencia', ...props }: Omit<AlertProps, 'variant'>) {
  return <Alert variant="warning" title={title} {...props} />;
}

export function InfoAlert({ title, ...props }: Omit<AlertProps, 'variant'>) {
  return <Alert variant="info" title={title} {...props} />;
}
