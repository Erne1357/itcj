#!/usr/bin/env python3
"""
Script de prueba para verificar que los error handlers funcionan correctamente
"""
import requests
import sys
import os

# Agregar el path del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_error_handlers():
    """Prueba los diferentes códigos de error"""
    base_url = "http://localhost:5000"
    
    # Códigos de error a probar
    test_codes = [400, 401, 403, 404, 500, 502, 503]
    
    print("Probando Error Handlers...")
    print("=" * 40)
    
    for code in test_codes:
        try:
            # Crear una URL que debería devolver el código de error específico
            test_url = f"{base_url}/test_error_{code}"
            
            response = requests.get(test_url, timeout=5)
            
            print(f"Código {code}: Status {response.status_code}")
            
            # Verificar si la respuesta contiene el template de error
            if "error-container" in response.text:
                print(f"  ✓ Template de error cargado correctamente")
            else:
                print(f"  ✗ Template de error no encontrado")
                
        except requests.exceptions.RequestException as e:
            print(f"Error al probar código {code}: {e}")
        
        print("-" * 30)

def create_test_routes():
    """
    Función para agregar rutas de prueba temporalmente a la aplicación
    Esta función se puede usar durante el desarrollo para probar los error handlers
    """
    from flask import abort
    from itcj import create_app
    
    app, socketio = create_app()
    
    # Rutas de prueba para diferentes códigos de error
    @app.route('/test_error_400')
    def test_400():
        abort(400)
    
    @app.route('/test_error_401') 
    def test_401():
        abort(401)
        
    @app.route('/test_error_403')
    def test_403():
        abort(403)
        
    @app.route('/test_error_404')
    def test_404():
        abort(404)
        
    @app.route('/test_error_500')
    def test_500():
        abort(500)
        
    @app.route('/test_error_502')
    def test_502():
        abort(502)
        
    @app.route('/test_error_503')
    def test_503():
        abort(503)
    
    return app, socketio

if __name__ == "__main__":
    print("Script de prueba para Error Handlers")
    print("Para probar, ejecuta la aplicación Flask y luego:")
    print("python test_error_handlers.py")
    print("\nO agrega las rutas de prueba temporalmente a tu aplicación")
    
    # Descomentar para crear rutas de prueba
    # app, socketio = create_test_routes()
    # app.run(debug=True, port=5000)