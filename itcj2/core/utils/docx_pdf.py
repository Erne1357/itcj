"""Conversión de ``.docx`` a PDF con LibreOffice headless.

Vivía en ``apps/helpdesk/services/document_service.py``; se movió aquí cuando
Prórrogas también necesitó convertir sus cartas. El cuerpo es el mismo: mismos
mensajes de error, misma medición ``measured(kind, "libreoffice")`` y mismo
límite de 60 s. Lo único nuevo es ``PdfConversionError``, que es subclase de
``RuntimeError`` para que quien ya atrapaba ``RuntimeError`` no note el cambio.

El ``kind`` lo decide el llamador y debe estar en
``itcj2.observability.work.DOCUMENT_KIND_ENGINE``.
"""
import logging
import os
import shutil
import subprocess
import tempfile

from itcj2.observability.work import measured

logger = logging.getLogger(__name__)


class PdfConversionError(RuntimeError):
    """LibreOffice no está, falló o no produjo el PDF."""


# Todo lo que puede salir de `docx_to_pdf` cuando LibreOffice no da el PDF. La
# función deja pasar `TimeoutExpired` tal cual (helpdesk lo cuenta como timeout)
# y `subprocess.run` puede lanzar `OSError`; quien quiera "PDF no disponible" en
# vez de un 500 atrapa esta tupla.
CONVERSION_ERRORS = (PdfConversionError, subprocess.TimeoutExpired, OSError)


def find_libreoffice() -> str | None:
    for cmd in ['libreoffice', 'soffice']:
        if shutil.which(cmd):
            return cmd

    win_paths = [
        r'C:\Program Files\LibreOffice\program\soffice.exe',
        r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    ]
    for path in win_paths:
        if os.path.exists(path):
            return path

    return None


def docx_to_pdf(docx: bytes, *, kind: str) -> bytes:
    """Convierte los bytes de un ``.docx`` a los bytes de un PDF."""
    lo_cmd = find_libreoffice()
    if not lo_cmd:
        raise PdfConversionError(
            'LibreOffice no está instalado. '
            'Instálalo para la conversión a PDF, o descarga en formato DOCX.'
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, 'document.docx')
        with open(docx_path, 'wb') as f:
            f.write(docx)

        # Los dos fallos que ya lanzaban (returncode != 0 y "salió con 0 pero
        # sin PDF") van DENTRO del bloque medido: la misma excepción de
        # siempre, contada como outcome="error". Fuera, un soffice que le pasa
        # el trabajo a otra instancia con el mismo perfil y sale con 0 sin
        # escribir nada contaba como éxito: justo la falla por concurrencia
        # que este panel existe para ver.
        with measured(kind, "libreoffice"):
            result = subprocess.run(
                [
                    lo_cmd, '--headless',
                    # Perfil propio por llamada: dos conversiones a la vez no chocan.
                    f'-env:UserInstallation=file://{tmpdir}/lo-profile',
                    '--convert-to', 'pdf',
                    '--outdir', tmpdir, docx_path
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                # El returncode no es etiqueta de la métrica (contrato): va
                # aquí. Matado por señal (OOM: -9) el stderr sale vacío y es
                # lo único que lo distingue de un documento rechazado.
                logger.error(
                    'LibreOffice error (kind=%s, returncode=%s): %s',
                    kind, result.returncode, result.stderr,
                )
                raise PdfConversionError(f'Error al convertir a PDF: {result.stderr}')

            pdf_path = os.path.join(tmpdir, 'document.pdf')
            if not os.path.exists(pdf_path):
                raise PdfConversionError('No se generó el archivo PDF')

        with open(pdf_path, 'rb') as f:
            return f.read()
