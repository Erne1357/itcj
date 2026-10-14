"""Elegibilidad automática contra el SII: sii-ping, sii-rules-validate, sii-check y sii-sweep."""
from pathlib import Path

import click

from itcj2.cli.titulatec._common import titulatec_cli


# ---------------------------------------------------------------------------
# Elegibilidad automática contra el SII (spec 2026-09-25 §3.4 y §7). Orden de
# despliegue: sii-ping → sii-rules-validate → sii-check <control de prueba>.
# Ninguno escribe en la BD. El NIP del SII jamás se imprime (`****`).
# ---------------------------------------------------------------------------
def _sii_fail(msg: str) -> None:
    click.echo(click.style(f"ERROR: {msg}", fg="red"))
    raise SystemExit(1)


@titulatec_cli.command("sii-ping")
def sii_ping_command():
    """Comprueba que el SII responde con el backend configurado."""
    import time

    from itcj2.apps.titulatec.services.sii.client import SiiConfig, get_sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError

    backend = SiiConfig.backend()
    click.echo(f"Backend: {backend}")
    t0 = time.monotonic()
    try:
        with get_sii_client() as sii:
            sii.ping()
    except SiiError as exc:
        _sii_fail(str(exc))
    ms = int((time.monotonic() - t0) * 1000)
    click.echo(click.style(f"OK: el SII responde ({ms} ms).", fg="green"))


@titulatec_cli.command("sii-rules-validate")
@click.option("--dir", "rules_dir", type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help="Carpeta a validar (default: TITULATEC_SII_RULES_DIR). Útil para "
                   "revisar reglas nuevas ANTES de copiarlas a su lugar.")
def sii_rules_validate_command(rules_dir):
    """Valida rules.toml + queries/*.sql sin consultar al SII."""
    from itcj2.apps.titulatec.services.sii.client import SiiConfig
    from itcj2.apps.titulatec.services.sii.errors import SiiRulesError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet

    rules_dir = rules_dir or SiiConfig.rules_dir()
    click.echo(f"Reglas: {rules_dir}")
    try:
        rs = RuleSet.load(rules_dir)
    except SiiRulesError as exc:
        _sii_fail(str(exc))
    click.echo(f"Versión: {rs.version or '(sin versión)'} · {len(rs.queries)} consultas · "
               f"{len(rs.rules)} reglas · credencial (NIP): "
               f"{'sí' if rs.has_credential else 'no'}")
    errors = rs.validate()
    if errors:
        for e in errors:
            click.echo(click.style(f"  - {e}", fg="red"))
        _sii_fail(f"{len(errors)} error(es) en las reglas.")
    for aviso in rs.advisories():
        click.echo(click.style(f"Advertencia: {aviso}", fg="yellow"))
    click.echo(click.style("OK: reglas válidas. (Las columnas de los mensajes se "
                           "verifican al ejecutar: usa sii-check.)", fg="green"))


_SII_STATUS_LABEL = {"apt": "APTA", "not_apt": "NO APTA", "error": "ERROR"}

# `nip_status` (`EligibilityService.classify_sii_nip`) → texto de `sii-check`.
# `None` = no se revisó (veredicto `error`), como en la consulta.
_SII_NIP_LABEL = {
    "available": "disponible",
    "missing": "no tiene",
    "invalid": "formato inválido",
    "unavailable": "no se pudo leer (el SII no respondió)",
    "error": "error de configuración",
    None: "sin revisar",
}
# El NIP no serviría para crear la cuenta: `sii-check` no pasa en verde.
_SII_NIP_FAILS = ("invalid", "unavailable", "error")


def _sii_cohort_outcome(cohort_id: int, control: str, nip_status: str | None) -> None:
    """Imprime lo que vería Servicios Escolares en «Por revisar» de esa
    convocatoria (spec 2026-09-27 §A7). Solo lectura (rollback).

    Ninguna se aprueba sola: con cualquier veredicto la decide SE. El botón
    sale de «¿tiene cuenta?» (contra `core_users` ahora, como al aprobar) y del
    estado del NIP, con la MISMA decisión que la bandeja
    (`EnrollmentRequestService.approval_path` + `APPROVAL_LABELS`, Ruling R8).
    Un control que no cumple `CONTROL_NUMBER_RE` no se busca en `core_users`
    (mismo corte que `EligibilityService.check` y la aprobación): cuenta como
    sin cuenta."""
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        APPROVAL_LABELS, EnrollmentRequestService,
    )
    from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            _sii_fail(f"No existe la convocatoria {cohort_id}.")
        tiene_cuenta = (CONTROL_NUMBER_RE.fullmatch(control) is not None
                        and db.query(User.id).filter_by(control_number=control)
                        .first() is not None)
        boton = APPROVAL_LABELS[EnrollmentRequestService.approval_path(tiene_cuenta, nip_status)]
        click.echo(f"Convocatoria: {cohort.name} (id {cohort.id}, {cohort.status})")
        click.echo(f"Cuenta: {'sí' if tiene_cuenta else 'no'}")
        click.echo(f"  → En «Por revisar», Servicios Escolares vería: {boton}")
    finally:
        db.rollback()
        db.close()


@titulatec_cli.command("sii-check")
@click.argument("control_number")
@click.option("--cohort", "cohort_id", type=int, default=None,
              help="Muestra además qué pasaría en esa convocatoria (solo lectura).")
def sii_check_command(control_number, cohort_id):
    """Dry-run: evalúa las reglas del SII para un número de control.

    Imprime el resultado por regla, los hechos, la identidad y el estado del
    NIP (`classify_sii_nip`; el valor siempre enmascarado): el que guardaría
    la consulta para una persona SIN cuenta. Aquí se pregunta siempre,
    aunque el control ya tenga cuenta (la consulta, en ese caso, ni lo pide y
    guarda `not_needed`). Con `--cohort`, el botón que vería Servicios
    Escolares. No escribe nada. Sale 1 ante `error` o un NIP que no serviría
    para crear la cuenta (formato inválido, SII sin respuesta, `[credential]`
    mal configurada).
    """
    import time

    from itcj2.apps.titulatec.services.eligibility_service import (
        EligibilityService, nip_failure,
    )
    from itcj2.apps.titulatec.services.sii.client import SiiConfig, get_sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError, SiiRulesError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet

    classify = EligibilityService.classify_sii_nip
    control = control_number.strip().upper()
    rules_dir = SiiConfig.rules_dir()
    try:
        rs = RuleSet.load(rules_dir)
        sii = get_sii_client()
    except SiiError as exc:
        _sii_fail(str(exc))

    t0 = time.monotonic()
    nip_status = None          # sin revisar, como la consulta con veredicto `error`
    with sii:
        verdict = rs.evaluate(sii, control)
        if verdict.status == "error":
            nip_detail = "no consultado (la evaluación falló)"
        elif not rs.has_credential:
            nip_status = classify(None, None)
            nip_detail = "sin NIP (las reglas no declaran [credential])"
        else:
            # El mensaje de estas excepciones ya viene sin el NIP: la consulta
            # va en modo sensible y el motor solo nombra columnas.
            try:
                # El `Secret` se clasifica y se descarta en esta misma línea.
                nip_status = classify(rs.fetch_credential(sii, control), None)
            except SiiRulesError as exc:
                nip_status = classify(None, nip_failure(exc))
                nip_detail = f"error en las reglas ({exc})"
            except SiiError as exc:
                nip_status = classify(None, nip_failure(exc))
                nip_detail = f"no se pudo consultar ({exc})"
            else:
                # Solo el formato, jamás el valor. Con otro formato la cuenta no
                # se podría crear al aprobarla: no pasa en verde.
                nip_detail = {
                    "available": "**** (el SII lo devuelve · 4 dígitos: sí)",
                    "invalid": ("**** (el SII lo devuelve · 4 dígitos: no — con ese "
                                "formato no se puede crear la cuenta)"),
                    "missing": "sin NIP (el SII no lo devuelve)",
                }[nip_status]
    ms = int((time.monotonic() - t0) * 1000)

    color = {"apt": "green", "not_apt": "yellow"}.get(verdict.status, "red")
    click.echo(f"Número de control: {control} · reglas {verdict.rules_version or '?'} "
               f"· backend {SiiConfig.backend()}")
    click.echo(click.style(f"Veredicto: {_SII_STATUS_LABEL.get(verdict.status, verdict.status)}",
                           fg=color, bold=True))
    if verdict.error:
        click.echo(click.style(f"  {verdict.error}", fg="red"))
    if verdict.results:
        width = max(len(r.rule) for r in verdict.results)
        for r in verdict.results:
            mark = click.style("OK   ", fg="green") if r.ok else click.style("FALLA", fg="red")
            click.echo(f"  {mark} {r.rule.ljust(width)}  {r.message}")
    for title, data in (("Hechos", verdict.facts), ("Identidad", verdict.identity)):
        click.echo(f"{title}:" + ("" if data else " (ninguno)"))
        for k, v in data.items():
            click.echo(f"  {k} = {v}")
    for w in verdict.warnings:
        click.echo(click.style(f"Advertencia: {w}", fg="yellow"))
    click.echo(f"NIP: {_SII_NIP_LABEL[nip_status]} — {nip_detail}")
    click.echo(f"Duración: {ms} ms")

    if cohort_id is not None:
        _sii_cohort_outcome(cohort_id, control, nip_status)
    if verdict.status == "error" or nip_status in _SII_NIP_FAILS:
        raise SystemExit(1)


@titulatec_cli.command("sii-sweep")
@click.option("--cohort", "cohort_id", type=int, default=None,
              help="Solo las solicitudes de esa convocatoria.")
@click.option("--reconsultar-errores", "reconsultar_errores", is_flag=True,
              help="En vez del barrido: encola una consulta forzada para toda "
                   "solicitud por revisar cuya consulta vigente sea un error "
                   "(de configuración o en el tope de intentos) o esté colgada. "
                   "Úsalo tras corregir las reglas o la conexión.")
def sii_sweep_command(cohort_id, reconsultar_errores):
    """Barrido manual del SII (lo mismo que la tarea periódica `sii_sweep`).

    Consulta las solicitudes por revisar que no tienen consulta y reintenta las
    fallidas. No aprueba nada (eso es de Servicios Escolares, desde la bandeja).
    Solo en el modo `sii`. ESCRIBE en la BD (las consultas); imprime solo los
    conteos.

    Con `--reconsultar-errores` solo ENCOLA reconsultas forzadas de lo que el
    barrido ya no toma (`EligibilityService.recheck_errors`); las hace el
    worker de celery.

    Con el SII sin configurar (`TITULATEC_SII_BACKEND=disabled`, spec
    2026-09-27 D11) el servicio no consulta ni encola nada: se avisa y sale 0.
    """
    from itcj2.apps.titulatec.services.eligibility_service import EligibilityService
    from itcj2.apps.titulatec.services.enrollment_request_service import (
        EnrollmentRequestService,
    )
    from itcj2.database import SessionLocal

    mode = EnrollmentRequestService.reviewer_mode()
    if mode != "sii":
        click.echo(click.style(
            f"El modo de revisión es '{mode}', no 'sii' (TITULATEC_ENROLLMENT_REVIEWER): "
            "el barrido no hace nada.", fg="yellow"))
        return
    db = SessionLocal()
    try:
        if reconsultar_errores:
            out = EligibilityService.recheck_errors(db, cohort_id=cohort_id)
        else:
            out = EligibilityService.sweep(db, cohort_id=cohort_id)
    finally:
        db.close()
    if out.get("disabled"):
        click.echo(click.style(
            "El SII no está configurado (TITULATEC_SII_BACKEND=disabled); "
            "no se consultó nada.", fg="yellow"))
        return
    if reconsultar_errores:
        click.echo(f"Reconsultas encoladas: {out['queued']}")
        if out["failed"]:
            click.echo(click.style(
                f"No se pudo encolar: {out['failed']} (¿broker caído?). Vuelve a "
                "correr el comando.", fg="yellow"))
        return
    click.echo(f"Consultadas: {out['checked']} · reintentadas: {out['retried']}")
