"""Every workflow file must be valid YAML, and every job must be reachable.

Written because a broken one was pushed. A single-quoted YAML scalar escapes an apostrophe by
DOUBLING it, not with a backslash, so `tonight\\'s` silently made the whole file unparseable — and
GitHub does not tell you until a dispatch fails, by which point the branch has no working workflows
at all and no obvious reason why.

pytest catches it in under a second. GitHub catches it after a push, a dispatch, and a confused
reader.
"""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_there_are_workflows_to_check():
    assert WORKFLOWS, "no workflow files found — the glob is wrong, not the repo"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_the_workflow_parses(path):
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path.name} is not a mapping"
    assert doc.get("jobs"), f"{path.name} declares no jobs"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_steps_and_a_runner(path):
    """A job with no steps is a job that silently does nothing, which is worse than one that fails."""
    for name, job in yaml.safe_load(path.read_text())["jobs"].items():
        if "uses" in job:                     # a reusable-workflow call has no steps of its own
            continue
        assert job.get("runs-on"), f"{path.name}:{name} has no runner"
        assert job.get("steps"), f"{path.name}:{name} has no steps"


def test_each_research_mode_in_the_description_has_a_job_that_runs_it():
    """The dispatch description lists the modes. A mode named there with no job behind it dispatches
    a workflow where every job skips — which reads as success and produces nothing."""
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "backtest.yml").read_text())
    desc = doc[True]["workflow_dispatch"]["inputs"]["research"]["description"]
    guards = " ".join(str(j.get("if", "")) for j in doc["jobs"].values())
    for mode in ("blend", "push_study", "concentrated", "dedupe", "verify", "census", "desk"):
        assert f"`{mode}`" in desc, f"research={mode} exists but is undocumented"
        assert f"inputs.research == '{mode}'" in guards, f"research={mode} is documented but no job runs it"


# ---- §4.1's chain, asserted against the plan rather than against itself -------------------------
#
# A workflow that parses can still run the wrong file. These check the two seams that have no other
# guard: every `run:` names a script that exists, and the nightly chain is the five jobs §4.1 lists
# in an order that is a data dependency rather than a preference.

def _pipeline():
    return yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline.yml").read_text())


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_python_step_names_a_file_that_exists(path):
    """A renamed job with a stale workflow fails at 02:00 UTC and nowhere else."""
    doc = yaml.safe_load(path.read_text())
    for job, spec in (doc.get("jobs") or {}).items():
        for step in spec.get("steps") or []:
            for token in (step.get("run") or "").split():
                if token.startswith("src/") and token.endswith(".py"):
                    assert (ROOT / token).exists(), f"{path.name}:{job} runs a missing {token}"


def test_the_nightly_chain_is_ss4_1s_five_jobs():
    """§4.1: ingest · score · compose · check · reconcile. `ingest` has its own workflows; the
    other four plus `notify` are this chain."""
    jobs = _pipeline()["jobs"]
    assert {"reconcile", "score", "check", "compose", "notify"} <= set(jobs)


def test_reconcile_runs_before_score():
    """Not a preference — a correctness argument the repository has already paid for. `score` reads
    `book` to decide what is held, so a fill taken this morning and not yet folded makes the engine
    propose a buy of a name it already owns. Four unrecorded fills on 2026-08-04 put RS.US through
    four consecutive briefs as a new entry at the price Zak had already paid."""
    jobs = _pipeline()["jobs"]
    needs = jobs["score"].get("needs")
    needs = [needs] if isinstance(needs, str) else needs
    assert "reconcile" in needs


def test_the_chain_runs_the_engine_and_not_the_retired_machine():
    """§6.3 retires the legacy jobs from the SCHEDULE. They remain on disk as dispatch-only
    tooling, so nothing but this assertion stops the chain quietly running them again."""
    runs = " ".join(step.get("run") or ""
                    for spec in _pipeline()["jobs"].values()
                    for step in spec.get("steps") or [])
    assert "src/sheet.py" in runs and "src/gauges.py" in runs and "src/brief.py" in runs
    for retired in ("src/score.py", "src/check.py", "src/compose.py", "src/fills.py"):
        assert retired not in runs, f"{retired} was retired from the schedule by §6.3"


def test_the_retired_engines_buttons_are_gone():
    """Deleted 2026-09-13 (learning 66). `check.yml` ran the retired checker under the live job's
    own name, so one press put a row without a `blocks_buys` verdict at the top of the ledger and
    the brief dropped "buys held"; the other three called fundamentals endpoints the plan no longer
    buys, and their 403 landed a red under the ingest verb. Retired means no workflow runs it."""
    for name in ("check.yml", "ingest-filings.yml", "phase0.yml", "fills.yml"):
        assert not (ROOT / ".github" / "workflows" / name).exists(), f"{name} is retired"


# ---- a rehearsal says it is one (QC 2026-10-07, A9 and A24; learning 67) -------------------------
#
# `dry_run` promises "compute everything, write nothing". A job that never hears it writes a live
# row on a rehearsal, and a live row of the wrong colour holds — or releases — the desk.

DRY = "${{ inputs.dry_run || 'false' }}"


def _is_autopsy(step):
    return "src/report_fail.py" in (step.get("run") or "")


def _runs_a_job(step):
    run = step.get("run") or ""
    return "src/" in run and ".py" in run and not _is_autopsy(step)


def test_every_chain_job_hears_that_the_dispatch_is_a_rehearsal():
    """A9: `check` was the one job in the chain without DRY_RUN (and `notify` the other), so a dry
    dispatch wrote a live check row — the newest verdict the brief reads — on a rehearsal."""
    for name, spec in _pipeline()["jobs"].items():
        for step in spec.get("steps") or []:
            if _runs_a_job(step):
                assert (step.get("env") or {}).get("DRY_RUN") == DRY, \
                    f"pipeline.yml:{name} runs {step['run']!r} without the dispatch's DRY_RUN"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_an_autopsy_records_a_rehearsal_as_a_rehearsal(path):
    """A24: the autopsy writes the row for a job that died before its heartbeat, so it must carry
    the DRY_RUN its job carried — or a dry dispatch's death is a live red under a price-critical
    name, and `freshness()` holds the buys on it."""
    for name, spec in (yaml.safe_load(path.read_text()).get("jobs") or {}).items():
        steps = spec.get("steps") or []
        told = {(s.get("env") or {}).get("DRY_RUN") for s in steps if _runs_a_job(s)} - {None}
        assert len(told) <= 1, f"{path.name}:{name} gives its steps different DRY_RUNs"
        want = next(iter(told), None)
        for step in filter(_is_autopsy, steps):
            assert (step.get("env") or {}).get("DRY_RUN") == want, \
                f"{path.name}:{name}'s autopsy does not get the DRY_RUN its job gets"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_an_autopsy_also_runs_when_the_job_is_cancelled(path):
    """QC 2026-10-07 (A45): a cancel — by hand, by `timeout-minutes`, by a lost runner — is not a
    failure() to GitHub, so an `if: failure()` autopsy never ran on one and the killed job's row
    read `running` for ever (production's run 905, since 2026-09-14). Every autopsy runs on a
    cancel as well, judged by its own job's work step: a cancel after a green finish is no death."""
    for name, spec in (yaml.safe_load(path.read_text()).get("jobs") or {}).items():
        steps = spec.get("steps") or []
        work = {s.get("id") for s in steps if _runs_a_job(s)}
        if not work:
            continue                        # nothing of its own to autopsy
        for step in filter(_is_autopsy, steps):
            cond = str(step.get("if", ""))
            assert "failure()" in cond and "cancelled()" in cond, \
                f"{path.name}:{name}'s autopsy never runs on a cancel: {cond!r}"
            judged_by = set(re.findall(r"steps\.([\w-]+)\.outcome", cond))
            assert judged_by and judged_by <= work - {None}, \
                f"{path.name}:{name}'s autopsy must judge a cancel by its own work step's outcome"


def test_the_composed_kind_is_the_kind_notify_expects():
    """The seam with no other guard: `brief` writes a kind and `notify` looks for one. When they
    disagree the chain is green end to end and Zak gets silence — which §4.7 rules is itself the
    alarm, and which nothing in the pipeline would have raised."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    import notify                                                          # noqa: E402
    slots = yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline.yml").read_text())
    picker = " ".join(step.get("run") or ""
                      for step in slots["jobs"]["slot"]["steps"])
    for slot in ("nightly", "saturday"):
        assert slot in picker, f"the slot picker can never emit {slot!r}"
        assert slot in notify.EXPECTED, f"notify does not know the {slot!r} slot"
        assert notify.EXPECTED[slot] == [slot], \
            f"brief writes kind {slot!r}; notify looks for {notify.EXPECTED[slot]}"
