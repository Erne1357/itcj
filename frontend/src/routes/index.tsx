import { Routes, Route, Navigate } from 'react-router-dom';
import { LoginPage } from '@/features/auth/components';
import { ProtectedRoute } from '@/components/auth';
import { Dashboard } from '@/pages';

/**
 * AppRoutes - Configuración de rutas de la aplicación
 *
 * Estructura:
 * - /login - Página de inicio de sesión (pública)
 * - / - Dashboard (protegida)
 * - /help-desk - Help Desk app (legacy, protegida) - TODO: Implementar
 * - /agendatec - AgendaTec app (legacy, protegida) - TODO: Implementar
 */
export function AppRoutes() {
  return (
    <Routes>
      {/* Ruta pública - Login */}
      <Route path="/login" element={<LoginPage />} />

      {/* Rutas protegidas */}
      <Route element={<ProtectedRoute />}>
        {/* Dashboard principal */}
        <Route path="/" element={<Dashboard />} />

        {/* TODO: Rutas para apps legacy con iframes */}
        {/* <Route path="/help-desk/*" element={<HelpDeskApp />} /> */}
        {/* <Route path="/agendatec/*" element={<AgendaTecApp />} /> */}
      </Route>

      {/* Ruta por defecto - redirige a dashboard */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
