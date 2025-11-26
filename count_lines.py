#!/usr/bin/env python3
"""
Contador de líneas de código del proyecto ITCJ
Excluye __pycache__, venv, node_modules y otros archivos innecesarios
"""

import os
import glob
from pathlib import Path

def count_lines_in_file(file_path):
    """Cuenta líneas en un archivo"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except:
        return 0

def should_exclude_path(path):
    """Determina si una ruta debe excluirse"""
    exclude_dirs = {
        '__pycache__', 'venv', 'node_modules', '.git', 
        '.pytest_cache', 'dist', 'build', '.vscode',
        '.idea', 'logs', 'tmp', '.DS_Store'
    }
    
    path_parts = Path(path).parts
    return any(excluded in path_parts for excluded in exclude_dirs)

def get_file_extensions():
    """Extensiones de archivos a incluir"""
    return {
        '.py', '.js', '.html', '.css', '.sql', '.md', 
        '.json', '.yml', '.yaml', '.txt', '.sh', '.bat',
        '.ini', '.cfg', '.conf', '.env'
    }

def count_project_lines(project_path='.'):
    """Cuenta todas las líneas del proyecto"""
    
    stats = {
        'total_lines': 0,
        'total_files': 0,
        'by_extension': {},
        'by_directory': {},
        'largest_files': []
    }
    
    valid_extensions = get_file_extensions()
    
    print("🔍 Analizando proyecto...")
    print("=" * 60)
    
    for root, dirs, files in os.walk(project_path):
        # Excluir directorios no deseados
        dirs[:] = [d for d in dirs if not should_exclude_path(os.path.join(root, d))]
        
        if should_exclude_path(root):
            continue
            
        dir_lines = 0
        
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = Path(file).suffix.lower()
            
            # Solo archivos con extensiones válidas
            if file_ext in valid_extensions:
                lines = count_lines_in_file(file_path)
                
                if lines > 0:
                    # Estadísticas globales
                    stats['total_lines'] += lines
                    stats['total_files'] += 1
                    
                    # Por extensión
                    if file_ext not in stats['by_extension']:
                        stats['by_extension'][file_ext] = {'files': 0, 'lines': 0}
                    stats['by_extension'][file_ext]['files'] += 1
                    stats['by_extension'][file_ext]['lines'] += lines
                    
                    # Por directorio
                    rel_dir = os.path.relpath(root, project_path)
                    if rel_dir not in stats['by_directory']:
                        stats['by_directory'][rel_dir] = 0
                    stats['by_directory'][rel_dir] += lines
                    
                    # Archivos más grandes
                    stats['largest_files'].append({
                        'path': os.path.relpath(file_path, project_path),
                        'lines': lines,
                        'extension': file_ext
                    })
                    
                    dir_lines += lines
        
        if dir_lines > 0:
            rel_dir = os.path.relpath(root, project_path)
            print(f"📁 {rel_dir:<40} {dir_lines:>6} líneas")
    
    return stats

def print_detailed_stats(stats):
    """Imprime estadísticas detalladas"""
    
    print("\n" + "="*60)
    print("📊 ESTADÍSTICAS GENERALES")
    print("="*60)
    print(f"📝 Total de líneas: {stats['total_lines']:,}")
    print(f"📄 Total de archivos: {stats['total_files']:,}")
    print(f"📊 Promedio líneas/archivo: {stats['total_lines']//stats['total_files']:,}")
    
    print("\n" + "="*60)
    print("📋 POR TIPO DE ARCHIVO")
    print("="*60)
    
    # Ordenar por líneas descendente
    sorted_ext = sorted(stats['by_extension'].items(), 
                       key=lambda x: x[1]['lines'], reverse=True)
    
    for ext, data in sorted_ext:
        percentage = (data['lines'] / stats['total_lines']) * 100
        print(f"{ext:<8} {data['files']:>4} archivos {data['lines']:>7,} líneas ({percentage:5.1f}%)")
    
    print("\n" + "="*60)
    print("📂 TOP 10 DIRECTORIOS")
    print("="*60)
    
    sorted_dirs = sorted(stats['by_directory'].items(), 
                        key=lambda x: x[1], reverse=True)[:10]
    
    for directory, lines in sorted_dirs:
        percentage = (lines / stats['total_lines']) * 100
        print(f"{directory:<40} {lines:>7,} líneas ({percentage:5.1f}%)")
    
    print("\n" + "="*60)
    print("🏆 TOP 10 ARCHIVOS MÁS GRANDES")
    print("="*60)
    
    largest = sorted(stats['largest_files'], 
                    key=lambda x: x['lines'], reverse=True)[:10]
    
    for i, file_info in enumerate(largest, 1):
        print(f"{i:2}. {file_info['path']:<50} {file_info['lines']:>5} líneas")
    
    print("\n" + "="*60)
    print("🎉 ¡IMPRESIONANTE PROGRESO!")
    
    # Mensajes motivacionales según el tamaño
    if stats['total_lines'] > 50000:
        print("🚀 ¡Este es un proyecto ENORME! Eres todo un arquitecto de software.")
    elif stats['total_lines'] > 20000:
        print("💪 ¡Excelente! Este es un proyecto sólido y bien estructurado.")
    elif stats['total_lines'] > 10000:
        print("👍 ¡Muy bien! Ya tienes una base sólida de código.")
    elif stats['total_lines'] > 5000:
        print("📈 ¡Buen progreso! El proyecto está tomando forma.")
    else:
        print("🌱 ¡Empezando fuerte! Cada línea cuenta.")
    
    print("="*60)

if __name__ == "__main__":
    print("🔢 CONTADOR DE LÍNEAS - PROYECTO ITCJ")
    print("="*60)
    
    # Cambiar al directorio del proyecto si es necesario
    project_root = r"c:\Users\soporte\Desktop\ITCJ"  # Ajusta esta ruta
    
    if os.path.exists(project_root):
        os.chdir(project_root)
        print(f"📍 Analizando: {os.getcwd()}")
    else:
        print(f"📍 Analizando directorio actual: {os.getcwd()}")
    
    stats = count_project_lines()
    print_detailed_stats(stats)