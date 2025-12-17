/**
 * Tipos de TypeScript para el módulo de autenticación
 */

/**
 * Información del usuario autenticado
 * Basado en el payload del JWT del backend
 */
export interface User {
  sub: number; // ID del usuario
  cn: string; // Username/CURP
  name: string; // Nombre completo
  role: string[]; // Roles del usuario ['ADMIN', 'USER', etc.]
  email?: string; // Email (opcional)
  department?: string; // Departamento (opcional)
}

/**
 * Credenciales para login
 */
export interface LoginCredentials {
  username: string;
  password: string;
}

/**
 * Respuesta del endpoint de login
 */
export interface LoginResponse {
  ok: boolean;
  message: string;
  user?: User;
  error?: {
    code: string;
    message: string;
  };
}

/**
 * Respuesta del endpoint de getCurrentUser
 */
export interface CurrentUserResponse {
  ok: boolean;
  user?: User;
  error?: {
    code: string;
    message: string;
  };
}

/**
 * Respuesta del endpoint de logout
 */
export interface LogoutResponse {
  ok: boolean;
  message: string;
}
