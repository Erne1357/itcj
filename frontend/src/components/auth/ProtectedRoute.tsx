import { useEffect } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/features/auth/hooks';

/**
 * ProtectedRoute - Componente de ruta protegida
 *
 * Verifica si el usuario está autenticado antes de renderizar las rutas hijas.
 * Si no está autenticado, redirige a /login.
 * Si es estudiante, redirige a /agendatec/ (app legacy).
 *
 * Uso:
 * <Route element={<ProtectedRoute />}>
 *   <Route path="/dashboard" element={<Dashboard />} />
 * </Route>
 */
export function ProtectedRoute() {
  const { isAuthenticated, isLoading, user } = useAuth();

  // IMPORTANTE: useEffect debe estar ANTES de cualquier return condicional
  // para cumplir con Rules of Hooks
  useEffect(() => {
    // Si es estudiante autenticado, redirigir a AgendaTec (app legacy)
    // Los estudiantes no tienen acceso al dashboard de React

    if (isAuthenticated && user?.role?.toLowerCase() === 'student') {
      window.location.href = '/agendatec/';
    }
  }, [isAuthenticated, user]);

  // Mientras verifica la autenticación, mostrar loading
  if (isLoading) {
    return (
      <div
        className="d-flex align-items-center justify-content-center bg-light"
        style={{ flex: 1, minHeight: '100vh' }}
      >
        <div className="text-center">
          <div className="spinner-border text-primary mb-3" role="status">
            <span className="visually-hidden">Cargando...</span>
          </div>
          <p className="text-muted">Verificando sesión...</p>
        </div>
      </div>
    );
  }

  // Si no está autenticado, redirigir a login
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // Si está autenticado y NO es estudiante, renderizar las rutas hijas
  return <Outlet />;
}
