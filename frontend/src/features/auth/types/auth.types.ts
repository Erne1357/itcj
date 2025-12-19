/**
 * Tipos de TypeScript para el módulo de autenticación
 * Adaptado para coincidir con el backend actual de Flask
 */

/**
 * Información del usuario autenticado
 * Basado en la respuesta del backend
 * Nota: role será array en el futuro (roles por app), pero actualmente es string | null
 */
export interface User {
  id: number; // ID del usuario
  control_number: string; // Número de control/CURP
  full_name: string; // Nombre completo
  role: string | null; // Rol del usuario (ej: 'ADMIN', 'USER', etc.) - puede ser null
  email?: string; // Email (opcional)
  department?: string; // Departamento (opcional)
}

/**
 * Credenciales para login
 * Backend espera control_number y nip
 */
export interface LoginCredentials {
  control_number: string; // Número de control o CURP
  nip: string; // NIP (contraseña)
}

/**
 * Respuesta del endpoint de login
 * POST /api/core/v1/auth/login
 */
export interface LoginResponse {
  ok?: boolean;
  message?: string;
  user?: {
    id: number;
    role: string | null;
    full_name: string;
  };
  error?: {
    code: string;
    message: string;
  };
}

/**
 * Respuesta del endpoint de getCurrentUser
 * GET /api/core/v1/auth/me
 */
export interface CurrentUserResponse {
  user?: {
    id: number;
    role: string | null;
    control_number: string;
    full_name: string;
  };
  error?: {
    code: string;
    message: string;
  };
}

/**
 * Respuesta del endpoint de logout
 * POST /api/core/v1/auth/logout
 */
export interface LogoutResponse {
  ok: boolean;
  message: string;
}
