"""Modelos de la app Credencial.

LOAD-BEARING: el create_all de CI importa este PAQUETE, no los submodulos. Un
modelo que no aparezca aqui no existe para CI y su tabla no se crea.
"""
from .photo import CredentialPhoto
from .verification import CredentialVerification

__all__ = ["CredentialPhoto", "CredentialVerification"]
