"""Carreras desde los CSV: parseo de los formatos del padrón y ProgramImportService."""
import dataclasses
import os
import secrets

import pytest

from itcj2.apps.credencial.services.program_import_service import (
    HEADERLESS_COLUMNS, ProgramImportService, StudentRow, read_student_rows, resolve_program_id,
)
from itcj2.core.models.program import Program
from itcj2.core.models.student_profile import StudentProfile
from itcj2.core.models.user import User

# Filas sintéticas (nombres, controles y CURP inventados)
SEMI_HEAD = "no_de_control;nombre_carrera;carrera;reticula;estatus_alumno;apellido_paterno;apellido_materno;nombre_alumno;nip"
COMMA_HEAD = ("no_de_control,carrera,reticula,nombre_carrera,estatus_alumno,apellido_paterno,"
              "apellido_materno,nombre_alumno,curp_alumno,nip,tipo alumno,campus")


def _w(tmp_path, name, text, mtime=None, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def test_semicolon_with_header(tmp_path):
    p = _w(tmp_path, "a.csv", "﻿" + SEMI_HEAD + "\n"
           "91000001;CONTADOR PUBLICO;5;2010;VIG;PEREZ;LOPEZ;ANA;1111\n"
           "91000002;INGENIERIA INDUSTRIAL;11;2010;VIG;DIAZ;RUIZ;LUIS;2222\n")
    rows = read_student_rows([p])
    assert rows["91000001"].nombre_carrera == "CONTADOR PUBLICO"
    assert rows["91000002"].reticula == "2010" and rows["91000002"].estatus == "VIG"
    assert rows["91000001"].tipo == "" and rows["91000001"].campus == ""


def test_comma_with_header(tmp_path):
    p = _w(tmp_path, "b.csv", COMMA_HEAD + "\n"
           "91000003,19,2,INGENIERIA EN GESTION EMPRESARIAL,ACT,SOTO,VEGA,EVA,AAAA000000HXXXXX00,3333,EAD,1\n")
    r = read_student_rows([p])["91000003"]
    assert (r.nombre_carrera, r.reticula, r.estatus, r.tipo, r.campus) == (
        "INGENIERIA EN GESTION EMPRESARIAL", "2", "ACT", "EAD", "1")


def test_headerless(tmp_path):
    p = _w(tmp_path, "c.csv",
           "91000004,19,2,INGENIERIA EN LOGISTICA,ACT,MORA,PAZ,JOSE,BBBB000000HXXXXX00,4444,PRESENCIAL,2\n")
    r = read_student_rows([p])["91000004"]
    assert r.nombre_carrera == "INGENIERIA EN LOGISTICA" and r.campus == "2" and r.tipo == "PRESENCIAL"
    assert len(HEADERLESS_COLUMNS) == 12


def test_single_quoted(tmp_path):
    p = _w(tmp_path, "d.csv",
           "'91000005','19',2,'INGENIERIA EN GESTION EMPRESARIAL','ASP','RUIZ','SOL','MARIA','CCCC000000MXXXXX00',5549,'PRESENCIAL','1'\n")
    r = read_student_rows([p])["91000005"]
    assert r.control == "91000005" and r.nombre_carrera == "INGENIERIA EN GESTION EMPRESARIAL"
    assert r.estatus == "ASP" and r.campus == "1"


def test_bom(tmp_path):
    p = _w(tmp_path, "e.csv", "﻿" + COMMA_HEAD + "\n91000006,5,2,CONTADOR PUBLICO,ACT,A,B,C,X,1,,1\n")
    assert "91000006" in read_student_rows([p])


def test_cp1252_file(tmp_path):
    p = _w(tmp_path, "f.csv", "91000007,5,2,MAESTRÍA EN ALGO,ACT,A,B,C,X,1,,1\n", encoding="cp1252")
    assert read_student_rows([p])["91000007"].nombre_carrera == "MAESTRÍA EN ALGO"


def test_newest_file_wins(tmp_path):
    new = _w(tmp_path, "a_new.csv", "91000008,5,2,CONTADOR PUBLICO,ACT,A,B,C,X,1,,1\n", mtime=2_000_000_000)
    old = _w(tmp_path, "z_old.csv", "91000008,11,2,INGENIERIA INDUSTRIAL,ACT,A,B,C,X,1,,1\n", mtime=1_000_000_000)
    assert read_student_rows([new, old])["91000008"].nombre_carrera == "CONTADOR PUBLICO"


def _row(nombre="INGENIERIA EN SISTEMAS COMPUTACIONALES", tipo="", campus="1"):
    return StudentRow("1", nombre, "", "", tipo, campus)


PROGS = {
    "Ing. Sistemas computacionales": 1,
    "Ing. Sistemas computacionales EAD": 2,
    "Ing. Sistemas computacionales CAMPUS II": 3,
    "Ing. Industrial": 4,
}


def test_ead_variant():
    assert resolve_program_id(PROGS, _row(tipo="EAD")) == 2
    assert resolve_program_id(PROGS, _row()) == 1


def test_campus_ii_variant():
    assert resolve_program_id(PROGS, _row(campus="2")) == 3


def test_variant_missing_falls_back_to_base():
    assert resolve_program_id(PROGS, _row("INGENIERIA INDUSTRIAL", tipo="EAD")) == 4
    assert resolve_program_id(PROGS, _row("CARRERA INVENTADA")) is None


def test_accents_and_missing_spaces_tolerated():
    assert resolve_program_id(PROGS, _row("Ingeniería  en Sistemas Computacionales")) == 1


def test_no_nip_or_curp_in_row():
    names = {f.name for f in dataclasses.fields(StudentRow)}
    assert not names & {"nip", "curp", "curp_alumno"}


# --- apply ---

def _ctl():
    return "8" + "".join(secrets.choice("0123456789") for _ in range(7))


@pytest.fixture
def prog(db_session):
    name = "Contador publico"
    p = db_session.query(Program).filter_by(name=name).first()
    if p is None:
        p = Program(name=name, level="licenciatura")
        db_session.add(p)
        db_session.flush()
    return p


@pytest.fixture
def other_prog(db_session):
    p = Program(name="Programa Test " + secrets.token_hex(4), level="licenciatura")
    db_session.add(p)
    db_session.flush()
    return p


def _user(db):
    u = User(first_name="Ana", last_name="Test", control_number=_ctl())
    db.add(u)
    db.flush()
    return u


def _rows(u, nombre="CONTADOR PUBLICO"):
    return {u.control_number: StudentRow(u.control_number, nombre, "2010", "VIG", "", "1")}


def test_apply_creates_profile(db_session, prog):
    u = _user(db_session)
    rep = ProgramImportService.apply(db_session, _rows(u), overwrite=False, dry_run=False)
    p = db_session.get(StudentProfile, u.id)
    assert (rep.created, rep.updated, rep.no_user) == (1, 0, 0)
    assert p.program_id == prog.id and p.program_text == "CONTADOR PUBLICO"
    assert (p.reticula, p.estatus_alumno, p.campus) == ("2010", "VIG", "1")


def test_apply_does_not_overwrite_existing_program(db_session, prog, other_prog):
    u = _user(db_session)
    db_session.add(StudentProfile(user_id=u.id, program_id=other_prog.id))
    db_session.flush()
    rep = ProgramImportService.apply(db_session, _rows(u), overwrite=False, dry_run=False)
    p = db_session.get(StudentProfile, u.id)
    assert p.program_id == other_prog.id          # no pisado
    assert p.reticula == "2010" and rep.updated == 1  # campos nulos sí se llenan
    ProgramImportService.apply(db_session, _rows(u), overwrite=True, dry_run=False)
    db_session.refresh(p)
    assert p.program_id == prog.id


def test_apply_reports_no_user_and_unmapped(db_session, prog):
    u = _user(db_session)
    rows = _rows(u, "CARRERA INVENTADA")
    rows["70000000"] = StudentRow("70000000", "CONTADOR PUBLICO", "", "", "", "")
    rep = ProgramImportService.apply(db_session, rows, overwrite=False, dry_run=False)
    assert rep.no_user == 1 and rep.unmapped == {"CARRERA INVENTADA": 1}


def test_apply_dry_run_writes_nothing(db_session, prog):
    u = _user(db_session)
    rep = ProgramImportService.apply(db_session, _rows(u), overwrite=False, dry_run=True)
    assert rep.created == 1
    assert db_session.get(StudentProfile, u.id) is None
