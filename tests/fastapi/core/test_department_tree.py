"""build_tree: árbol completo sin N+1 (C3). Real-PG (joins/agregados)."""
from datetime import date, timedelta

from sqlalchemy import event, text

from itcj2.core.models.department import Department
from itcj2.core.models.position import Position, UserPosition
from itcj2.core.models.user import User
from itcj2.core.services import departments_service as ds


def _mk(db, code, parent=None, active=True, official=False):
    d = Department(code=code, name=code, parent_id=parent,
                   is_active=active, is_official=official)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _find(nodes, code):
    for n in nodes:
        if n["code"] == code:
            return n
        found = _find(n["children"], code)
        if found:
            return found
    return None


def test_tree_depth4_nested(db_session):
    r = _mk(db_session, "bt_root", official=True)
    l1 = _mk(db_session, "bt_l1", parent=r.id)
    l2 = _mk(db_session, "bt_l2", parent=l1.id)
    _mk(db_session, "bt_l3", parent=l2.id)
    tree = ds.build_tree(db_session)
    root = _find(tree, "bt_root")
    assert root is not None
    assert root["depth"] == 0 and root["is_official"] is True
    n1 = _find(root["children"], "bt_l1")
    assert n1["children"][0]["code"] == "bt_l2"
    assert n1["children"][0]["children"][0]["code"] == "bt_l3"
    assert n1["children"][0]["children"][0]["depth"] == 3


def test_tree_counts_and_head(db_session):
    d = _mk(db_session, "bt_head")
    db_session.add(Position(code="aux_bt_head", title="aux",
                            department_id=d.id, is_active=True))
    head_pos = Position(code="head_bt_head", title="jefe",
                        department_id=d.id, is_active=True)
    db_session.add(head_pos)
    db_session.commit()
    db_session.refresh(head_pos)
    u = User(first_name="Jefa", last_name="Tree", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    db_session.add(UserPosition(user_id=u.id, position_id=head_pos.id,
                                start_date=date.today() - timedelta(days=1),
                                is_active=True))
    db_session.commit()
    node = _find(ds.build_tree(db_session), "bt_head")
    assert node["positions_count"] == 2
    assert node["head"] == {"id": u.id, "name": u.full_name}


def test_tree_excludes_inactive(db_session):
    r = _mk(db_session, "bt_act")
    _mk(db_session, "bt_inact", parent=r.id, active=False)
    tree = ds.build_tree(db_session)
    assert _find(tree, "bt_act")["children"] == []
    assert _find(tree, "bt_inact") is None


def test_tree_cycle_safe(db_session):
    a = _mk(db_session, "bt_cyc_a")
    b = _mk(db_session, "bt_cyc_b", parent=a.id)
    a.parent_id = b.id  # ciclo A<->B por ORM (el CHECK solo impide self-parent)
    db_session.commit()
    tree = ds.build_tree(db_session)  # NO debe colgarse
    # sin raíz alcanzable, los nodos del ciclo no aparecen (comportamiento documentado)
    assert _find(tree, "bt_cyc_a") is None
    assert _find(tree, "bt_cyc_b") is None


def test_tree_no_n_plus_one(db_session):
    r = _mk(db_session, "bt_q_root")
    for i in range(6):
        _mk(db_session, f"bt_q_{i}", parent=r.id)
    db_session.commit()
    # Warm-up: la fixture db_session usa join_transaction_mode="create_savepoint";
    # tras un commit(), la PRIMERA query siguiente dispara un "SAVEPOINT ..." de
    # autobegin (overhead de la fixture, no de build_tree). Se paga aquí, fuera
    # de la ventana contada, para que el contador refleje solo queries reales.
    db_session.execute(text("SELECT 1"))
    engine = db_session.get_bind().engine
    counter = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        ds.build_tree(db_session)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert counter["n"] <= 3, f"build_tree emitió {counter['n']} queries (esperado <=3)"


def test_to_dict_children_stays_single_level(db_session):
    # PIN: to_dict NO recursa (decisión spec §3.2: el árbol es del service).
    # El drill-down clásico (departments.js) consume 1 nivel; los nietos NO viajan.
    r = _mk(db_session, "bt_pin_r")
    s = _mk(db_session, "bt_pin_s", parent=r.id)
    _mk(db_session, "bt_pin_n", parent=s.id)
    d = r.to_dict(include_children=True)
    assert [c["code"] for c in d["children"]] == ["bt_pin_s"]
    assert "children" not in d["children"][0]
