import { useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

interface ChangePasswordPayload {
  new_password: string;
}

interface ChangePasswordResponse {
  message?: string;
}

/**
 * Hook para cambiar la contraseña del usuario
 *
 * POST /api/core/v1/user/change-password
 * Body: { new_password: string }
 *
 * @returns Mutation para cambiar la contraseña
 */
export const useChangePassword = () => {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (payload: ChangePasswordPayload) => {
      const response = await axios.post<ChangePasswordResponse>(
        '/api/core/v1/user/change-password',
        payload,
        {
          withCredentials: true,
          headers: {
            'Content-Type': 'application/json',
          },
        }
      );
      return response.data;
    },

    onSuccess: () => {
      // Invalidar la query de password-state para refrescar el estado
      queryClient.invalidateQueries({ queryKey: ['password-state'] });
    },

    onError: (error: any) => {
      console.error('Error al cambiar contraseña:', error);
    },
  });

  return {
    changePassword: mutation.mutate,
    changePasswordAsync: mutation.mutateAsync,
    isLoading: mutation.isPending,
    isSuccess: mutation.isSuccess,
    isError: mutation.isError,
    error: mutation.error,
  };
};
