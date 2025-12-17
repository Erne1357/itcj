import { apiClient } from './client';

export interface HealthResponse {
  status: string;
  message: string;
}

/**
 * Verifica el estado de salud del backend
 */
export const checkHealth = async (): Promise<HealthResponse> => {
  const response = await apiClient.get<HealthResponse>('/core/v1/health');
  return response.data;
};
