"""Migration 066: the REST API's public roles can reach nothing.

Supabase's linter found it on 2026-09-13: seven tables created since 051 had no row level
security, every view ran with its owner's rights, and the ledger function was executable by
PUBLIC — so the project's publishable key could read the whole desk and write the engine's own
sessions and ranks. The harness stages `anon` and `authenticated` with Supabase's default grants
before the migrations run (conftest), so what these tests check is the same door 066 closed in
production.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))

PUBLIC_ROLES = ("anon", "authenticated")


def test_every_table_in_public_has_row_level_security(db):
    """The pattern every migration since 001 followed, and the one 051, 054, 055 and the research
    tables broke. RLS with no policy is default-deny for every role that is not the owner."""
    with db.cursor() as cur:
        cur.execute("""select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
                       where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
                       order by 1""")
        unprotected = [r[0] for r in cur.fetchall()]
    assert unprotected == [], f"tables without RLS: {unprotected}"


@pytest.mark.parametrize("role", PUBLIC_ROLES)
def test_the_public_role_holds_no_grant_on_any_table_or_view(db, role):
    with db.cursor() as cur:
        cur.execute("""select table_name, privilege_type from information_schema.role_table_grants
                       where grantee = %s and table_schema = 'public' order by 1, 2""", (role,))
        grants = cur.fetchall()
    assert grants == [], f"{role} still holds {grants}"


@pytest.mark.parametrize("role", PUBLIC_ROLES)
def test_the_public_role_cannot_execute_the_ledger_function(db, role):
    """SECURITY DEFINER plus PUBLIC execute is a door into `book` for anyone with the key."""
    with db.cursor() as cur:
        cur.execute("select has_function_privilege(%s, 'yuna_book_from_ledger(text, text)', 'execute')",
                    (role,))
        assert cur.fetchone()[0] is False
        cur.execute("select has_function_privilege('yuna_session', 'yuna_book_from_ledger(text, text)', 'execute')")
        assert cur.fetchone()[0] is True, "the session's ledger insert still fires it"


def test_every_function_in_public_pins_its_search_path(db):
    """Migration 067. `create or replace function` silently drops the setting, so a redefinition
    without `set search_path` in its body would reopen the linter's warning — this is what says so."""
    with db.cursor() as cur:
        cur.execute("""select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                       where n.nspname = 'public'
                         and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c
                                          where c like 'search_path=%')
                       order by 1""")
        unpinned = [r[0] for r in cur.fetchall()]
    assert unpinned == [], f"functions without a pinned search_path: {unpinned}"


@pytest.mark.parametrize("role", PUBLIC_ROLES)
def test_a_table_created_tomorrow_is_not_handed_to_the_public_role(db, role):
    """The default privileges are how every past table became public the moment it was created.
    066 revokes them, so the next migration's table starts closed."""
    with db.cursor() as cur:
        cur.execute("create table if not exists zz_probe_066 (id int)")
        try:
            cur.execute("""select privilege_type from information_schema.role_table_grants
                           where grantee = %s and table_name = 'zz_probe_066'""", (role,))
            assert cur.fetchall() == []
        finally:
            cur.execute("drop table if exists zz_probe_066")
    db.commit()
