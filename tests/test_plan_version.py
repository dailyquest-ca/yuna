"""§0.7's guard on the law itself, without a database: the plan names one version, on its first
line, in its status line and as its newest changelog entry, and the law job refuses a plan that
names none. A header that says v1.2 over a changelog that ends at v1.1 is how a reader comes to
quote a law nobody promoted."""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import law                                                                # noqa: E402

PLAN = (ROOT / "docs" / "yuna_plan.md").read_text(encoding="utf-8")
# a versioned §7 entry: "**v1.2 — 2026-10-08 — ...". Dated amendments without a version are not.
ENTRY = re.compile(r"^\*\*(v\d+(?:\.\d+)+) — (\d{4}-\d{2}-\d{2}) — ", re.M)


def test_the_plan_names_its_version_on_its_first_line():
    assert law.plan_version(PLAN), "the law job refuses a plan whose first line names no version"


def test_the_header_the_status_line_and_the_newest_changelog_entry_agree():
    version = law.plan_version(PLAN)
    changelog = PLAN.split("## §7")[1].split("## §8")[0]
    entries = ENTRY.findall(changelog)
    assert entries, "§7 carries no versioned entry"
    assert entries[-1][0] == version, (
        f"the header says {version}, and §7's newest versioned entry is {entries[-1][0]}")
    status = next(line for line in PLAN.splitlines() if line.startswith("**Status:"))
    assert f"{version} promoted by Zak" in status, status


def test_a_plan_that_names_no_version_is_never_published(tmp_path):
    (tmp_path / "plan.md").write_text("# a plan without a version\n", encoding="utf-8")

    class Untouched:
        def execute(self, *args):
            raise AssertionError("nothing may be read or written before the plan is refused")

    with pytest.raises(SystemExit, match="names no version"):
        law.publish(Untouched(), {"plan": tmp_path / "plan.md"}, "0" * 40)
