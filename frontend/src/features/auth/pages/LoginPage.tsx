import { useNavigate } from 'react-router-dom';
import { LoginForm } from '../components/LoginForm';

/**
 * Página de Login
 *
 * Características:
 * - Diseño profesional y moderno
 * - Completamente responsive
 * - Branding de ITCJ
 * - Animaciones sutiles
 * - Accesibilidad completa
 */
export function LoginPage() {
  const navigate = useNavigate();

  const handleLoginSuccess = () => {
    // Redirigir al dashboard después del login exitoso
    navigate('/');
  };

  return (
    <div className="min-vh-100 d-flex align-items-center bg-light">
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-12 col-sm-10 col-md-8 col-lg-6 col-xl-5 col-xxl-4">
            {/* Card principal */}
            <div className="card shadow-lg border-0 rounded-4">
              <div className="card-body p-4 p-sm-5">
                {/* Header - Logo y título */}
                <div className="text-center mb-4">
                  {/* Logo placeholder - reemplazar con logo real de ITCJ */}
                  <div className="mb-3">
                    <div
                      className="d-inline-flex align-items-center justify-content-center bg-primary bg-gradient rounded-circle"
                      style={{ width: '80px', height: '80px' }}
                    >
                      <span className="text-white fw-bold fs-2">ITCJ</span>
                    </div>
                  </div>

                  <h1 className="h3 fw-bold mb-2">Bienvenido al Sistema ITCJ</h1>
                  <p className="text-muted mb-0">Ingresa tus credenciales para continuar</p>
                </div>

                {/* Formulario de login */}
                <LoginForm onSuccess={handleLoginSuccess} />
              </div>

              {/* Footer del card */}
              <div className="card-footer bg-white border-0 text-center py-3 rounded-bottom-4">
                <small className="text-muted">Instituto Tecnológico de Ciudad Juárez</small>
              </div>
            </div>

            {/* Info adicional */}
            <div className="text-center mt-4">
              <p className="text-muted small mb-2">Sistema de Gestión Institucional</p>
              <p className="text-muted small">
                &copy; {new Date().getFullYear()} ITCJ. Todos los derechos reservados.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* CSS adicional para animaciones y estilos personalizados */}
      <style>{`
        /* Animación sutil al cargar */
        .card {
          animation: fadeInUp 0.5s ease-out;
        }

        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        /* Hover effect en el card */
        .card {
          transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .card:hover {
          transform: translateY(-2px);
        }

        /* Fondo con gradiente sutil */
        .bg-light {
          background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        }

        /* Estilo del logo placeholder */
        .bg-primary.bg-gradient {
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        }

        /* Responsive adjustments */
        @media (max-width: 576px) {
          .card-body {
            padding: 1.5rem !important;
          }

          h1.h3 {
            font-size: 1.5rem !important;
          }
        }
      `}</style>
    </div>
  );
}
