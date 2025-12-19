import { useState } from 'react';
import { AlertTriangle, Lock, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui';

export interface PasswordChangeModalProps {
  isOpen: boolean;
  userFullName: string;
  onPasswordChange: (newPassword: string) => Promise<void>;
}

/**
 * PasswordChangeModal - Modal de cambio de contraseña obligatorio
 *
 * Se muestra cuando el usuario tiene contraseña por defecto
 * y debe cambiarla por seguridad antes de continuar
 */
export function PasswordChangeModal({
  isOpen,
  userFullName,
  onPasswordChange,
}: PasswordChangeModalProps) {
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Validaciones
    if (!newPassword || !confirmPassword) {
      setError('Todos los campos son obligatorios');
      return;
    }

    if (newPassword.length < 8) {
      setError('La contraseña debe tener al menos 8 caracteres');
      return;
    }

    if (newPassword === 'tecno#2K') {
      setError('No puedes usar la contraseña por defecto. Elige una diferente.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setError('Las contraseñas no coinciden');
      return;
    }

    setIsLoading(true);
    try {
      await onPasswordChange(newPassword);
      // El modal se cerrará automáticamente cuando se actualice el estado del usuario
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Error al cambiar la contraseña');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      {/* Overlay - No se puede cerrar */}
      <div className="password-modal-overlay" />

      {/* Modal */}
      <div className="password-modal">
        {/* Header con alerta de seguridad */}
        <div className="password-modal-header">
          <div className="security-alert">
            <AlertTriangle size={28} />
            <div>
              <h2 className="modal-title">Alerta de Seguridad</h2>
              <p className="modal-subtitle">Cambio de contraseña requerido</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="password-modal-content">
          <div className="welcome-message">
            <p>
              <strong>Bienvenido/a, {userFullName}</strong>
            </p>
            <p className="text-muted">
              Por tu seguridad, debes cambiar tu contraseña por defecto antes de continuar.
              Asegúrate de usar una contraseña segura que contenga letras, números y caracteres
              especiales.
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit}>
            {error && (
              <div className="alert alert-danger" role="alert">
                {error}
              </div>
            )}

            {/* Nueva contraseña */}
            <div className="mb-3">
              <label className="form-label">Nueva Contraseña</label>
              <div className="input-group">
                <span className="input-group-text">
                  <Lock size={18} />
                </span>
                <input
                  type={showNewPassword ? 'text' : 'password'}
                  className="form-control"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isLoading}
                  required
                  minLength={8}
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  tabIndex={-1}
                >
                  {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <small className="text-muted">Mínimo 8 caracteres</small>
            </div>

            {/* Confirmar contraseña */}
            <div className="mb-4">
              <label className="form-label">Confirmar Nueva Contraseña</label>
              <div className="input-group">
                <span className="input-group-text">
                  <Lock size={18} />
                </span>
                <input
                  type={showConfirmPassword ? 'text' : 'password'}
                  className="form-control"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isLoading}
                  required
                  minLength={8}
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  tabIndex={-1}
                >
                  {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <Button
              type="submit"
              variant="primary"
              size="lg"
              fullWidth
              isLoading={isLoading}
              loadingText="Cambiando contraseña..."
            >
              Cambiar Contraseña
            </Button>
          </form>
        </div>
      </div>
    </>
  );
}
