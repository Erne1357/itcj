import { apiClient } from '@/lib/api/client';
import type {
  LoginCredentials,
  LoginResponse,
  CurrentUserResponse,
  LogoutResponse,
} from '../types/auth.types';

/**
 * API de autenticación
 * Todas las funciones de este módulo se comunican con el backend Flask
 */
export const authApi = {
  /**
   * Inicia sesión con username y password
   * @param credentials - Username y password del usuario
   * @returns Respuesta con información del usuario si es exitoso
   */
  login: async (credentials: LoginCredentials): Promise<LoginResponse> => {
    const response = await apiClient.post<LoginResponse>('/core/v1/auth/login', credentials);
    return response.data;
  },

  /**
   * Obtiene la información del usuario actual basado en la cookie JWT
   * @returns Información del usuario si está autenticado
   */
  getCurrentUser: async (): Promise<CurrentUserResponse> => {
    const response = await apiClient.get<CurrentUserResponse>('/core/v1/auth/me');
    return response.data;
  },

  /**
   * Cierra la sesión del usuario actual
   * @returns Confirmación de logout
   */
  logout: async (): Promise<LogoutResponse> => {
    const response = await apiClient.post<LogoutResponse>('/core/v1/auth/logout');
    return response.data;
  },
};
