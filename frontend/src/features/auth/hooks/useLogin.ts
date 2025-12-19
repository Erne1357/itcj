import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../store/authStore';
import { authApi } from '../api/authApi';
import type { LoginCredentials } from '../types/auth.types';

/**
 * Hook para manejar el proceso de login
 *
 * Este hook:
 * 1. Realiza la petición de login al backend
 * 2. Actualiza el store con el usuario si es exitoso
 * 3. Invalida la query de current-user para refrescar
 * 4. Maneja errores de autenticación
 *
 * @returns Mutation de login con estado y funciones
 */
export const useLogin = () => {
  const queryClient = useQueryClient();
  const setUser = useAuthStore((state) => state.setUser);

  const mutation = useMutation({
    mutationFn: (credentials: LoginCredentials) => authApi.login(credentials),

    onSuccess: (data) => {
      if (data.user) {
        // Login exitoso - actualizar store con información del usuario
        // Normalizamos la respuesta del backend al formato del User del store
        setUser({
          id: data.user.id,
          control_number: '', // El backend no lo devuelve en login, se obtiene en /me
          full_name: data.user.full_name,
          role: data.user.role,
        });

        // Invalidar la query de current-user para obtener datos completos
        queryClient.invalidateQueries({ queryKey: ['auth', 'current-user'] });
      } else {
        // Login fallido - el backend devolvió error
        throw new Error(data.error?.message || 'Credenciales inválidas');
      }
    },

    onError: (error: any) => {
      // Limpiar usuario del store en caso de error
      setUser(null);

      // El error se puede manejar en el componente
      console.error('Error en login:', error);
    },
  });

  return {
    login: mutation.mutate,
    loginAsync: mutation.mutateAsync,
    isLoading: mutation.isPending,
    isSuccess: mutation.isSuccess,
    isError: mutation.isError,
    error: mutation.error,
    reset: mutation.reset,
  };
};
