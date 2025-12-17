import axios from 'axios';

// Configuración base del cliente Axios
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  withCredentials: true, // CRÍTICO: Incluir cookies JWT
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor para manejar respuestas
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Usuario no autenticado, redirect a login
      console.error('No autenticado - redirigiendo a login');
      // TODO: Implementar redirect cuando tengamos React Router
    }

    console.error('API Error:', {
      url: error.config?.url,
      status: error.response?.status,
      message: error.response?.data?.message || error.message,
    });

    return Promise.reject(error);
  }
);

export { apiClient };
