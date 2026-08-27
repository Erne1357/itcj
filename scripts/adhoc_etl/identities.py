"""Resuelve los 59 usuarios del legacy contra `core_users`.

Fase F3 del ETL de Calidad. Produce `_identity_map.json`, del que depende TODO
lo demas: si una identidad se resuelve mal, el historial queda atribuido a otra
persona y no hay forma de notarlo despues.

Por eso este paso es un artefacto revisable aparte y no una funcion escondida
dentro del transform.

## Reglas (decisiones D1 y D6 del spec)

1. BLACKLIST. Dos usernames empatan pero son personas distintas:
     legacy `mruiz`   = Mahelet Ruiz            != core `mruiz`   = Mario Macario Ruiz Grijalva (Director)
     legacy `jchavez` = Jesus Miguel Chavez Casas != core `jchavez` = Janeth Sarahi Chavez Rodarte
   El Director SI es el legacy `mmruiz`. Sin esta blacklist, 449 registros
   quedan atribuidos a quien no es.

2. FUSION de cuentas duplicadas del mismo humano:
     vreyes + vuribe   -> Viridiana Reyes Uribe   (661 referencias)
     dbecerra+ fbecerra -> Delfino Becerra Robles  (244 referencias)

3. Cadena de resolucion, en orden: username exacto -> email (`usuarios.extra`,
   que el analisis previo no documentaba) -> nombre normalizado -> placeholder.

4. Lo que no resuelve se crea como `core_users` inactivo. NO se descarta: hay
   destinos NOT NULL (`adhoc_task_comments.user_id`) donde un NULL no cabe.

## Salida

`build/adhoc_legacy/_identity_map.json` con una entrada por usuario legacy:
su veredicto, el `core_users.id` propuesto (o la especificacion del placeholder)
y el numero de referencias que arrastra, para poder revisar por impacto.
"""
from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "build" / "adhoc_legacy"
OUT = DATA_DIR / "_identity_map.json"

PG_CONTAINER = "itcj-postgres-1"
PG_DB = "itcj"

# --- D6: usernames que NUNCA deben empatar automaticamente ---
USERNAME_BLACKLIST = {"mruiz", "jchavez"}

# --- D6: el username del legacy no siempre es el del core. {legacy: core} ---
# `mmruiz` (Mario Macario Ruiz Grijalva, el Director) es `mruiz` en core_users,
# justo el username que la blacklist prohibe para el legacy `mruiz` (Mahelet).
USERNAME_ALIASES = {
    "mmruiz": "mruiz",
}

# --- D6: cuentas duplicadas del mismo humano. {alias: canonico} ---
ACCOUNT_MERGES = {
    "vuribe": "vreyes",
    "fbecerra": "dbecerra",
}

# Los 59 usuarios del legacy son PERSONAL del ITCJ; el SGC nunca tuvo alumnos.
# En `core_users` el personal lleva `username` y los alumnos `control_number`
# (202 vs 8196 filas). Empatar por nombre contra toda la tabla produce falsos
# positivos con alumnos homonimos: el legacy `jgomez` (Julio Cesar Gomez
# Salazar, personal dado de baja) empataba con core 7449, que es el alumno
# D22111863 "Julio Cesar Salazar Gomez" — los mismos apellidos al reves.
# Por eso TODO el empate se restringe a filas con `username`.
ONLY_MATCH_STAFF = True

# Cuentas que no son personas. Se crean igual (arrastran 1048 referencias
# reales entre las 7) pero marcadas, para que Calidad sepa que no son humanos.
INSTITUTIONAL = {
    "buzonitcj", "comiteac", "estudiantes", "secretarias",
    "docentes", "personaladministrativo", "control_doc_271",
}

# Identidades tachadas a mano en el legacy. El unico rastro es el email.
REDACTED = {"<<<", "z"}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def norm(text: str | None) -> str:
    """Mayusculas, sin acentos, solo letras y espacios simples."""
    if not text:
        return ""
    cleaned = strip_accents(text).upper()
    cleaned = re.sub(r"[^A-Z\s]", " ", cleaned)
    return " ".join(cleaned.split())


def load(table: str) -> list[dict]:
    return json.loads((DATA_DIR / f"{table}.json").read_text(encoding="utf-8"))


def fetch_core_users() -> list[dict]:
    """Trae core_users por psql en CSV (robusto ante comas y acentos)."""
    sql = (
        "SELECT id, coalesce(username,''), coalesce(email,''), "
        "coalesce(first_name,''), coalesce(middle_name,''), coalesce(last_name,''), "
        "is_active FROM core_users"
    )
    proc = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", PG_DB,
         "--csv", "-t", "-c", sql],
        check=True, capture_output=True,
    )
    import csv, io
    text = proc.stdout.decode("utf-8")
    rows = []
    for r in csv.reader(io.StringIO(text)):
        if len(r) != 7:
            continue
        rows.append({
            "id": int(r[0]), "username": r[1], "email": r[2],
            "first_name": r[3], "middle_name": r[4], "last_name": r[5],
            "is_active": r[6] == "t",
        })
    return rows


def count_references() -> Counter:
    """Cuenta cuantas veces aparece cada id_usuario legacy en lo que SI se migra.

    `ver_doctos` se cuenta aparte: son 30k filas de acuses y aplastarian
    cualquier otra señal al ordenar por impacto.
    """
    refs: Counter = Counter()
    sources = [
        ("doc_com", "tc_user"), ("indiceprin", "a_user"), ("indiceprin", "a_resp"),
        ("tareas", "task_resp"), ("tareas", "task_solicit"),
        ("tareas_usrs", "tu_usr"), ("tareas_admins", "tu_usr"),
        ("tareas_com", "tc_user"), ("tareas_doc", "td_user"),
        ("appr_usrs", "au_user"), ("appr_usrs_boss", "au_user"),
        ("proyectos", "proj_resp"), ("areas", "responsable"),
        ("programas", "proj_resp"), ("tareas_prog", "task_resp"),
        ("tareas_prog_usrs", "tu_usr"), ("tareas_prog_admins", "tu_usr"),
        ("tareas_prog_com", "tc_user"), ("tareas_prog_doc", "td_user"),
    ]
    for table, column in sources:
        for row in load(table):
            value = row.get(column)
            if isinstance(value, int):
                refs[value] += 1
    return refs


def build_name_index(core: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for user in core:
        first = norm(user["first_name"])
        last = norm(f"{user['last_name']} {user['middle_name']}")
        if not first and not last:
            continue
        keys = {
            f"{first}|{last}",
            f"{first.split(' ')[0]}|{last.split(' ')[0]}" if first and last else "",
        }
        for key in filter(None, keys):
            index.setdefault(key, []).append(user)
    return index


def name_keys(nombre: str | None, apellidos: str | None) -> list[str]:
    first, last = norm(nombre), norm(apellidos)
    if not first or not last:
        return []
    keys = [f"{first}|{last}"]
    keys.append(f"{first.split(' ')[0]}|{last.split(' ')[0]}")
    return keys


def resolve() -> list[dict]:
    legacy = load("usuarios")
    core = fetch_core_users()
    refs = count_references()

    # Solo personal: los alumnos no tuvieron nunca acceso al SGC y sus homonimos
    # generan falsos positivos al empatar por nombre (ver ONLY_MATCH_STAFF).
    staff = [u for u in core if u["username"]] if ONLY_MATCH_STAFF else core

    by_username = {u["username"].strip().lower(): u for u in staff}
    by_email = {u["email"].strip().lower(): u for u in staff if u["email"]}
    by_name = build_name_index(staff)

    # `ver_doctos` aparte, para no distorsionar el orden por impacto.
    ack_refs = Counter(r["vd_user"] for r in load("ver_doctos") if isinstance(r.get("vd_user"), int))

    canonical_of = ACCOUNT_MERGES
    results = []

    for row in legacy:
        username = (row.get("username") or "").strip().lower()
        email = (row.get("email") or "").strip().lower()
        entry = {
            "legacy_id": row["id_usuario"],
            "username": username,
            "name": " ".join(filter(None, [row.get("nombre"), row.get("apellidos")])).strip(),
            "email": email,
            "active": bool(row.get("activo")),
            "flags": {k: row.get(k) for k in ("ac_docs", "ac_inci", "ac_repo")},
            "refs": refs.get(row["id_usuario"], 0),
            "ack_refs": ack_refs.get(row["id_usuario"], 0),
            "verdict": None,
            "core_user_id": None,
            # Username en core_users, que NO siempre es el del legacy: el empate
            # por nombre resuelve `lvillarreal` a `dbustillos`, `ghernandez` a
            # `gcruz` y `jcpizarro` a `jpizarro`. El ETL joinea por username, asi
            # que sin este campo esos usuarios caen al usuario tecnico.
            "core_username": None,
            "matched_by": None,
            "note": None,
        }

        if username in canonical_of:
            entry["verdict"] = "merge"
            entry["note"] = f"cuenta duplicada; se fusiona con '{canonical_of[username]}' (D6)"
            results.append(entry)
            continue

        if username in REDACTED:
            entry["verdict"] = "placeholder"
            entry["note"] = f"identidad tachada en el legacy; unico rastro: {email or 'sin email'}"
            results.append(entry)
            continue

        candidate = None
        if username in USERNAME_ALIASES:
            candidate = by_username.get(USERNAME_ALIASES[username])
            if candidate:
                entry["matched_by"] = f"alias D6 ({username} -> {USERNAME_ALIASES[username]})"
        elif username and username not in USERNAME_BLACKLIST:
            candidate = by_username.get(username)
            if candidate:
                entry["matched_by"] = "username"

        if not candidate and email:
            candidate = by_email.get(email)
            if candidate:
                entry["matched_by"] = "email"

        if not candidate:
            for key in name_keys(row.get("nombre"), row.get("apellidos")):
                hits = by_name.get(key, [])
                if len(hits) == 1:
                    candidate = hits[0]
                    entry["matched_by"] = f"nombre ({key})"
                    break
                if len(hits) > 1:
                    entry["note"] = f"nombre ambiguo: {len(hits)} candidatos en core_users"
                    break

        if candidate:
            entry["verdict"] = "match"
            entry["core_user_id"] = candidate["id"]
            entry["core_username"] = candidate["username"]
        else:
            entry["verdict"] = "placeholder"
            if username in USERNAME_BLACKLIST:
                collision = by_username.get(username)
                entry["note"] = (
                    f"BLACKLIST D6: core_users '{username}' (id {collision['id']}) es "
                    f"{collision['first_name']} {collision['last_name']}, otra persona"
                )
            elif username in INSTITUTIONAL:
                entry["note"] = "cuenta institucional, no es una persona"

        results.append(entry)

    return results


def main() -> int:
    rows = resolve()
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    tally = Counter(r["verdict"] for r in rows)
    print(f"{len(rows)} usuarios legacy -> {dict(tally)}\n")

    print(f"{'id':>3}  {'username':<22} {'refs':>5} {'acuses':>6}  {'veredicto':<12} nota")
    print("-" * 108)
    for r in sorted(rows, key=lambda r: -r["refs"]):
        flag = "!" if r["verdict"] == "placeholder" and r["refs"] > 100 else " "
        note = r["note"] or (f"core_users.id={r['core_user_id']} via {r['matched_by']}"
                             if r["core_user_id"] else "")
        print(f"{r['legacy_id']:>3}{flag} {r['username']:<22} {r['refs']:>5} "
              f"{r['ack_refs']:>6}  {r['verdict']:<12} {note[:52]}")

    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
