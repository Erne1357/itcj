import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { User, Lock } from 'lucide-react';
import { Input, Button, ErrorAlert } from '@/components/ui';
import { useLogin } from '../hooks/useLogin';
import { useAuthStore } from '../store/authStore';

/**
 * Schema de validación con Zod
 */
const loginSchema = z.object({
  control_number: z.string().min(1, 'El número de control es requerido').trim(),
  nip: z
    .string()
    .min(4, 'El NIP debe tener al menos 4 caracteres')
    .max(50, 'El NIP es demasiado largo'),
});

type LoginFormData = z.infer<typeof loginSchema>;

export interface LoginFormProps {
  onSuccess?: () => void;
}

/**
 * Formulario de login con validación
 *
 * Características:
 * - Validación con react-hook-form + zod
 * - Mensajes de error claros
 * - Loading states
 * - Accesibilidad completa
 * - Responsive
 * - Redirección automática basada en rol
 */
export function LoginForm({ onSuccess }: LoginFormProps) {
  const navigate = useNavigate();
  const { loginAsync, isLoading, isError, error } = useLogin();

  // Configurar react-hook-form
  const {
    register,
    handleSubmit,
    formState: { errors },
    setFocus,
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    mode: 'onBlur', // Validar al salir del campo
  });

  // Auto-focus en el primer campo al montar
  useEffect(() => {
    setFocus('control_number');
  }, [setFocus]);

  // Handler del submit - usa el response directo para evitar problemas de timing
  const onSubmit = async (data: LoginFormData) => {
    try {
      // Esperar a que el login termine y obtener el response
      const response = await loginAsync(data);

      // Usar el role del response directamente
      const userRole = response.user?.role?.toLowerCase();

      // SOLUCIÓN: Usar window.location.href para TODOS los casos
      // Esto garantiza un full page reload y que el store se sincronice correctamente
      // con la cookie del backend antes de que ProtectedRoute se monte
      if (userRole === 'student') {
        // Estudiantes van a AgendaTec
        window.location.href = '/agendatec/';
      } else {
        // Todos los demás al dashboard (full reload garantiza sincronización)
        window.location.href = '/';
      }

      // Llamar callback si existe (para notificaciones, etc)
      if (onSuccess) {
        onSuccess();
      }
    } catch (err) {
      // El error ya está manejado por useLogin
      console.error('Error en login:', err);
    }
  };

  // Extraer mensaje de error
  const errorMessage =
    error instanceof Error
      ? error.message
      : 'Ocurrió un error al iniciar sesión. Por favor intenta nuevamente.';

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate>
      {/* Error alert */}
      {isError && (
        <ErrorAlert dismissible className="mb-4">
          {errorMessage}
        </ErrorAlert>
      )}

      {/* Control Number Input */}
      <Input
        {...register('control_number')}
        type="text"
        label="Usuario / No. Control"
        placeholder="Ingresa tu usuario o número de control"
        error={errors.control_number?.message}
        isInvalid={!!errors.control_number}
        leftIcon={<User size={20} className="text-muted" />}
        autoComplete="username"
        disabled={isLoading}
        required
      />

      {/* NIP Input */}
      <Input
        {...register('nip')}
        type="password"
        label="Contraseña / NIP"
        placeholder="Ingresa tu contraseña o NIP"
        error={errors.nip?.message}
        isInvalid={!!errors.nip}
        leftIcon={<Lock size={20} className="text-muted" />}
        autoComplete="current-password"
        disabled={isLoading}
        required
      />

      {/* Submit Button */}
      <Button
        type="submit"
        variant="primary"
        size="lg"
        fullWidth
        isLoading={isLoading}
        loadingText="Iniciando sesión..."
      >
        Iniciar Sesión
      </Button>

      {/* Helper text */}
      <div className="text-center mt-3">
        <small className="text-muted">
          ¿Olvidaste tu contraseña? Contacta al administrador del sistema.
        </small>
      </div>
    </form>
  );
}
