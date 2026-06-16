"""Conftest de tests de la app titulatec.

Carga eager de `itcj2.models` para resolver los mappers de SQLAlchemy (necesario
para importar los servicios que referencian modelos en imports locales).
"""
import itcj2.models  # noqa: F401
