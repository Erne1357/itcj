import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  useAuthStore,
  selectUser,
  selectIsAuthenticated,
  selectIsLoading,
} from '../store/authStore';
import { authApi } from '../api/authApi';

/**
 * Hook principal de autenticación
 *
 * Este hook:
 * 1. Verifica si hay una sesión activa al cargar la app
 * 2. Sincroniza el estado del store con el backend
 * 3. Proporciona información del usuario y estado de autenticación
 *
 * @returns Estado de autenticación y acciones
 */
export const useAuth = () => {
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const isLoading = useAuthStore(selectIsLoading);
  const setUser = useAuthStore((state) => state.setUser);
  const setLoading = useAuthStore((state) => state.setLoading);
  const logout = useAuthStore((state) => state.logout);

  // Query para verificar la sesión actual
  const {
    data,
    error,
    isLoading: isQueryLoading,
  } = useQuery({
    queryKey: ['auth', 'current-user'],
    queryFn: authApi.getCurrentUser,
    retry: false, // No reintentar si falla
    staleTime: Infinity, // No refrescar automáticamente
    gcTime: Infinity, // Mantener en caché indefinidamente
    enabled: isLoading, // Solo ejecutar si estamos en estado de carga inicial
  });

  // Sincronizar el resultado de la query con el store
  useEffect(() => {
    if (data) {
      if (data.user) {
        // Sesión activa - actualizar store con información del usuario
        setUser(data.user);
      } else {
        // No hay sesión activa o hay un error
        setUser(null);
      }
    } else if (error) {
      // Error al verificar sesión (probablemente 401)
      setUser(null);
    }
  }, [data, error, setUser]);

  // Actualizar el estado de loading
  useEffect(() => {
    if (!isQueryLoading && isLoading) {
      setLoading(false);
    }
  }, [isQueryLoading, isLoading, setLoading]);

  return {
    user,
    isAuthenticated,
    isLoading: isLoading || isQueryLoading,
    logout,
  };
};
