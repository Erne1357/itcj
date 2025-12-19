import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LoginForm } from './LoginForm';
import { useAuth } from '../hooks';

export interface LoginPageProps {
  onSuccess?: () => void;
}

/**
 * Página de Login del ITCJ
 *
 * Características:
 * - Diseño basado en el login original del ITCJ
 * - Completamente responsive
 * - Fondo con imagen institucional
 * - Colores oficiales del ITCJ
 * - Accesibilidad completa
 * - Redirección automática después del login basada en rol
 */
export function LoginPage({ onSuccess }: LoginPageProps) {
  const navigate = useNavigate();
  const { user, isAuthenticated } = useAuth();

  // Redirigir si ya está autenticado (ej. al acceder directamente a /login)
  useEffect(() => {
    if (isAuthenticated && user) {
      // Siempre redirigir al dashboard - el servidor manejará la redirección final
      navigate('/', { replace: true });
    }
  }, [isAuthenticated, user, navigate]);

  return (
    <>
      <div className="itcj-login-page">
        <div className="login-card">
          <div className="card-body p-4 p-md-5">
            {/* Logo/Brand */}
            <h1 className="mb-4 text-center fw-bold brand text-danger">ITCJ</h1>

            {/* Formulario de login - maneja su propia redirección */}
            <LoginForm onSuccess={onSuccess} />
          </div>
        </div>
      </div>

      {/* Estilos personalizados */}
      <style>{`
        /* Colores oficiales ITCJ */
        :root {
          --rojoTec: #dc3545;
          --azulFuerte: #1a71cf;
        }

        /* Fondo con imagen institucional */
        .itcj-login-page {
          background: url('/images/fondo.png') no-repeat center center fixed;
          background-size: cover;
          min-height: 100vh;
          height: 100%;
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 1rem;
          flex: 1;
        }

        /* Card de login */
        .login-card {
          background: rgba(255, 255, 255, 1);
          width: 100%;
          max-width: 380px;
          border-radius: 1rem;
          border: none;
          border-top: 5px solid var(--rojoTec) !important;
          box-shadow: 6px 5px 15px 0px rgba(0, 0, 0, 0.3);
        }

        /* Brand/Logo */
        .brand {
          letter-spacing: 0.5px;
          font-size: 2.5rem;
        }

        /* Focus en inputs - color rojo ITCJ */
        .form-control:focus {
          border-color: var(--rojoTec);
          box-shadow: 0 0 0 0.2rem rgba(220, 53, 69, 0.15);
        }

        /* Botones - ajustar para usar azul ITCJ */
        .btn-primary {
          background-color: var(--azulFuerte);
          border-color: var(--azulFuerte);
          border-radius: 0.75rem;
        }

        .btn-primary:hover,
        .btn-primary:focus {
          background-color: #084a8e;
          border-color: #084a8e;
        }

        .btn-primary:active {
          background-color: #084a8e !important;
          border-color: #084a8e !important;
        }

        /* Responsive - mobile */
        @media (max-width: 576px) {
          .login-card {
            max-width: 100%;
          }

          .brand {
            font-size: 2rem;
          }

          .card-body {
            padding: 1.5rem !important;
          }
        }

        /* Responsive - tablet y desktop */
        @media (min-width: 577px) and (max-width: 991px) {
          .login-card {
            max-width: 400px;
          }
        }

        /* Desktop grande - mantener delgado */
        @media (min-width: 992px) {
          .login-card {
            max-width: 420px;
          }

          .brand {
            font-size: 3rem;
          }
        }

        /* Ultra wide - un poco más ancho pero aún delgado */
        @media (min-width: 1400px) {
          .login-card {
            max-width: 450px;
          }
        }
      `}</style>
    </>
  );
}
