"""Regresión: app_key nunca debe llegar crudo al filesystem.

Incidente (julio 2026): `/itcj/config/email/auth/callback` no tenía dependencia de
auth y pasaba el query param `state` tal cual como app_key hasta
`_email_dir(app_key).mkdir(parents=True)`. Un escaneo automatizado (Acunetix)
fuzzeó ese parámetro y creó ~80 directorios bajo instance/apps/ con nombres de
payload — cada uno con su subcarpeta email/, la firma inconfundible de
`_email_dir`. Estos tests fijan el contrato para que no vuelva a abrirse.
"""
import pytest

from itcj2.core.utils import msgraph_mail as mg


# Muestra literal de nombres encontrados en el servidor + traversal explícito.
HOSTILE_KEYS = [
    "../../../tmp/pwned",
    "..",
    "/etc",
    "c:",
    "http:",
    "bxss.me",
    "xfs.bxss.me",
    "redirtest.acx",
    "-1' OR 5*5=25 -- ",
    "${@print(md5(31337))}",
    "$(nslookup -q=cname hitniduwrotcwcc968.bxss.me)",
    "<!--",
    "'\"()&%<zzz><ScRiPt >2Btn(9294)<",
    "",
    "Helpdesk",          # mayúsculas: fuera del charset
    "help desk",         # espacio
    "helpdesk/email",    # separador de ruta
    "a" * 33,            # excede el largo máximo
    None,
    123,
]

VALID_KEYS = ["helpdesk", "maint", "agendatec", "vistetec", "titulatec",
              "warehouse", "directory", "itcj", "a", "app_2", "app-2"]

# "callback" también apareció entre los directorios del escaneo, pero tiene FORMA
# de app_key válida (minúsculas, sin separadores), así que el regex no lo puede
# rechazar. Lo corta la segunda capa: _resolve_app_key en core/api/email.py exige
# que exista en core_apps, y el callback OAuth resuelve el app_key desde el nonce
# de Redis. Por eso la defensa es en dos capas y no solo el regex.
SHAPE_VALID_BUT_NOT_AN_APP = ["callback", "email", "admin"]


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_email_dir_rejects_hostile_keys(key):
    with pytest.raises(mg.InvalidAppKey):
        mg._email_dir(key)


@pytest.mark.parametrize("key", SHAPE_VALID_BUT_NOT_AN_APP)
def test_shape_valid_keys_pass_regex_and_rely_on_db_allowlist(key):
    """El regex solo valida FORMA. La identidad la valida core_apps."""
    assert mg._safe_app_key(key) == key


@pytest.mark.parametrize("key", VALID_KEYS)
def test_email_dir_accepts_real_app_keys(key):
    d = mg._email_dir(key)
    assert d.name == "email"
    assert d.parent.name == key
    assert mg._INSTANCE_BASE.resolve() in d.resolve().parents


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_process_auth_code_fails_hard(key):
    """La ruta que el escaneo abusó: falla antes de tocar el filesystem."""
    with pytest.raises(mg.InvalidAppKey):
        mg.process_auth_code(key, "cualquier-code")


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_build_auth_url_fails_hard(key):
    with pytest.raises(mg.InvalidAppKey):
        mg.build_auth_url(key)


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_read_paths_fail_soft(key):
    """Lecturas: None/no-op, nunca excepción (la página itera todas las apps)."""
    assert mg.read_account_info(key) is None
    assert mg.acquire_token_silent(key) is None
    mg.clear_account_and_cache(key)  # no debe lanzar


def test_load_cache_does_not_create_directories(tmp_path, monkeypatch):
    """Leer NO crea directorios. Era `_ensure_dirs` dentro de `load_cache` lo que
    convertía cualquier lectura en un mkdir."""
    monkeypatch.setattr(mg, "_INSTANCE_BASE", tmp_path)
    mg.load_cache("helpdesk")
    assert list(tmp_path.iterdir()) == []


def test_no_mkdir_reaches_disk_for_hostile_key(tmp_path, monkeypatch):
    """Barrido end-to-end: ningún key hostil deja rastro en disco."""
    monkeypatch.setattr(mg, "_INSTANCE_BASE", tmp_path)
    for key in HOSTILE_KEYS:
        for fn in (mg.read_account_info, mg.acquire_token_silent,
                   mg.clear_account_and_cache):
            fn(key)
        for fn in (mg.build_auth_url,):
            with pytest.raises(mg.InvalidAppKey):
                fn(key)
    assert list(tmp_path.rglob("*")) == []
