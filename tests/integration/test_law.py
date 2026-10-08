"""§0.7: one copy of the law, published one way (migration 076, src/law.py, law.yml).

`law` is append-only and refuses TRUNCATE, so the suite's fixture cannot empty it: every test here
publishes documents marked uniquely for itself and asserts on the rows it wrote.
"""
import hashlib
import pathlib
import subprocess
import sys
import uuid

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import brief                                                              # noqa: E402
import law                                                                # noqa: E402


def _documents(tmp_path, version="v9.9", marker=None):
    marker = marker or uuid.uuid4().hex
    plan = tmp_path / "yuna_plan.md"
    plan.write_text(f"# yuna_plan.md — {version}\n\n{marker}\n", encoding="utf-8")
    contract = tmp_path / "routines-contract.md"
    contract.write_text(f"# Routines contract\n\n{marker}\n", encoding="utf-8")
    return {"plan": plan, "routines-contract": contract}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_changed_law_is_published_once_and_a_rerun_publishes_nothing(db, tmp_path):
    docs = _documents(tmp_path)
    with db.cursor() as cur:
        first = law.publish(cur, docs, "a" * 40)
        again = law.publish(cur, docs, "b" * 40)
        db.commit()
        cur.execute("select document, version, sha256, git_commit from v_law order by document")
        newest = cur.fetchall()
    assert [(d, new) for d, _, _, new in first] == [("plan", True), ("routines-contract", True)]
    assert [new for *_, new in again] == [False, False], "same text, nothing published"
    assert newest == [("plan", "v9.9", _sha(docs["plan"]), "a" * 40),
                      ("routines-contract", None, _sha(docs["routines-contract"]), "a" * 40)]

    docs["plan"].write_text(docs["plan"].read_text() + "amended\n", encoding="utf-8")
    with db.cursor() as cur:
        changed = law.publish(cur, docs, "c" * 40)
        db.commit()
        cur.execute("select sha256, git_commit from v_law where document = 'plan'")
        assert cur.fetchone() == (_sha(docs["plan"]), "c" * 40)
    assert [(d, new) for d, _, _, new in changed] == [("plan", True), ("routines-contract", False)]


def test_a_published_law_is_never_edited_or_deleted(db, tmp_path):
    docs = _documents(tmp_path)
    with db.cursor() as cur:
        law.publish(cur, docs, "d" * 40)
        db.commit()
        cur.execute("select max(id) from law")
        mine = cur.fetchone()[0]
        for sql in ("update law set body = 'rewritten' where id = %s",
                    "delete from law where id = %s"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                cur.execute(sql, (mine,))
            db.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            cur.execute("truncate law")
        db.rollback()
        cur.execute("select count(*) from law where id = %s", (mine,))
        assert cur.fetchone()[0] == 1


def test_the_brief_names_the_law_it_was_read_under(db, tmp_path):
    docs = _documents(tmp_path, version="v9.8")
    with db.cursor() as cur:
        law.publish(cur, docs, "e" * 40)
        db.commit()
        p = brief.payload(cur)
    assert p["law"]["version"] == "v9.8" and p["law"]["hash"] == _sha(docs["plan"])[:12]
    header = brief.render(p).splitlines()[0]
    assert header.endswith(f"· law v9.8 · {_sha(docs['plan'])[:12]}"), header


def test_the_job_publishes_the_plan_on_main_and_records_its_run(db, migrated):
    out = subprocess.run([sys.executable, str(ROOT / "src" / "law.py")], capture_output=True,
                         text=True, env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                                         "GITHUB_SHA": "f" * 40, "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    plan = ROOT / "docs" / "yuna_plan.md"
    with db.cursor() as cur:
        cur.execute("select version, sha256 from v_law where document = 'plan'")
        assert cur.fetchone() == (law.plan_version(plan.read_text(encoding="utf-8")), _sha(plan))
        cur.execute("select status, detail from runs where job = 'law'")
        (status, detail), = cur.fetchall()
    assert status == "green" and detail["commit"] == "f" * 40
    assert {d["document"] for d in detail["documents"]} == {"plan", "routines-contract"}
