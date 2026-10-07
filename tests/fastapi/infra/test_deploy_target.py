"""deploy.sh despliega el commit que probó el CI y no pisa uno más nuevo.

Ejecuta con bash el bloque REAL `resolve_deploy_target` de
`docker/scripts/deploy.sh` contra un repo git desechable con remoto bare.

El caso que motiva la guarda: un run normal (A) sigue en tests cuando se
fusiona un hotfix (H, encima de A) por el carril rápido y se despliega antes.
Cuando A termina, su deploy no debe regresar prod a A. Sin la guarda, y con el
viejo `git reset --hard origin/main`, el run de un commit desplegaba la punta
de main aunque sus tests no hubieran terminado.

Necesita `git` y `bash`: el runner de CI los trae; el contenedor de dev no
trae git, así que ahí se salta.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parents[3] / "docker" / "scripts" / "deploy.sh"
_START = "# >>> resolve_deploy_target"
_END = "# <<< resolve_deploy_target"


def _deploy_text() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def _block() -> str:
    text = _deploy_text()
    return text[text.index(_START):text.index(_END)]


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """main = A → B → C (en el remoto); feat = C → F (solo en una rama)."""
    git, bash = shutil.which("git"), shutil.which("bash")
    if git is None or bash is None:  # pragma: no cover - el runner de CI los trae
        pytest.skip("git y bash hacen falta para ejecutar el bloque de deploy.sh")

    root = tmp_path_factory.mktemp("deploy_target")
    work = root / "work"

    def g(*args, cwd=work):
        return subprocess.run(
            [git, *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()

    g("init", "-q", "--bare", "remote.git", cwd=root)
    g("clone", "-q", str(root / "remote.git"), str(work), cwd=root)
    g("config", "user.email", "ci@example.invalid")
    g("config", "user.name", "ci")
    g("checkout", "-q", "-b", "main")
    shas = {}
    for name in ("A", "B", "C"):
        g("commit", "-q", "--allow-empty", "-m", name)
        shas[name] = g("rev-parse", "HEAD")
    g("push", "-q", "origin", "main")
    g("checkout", "-q", "-b", "feat")
    g("commit", "-q", "--allow-empty", "-m", "F")
    shas["F"] = g("rev-parse", "HEAD")
    g("push", "-q", "origin", "feat")
    g("checkout", "-q", "main")
    g("fetch", "-q", "origin")
    return work, shas, bash


def _resolve(repo, target: str, last_good: str | None = None):
    work, _, bash = repo
    last_good_file = work.parent / "last-good-image"
    last_good_file.unlink(missing_ok=True)
    if last_good is not None:
        last_good_file.write_text(last_good + "\n", encoding="utf-8")
    script = _block() + '\nresolve_deploy_target "$1" "$2"\n'
    proc = subprocess.run(
        [bash, "-c", script, "resolve", target, str(last_good_file)],
        cwd=work, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout.strip()


def test_sin_sha_despliega_la_punta_de_main(repo):
    _, shas, _ = repo
    assert _resolve(repo, "") == (0, shas["C"])


def test_sha_corto_sin_estado_previo_se_expande(repo):
    _, shas, _ = repo
    assert _resolve(repo, shas["B"][:7]) == (0, shas["B"])


def test_ancestro_de_lo_que_sirve_prod_no_se_despliega(repo):
    _, shas, _ = repo
    rc, out = _resolve(repo, shas["B"], last_good=shas["C"][:7])
    assert rc == 3
    assert out == ""


def test_el_mismo_commit_que_sirve_prod_se_puede_redesplegar(repo):
    _, shas, _ = repo
    assert _resolve(repo, shas["C"], last_good=shas["C"][:7]) == (0, shas["C"])


def test_descendiente_de_prod_se_despliega(repo):
    _, shas, _ = repo
    assert _resolve(repo, shas["C"], last_good=shas["A"][:7]) == (0, shas["C"])


def test_commit_que_solo_vive_en_una_rama_se_rechaza(repo):
    _, shas, _ = repo
    assert _resolve(repo, shas["F"])[0] == 1


def test_sha_inexistente_se_rechaza(repo):
    assert _resolve(repo, "deadbeefdeadbeef")[0] == 1


def test_estado_previo_ilegible_no_bloquea_el_deploy(repo):
    _, shas, _ = repo
    assert _resolve(repo, shas["B"], last_good="no-es-un-sha") == (0, shas["B"])


def test_el_reset_va_al_commit_resuelto_y_nunca_a_la_punta():
    text = _deploy_text()
    body = text[text.index(_END):]
    assert "git reset --hard origin/main" not in text
    resolve_at = body.index('resolve_deploy_target "$TARGET_SHA"')
    reset_at = body.index('git reset --hard "$DEPLOY_SHA"')
    assert resolve_at < reset_at
