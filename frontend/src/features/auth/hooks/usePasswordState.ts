import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

interface PasswordStateResponse {
  must_change: boolean;
}

/**
 * Hook para verificar si el usuario debe cambiar su contraseña
 *
 * Consulta el endpoint /api/core/v1/user/password-state
 * que devuelve {must_change: boolean}
 *
 * @returns Estado de la contraseña y estados de carga/error
 */
export const usePasswordState = () => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['password-state'],
    queryFn: async () => {
      const response = await axios.get<PasswordStateResponse>(
        '/api/core/v1/user/password-state',
        {
          withCredentials: true,
        }
      );
      return response.data;
    },
    retry: false,
    staleTime: Infinity, // No refrescar automáticamente
  });

  return {
    mustChangePassword: data?.must_change || false,
    isLoading,
    error,
  };
};
