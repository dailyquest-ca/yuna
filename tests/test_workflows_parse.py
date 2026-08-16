"""Every workflow file must be valid YAML, and every job must be reachable.

Written because a broken one was pushed. A single-quoted YAML scalar escapes an apostrophe by
DOUBLING it, not with a backslash, so `tonight\\'s` silently made the whole file unparseable — and
GitHub does not tell you until a dispatch fails, by which point the branch has no working workflows
at all and no obvious reason why.

pytest catches it in under a second. GitHub catches it after a push, a dispatch, and a confused
reader.
"""
import pathlib

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
