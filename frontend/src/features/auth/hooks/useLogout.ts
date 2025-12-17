import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../store/authStore';
import { authApi } from '../api/authApi';

/**
 * Hook para manejar el proceso de logout
 *
 * Este hook:
 * 1. Realiza la petición de logout al backend
 * 2. Limpia el store de autenticación
 * 3. Invalida todas las queries en caché
 * 4. Redirige al usuario (opcional)
 *
 * @returns Mutation de logout con estado y funciones
 */
export const useLogout = () => {
  const queryClient = useQueryClient();
  const logout = useAuthStore((state) => state.logout);

  const mutation = useMutation({
    mutationFn: () => authApi.logout(),

    onSuccess: () => {
      // Limpiar store de autenticación
      logout();

      // Limpiar todas las queries en caché
      queryClient.clear();

      // Opcional: Redirigir a login
      // window.location.href = '/login';
    },

    onError: (error) => {
      console.error('Error en logout:', error);

      // Incluso si el backend falla, limpiar el store local
      logout();
      queryClient.clear();
    },
  });

  return {
    logout: mutation.mutate,
    logoutAsync: mutation.mutateAsync,
    isLoading: mutation.isPending,
    isSuccess: mutation.isSuccess,
    isError: mutation.isError,
  };
};
