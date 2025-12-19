import { forwardRef } from 'react';
import type { ButtonHTMLAttributes } from 'react';
import clsx from 'clsx';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:
    | 'primary'
    | 'secondary'
    | 'success'
    | 'danger'
    | 'warning'
    | 'info'
    | 'light'
    | 'dark'
    | 'link';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  loadingText?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  fullWidth?: boolean;
  outline?: boolean;
}

/**
 * Button component con Bootstrap styling y loading state
 *
 * Características:
 * - Variantes de Bootstrap
 * - Tamaños configurables
 * - Estado de loading con spinner
 * - Iconos opcionales
 * - Soporte para outline
 * - Responsive
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      children,
      variant = 'primary',
      size = 'md',
      isLoading = false,
      loadingText,
      leftIcon,
      rightIcon,
      fullWidth = false,
      outline = false,
      disabled,
      className,
      type = 'button',
      ...props
    },
    ref
  ) => {
    const buttonClasses = clsx(
      'btn',
      {
        // Variantes
        [`btn-${variant}`]: !outline,
        [`btn-outline-${variant}`]: outline,
        // Tamaños
        'btn-sm': size === 'sm',
        'btn-lg': size === 'lg',
        // Full width
        'w-100': fullWidth,
        // Disabled state
        disabled: isLoading || disabled,
      },
      className
    );

    return (
      <button
        ref={ref}
        type={type}
        className={buttonClasses}
        disabled={isLoading || disabled}
        {...props}
      >
        {/* Loading spinner */}
        {isLoading && (
          <span
            className="spinner-border spinner-border-sm me-2"
            role="status"
            aria-hidden="true"
          />
        )}

        {/* Left icon */}
        {!isLoading && leftIcon && (
          <span className="me-2" aria-hidden="true">
            {leftIcon}
          </span>
        )}

        {/* Button text */}
        <span>{isLoading && loadingText ? loadingText : children}</span>

        {/* Right icon */}
        {!isLoading && rightIcon && (
          <span className="ms-2" aria-hidden="true">
            {rightIcon}
          </span>
        )}
      </button>
    );
  }
);

Button.displayName = 'Button';
