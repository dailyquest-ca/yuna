"""The plan-to-code check, run in both directions.

This is the test that would have caught the defects this build actually shipped —
not because it checks arithmetic, but because it checks *claims*. Code that quietly
enforces a rule the plan never stated passes every unit test ever written for it.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import yuna
from yuna import rules
from yuna.rules import BUILT, MANUAL, OPEN, PENDING, SESSION

PLAN = Path(__file__).resolve().parents[1] / "docs" / "yuna_plan.md"

# Modules that talk to a database or the vendor at import time would be unsafe to
# import here; none currently do, and this test is what keeps that true.
SKIP_MODULES: frozenset[str] = frozenset()


@pytest.fixture(scope="module", autouse=True)
def _import_everything() -> None:
    """Decorators only register when their module is imported."""
    for mod in pkgutil.iter_modules(yuna.__path__):
        if mod.name in SKIP_MODULES:
            continue
        importlib.import_module(f"yuna.{mod.name}")


@pytest.fixture(scope="module")
def plan_text() -> str:
    return PLAN.read_text(encoding="utf-8")


# --- direction 1: code -> plan ---------------------------------------------

def test_every_decorator_names_a_known_clause() -> None:
    """No invented rules. A decorator citing a clause not in the ledger is a rule
    someone added to the code without adding it to the plan's account of itself."""
    unknown = sorted({s.key for s in rules.sites()} - set(rules.clauses()))
    assert not unknown, f"@implements cites clauses that are not in the ledger: {unknown}"


def test_every_clause_cites_a_real_plan_section(plan_text: str) -> None:
    """No citations to nothing. Every clause key's section must exist as a heading
    in the plan — this is what catches a section renumbered out from under us."""
    headings = set(re.findall(r"^#{2,4}\s+(?:Section\s+)?(\d+(?:\.\d+)?)", plan_text, re.M))
    missing = sorted({c.section for c in rules.CLAUSES} - headings)
    assert not missing, f"clauses cite plan sections that do not exist: {missing}"


# --- direction 2: plan -> code ---------------------------------------------

def test_built_clauses_have_an_implementation() -> None:
    """No imaginary builds. Claiming BUILT without a decorator anywhere is the
    single easiest way for this ledger to start lying."""
    have = {s.key for s in rules.sites()}
    claimed = {c.key for c in rules.by_status(BUILT)}
    assert not sorted(claimed - have), \
        f"marked BUILT but nothing implements them: {sorted(claimed - have)}"


def test_unbuilt_clauses_have_no_implementation() -> None:
    """The other direction, which matters more than it looks.

    A clause marked OPEN that *does* have code is either a rule someone built and
    forgot to record, or — the case that bit us — code implementing a superseded
    version of the rule while the ledger honestly says the current version is not
    built. Both need a human to look.
    """
    have = {s.key for s in rules.sites()}
    for status in (OPEN, PENDING, SESSION, MANUAL):
        bad = sorted({c.key for c in rules.by_status(status)} & have)
        assert not bad, f"marked {status} but code claims to implement them: {bad}"


def test_deferred_clauses_say_why() -> None:
    """No silent deferrals. OPEN with no note is indistinguishable from forgotten."""
    for c in rules.CLAUSES:
        if c.status == PENDING:
            assert c.note, f"{c.key}: PENDING must name the question blocking it"
            assert re.match(r"^X\d", c.note), \
                f"{c.key}: PENDING note should start with the open question's id (X2, X3, ...)"


def test_wired_implies_built() -> None:
    """A clause cannot be live in the system without existing in it."""
    for c in rules.CLAUSES:
        if c.wired:
            assert c.status == BUILT, f"{c.key}: wired={c.wired} but status={c.status}"


def test_no_duplicate_clause_keys() -> None:
    keys = [c.key for c in rules.CLAUSES]
    assert len(keys) == len(set(keys))


# --- the honest summary -----------------------------------------------------

def test_report(capsys: pytest.CaptureFixture[str]) -> None:
    """Not an assertion — a printout. `pytest -s` gives the real build state."""
    built = rules.by_status(BUILT)
    wired = [c for c in rules.CLAUSES if c.wired]
    with capsys.disabled():
        print(f"\n  plan conformance: {len(rules.CLAUSES)} clauses · "
              f"{len(built)} built · {len(wired)} wired into a running job · "
              f"{len(rules.by_status(OPEN))} open · {len(rules.by_status(PENDING))} awaiting a ruling")
        for c in rules.by_status(PENDING):
            print(f"    awaiting ruling — {c.key}: {c.note}")
        unwired = [c for c in built if not c.wired]
        if unwired:
            print(f"    built but not wired ({len(unwired)}): {', '.join(c.key for c in unwired)}")


def test_wired_is_true_only_when_a_job_actually_calls_it() -> None:
    """`wired` must be derived, not asserted.

    This check exists because the flag was wrong in nine places at once. Each of
    those clauses really was enforced by the running system — but by the job's own
    inline copy of the rule, while the `policy` function that claimed the clause
    sat untested-in-production and uncalled. Two implementations, and only the one
    nobody tested actually ran. That is the exact failure the ledger was built to
    catch, reproduced inside the ledger.

    So the ledger no longer gets to say. A clause is wired when a job module calls
    its implementation, transitively, and not otherwise.
    """
    wrong = []
    for c in rules.CLAUSES:
        actual = rules.is_wired(c.key)
        if c.wired != actual:
            wrong.append(f"{c.key}: ledger says wired={c.wired}, call graph says {actual}")
    assert not wrong, "the wired flag disagrees with the call graph:\n  " + "\n  ".join(wrong)
