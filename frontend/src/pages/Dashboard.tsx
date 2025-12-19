import { useAuth, usePasswordState, useChangePassword } from '@/features/auth/hooks';
import { Desktop, type DesktopApp, PasswordChangeModal } from '@/components/dashboard';

/**
 * Dashboard - Página principal estilo Windows/MacOS
 *
 * Características:
 * - Escritorio con iconos de aplicaciones
 * - Taskbar con apps ancladas
 * - System tray con reloj en tiempo real
 * - Fondo institucional con glassmorphism
 * - Modal de cambio de contraseña obligatorio
 */
export function Dashboard() {
  const { user } = useAuth();
  const { mustChangePassword, isLoading: isLoadingPasswordState } = usePasswordState();
  const { changePasswordAsync } = useChangePassword();

  if (!user) {
    return null;
  }

  // Configuración de aplicaciones del escritorio
  const desktopApps: DesktopApp[] = [
    {
      id: 'agendatec',
      icon: '/images/apps/agendatec.ico',
      label: 'AgendaTec',
      url: '/agendatec/', // Abrir en iframe
    },
    {
      id: 'helpdesk',
      icon: '/images/apps/help-desk.png',
      label: 'Help Desk',
      url: '/help-desk/', // Abrir en iframe
      // badge se puede agregar cuando haya datos reales de tickets pendientes
    },
  ];

  const handlePasswordChange = async (newPassword: string) => {
    try {
      await changePasswordAsync({ new_password: newPassword });
      // El modal se cerrará automáticamente cuando must_change cambie a false
      // porque usePasswordState invalidará la query
    } catch (error: any) {
      // El error ya se maneja en el modal
      throw error;
    }
  };

  return (
    <>
      <Desktop apps={desktopApps} notificationCount={0} />

      {/* Modal de cambio de contraseña */}
      {!isLoadingPasswordState && (
        <PasswordChangeModal
          isOpen={mustChangePassword}
          userFullName={user.full_name}
          onPasswordChange={handlePasswordChange}
        />
      )}
    </>
  );
}
