import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';
import clsx from 'clsx';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  isInvalid?: boolean;
  isValid?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

/**
 * Input component con soporte para validación y Bootstrap styling
 *
 * Características:
 * - Integración con react-hook-form (forwardRef)
 * - Estados de validación (error, success)
 * - Label y helper text
 * - Iconos opcionales
 * - Responsive y accesible
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      label,
      error,
      helperText,
      isInvalid,
      isValid,
      leftIcon,
      rightIcon,
      className,
      required,
      id,
      ...props
    },
    ref
  ) => {
    // Generar ID único si no se proporciona
    const inputId = id || `input-${label?.toLowerCase().replace(/\s+/g, '-')}`;

    // Determinar estado de validación
    const hasError = isInvalid || !!error;
    const hasSuccess = isValid && !hasError;

    return (
      <div className="mb-3">
        {/* Label */}
        {label && (
          <label htmlFor={inputId} className="form-label">
            {label}
            {required && <span className="text-danger ms-1">*</span>}
          </label>
        )}

        {/* Input container */}
        <div className="position-relative">
          {/* Left icon */}
          {leftIcon && (
            <div className="position-absolute top-50 translate-middle-y ms-3">{leftIcon}</div>
          )}

          {/* Input */}
          <input
            ref={ref}
            id={inputId}
            className={clsx(
              'form-control',
              {
                'is-invalid': hasError,
                'is-valid': hasSuccess,
                'ps-5': leftIcon, // Padding left para icono
                'pe-5': rightIcon, // Padding right para icono
              },
              className
            )}
            aria-invalid={hasError}
            aria-describedby={
              error ? `${inputId}-error` : helperText ? `${inputId}-help` : undefined
            }
            {...props}
          />

          {/* Right icon */}
          {rightIcon && (
            <div className="position-absolute top-50 end-0 translate-middle-y me-3">
              {rightIcon}
            </div>
          )}
        </div>

        {/* Error message */}
        {error && (
          <div id={`${inputId}-error`} className="invalid-feedback d-block">
            {error}
          </div>
        )}

        {/* Helper text */}
        {!error && helperText && (
          <div id={`${inputId}-help`} className="form-text">
            {helperText}
          </div>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
