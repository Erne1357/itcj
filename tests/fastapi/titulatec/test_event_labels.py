"""Ningun historial de TitulaTec enseña un `event_type` en crudo (2026-09-18).

EL DEFECTO, reportado con una captura del panel del alumno. En el acordeon de
fases, el HISTORIAL decia:

    document_uploaded    17 sep 2026 · 14:51
    document_approved    17 sep 2026 · 14:52
    Fase aprobada        17 sep 2026 · 14:52

Tres renglones en ingles y con guiones bajos, y uno traducido, en la misma
lista. Causa: hay DOS mapas de etiquetas, uno por audiencia
(`pages/student.py::_EVENT_LABELS` y `pages/admin.py::_EVENT_UI`), cada uno se
fue llenando a mano segun la pantalla que tocaba la tarea del dia, y los dos
caen al codigo crudo cuando no encuentran la clave:

    _EVENT_LABELS.get(ev.event_type, ev.event_type)
    _EVENT_UI.get(ev.event_type, (ev.event_type, "dot", "neutral"))

Al alumno le faltaban DIEZ (todo el bloque de documentos, los tres de proceso,
los dos de requisitos y el alta publica) y al admin OCHO (`appointment_cancelled`,
`enrollment_self_service`, los dos de pausa/reanudacion y los cuatro
`survey_review_*`). El del admin «se veia bien» solo porque los datos de dev no
habian producido todavia ninguno de los suyos.

POR QUE ESTE TEST Y NO SOLO EL ARREGLO. Completar los dos dicts a mano arregla
hoy y no impide nada mañana: el siguiente `event_type` vuelve a filtrarse y nos
enteramos por otra captura. Aqui el dominio es `EVENT_TYPES`
(`models/process_event.py`), y agregar un evento sin sus DOS etiquetas rompe la
suite.

EL FALLBACK AL CODIGO CRUDO SE QUEDA, y es deliberado: un historial que se calla
es peor que uno en ingles. Lo que estos tests garantizan es que no se dispare
para ningun evento que la app sepa escribir.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import itcj2  # noqa: F401
from itcj2.apps.titulatec.models.process_event import EVENT_TYPES

_APP_DIR = Path(itcj2.__file__).resolve().parent / "apps" / "titulatec"


def _labels_alumno() -> dict:
    from itcj2.apps.titulatec.pages.student import _EVENT_LABELS
    return _EVENT_LABELS


def _labels_admin() -> dict:
    from itcj2.apps.titulatec.pages.admin import _EVENT_UI
    return _EVENT_UI


# ---------------------------------------------------------------------------
# Cobertura: los dos mapas contra el dominio
# ---------------------------------------------------------------------------
def test_el_alumno_tiene_etiqueta_para_todo_evento_conocido():
    faltan = sorted(EVENT_TYPES - set(_labels_alumno()))
    assert not faltan, (
        "el historial del alumno enseñaria estos codigos EN CRUDO:\n  "
        + "\n  ".join(faltan)
        + "\nAgregalos a `pages/student.py::_EVENT_LABELS`, en su voz (tu/te)."
    )


def test_el_admin_tiene_etiqueta_para_todo_evento_conocido():
    faltan = sorted(EVENT_TYPES - set(_labels_admin()))
    assert not faltan, (
        "el expediente del admin enseñaria estos codigos EN CRUDO:\n  "
        + "\n  ".join(faltan)
        + "\nAgregalos a `pages/admin.py::_EVENT_UI`, en voz de ventanilla."
    )


def test_ningun_mapa_traduce_un_evento_que_no_existe():
    """Una etiqueta de mas es CODIGO MUERTO y, peor, una pista falsa: hace creer
    que el evento se escribe en algun lado."""
    for nombre, mapa in (("student", _labels_alumno()), ("admin", _labels_admin())):
        sobran = sorted(set(mapa) - EVENT_TYPES)
        assert not sobran, (
            f"{nombre} etiqueta eventos que nadie escribe: {sobran}. "
            "O falta la fila en `EVENT_TYPES`, o la etiqueta sobra."
        )


# ---------------------------------------------------------------------------
# Forma de las etiquetas
# ---------------------------------------------------------------------------
def test_ninguna_etiqueta_es_el_codigo_disfrazado():
    """Copiar la clave como valor pasa la cobertura y no traduce nada."""
    for nombre, mapa in (("student", _labels_alumno()), ("admin", _labels_admin())):
        for clave, valor in mapa.items():
            etiqueta = valor[0] if isinstance(valor, tuple) else valor
            assert etiqueta != clave, f"{nombre}: {clave} se etiqueta consigo mismo"
            assert "_" not in etiqueta, (
                f"{nombre}: la etiqueta de {clave} trae guion bajo ({etiqueta!r}); "
                "eso es el codigo, no una frase"
            )
            assert etiqueta[:1].isupper(), (
                f"{nombre}: la etiqueta de {clave} no empieza con mayuscula ({etiqueta!r})"
            )


def test_el_admin_declara_icono_y_tono_de_cada_evento():
    """`_EVENT_UI` es (etiqueta, icono, tono); el tono decide el color."""
    tonos = {"neutral", "success", "danger", "amber"}
    for clave, valor in _labels_admin().items():
        assert isinstance(valor, tuple) and len(valor) == 3, f"{clave}: {valor!r}"
        etiqueta, icono, tono = valor
        assert etiqueta and icono, clave
        assert not icono.startswith("bi-"), (
            f"{clave}: el icono va SIN el prefijo `bi-`, la plantilla lo pone"
        )
        assert tono in tonos, f"{clave}: tono desconocido {tono!r}"


def test_las_dos_voces_no_son_la_misma_frase_repetida():
    """Si las dos audiencias dijeran lo mismo sobrarian los dos mapas.

    No se exige que TODAS difieran -«Fase aprobada» es correcto en las dos
    bocas-, pero si que la distincion siga viva en los eventos donde hay un
    sujeto: el alumno lee «Subiste un documento» y el oficial «Subio un
    documento».
    """
    alumno, admin = _labels_alumno(), _labels_admin()
    for clave in ("document_uploaded", "appointment_confirmed", "process_created"):
        assert alumno[clave] != admin[clave][0], (
            f"{clave} dice lo mismo en las dos pantallas: {alumno[clave]!r}"
        )


def test_la_reasignacion_del_nip_se_lee_en_las_dos_voces():
    """`enrollment_access_reset` (2026-09-24): Centro de Computo reasigno el NIP
    porque el correo de acceso no salio. El payload nunca lleva el NIP, asi que
    la etiqueta es todo lo que el historial dice."""
    assert "enrollment_access_reset" in EVENT_TYPES
    assert _labels_admin()["enrollment_access_reset"] == (
        "Se reasignó el NIP de acceso", "key", "neutral")
    assert _labels_alumno()["enrollment_access_reset"] == "Se reasignó tu NIP de acceso"


# ---------------------------------------------------------------------------
# El dominio no puede quedarse atras del codigo que escribe eventos
# ---------------------------------------------------------------------------
def test_todo_event_type_que_el_codigo_escribe_esta_en_el_dominio():
    """Barre los literales de los `_log(...)` y `ProcessEvent(...)` reales.

    Es la mitad que las dos pruebas de cobertura no pueden ver: ellas comparan
    los mapas contra `EVENT_TYPES`, pero si alguien escribe un evento nuevo y no
    lo agrega al frozenset, los tres pasarian y la pantalla volveria a enseñar
    el codigo crudo. Aqui la fuente es el codigo.
    """
    prefijos = ("process", "document", "phase", "requirement", "appointment",
                "survey_review", "enrollment")
    patron = re.compile(r'"((?:' + "|".join(prefijos) + r')_[a-z_]+)"')
    # Claves de payload y nombres de campo que comparten prefijo con un evento.
    no_son_eventos = {
        "process_id", "phase_name", "phase_number", "phase_rows", "requirement_id",
        "enrollment_request", "enrollment_approved", "enrollment_rejected",
        "enrollment_done",          # plantillas de correo, no eventos
    }

    escritos: set[str] = set()
    for ruta in sorted((_APP_DIR / "services").glob("*.py")):
        texto = ruta.read_text(encoding="utf-8")
        texto = re.sub(r'""".*?"""', " ", texto, flags=re.S)      # fuera docstrings
        texto = re.sub(r"#.*", " ", texto)                        # fuera comentarios
        for bloque in re.findall(r"(?:_log|ProcessEvent)\s*\((?:[^()]|\([^()]*\))*\)",
                                 texto, flags=re.S):
            escritos |= {m for m in patron.findall(bloque) if m not in no_son_eventos}

    assert escritos, "el barrido no encontro ni un evento: el patron se quedo obsoleto"
    fuera = sorted(escritos - EVENT_TYPES)
    assert not fuera, (
        "estos eventos los escribe un service y no estan en `EVENT_TYPES`, asi que "
        "nadie obliga a traducirlos:\n  " + "\n  ".join(fuera)
    )
